from pathlib import Path

import pytest
from langchain_core.documents import Document

from src.citations import append_citation_warning, validate_citations
from src.config import Settings
from src.reranker import rerank


def make_settings(**overrides):
    values = {
        "obsidian_vault_path": Path("."),
        "ollama_base_url": "http://127.0.0.1:11434",
        "ollama_chat_model": "llama3.2",
        "ollama_embed_model": "nomic-embed-text",
        "ollama_temperature": 0.2,
        "faiss_index_path": Path("data/index"),
        "memory_db_path": Path("data/memory.sqlite"),
        "trace_db_path": Path("data/traces.sqlite"),
        "trace_retention_runs": 10,
        "retrieval_k": 3,
        "web_max_results": 5,
        "web_page_char_limit": 1000,
        "web_request_timeout": 10,
        "watch_obsidian": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_invalid_settings_are_rejected():
    with pytest.raises(ValueError, match="RETRIEVAL_K"):
        make_settings(retrieval_k=0)
    with pytest.raises(ValueError, match="OLLAMA_TEMPERATURE"):
        make_settings(ollama_temperature=3.0)


def test_citation_validator_flags_unknown_markers():
    report = validate_citations("Fact [OBSIDIAN-1], invented [OBSIDIAN-9]", {"[OBSIDIAN-1]"})
    assert report.valid == ("[OBSIDIAN-1]",)
    assert report.invalid == ("[OBSIDIAN-9]",)
    assert "OBSIDIAN-9" in append_citation_warning(
        "Fact [OBSIDIAN-1], invented [OBSIDIAN-9]", {"[OBSIDIAN-1]"}
    )


def test_reranker_promotes_query_overlap():
    documents = [
        Document(page_content="unrelated astronomy text"),
        Document(page_content="RAG retrieval and hybrid search"),
    ]
    ranked = rerank("hybrid RAG search", documents, top_n=1)
    assert ranked[0].page_content.startswith("RAG retrieval")
