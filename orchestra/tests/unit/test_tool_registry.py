import pytest
from tools.registry import ToolRegistry, ToolSchema, ToolResult
from tools.builtin.file_tools import FileReadTool, FileWriteTool

@pytest.fixture
def registry():
    return ToolRegistry()

@pytest.fixture
def workspace(tmp_path):
    return str(tmp_path)

@pytest.mark.asyncio
async def test_tool_registration(registry):
    # Create a dummy tool
    from tools.registry import BaseTool
    class DummyTool(BaseTool):
        async def run(self, **kwargs):
            return ToolResult(content="success")
    
    schema = ToolSchema(name="dummy", description="test", parameters={})
    tool = DummyTool(schema)
    registry.register(tool)
    
    assert registry.get_tool("dummy") == tool
    assert len(registry.list_tools()) == 1

@pytest.mark.asyncio
async def test_permission_enforcement(registry):
    from tools.registry import BaseTool
    class DummyTool(BaseTool):
        async def run(self, **kwargs):
            return ToolResult(content="success")
    
    schema = ToolSchema(
        name="restricted", 
        description="test", 
        parameters={}, 
        allowed_specialists=["admin"]
    )
    tool = DummyTool(schema)
    registry.register(tool)
    
    # Permitted specialist
    res = await registry.execute("restricted", "admin")
    assert res.status == "success"
    
    # Unpermitted specialist
    res = await registry.execute("restricted", "guest")
    assert res.status == "error"
    assert "not permitted" in res.error

@pytest.mark.asyncio
async def test_rate_limiting(registry):
    from tools.registry import BaseTool
    class DummyTool(BaseTool):
        async def run(self, **kwargs):
            return ToolResult(content="success")
    
    schema = ToolSchema(
        name="limited", 
        description="test", 
        parameters={}, 
        rate_limit=2
    )
    tool = DummyTool(schema)
    registry.register(tool)
    
    # First two calls should succeed
    assert (await registry.execute("limited", "admin")).status == "success"
    assert (await registry.execute("limited", "admin")).status == "success"
    
    # Third call should fail
    res = await registry.execute("limited", "admin")
    assert res.status == "error"
    assert "Rate limit exceeded" in res.error

@pytest.mark.asyncio
async def test_file_tools_jail(registry, workspace):
    read_tool = FileReadTool(workspace)
    write_tool = FileWriteTool(workspace)
    registry.register(read_tool)
    registry.register(write_tool)
    
    # Test write and then read
    filename = "test.txt"
    content = "Hello World"
    await registry.execute("file_write", "writer", path=filename, content=content)
    
    res = await registry.execute("file_read", "researcher", path=filename)
    assert res.content == content
    
    # Test jail escape attempt
    res = await registry.execute("file_read", "researcher", path="../etc/passwd")
    assert res.status == "error"
    assert "Security violation" in res.error
