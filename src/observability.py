from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger("obsidian_agent.metrics")


@contextmanager
def timed(event: str, **fields: object) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        payload = {
            "event": event,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            **fields,
        }
        logger.info(json.dumps(payload, ensure_ascii=False, default=str))
