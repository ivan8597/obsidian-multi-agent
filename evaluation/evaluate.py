from __future__ import annotations

import argparse
import json
from pathlib import Path

from .metrics import (
    aggregate,
    citation_correctness,
    keyword_relevance,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    routing_accuracy,
)


def evaluate(dataset_path: Path, predictions_path: Path) -> dict[str, float]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
    retrieval_recall = []
    retrieval_precision = []
    mrr = []
    citations = []
    relevance = []
    expected_routes = []
    predicted_routes = []
    for item, prediction in zip(dataset, predictions):
        retrieved = prediction.get("retrieved_sources", [])
        expected = item.get("expected_source", "")
        retrieval_recall.append(recall_at_k(expected, retrieved, prediction.get("k", 5)))
        retrieval_precision.append(precision_at_k(expected, retrieved, prediction.get("k", 5)))
        mrr.append(reciprocal_rank(expected, retrieved))
        citations.append(citation_correctness(prediction.get("answer", ""), prediction.get("valid_citations", [])))
        relevance.append(keyword_relevance(prediction.get("answer", ""), item.get("expected_answer_keywords", [])))
        expected_routes.append(item.get("expected_route", "unknown"))
        predicted_routes.append(prediction.get("predicted_route", "unknown"))
    return {
        "recall_at_k": aggregate(retrieval_recall),
        "precision_at_k": aggregate(retrieval_precision),
        "mrr": aggregate(mrr),
        "citation_correctness": aggregate(citations),
        "keyword_relevance": aggregate(relevance),
        "routing_accuracy": routing_accuracy(expected_routes, predicted_routes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate local RAG and routing predictions")
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/dataset.json"))
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.dataset, args.predictions), indent=2))


if __name__ == "__main__":
    main()
