from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_core.tools import tool

from .config import Settings
from .indexer import ObsidianIndex

logger = logging.getLogger(__name__)


def _safe_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def build_tools(index: ObsidianIndex, settings: Settings):
    @tool
    def search_obsidian(query: str) -> str:
        """Search only the user's local Obsidian notes and return evidence."""
        docs = index.search(query)
        if not docs:
            return "No relevant Obsidian notes were found."
        blocks = []
        for number, doc in enumerate(docs, start=1):
            source = doc.metadata.get("relative_source", doc.metadata.get("source", "unknown"))
            blocks.append(f"[OBSIDIAN-{number}] {source}\n{doc.page_content}")
        return "\n\n".join(blocks)

    @tool
    def search_web(query: str) -> str:
        """Search the public web and return a small set of source links."""
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    query,
                    region="ru-ru",
                    safesearch="moderate",
                    max_results=settings.web_max_results,
                ))
            if not results:
                return "No web results were found."
            blocks = []
            for number, result in enumerate(results, start=1):
                blocks.append(
                    f"[WEB-{number}] {result.get('title', 'Untitled')}\n"
                    f"{result.get('body', '')}\nURL: {result.get('href', '')}"
                )
            return "\n\n".join(blocks)
        except Exception as exc:
            logger.exception("Web search failed")
            return f"Web search failed safely: {exc}"

    @tool
    def browse_page(url: str) -> str:
        """Fetch readable text from one HTTP(S) page; reject unsafe URL schemes."""
        if not _safe_url(url):
            return "Rejected URL: only http and https URLs are allowed."
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; LocalResearchAgent/0.1)"},
                timeout=settings.web_request_timeout,
                allow_redirects=True,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return f"Skipped non-text response: {content_type}"
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "form"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            return f"[WEB-PAGE] {response.url}\n\n{text[:settings.web_page_char_limit]}"
        except Exception as exc:
            logger.exception("Page browsing failed for %s", url)
            return f"Page fetch failed safely: {exc}"

    return [search_obsidian, search_web, browse_page]
