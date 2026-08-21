from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import Settings

logger = logging.getLogger(__name__)


class ObsidianIndex:
    """Persistent FAISS index for Markdown and text notes.

    The index is rebuilt atomically on vault changes. This is intentionally
    conservative: FAISS does not provide a portable, version-stable delete-by-
    metadata operation across all LangChain releases.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()
        self._lock = threading.RLock()
        self._embeddings = OllamaEmbeddings(
            model=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
        )
        self._splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
        self._vectorstore: FAISS | None = None
        self._fingerprint: str | None = None

    @property
    def ready(self) -> bool:
        return self._vectorstore is not None

    def _files(self) -> list[Path]:
        return sorted(
            p for p in self.settings.obsidian_vault_path.rglob("*")
            if p.is_file() and p.suffix.lower() in {".md", ".txt"}
        )

    def _current_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in self._files():
            stat = path.stat()
            digest.update(str(path.relative_to(self.settings.obsidian_vault_path)).encode())
            digest.update(str(stat.st_mtime_ns).encode())
            digest.update(str(stat.st_size).encode())
        return digest.hexdigest()

    def _documents(self) -> list[Document]:
        docs: list[Document] = []
        for path in self._files():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning("Skipping non-UTF-8 note: %s", path)
                continue
            docs.append(Document(
                page_content=text,
                metadata={
                    "source": str(path),
                    "relative_source": str(path.relative_to(self.settings.obsidian_vault_path)),
                    "kind": "obsidian",
                },
            ))
        return self._splitter.split_documents(docs)

    def rebuild(self, force: bool = False) -> int:
        with self._lock:
            fingerprint = self._current_fingerprint()
            if not force and fingerprint == self._fingerprint and self._vectorstore is not None:
                return self._vectorstore.index.ntotal
            chunks = self._documents()
            if not chunks:
                self._vectorstore = None
                self._fingerprint = fingerprint
                logger.warning("No Markdown or text notes found in %s", self.settings.obsidian_vault_path)
                return 0
            new_store = FAISS.from_documents(chunks, self._embeddings)
            new_store.save_local(str(self.settings.faiss_index_path))
            self._vectorstore = new_store
            self._fingerprint = fingerprint
            logger.info("Indexed %d chunks from %d files", len(chunks), len(self._files()))
            return len(chunks)

    def load_or_build(self) -> int:
        with self._lock:
            if self.settings.faiss_index_path.exists() and self.settings.faiss_index_path.with_suffix(".pkl").exists():
                try:
                    self._vectorstore = FAISS.load_local(
                        str(self.settings.faiss_index_path),
                        self._embeddings,
                        allow_dangerous_deserialization=True,
                    )
                    self._fingerprint = self._current_fingerprint()
                    logger.info("Loaded FAISS index with %d vectors", self._vectorstore.index.ntotal)
                    return self._vectorstore.index.ntotal
                except Exception:
                    logger.exception("Could not load existing index; rebuilding it")
            return self.rebuild(force=True)

    def search(self, query: str, k: int | None = None) -> list[Document]:
        with self._lock:
            if self._vectorstore is None:
                return []
            return self._vectorstore.similarity_search(query, k=k or self.settings.retrieval_k)


class _VaultHandler(FileSystemEventHandler):
    def __init__(self, index: ObsidianIndex) -> None:
        self.index = index

    def on_any_event(self, event) -> None:
        if event.is_directory:
            return
        path = str(getattr(event, "src_path", ""))
        if Path(path).suffix.lower() in {".md", ".txt"}:
            try:
                self.index.rebuild(force=True)
            except Exception:
                logger.exception("Failed to rebuild index after vault change")


def start_vault_watch(index: ObsidianIndex) -> Observer:
    observer = Observer()
    observer.schedule(_VaultHandler(index), str(index.settings.obsidian_vault_path), recursive=True)
    observer.start()
    return observer
