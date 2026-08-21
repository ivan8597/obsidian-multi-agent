from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CitationReport:
    cited: tuple[str, ...]
    valid: tuple[str, ...]
    invalid: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.invalid


def validate_citations(answer: str, valid_citations: set[str]) -> CitationReport:
    cited = tuple(dict.fromkeys(re.findall(r"\[OBSIDIAN-\d+\]", answer)))
    valid = tuple(citation for citation in cited if citation in valid_citations)
    invalid = tuple(citation for citation in cited if citation not in valid_citations)
    return CitationReport(cited=cited, valid=valid, invalid=invalid)


def append_citation_warning(answer: str, valid_citations: set[str]) -> str:
    report = validate_citations(answer, valid_citations)
    if report.is_valid:
        return answer
    invalid = ", ".join(report.invalid)
    return f"{answer}\n\n⚠️ Citation validation warning: unknown source marker(s): {invalid}."
