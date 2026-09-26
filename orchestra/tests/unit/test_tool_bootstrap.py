from tools.bootstrap import SENSITIVE_TOOLS, build_tool_registry
from tools.permissions import permission_manager


def test_registry_contains_builtin_tools(tmp_path):
    registry = build_tool_registry("task-1", workspace_root=str(tmp_path))
    names = {schema.name for schema in registry.list_tools()}
    assert names == {"web_search", "http_get", "file_read", "file_write", "code_execute"}


def test_workspace_is_per_task(tmp_path):
    build_tool_registry("task-a", workspace_root=str(tmp_path))
    build_tool_registry("task-b", workspace_root=str(tmp_path))
    assert (tmp_path / "task-a").is_dir()
    assert (tmp_path / "task-b").is_dir()


def test_sensitive_tools_are_marked(tmp_path):
    permission_manager._sensitive_tools.clear()
    build_tool_registry("task-1", workspace_root=str(tmp_path))

    for name in SENSITIVE_TOOLS:
        assert permission_manager.is_sensitive(name), name
    assert not permission_manager.is_sensitive("file_read")
    assert not permission_manager.is_sensitive("web_search")


def test_file_tools_are_jailed_to_the_task_workspace(tmp_path):
    registry = build_tool_registry("task-x", workspace_root=str(tmp_path))
    file_write = registry.get_tool("file_write")
    file_read = registry.get_tool("file_read")
    assert file_write is not None and file_read is not None
    assert file_write.workspace_root == str(tmp_path / "task-x")  # type: ignore[attr-defined]
    assert file_read.workspace_root == str(tmp_path / "task-x")  # type: ignore[attr-defined]
