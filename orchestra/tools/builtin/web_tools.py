import asyncio
import ipaddress
import os
import socket
from typing import Any, List, Optional
from urllib.parse import urlparse

import httpx

from tools.registry import BaseTool, ToolResult, ToolSchema

MAX_REDIRECTS = 3


def _is_blocked_address(host: str) -> bool:
    """True when the host resolves to a loopback/private/link-local address."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True  # unresolvable hosts are not allowed through either
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            return True
    return False


class WebSearchTool(BaseTool):
    """Simulates a web search tool."""

    def __init__(self) -> None:
        schema = ToolSchema(
            name="web_search",
            description="Search the web for information.",
            parameters={"query": {"type": "string", "description": "Search query"}},
            allowed_specialists=["researcher", "data_analyst"]
        )
        super().__init__(schema)

    async def run(self, query: str = "", **kwargs: Any) -> ToolResult:
        # Simulated search results (real Tavily integration is a later phase).
        return ToolResult(
            content=f"Search results for '{query}':\n1. [Result 1] Orchestra is a multi-agent platform.\n2. [Result 2] AI agents are evolving rapidly."
        )


class TavilySearchTool(BaseTool):
    """Real web search through Tavily (the approved search library).

    Fails with a clear error instead of silently returning nothing when no
    API key is configured; bootstrap falls back to the simulated tool only
    when no key exists.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        schema = ToolSchema(
            name="web_search",
            description="Search the web for information.",
            parameters={"query": {"type": "string", "description": "Search query"}},
            allowed_specialists=["researcher", "data_analyst"],
        )
        super().__init__(schema)
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")

    async def run(self, query: str = "", **kwargs: Any) -> ToolResult:
        if not self.api_key:
            return ToolResult(
                content="", status="error",
                error="search not configured: set TAVILY_API_KEY",
            )
        try:
            from tavily import TavilyClient
        except ImportError:
            return ToolResult(
                content="", status="error", error="tavily-python is not installed"
            )

        client = TavilyClient(api_key=self.api_key)
        try:
            response = await asyncio.to_thread(client.search, query, max_results=5)
        except Exception as exc:
            return ToolResult(content="", status="error", error=f"search failed: {exc}")

        results = (response or {}).get("results", [])
        if not results:
            return ToolResult(content=f"No results for '{query}'.")
        formatted = "\n\n".join(
            f"{r.get('title', 'Untitled')} — {r.get('url', '')}\n{r.get('content', '')}"
            for r in results
        )
        return ToolResult(content=f"Search results:\n\n{formatted}")


class HttpCallTool(BaseTool):
    """Performs an HTTP GET request to an allowlisted domain.

    Every redirect hop is re-checked against the allowlist and against private
    address ranges, so a public allowlisted host cannot bounce the request to
    localhost or to a non-allowlisted domain (SSRF, TRD section 7).
    """

    def __init__(self, allowed_domains: List[str]) -> None:
        self.allowed_domains = {d.lower().removeprefix("www.") for d in allowed_domains}
        schema = ToolSchema(
            name="http_get",
            description="Perform an HTTP GET request.",
            parameters={"url": {"type": "string", "description": "The URL to fetch"}},
            allowed_specialists=["researcher"]
        )
        super().__init__(schema)

    def _rejection(self, url: str) -> Optional[str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return f"Scheme {parsed.scheme or '(none)'} is not allowed"
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if not host:
            return "URL has no host"
        if host not in self.allowed_domains:
            return f"Domain {host} is not in the allowlist"
        if _is_blocked_address(host):
            return f"Domain {host} resolves to a private or reserved address"
        return None

    async def run(self, url: str = "", **kwargs: Any) -> ToolResult:
        target = url

        async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
            for _ in range(MAX_REDIRECTS + 1):
                reason = self._rejection(target)
                if reason:
                    return ToolResult(content="", status="error", error=reason)

                try:
                    response = await client.get(target)
                except Exception as e:
                    return ToolResult(content="", status="error", error=str(e))

                if response.is_redirect and response.headers.get("location"):
                    target = str(httpx.URL(target).join(response.headers["location"]))
                    continue
                return ToolResult(content=response.text)

        return ToolResult(content="", status="error", error="Too many redirects")
