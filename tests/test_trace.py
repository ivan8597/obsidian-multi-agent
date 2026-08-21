from src.agent import explain_route
from src.tracing import RunBudget, RunTrace


def test_explain_route_reports_local_web_or_combined_reason():
    route, reason = explain_route("Сравни мои заметки с актуальной документацией в интернете")
    assert route == "obsidian_expert + web_researcher"
    assert "личные заметки" in reason

    route, _ = explain_route("Проверь актуальную документацию LangGraph")
    assert route == "web_researcher"

    route, _ = explain_route("Что в моих заметках о RAG?")
    assert route == "obsidian_expert"


def test_trace_contains_machine_readable_diagnostics():
    trace = RunTrace(
        query="test",
        thread_id="thread-1",
        route="obsidian_expert",
        route_reason="local query",
        budget=RunBudget(max_tool_calls=2),
    )
    trace.add("tool_call", name="search_obsidian")
    trace.citations.add("[OBSIDIAN-1]")
    trace.finish("stopped", "tool_call_budget_exhausted")
    diagnostics = trace.diagnostics()
    assert diagnostics["status"] == "stopped"
    assert diagnostics["stop_reason"] == "tool_call_budget_exhausted"
    assert diagnostics["tool_calls"] == 1
    assert diagnostics["obsidian_citations"] == ["[OBSIDIAN-1]"]
    assert "Диагностика запуска" in trace.diagnostics_markdown()
