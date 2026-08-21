from pathlib import Path

from langchain_core.embeddings import Embeddings

from src import indexer as indexer_module
from src.config import Settings
from src.indexer import ObsidianIndex


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), float(sum(map(ord, text)) % 997)] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), float(sum(map(ord, text)) % 997)]


def make_settings(vault: Path, data: Path) -> Settings:
    return Settings(
        obsidian_vault_path=vault,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_chat_model="llama3.2",
        ollama_embed_model="fake",
        ollama_temperature=0.2,
        faiss_index_path=data / "faiss",
        memory_db_path=data / "memory.sqlite",
        trace_db_path=data / "traces.sqlite",
        trace_retention_runs=10,
        retrieval_k=2,
        web_max_results=2,
        web_page_char_limit=1000,
        web_request_timeout=5,
        watch_obsidian=False,
    )


def test_incremental_index_updates_changed_file(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(indexer_module, "OllamaEmbeddings", lambda **_: FakeEmbeddings())
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("alpha retrieval", encoding="utf-8")
    index = ObsidianIndex(make_settings(vault, tmp_path / "data"))

    assert index.rebuild(force=True) == 1
    note.write_text("beta reranking", encoding="utf-8")
    assert index.rebuild(force=True) == 1
    assert index.search("beta", k=1)[0].page_content == "beta reranking"
