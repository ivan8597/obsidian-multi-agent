from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from .agent import create_agent
from .config import Settings
from .indexer import ObsidianIndex, start_vault_watch


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def print_help() -> None:
    print("Команды: /help, /reindex, /sources, /exit. Обычный текст отправляется агенту.")


def main() -> None:
    load_dotenv()
    configure_logging()
    parser = argparse.ArgumentParser(description="Local Obsidian + web multi-agent RAG assistant")
    parser.add_argument("--no-watch", action="store_true", help="disable live Obsidian reindexing")
    parser.add_argument("--thread", default="local-researcher", help="conversation memory thread id")
    args = parser.parse_args()

    settings = Settings.from_env()
    settings.validate_vault()
    index = ObsidianIndex(settings)
    count = index.load_or_build()
    print(f"Индекс готов: {count} фрагментов")

    observer = None
    if settings.watch_obsidian and not args.no_watch:
        observer = start_vault_watch(index)
        print("Watchdog включён: изменения в .md/.txt будут переиндексироваться автоматически")

    agent = create_agent(settings, index)
    print(f"Локальный агент готов. Модель: {settings.ollama_chat_model}")
    print_help()

    try:
        while True:
            try:
                query = input("\nВы: ").strip()
            except EOFError:
                break
            if not query:
                continue
            if query.lower() in {"/exit", "/quit", "выход", "стоп"}:
                break
            if query == "/help":
                print_help()
                continue
            if query == "/reindex":
                print(f"Переиндексировано фрагментов: {index.rebuild(force=True)}")
                continue
            if query == "/sources":
                print("Источники указываются агентом в формате [OBSIDIAN-N] и URL веб-страниц.")
                continue

            print("\nАгент: ", end="", flush=True)
            try:
                for chunk in agent.stream(query, thread_id=args.thread):
                    print(chunk, end="", flush=True)
                print()
            except Exception as exc:
                logging.getLogger(__name__).exception("Agent invocation failed")
                print(f"\nОшибка агента: {exc}")
    except KeyboardInterrupt:
        print("\nЗавершение...")
    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)


if __name__ == "__main__":
    main()
