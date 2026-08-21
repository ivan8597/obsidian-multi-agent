from __future__ import annotations

import re
from collections.abc import Iterable, Sequence


def recall_at_k(expected: str, retrieved: Sequence[str], k: int) -> float:
    return float(expected in retrieved[:k])


def precision_at_k(expected: str, retrieved: Sequence[str], k: int) -> float:
    top = retrieved[:k]
    return 1.0 / len(top) if expected in top and top else 0.0


def reciprocal_rank(expected: str, retrieved: Sequence[str]) -> float:
    try:
        return 1.0 / (retrieved.index(expected) + 1)
    except ValueError:
        return 0.0


def citation_correctness(answer: str, valid_citations: Iterable[str]) -> float:
    valid = set(valid_citations)
    cited = set(re.findall(r"\[OBSIDIAN-[^\]]+\]", answer))
    if not cited:
        return 1.0 if not valid else 0.0
    return len(cited & valid) / len(cited)


def keyword_relevance(answer: str, expected_keywords: Iterable[str]) -> float:
    keywords = [keyword.lower() for keyword in expected_keywords]
    if not keywords:
        return 1.0
    normalized = answer.lower()
    return sum(keyword in normalized for keyword in keywords) / len(keywords)


def routing_accuracy(expected: Sequence[str], predicted: Sequence[str]) -> float:
    if not expected:
        return 0.0
    return sum(left == right for left, right in zip(expected, predicted)) / len(expected)


def aggregate(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0
