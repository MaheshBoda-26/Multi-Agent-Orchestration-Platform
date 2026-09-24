import asyncio
from tools.registry import BaseTool, ToolSchema, ToolResult

class WebSearchTool(BaseTool):
    """Simulates a web search tool."""
    
    def __init__(self):
        schema = ToolSchema(
            name="web_search",
            description="Search the web for information.",
            parameters={"query": {"type": "string", "description": "Search query"}},
            allowed_specialists=["researcher", "data_analyst"]
        )
        super().__init__(schema)

    async def run(self, query: str, **kwargs) -> ToolResult:
        # Simulated search results
        return ToolResult(
            content=f"Search results for '{query}':\n1. [Result 1] Orchestra is a multi-agent platform.\n2. [Result 2] AI agents are evolving rapidly."
        )

class HttpCallTool(BaseTool):
    """Performs an HTTP GET request to an allowed domain."""
    
    def __init__(self, allowed_domains: list[str]):
        self.allowed_domains = allowed_domains
        schema = ToolSchema(
            name="http_get",
            description="Perform an HTTP GET request.",
            parameters={"url": {"type": "string", "description": "The URL to fetch"}},
            allowed_specialists=["researcher"]
        )
        super().__init__(schema)

    async def run(self, url: str, **kwargs) -> ToolResult:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        
        if domain not in self.allowed_domains:
            return ToolResult(content="", status="error", error=f"Domain {domain} is not in the allowlist")

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                return ToolResult(content=response.text)
        except Exception as e:
            return ToolResult(content="", status="error", error=str(e))
