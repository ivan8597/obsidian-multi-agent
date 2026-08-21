from __future__ import annotations

import re
from collections.abc import Sequence

from langchain_core.documents import Document


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[\w-]{3,}", text.lower()))


def rerank(query: str, documents: Sequence[Document], top_n: int) -> list[Document]:
    """Rank retrieved documents by query-term overlap, preserving stable ties."""
    query_tokens = _tokens(query)
    scored = []
    for position, document in enumerate(documents):
        doc_tokens = _tokens(document.page_content)
        overlap = len(query_tokens & doc_tokens) / max(1, len(query_tokens))
        scored.append((overlap, -position, document))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:top_n]]
