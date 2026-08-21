from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.tracing import TraceStore


def _answer_from_events(events: list[dict[str, Any]]) -> str:
    answers = [event["data"].get("answer", "") for event in events if event["event_type"] == "final_answer"]
    return answers[-1] if answers else ""


def export_training(store: TraceStore, output: Path, min_label: str = "useful") -> int:
    feedback_rows = store.list_feedback(limit=5000)
    selected: dict[str, dict[str, Any]] = {}
    for feedback in feedback_rows:
        if feedback["label"] == min_label:
            selected.setdefault(feedback["run_id"], feedback)
    output.parent.mkdir(parents=True, exist_ok=True)
    exported = 0
    with output.open("w", encoding="utf-8") as handle:
        for run_id, feedback in selected.items():
            run = store.get_run(run_id)
            if not run:
                continue
            answer = _answer_from_events(run["events"])
            if not answer.strip():
                continue
            record = {
                "messages": [
                    {"role": "user", "content": run["query"]},
                    {"role": "assistant", "content": answer},
                ],
                "metadata": {
                    "run_id": run_id,
                    "route": run["route"],
                    "sources": run["metadata"],
                    "feedback_label": feedback["label"],
                    "created_at": run["created_at"],
                },
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            exported += 1
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description="Export positively rated traces to JSONL")
    parser.add_argument("--db", type=Path, default=Path("data/traces.sqlite"))
    parser.add_argument("--output", type=Path, default=Path("data/training.jsonl"))
    parser.add_argument("--label", default="useful", choices=["useful"])
    args = parser.parse_args()
    count = export_training(TraceStore(args.db), args.output, args.label)
    print(f"Exported {count} records to {args.output}")


if __name__ == "__main__":
    main()
