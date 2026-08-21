from pathlib import Path

from src.tracing import RunBudget, RunTrace, TraceStore


def test_trace_store_persists_run_and_events_after_reopen(tmp_path: Path):
    path = tmp_path / "traces.sqlite"
    store = TraceStore(path, retention_runs=10)
    trace = RunTrace(
        query="Что в заметках о RAG?",
        thread_id="thread-1",
        route="obsidian_expert",
        route_reason="local query",
        budget=RunBudget(),
        store=store,
    )
    trace.add("tool_call", name="search_obsidian")
    trace.finish("success")

    reopened = TraceStore(path, retention_runs=10)
    run = reopened.get_run(trace.run_id)
    assert run is not None
    assert run["status"] == "success"
    assert run["tool_calls"] == 1
    assert [event["event_type"] for event in run["events"]] == ["tool_call", "final_status"]
    assert reopened.list_runs(1)[0]["run_id"] == trace.run_id


def test_trace_store_prunes_old_runs(tmp_path: Path):
    store = TraceStore(tmp_path / "traces.sqlite", retention_runs=2)
    for index in range(3):
        trace = RunTrace(
            query=f"query-{index}",
            thread_id="thread",
            route="obsidian_expert",
            route_reason="local",
            budget=RunBudget(),
            store=store,
        )
        trace.finish()
    assert len(store.list_runs(10)) == 2
