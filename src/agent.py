from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor

from .config import Settings
from .indexer import ObsidianIndex
from .memory import build_memanto_memory
from .tools import build_tools

logger = logging.getLogger(__name__)


@dataclass
class LocalResearchAgent:
    app: object
    index: ObsidianIndex
    memory: MemorySaver

    def invoke(self, query: str, thread_id: str = "local-researcher") -> str:
        result = self.app.invoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        messages = result.get("messages", [])
        return _last_text(messages)

    def stream(self, query: str, thread_id: str = "local-researcher"):
        config = {"configurable": {"thread_id": thread_id}}
        for item in self.app.stream(
            {"messages": [{"role": "user", "content": query}]},
            config=config,
            stream_mode="messages",
        ):
            message = item[0] if isinstance(item, tuple) and item else item
            content = getattr(message, "content", "")
            if content:
                yield content


def _last_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            return content
    return "The agent returned no textual answer."


def create_agent(settings: Settings, index: ObsidianIndex) -> LocalResearchAgent:
    llm = ChatOllama(
        model=settings.ollama_chat_model,
        base_url=settings.ollama_base_url,
        temperature=settings.ollama_temperature,
    )
    obsidian_tool, web_search_tool, browse_tool = build_tools(index, settings)
    memanto = build_memanto_memory()
    memory_tools = memanto.tools

    obsidian_agent = create_react_agent(
        model=llm,
        tools=[obsidian_tool, *memory_tools],
        name="obsidian_expert",
        prompt=(
            "Ты эксперт по личным заметкам пользователя в Obsidian. "
            "Используй только инструмент search_obsidian. Не выдавай догадки как факты. "
            "В каждом существенном утверждении указывай источник [OBSIDIAN-N]. "
            "Если в заметках нет ответа, прямо скажи об этом. "
            "При включённом Memanto используй memanto_recall для долговременных фактов "
            "и memanto_remember для важных предпочтений, решений и фактов пользователя."
        ),
    )
    web_agent = create_react_agent(
        model=llm,
        tools=[web_search_tool, browse_tool, *memory_tools],
        name="web_researcher",
        prompt=(
            "Ты исследователь публичного интернета. Сначала ищи источники, затем при необходимости "
            "читай страницы через browse_page. Указывай URL после каждого существенного утверждения. "
            "Не утверждай, что проверил страницу, если инструмент вернул ошибку. "
            "При включённом Memanto сохраняй устойчивые результаты исследования как facts или learnings."
        ),
    )
    supervisor = create_supervisor(
        [obsidian_agent, web_agent],
        model=llm,
        prompt=(
            "Ты Supervisor локального research-агента. Анализируй запрос и выбирай obsidian_expert, "
            "web_researcher или обоих. Если пользователь просит сведения из личных заметок, не заменяй "
            "их веб-поиском. Если нужны актуальные сведения, используй web_researcher. "
            "Финальный ответ обязан разделять: (1) факты из Obsidian, (2) внешние факты, "
            "(3) выводы модели. Никогда не выдумывай цитаты, URL или содержимое заметок. "
            "Если источники противоречат друг другу или данных недостаточно, явно сообщи об этом. "
            "Краткая история текущего диалога хранится LangGraph, а долговременная память — Memanto, "
            "если он включён."
        ),
    )
    memory = MemorySaver()
    app = supervisor.compile(checkpointer=memory)
    return LocalResearchAgent(app=app, index=index, memory=memory)
