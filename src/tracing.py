from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RunBudget:
    max_seconds: float = 45.0
    max_tool_calls: int = 6
    max_stream_chunks: int = 500


@dataclass
class TraceEvent:
    event_type: str
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunTrace:
    query: str
    thread_id: str
    route: str
    route_reason: str
    budget: RunBudget
    run_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: float = field(default_factory=time.perf_counter)
    finished_at: float | None = None
    status: str = "running"
    stop_reason: str | None = None
    events: list[TraceEvent] = field(default_factory=list)
    citations: set[str] = field(default_factory=set)
    web_urls: set[str] = field(default_factory=set)

    def add(self, event_type: str, **data: Any) -> None:
        self.events.append(TraceEvent(event_type, time.time(), data))

    def finish(self, status: str = "success", stop_reason: str | None = None) -> None:
        self.finished_at = time.perf_counter()
        self.status = status
        self.stop_reason = stop_reason
        self.add("final_status", status=status, stop_reason=stop_reason)

    @property
    def latency_ms(self) -> float | None:
        if self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at) * 1000, 2)

    @property
    def tool_calls(self) -> int:
        return sum(event.event_type == "tool_call" for event in self.events)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "route": self.route,
            "route_reason": self.route_reason,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "latency_ms": self.latency_ms,
            "tool_calls": self.tool_calls,
            "obsidian_citations": sorted(self.citations),
            "web_urls": sorted(self.web_urls),
            "event_types": [event.event_type for event in self.events],
            "budget": asdict(self.budget),
        }

    def diagnostics_markdown(self) -> str:
        info = self.diagnostics()
        lines = [
            "### Диагностика запуска",
            f"- **Run ID:** `{info['run_id']}`",
            f"- **Route:** `{info['route']}` — {info['route_reason']}",
            f"- **Status:** `{info['status']}`",
            f"- **Latency:** `{info['latency_ms']} ms`" if info["latency_ms"] is not None else "- **Latency:** измеряется",
            f"- **Tool calls:** `{info['tool_calls']}/{self.budget.max_tool_calls}`",
        ]
        if info["stop_reason"]:
            lines.append(f"- **Stop reason:** `{info['stop_reason']}`")
        lines.append(f"- **Obsidian citations:** `{len(info['obsidian_citations'])}`")
        lines.append(f"- **Web URLs:** `{len(info['web_urls'])}`")
        return "\n".join(lines)
