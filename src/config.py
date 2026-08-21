from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    obsidian_vault_path: Path
    ollama_base_url: str
    ollama_chat_model: str
    ollama_embed_model: str
    ollama_temperature: float
    faiss_index_path: Path
    memory_db_path: Path
    retrieval_k: int
    web_max_results: int
    web_page_char_limit: int
    web_request_timeout: int
    watch_obsidian: bool

    @classmethod
    def from_env(cls) -> Settings:
        vault = Path(os.getenv("OBSIDIAN_VAULT_PATH", "./data/obsidian_vault")).expanduser()
        index = Path(os.getenv("FAISS_INDEX_PATH", "./data/faiss_obsidian")).expanduser()
        memory = Path(os.getenv("MEMORY_DB_PATH", "./data/checkpoints.sqlite")).expanduser()
        return cls(
            obsidian_vault_path=vault,
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            ollama_chat_model=os.getenv("OLLAMA_CHAT_MODEL", "llama3.2"),
            ollama_embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            ollama_temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.2")),
            faiss_index_path=index,
            memory_db_path=memory,
            retrieval_k=int(os.getenv("RETRIEVAL_K", "6")),
            web_max_results=int(os.getenv("WEB_MAX_RESULTS", "5")),
            web_page_char_limit=int(os.getenv("WEB_PAGE_CHAR_LIMIT", "7000")),
            web_request_timeout=int(os.getenv("WEB_REQUEST_TIMEOUT", "15")),
            watch_obsidian=_bool("WATCH_OBSIDIAN", True),
        )

    def ensure_directories(self) -> None:
        self.faiss_index_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_db_path.parent.mkdir(parents=True, exist_ok=True)

    def validate_vault(self) -> None:
        if not self.obsidian_vault_path.exists():
            raise FileNotFoundError(
                f"Obsidian vault not found: {self.obsidian_vault_path}. "
                "Set OBSIDIAN_VAULT_PATH in .env."
            )
        if not self.obsidian_vault_path.is_dir():
            raise NotADirectoryError(f"OBSIDIAN_VAULT_PATH is not a directory: {self.obsidian_vault_path}")
