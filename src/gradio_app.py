from __future__ import annotations

import argparse
import logging
import os
import re

import gradio as gr
from dotenv import load_dotenv

from .agent import LocalResearchAgent, create_agent
from .config import Settings
from .indexer import ObsidianIndex, start_vault_watch

logger = logging.getLogger(__name__)


def extract_sources(text: str) -> str:
    """Extract explicit Obsidian markers and URLs for a readable evidence panel."""
    obsidian = sorted(set(re.findall(r"\[OBSIDIAN-[^\]]+\]\s*[^\n]*", text)))
    urls = sorted(set(re.findall(r"https?://[^\s)]+", text)))
    lines = []
    if obsidian:
        lines.append("### Источники Obsidian\n" + "\n".join(f"- {item}" for item in obsidian))
    if urls:
        lines.append("### Веб-ссылки\n" + "\n".join(f"- {url}" for url in urls))
    return "\n\n".join(lines) if lines else "Источники в ответе не обнаружены."


def build_ui(agent: LocalResearchAgent, index: ObsidianIndex, observer=None) -> gr.Blocks:
    def index_status() -> str:
        if not index.ready:
            return "Индекс: не загружен"
        count = index._vectorstore.index.ntotal if index._vectorstore is not None else 0
        return f"Индекс: готов, фрагментов — {count}"

    def reindex() -> tuple[str, str]:
        try:
            count = index.rebuild(force=True)
            return f"Переиндексация завершена: {count} фрагментов", index_status()
        except Exception as exc:
            logger.exception("Reindex failed")
            return f"Ошибка переиндексации: {exc}", index_status()

    def respond(message: str, history: list, thread_id: str):
        if not message.strip():
            yield history, "", "Введите вопрос.", index_status()
            return
        history = history or []
        history = history + [[message, ""]]
        answer = ""
        try:
            for chunk in agent.stream(message, thread_id=thread_id or "gradio-local"):
                answer += chunk
                history[-1][1] = answer
                yield history, "", extract_sources(answer), index_status()
            if not answer:
                history[-1][1] = "Агент не вернул текстовый ответ."
            yield history, "", extract_sources(answer), index_status()
        except Exception as exc:
            logger.exception("Gradio agent invocation failed")
            history[-1][1] = f"Ошибка агента: {exc}"
            yield history, "", "Источники недоступны из-за ошибки.", index_status()

    with gr.Blocks(title="Local Obsidian Research Agent", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# Локальный Obsidian Research Agent\n"
            "Мультиагентный RAG: личные заметки, веб-исследование и проверяемые источники."
        )
        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(label="Диалог", height=600)
                message = gr.Textbox(
                    label="Ваш вопрос",
                    placeholder="Например: сравни эту идею с моими заметками и проверь актуальные источники в интернете",
                    lines=3,
                )
                with gr.Row():
                    send = gr.Button("Отправить", variant="primary")
                    gr.ClearButton([message, chatbot], value="Очистить")
            with gr.Column(scale=1):
                thread_id = gr.Textbox(value="gradio-local", label="ID сессии")
                status = gr.Markdown(index_status())
                reindex_button = gr.Button("Переиндексировать Obsidian")
                reindex_result = gr.Markdown()
                sources = gr.Markdown("Источники появятся после ответа.", label="Источники")
                gr.Markdown(
                    "**Правила:** `[OBSIDIAN-N]` — фрагмент локальной заметки; "
                    "URL — внешний источник. Агент не должен выдавать неподтверждённые сведения как факты."
                )

        submit = [message, chatbot, thread_id]
        outputs = [chatbot, message, sources, status]
        send.click(respond, inputs=submit, outputs=outputs)
        message.submit(respond, inputs=submit, outputs=outputs)
        reindex_button.click(reindex, outputs=[reindex_result, status])

    return demo


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    parser = argparse.ArgumentParser(description="Run the local Gradio interface")
    parser.add_argument("--host", default=os.getenv("GRADIO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("GRADIO_PORT", "7860")))
    parser.add_argument("--no-watch", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env()
    settings.validate_vault()
    index = ObsidianIndex(settings)
    index.load_or_build()
    observer = None
    if settings.watch_obsidian and not args.no_watch:
        observer = start_vault_watch(index)
    agent = create_agent(settings, index)
    demo = build_ui(agent, index, observer)
    try:
        demo.launch(server_name=args.host, server_port=args.port, show_error=True)
    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)


if __name__ == "__main__":
    main()
