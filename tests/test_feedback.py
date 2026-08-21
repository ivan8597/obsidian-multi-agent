from pathlib import Path

import pytest

from src.tracing import RunBudget, RunTrace, TraceStore


def test_feedback_is_persisted_for_existing_run(tmp_path: Path):
    store = TraceStore(tmp_path / "traces.sqlite")
    trace = RunTrace("query", "thread", "obsidian_expert", "local", RunBudget(), store=store)
    trace.finish()
    assert store.add_feedback(trace.run_id, "useful") is True
    feedback = store.list_feedback()
    assert feedback[0]["run_id"] == trace.run_id
    assert feedback[0]["label"] == "useful"


def test_feedback_rejects_unknown_label(tmp_path: Path):
    store = TraceStore(tmp_path / "traces.sqlite")
    with pytest.raises(ValueError, match="Unknown feedback"):
        store.add_feedback("missing", "maybe")
