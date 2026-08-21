from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import Settings
from .observability import timed
from .reranker import rerank

logger = logging.getLogger(__name__)


class ObsidianIndex:
    """Persistent FAISS index with manifest-backed incremental file updates."""

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
        self._file_hashes: dict[str, str] = {}
        self._file_chunk_ids: dict[str, list[str]] = {}

    @property
    def ready(self) -> bool:
        return self._vectorstore is not None

    @property
    def manifest_path(self) -> Path:
        return self.settings.faiss_index_path.parent / f"{self.settings.faiss_index_path.name}.manifest.json"

    def _files(self) -> list[Path]:
        return sorted(
            path
            for path in self.settings.obsidian_vault_path.rglob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".txt"}
        )

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.settings.obsidian_vault_path))

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _snapshot(self) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for path in self._files():
            try:
                snapshot[self._relative(path)] = self._hash_text(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                logger.warning("Skipping non-UTF-8 note: %s", path)
        return snapshot

    def _current_fingerprint(self, snapshot: dict[str, str] | None = None) -> str:
        snapshot = snapshot or self._snapshot()
        payload = json.dumps(snapshot, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _chunk_documents(self, path: Path, text: str, file_hash: str) -> tuple[list[Document], list[str]]:
        relative = self._relative(path)
        base = Document(
            page_content=text,
            metadata={
                "source": str(path),
                "relative_source": relative,
                "kind": "obsidian",
                "file_hash": file_hash,
            },
        )
        chunks = self._splitter.split_documents([base])
        ids: list[str] = []
        for number, chunk in enumerate(chunks):
            chunk_id = hashlib.sha256(f"{relative}:{file_hash}:{number}".encode()).hexdigest()
            chunk.metadata["chunk_id"] = chunk_id
            chunk.metadata["chunk_number"] = number
            ids.append(chunk_id)
        return chunks, ids

    def _all_documents(self, snapshot: dict[str, str]) -> tuple[list[Document], list[str]]:
        documents: list[Document] = []
        ids: list[str] = []
        for path in self._files():
            relative = self._relative(path)
            file_hash = snapshot.get(relative)
            if file_hash is None:
                continue
            try:
                chunks, chunk_ids = self._chunk_documents(path, path.read_text(encoding="utf-8"), file_hash)
            except UnicodeDecodeError:
                continue
            documents.extend(chunks)
            ids.extend(chunk_ids)
        return documents, ids

    def _save_manifest(self) -> None:
        payload = {
            "file_hashes": self._file_hashes,
            "file_chunk_ids": self._file_chunk_ids,
            "fingerprint": self._fingerprint,
        }
        self.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_manifest(self) -> bool:
        try:
            payload: dict[str, Any] = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            self._file_hashes = dict(payload.get("file_hashes", {}))
            self._file_chunk_ids = {
                key: list(value) for key, value in payload.get("file_chunk_ids", {}).items()
            }
            self._fingerprint = payload.get("fingerprint")
            return True
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return False

    def _save(self) -> None:
        if self._vectorstore is not None:
            self._vectorstore.save_local(str(self.settings.faiss_index_path))
        self._save_manifest()

    def _full_rebuild(self, snapshot: dict[str, str]) -> int:
        documents, ids = self._all_documents(snapshot)
        if not documents:
            self._vectorstore = None
            self._file_hashes = snapshot
            self._file_chunk_ids = {}
            self._fingerprint = self._current_fingerprint(snapshot)
            self._save_manifest()
            logger.warning("No Markdown or text notes found in %s", self.settings.obsidian_vault_path)
            return 0
        self._vectorstore = FAISS.from_documents(documents, self._embeddings, ids=ids)
        self._file_hashes = snapshot
        self._file_chunk_ids = {}
        for document in documents:
            relative = document.metadata["relative_source"]
            self._file_chunk_ids.setdefault(relative, []).append(document.metadata["chunk_id"])
        self._fingerprint = self._current_fingerprint(snapshot)
        self._save()
        logger.info("Built index with %d chunks from %d files", len(documents), len(snapshot))
        return len(documents)

    def _incremental_update(self, snapshot: dict[str, str]) -> int:
        if self._vectorstore is None:
            return self._full_rebuild(snapshot)
        changed = {
            relative for relative, file_hash in snapshot.items()
            if self._file_hashes.get(relative) != file_hash
        }
        removed = set(self._file_hashes) - set(snapshot)
        affected = changed | removed
        if not affected:
            return self._vectorstore.index.ntotal
        old_ids = [chunk_id for relative in affected for chunk_id in self._file_chunk_ids.get(relative, [])]
        if old_ids:
            self._vectorstore.delete(ids=old_ids)
        for relative in sorted(changed):
            path = self.settings.obsidian_vault_path / relative
            try:
                chunks, ids = self._chunk_documents(path, path.read_text(encoding="utf-8"), snapshot[relative])
            except (FileNotFoundError, UnicodeDecodeError):
                continue
            self._vectorstore.add_documents(chunks, ids=ids)
            self._file_chunk_ids[relative] = ids
        for relative in removed:
            self._file_chunk_ids.pop(relative, None)
        self._file_hashes = snapshot
        self._fingerprint = self._current_fingerprint(snapshot)
        self._save()
        logger.info("Incrementally updated %d changed files; index now has %d chunks", len(affected), self._vectorstore.index.ntotal)
        return self._vectorstore.index.ntotal

    def rebuild(self, force: bool = False) -> int:
        with self._lock:
            snapshot = self._snapshot()
            if not force and self._fingerprint == self._current_fingerprint(snapshot) and self._vectorstore is not None:
                return self._vectorstore.index.ntotal
            if force and self._vectorstore is not None and self._load_manifest():
                try:
                    return self._incremental_update(snapshot)
                except Exception:
                    logger.exception("Incremental update failed; falling back to full rebuild")
            return self._full_rebuild(snapshot)

    def load_or_build(self) -> int:
        with self._lock:
            index_file = self.settings.faiss_index_path.with_suffix(".pkl")
            if self.settings.faiss_index_path.exists() and index_file.exists():
                try:
                    self._vectorstore = FAISS.load_local(
                        str(self.settings.faiss_index_path),
                        self._embeddings,
                        allow_dangerous_deserialization=True,
                    )
                    if not self._load_manifest():
                        return self._full_rebuild(self._snapshot())
                    if self._fingerprint != self._current_fingerprint():
                        return self._incremental_update(self._snapshot())
                    logger.info("Loaded FAISS index with %d vectors", self._vectorstore.index.ntotal)
                    return self._vectorstore.index.ntotal
                except Exception:
                    logger.exception("Could not load existing trusted local index; rebuilding it")
            return self._full_rebuild(self._snapshot())

    def search(self, query: str, k: int | None = None) -> list[Document]:
        with self._lock:
            if self._vectorstore is None:
                return []
            limit = k or self.settings.retrieval_k
            with timed("retrieval", retrieval_k=limit):
                candidates = self._vectorstore.similarity_search(query, k=max(limit * 2, limit))
                return rerank(query, candidates, limit)


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
                logger.exception("Failed to update index after vault change")


def start_vault_watch(index: ObsidianIndex) -> Observer:
    observer = Observer()
    observer.schedule(_VaultHandler(index), str(index.settings.obsidian_vault_path), recursive=True)
    observer.start()
    return observer
