from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

from .tracing import TraceStore

LABELS = {
    "useful": "Полезно",
    "not_useful": "Не полезно",
    "wrong_source": "Неверный источник",
    "missing_document": "Не найден документ",
}


def summarize_store(store: TraceStore, limit: int = 500) -> dict[str, Any]:
    runs = store.list_runs(limit)
    feedback = store.list_feedback(limit)
    statuses = Counter(run["status"] for run in runs)
    routes = Counter(run["route"] for run in runs)
    labels = Counter(item["label"] for item in feedback)
    latencies = [run["latency_ms"] for run in runs if run["latency_ms"] is not None]
    return {
        "runs": len(runs),
        "completed": statuses.get("success", 0),
        "errors": statuses.get("error", 0),
        "stopped": statuses.get("stopped", 0),
        "success_rate": round(statuses.get("success", 0) / len(runs), 3) if runs else 0.0,
        "avg_latency_ms": round(mean(latencies), 2) if latencies else None,
        "p95_latency_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
        "routes": dict(routes),
        "feedback_total": len(feedback),
        "feedback": dict(labels),
        "positive_feedback_rate": round(labels.get("useful", 0) / len(feedback), 3) if feedback else 0.0,
    }


def summarize_markdown(store: TraceStore | None) -> str:
    if store is None:
        return "Аналитика отключена."
    summary = summarize_store(store)
    feedback_lines = [f"- **{LABELS.get(label, label)}:** `{count}`" for label, count in summary["feedback"].items()]
    route_lines = [f"- `{route}`: `{count}`" for route, count in summary["routes"].items()]
    return "\n".join(
        [
            "### Аналитика запусков",
            f"- **Всего запусков:** `{summary['runs']}`",
            f"- **Успешных:** `{summary['completed']}`",
            f"- **Ошибок:** `{summary['errors']}`",
            f"- **Остановлено по budget:** `{summary['stopped']}`",
            f"- **Success rate:** `{summary['success_rate']:.1%}`",
            f"- **Средняя latency:** `{summary['avg_latency_ms']} ms`",
            f"- **P95 latency:** `{summary['p95_latency_ms']} ms`",
            f"- **Feedback:** `{summary['feedback_total']}`",
            f"- **Positive feedback rate:** `{summary['positive_feedback_rate']:.1%}`",
            "",
            "#### Маршруты",
            *(route_lines or ["- Данных пока нет"]),
            "",
            "#### Feedback",
            *(feedback_lines or ["- Feedback пока нет"]),
        ]
    )
