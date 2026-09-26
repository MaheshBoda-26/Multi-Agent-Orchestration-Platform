import pytest

from tools.bootstrap import _search_tool
from tools.builtin.web_tools import TavilySearchTool, WebSearchTool


class FakeTavilyClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.queries = []

    def search(self, query: str, max_results: int = 5):
        self.queries.append(query)
        return {
            "results": [
                {"title": "Orchestra docs", "url": "https://example.com/docs", "content": "How it works"},
                {"title": "Agents", "url": "https://example.com/agents", "content": "About agents"},
            ]
        }


@pytest.mark.asyncio
async def test_missing_key_returns_clear_error(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    tool = TavilySearchTool(api_key="")

    result = await tool.run(query="anything")

    assert result.status == "error"
    assert "TAVILY_API_KEY" in (result.error or "")


@pytest.mark.asyncio
async def test_results_are_formatted_with_sources(monkeypatch):
    import tavily

    monkeypatch.setattr(tavily, "TavilyClient", FakeTavilyClient)
    tool = TavilySearchTool(api_key="test-key")

    result = await tool.run(query="orchestra agents")

    assert result.status == "success"
    assert "Orchestra docs — https://example.com/docs" in result.content
    assert "About agents" in result.content


def test_bootstrap_prefers_simulated_without_a_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_BACKEND", raising=False)
    assert isinstance(_search_tool(None), WebSearchTool)


def test_bootstrap_uses_tavily_when_key_present(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.delenv("SEARCH_BACKEND", raising=False)
    assert isinstance(_search_tool(None), TavilySearchTool)


def test_bootstrap_honours_explicit_backend(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert isinstance(_search_tool("tavily"), TavilySearchTool)
    assert isinstance(_search_tool("simulated"), WebSearchTool)
