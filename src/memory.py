from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryIntegration:
    tools: list[Any]
    enabled: bool
    description: str


def build_memanto_memory() -> MemoryIntegration:
    """Create optional Memanto tools without making the base agent depend on a cloud key.

    For a fully local deployment, run Memanto in its on-prem/Docker mode and point
    its client configuration at that local service. If the integration is not
    configured, the agent remains usable with LangGraph's conversation memory.
    """
    enabled = os.getenv("MEMANTO_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return MemoryIntegration([], False, "Memanto disabled; using LangGraph thread memory only")

    try:
        from langgraph_memanto import create_memanto_tools
        from memanto.cli.client.sdk_client import SdkClient
    except ImportError as exc:
        raise RuntimeError(
            "MEMANTO_ENABLED=true but Memanto integration is not installed. "
            "Install memanto and langgraph-memanto."
        ) from exc

    api_key = os.getenv("MOORCHEH_API_KEY", "")
    agent_id = os.getenv("MEMANTO_AGENT_ID", "local-obsidian-researcher")
    client = SdkClient(api_key=api_key)
    tools = create_memanto_tools(client, agent_id)
    logger.info("Memanto enabled for agent namespace %s", agent_id)
    return MemoryIntegration(
        tools=tools,
        enabled=True,
        description=f"Memanto long-term memory enabled for namespace {agent_id}",
    )
