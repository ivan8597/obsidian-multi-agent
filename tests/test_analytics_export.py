import json
from pathlib import Path

from scripts.export_training import export_training
from src.analytics import summarize_store
from src.tracing import RunBudget, RunTrace, TraceStore


def _seed_store(path: Path) -> tuple[TraceStore, str]:
    store = TraceStore(path)
    trace = RunTrace("Что в заметках о RAG?", "thread", "obsidian_expert", "local", RunBudget(), metadata={"model_name": "test"}, store=store)
    trace.add("final_answer", answer="Ответ из [OBSIDIAN-1]", answer_chars=23)
    trace.finish()
    store.add_feedback(trace.run_id, "useful")
    return store, trace.run_id


def test_analytics_counts_feedback_and_success(tmp_path: Path):
    store, _ = _seed_store(tmp_path / "traces.sqlite")
    summary = summarize_store(store)
    assert summary["runs"] == 1
    assert summary["completed"] == 1
    assert summary["feedback_total"] == 1
    assert summary["positive_feedback_rate"] == 1.0


def test_export_training_writes_chat_jsonl(tmp_path: Path):
    store, _ = _seed_store(tmp_path / "traces.sqlite")
    output = tmp_path / "training.jsonl"
    assert export_training(store, output) == 1
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["messages"][0]["role"] == "user"
    assert "OBSIDIAN-1" in record["messages"][1]["content"]
    assert record["metadata"]["feedback_label"] == "useful"
