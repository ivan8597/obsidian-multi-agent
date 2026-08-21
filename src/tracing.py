from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


class TraceStore:
    """Small SQLite-backed store for operational run traces, not hidden reasoning."""

    def __init__(self, path: Path, retention_runs: int = 500) -> None:
        self.path = path
        self.retention_runs = retention_runs
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS trace_runs (
                    run_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    route TEXT NOT NULL,
                    route_reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stop_reason TEXT,
                    created_at REAL NOT NULL,
                    finished_at REAL,
                    latency_ms REAL,
                    tool_calls INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS trace_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES trace_runs(run_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_trace_runs_created_at ON trace_runs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_trace_events_run_id ON trace_events(run_id, id);
                CREATE TABLE IF NOT EXISTS trace_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES trace_runs(run_id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    note TEXT,
                    created_at REAL NOT NULL
                );
                """
            )

    def create_run(self, trace: RunTrace) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO trace_runs
                (run_id, thread_id, query, route, route_reason, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (trace.run_id, trace.thread_id, trace.query, trace.route, trace.route_reason, trace.status, time.time()),
            )
            self._prune(connection)

    def append_event(self, trace: RunTrace, event: TraceEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO trace_events (run_id, event_type, timestamp, data_json) VALUES (?, ?, ?, ?)",
                (trace.run_id, event.event_type, event.timestamp, json.dumps(event.data, ensure_ascii=False, default=str)),
            )

    def finish_run(self, trace: RunTrace) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE trace_runs SET status=?, stop_reason=?, finished_at=?, latency_ms=?, tool_calls=?
                WHERE run_id=?""",
                (trace.status, trace.stop_reason, time.time(), trace.latency_ms, trace.tool_calls, trace.run_id),
            )

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trace_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            run = connection.execute("SELECT * FROM trace_runs WHERE run_id = ?", (run_id,)).fetchone()
            if run is None:
                return None
            events = connection.execute(
                "SELECT event_type, timestamp, data_json FROM trace_events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        result = dict(run)
        result["events"] = [
            {"event_type": row["event_type"], "timestamp": row["timestamp"], "data": json.loads(row["data_json"])}
            for row in events
        ]
        return result

    def add_feedback(self, run_id: str, label: str, note: str | None = None) -> bool:
        allowed = {"useful", "not_useful", "wrong_source", "missing_document"}
        if label not in allowed:
            raise ValueError(f"Unknown feedback label: {label}")
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM trace_runs WHERE run_id = ?", (run_id,)).fetchone()
            if exists is None:
                return False
            connection.execute(
                "INSERT INTO trace_feedback (run_id, label, note, created_at) VALUES (?, ?, ?, ?)",
                (run_id, label, note, time.time()),
            )
        return True

    def list_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trace_feedback ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)
            ).fetchall()
        return [dict(row) for row in rows]

    def _prune(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """DELETE FROM trace_runs WHERE run_id NOT IN
            (SELECT run_id FROM trace_runs ORDER BY created_at DESC LIMIT ?)""",
            (max(1, self.retention_runs),),
        )


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
    store: TraceStore | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.store:
            self.store.create_run(self)

    def add(self, event_type: str, **data: Any) -> None:
        event = TraceEvent(event_type, time.time(), data)
        self.events.append(event)
        if self.store:
            self.store.append_event(self, event)

    def finish(self, status: str = "success", stop_reason: str | None = None) -> None:
        self.finished_at = time.perf_counter()
        self.status = status
        self.stop_reason = stop_reason
        self.add("final_status", status=status, stop_reason=stop_reason)
        if self.store:
            self.store.finish_run(self)

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
