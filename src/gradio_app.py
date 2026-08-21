from __future__ import annotations

import argparse
import logging
import os
import re

import gradio as gr
from dotenv import load_dotenv

from .agent import LocalResearchAgent, create_agent
from .analytics import summarize_markdown
from .citations import append_citation_warning
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


def trace_history_markdown(agent: LocalResearchAgent, limit: int = 10) -> str:
    if agent.trace_store is None:
        return "История trace отключена."
    runs = agent.trace_store.list_runs(limit)
    if not runs:
        return "История запусков пока пуста."
    lines = ["### Последние запуски", "", "| Run ID | Route | Status | Latency | Tool calls |", "|---|---|---|---:|---:|"]
    for run in runs:
        latency = f"{run['latency_ms']:.0f} ms" if run["latency_ms"] is not None else "running"
        lines.append(
            f"| `{run['run_id'][:12]}` | `{run['route']}` | `{run['status']}` | {latency} | "
            f"{run['tool_calls']} |"
        )
    return "\n".join(lines)


def trace_detail_markdown(agent: LocalResearchAgent, run_id: str) -> str:
    if agent.trace_store is None:
        return "История trace отключена."
    run = agent.trace_store.get_run(run_id.strip())
    if run is None:
        return "Запуск с таким run_id не найден."
    lines = [
        "### Детали запуска",
        f"- **Run ID:** `{run['run_id']}`",
        f"- **Thread:** `{run['thread_id']}`",
        f"- **Route:** `{run['route']}` — {run['route_reason']}",
        f"- **Status:** `{run['status']}`",
        f"- **Stop reason:** `{run['stop_reason'] or '—'}`",
        f"- **Latency:** `{run['latency_ms']} ms`",
        f"- **Query:** {run['query']}",
        "",
        "#### Events",
    ]
    lines.extend(f"- `{event['event_type']}` — `{event['data']}`" for event in run["events"])
    return "\n".join(lines)


def build_ui(agent: LocalResearchAgent, index: ObsidianIndex, observer=None) -> gr.Blocks:
    def index_status() -> str:
        if not index.ready:
            return "Индекс: не загружен"
        count = index._vectorstore.index.ntotal if index._vectorstore is not None else 0
        return f"Индекс: готов, фрагментов — {count}"

    def save_feedback(label: str) -> str:
        trace = agent.last_trace
        if trace is None or agent.trace_store is None:
            return "Feedback недоступен: запуск ещё не выполнен."
        if not agent.trace_store.add_feedback(trace.run_id, label):
            return "Feedback не сохранён: run_id не найден в истории."
        return f"Feedback сохранён для run `{trace.run_id[:12]}`."

    def reindex() -> tuple[str, str]:
        try:
            count = index.rebuild(force=True)
            return f"Переиндексация завершена: {count} фрагментов", index_status()
        except Exception as exc:
            logger.exception("Reindex failed")
            return f"Ошибка переиндексации: {exc}", index_status()

    def respond(message: str, history: list, thread_id: str):
        if not message.strip():
            yield history, "", "Введите вопрос.", index_status(), "Диагностика недоступна: пустой запрос."
            return
        history = history or []
        history = history + [[message, ""]]
        answer = ""
        observed_citations: set[str] = set()
        try:
            for chunk in agent.stream(message, thread_id=thread_id or "gradio-local"):
                answer += chunk
                observed_citations.update(re.findall(r"\[OBSIDIAN-\d+\]", chunk))
                history[-1][1] = answer
                trace = agent.last_trace
                diagnostics = trace.diagnostics_markdown() if trace else "Диагностика недоступна."
                yield history, "", extract_sources(answer), index_status(), diagnostics
            if not answer:
                history[-1][1] = "Агент не вернул текстовый ответ."
            else:
                answer = append_citation_warning(answer, observed_citations)
                history[-1][1] = answer
            trace = agent.last_trace
            diagnostics = trace.diagnostics_markdown() if trace else "Диагностика недоступна."
            yield history, "", extract_sources(answer), index_status(), diagnostics
        except Exception as exc:
            logger.exception("Gradio agent invocation failed")
            history[-1][1] = f"Ошибка агента: {exc}"
            trace = agent.last_trace
            diagnostics = trace.diagnostics_markdown() if trace else "Ошибка до создания trace."
            yield history, "", "Источники недоступны из-за ошибки.", index_status(), diagnostics

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
                diagnostics = gr.Markdown("Диагностика запуска появится после ответа.", label="Диагностика")
                refresh_traces = gr.Button("Обновить историю запусков")
                trace_history = gr.Markdown(trace_history_markdown(agent))
                trace_id = gr.Textbox(label="Run ID для просмотра", placeholder="Вставьте полный run_id")
                show_trace = gr.Button("Показать детали trace")
                trace_detail = gr.Markdown("Детали выбранного запуска появятся здесь.")
                gr.Markdown("### Оценка ответа")
                with gr.Row():
                    useful = gr.Button("Полезно")
                    not_useful = gr.Button("Не полезно")
                    wrong_source = gr.Button("Неверный источник")
                    missing_document = gr.Button("Не найден документ")
                feedback_status = gr.Markdown()
                refresh_analytics = gr.Button("Обновить аналитику")
                analytics_panel = gr.Markdown("Аналитика появится после первого запуска.")
                gr.Markdown(
                    "**Правила:** `[OBSIDIAN-N]` — фрагмент локальной заметки; "
                    "URL — внешний источник. Агент не должен выдавать неподтверждённые сведения как факты."
                )

        submit = [message, chatbot, thread_id]
        outputs = [chatbot, message, sources, status, diagnostics]
        send.click(respond, inputs=submit, outputs=outputs)
        message.submit(respond, inputs=submit, outputs=outputs)
        reindex_button.click(reindex, outputs=[reindex_result, status])
        refresh_traces.click(lambda: trace_history_markdown(agent), outputs=trace_history)
        show_trace.click(lambda run_id: trace_detail_markdown(agent, run_id), inputs=trace_id, outputs=trace_detail)
        useful.click(lambda: save_feedback("useful"), outputs=feedback_status)
        not_useful.click(lambda: save_feedback("not_useful"), outputs=feedback_status)
        wrong_source.click(lambda: save_feedback("wrong_source"), outputs=feedback_status)
        missing_document.click(lambda: save_feedback("missing_document"), outputs=feedback_status)
        refresh_analytics.click(lambda: summarize_markdown(agent.trace_store), outputs=analytics_panel)

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
