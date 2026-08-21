from pathlib import Path

from src.config import Settings
from src.memory import build_memanto_memory
from src.tools import _safe_url


def test_safe_url_allows_http_and_https_only():
    assert _safe_url("https://example.com/page")
    assert not _safe_url("http://localhost:8000")
    assert not _safe_url("file:///etc/passwd")
    assert not _safe_url("javascript:alert(1)")


def test_settings_defaults_are_local(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    settings = Settings.from_env()
    assert settings.ollama_base_url.startswith("http://127.0.0.1")
    assert settings.watch_obsidian is True


def test_memanto_is_optional(monkeypatch):
    monkeypatch.setenv("MEMANTO_ENABLED", "false")
    integration = build_memanto_memory()
    assert integration.enabled is False
    assert integration.tools == []
