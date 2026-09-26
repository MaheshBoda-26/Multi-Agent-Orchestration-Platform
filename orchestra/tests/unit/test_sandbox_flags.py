from typing import Any, Dict

import pytest

from tools.builtin.sandbox import CodeExecutionTool
from tools.sandbox_runner import DockerSandboxRunner


class FakeContainer:
    def __init__(self) -> None:
        self.started = False
        self.killed = False
        self.removed = False
        self.raise_on_wait = False

    def start(self) -> None:
        self.started = True

    def wait(self, timeout: int = 0) -> Dict[str, int]:
        if self.raise_on_wait:
            raise RuntimeError("timed out")
        return {"StatusCode": 0}

    def logs(self, stdout: bool = True, stderr: bool = False) -> bytes:
        return b"4\n" if stdout else b""

    def kill(self) -> None:
        self.killed = True

    def remove(self, force: bool = False) -> None:
        self.removed = True


class FakeClient:
    def __init__(self, container: FakeContainer) -> None:
        self.container = container
        self.containers = self
        self.last_create: Dict[str, Any] = {}

    def create(self, image: str, command: Any, **kwargs: Any) -> FakeContainer:
        self.last_create = {"image": image, "command": command, **kwargs}
        return self.container


def test_runner_uses_full_isolation_flags(tmp_path):
    container = FakeContainer()
    client = FakeClient(container)
    runner = DockerSandboxRunner(client_factory=lambda: client)

    result = runner.run("print(2+2)", workspace=str(tmp_path))

    assert result.exit_code == 0
    assert result.stdout == "4\n"
    assert container.started and container.removed
    spec = client.last_create
    assert spec["command"] == ["python", "-c", "print(2+2)"]
    assert spec["network_disabled"] is True
    assert spec["mem_limit"] == "256m"
    assert spec["nano_cpus"] == 500_000_000
    assert spec["pids_limit"] == 64
    assert spec["read_only"] is True
    assert spec["tmpfs"] == {"/tmp": "rw,size=64m"}
    assert spec["working_dir"] == "/work"
    assert spec["volumes"] == {str(tmp_path): {"bind": "/work", "mode": "rw"}}


def test_timeout_kills_the_container(tmp_path):
    container = FakeContainer()
    container.raise_on_wait = True
    client = FakeClient(container)
    runner = DockerSandboxRunner(client_factory=lambda: client)

    result = runner.run("while True: pass", workspace=str(tmp_path), timeout_seconds=3)

    assert result.timed_out is True
    assert container.killed is True
    assert container.removed is True


@pytest.mark.asyncio
async def test_code_execution_tool_reports_timeout(monkeypatch, tmp_path):
    container = FakeContainer()
    container.raise_on_wait = True
    client = FakeClient(container)
    tool = CodeExecutionTool(
        runner=DockerSandboxRunner(client_factory=lambda: client), workspace=str(tmp_path)
    )

    result = await tool.run(code="while True: pass")

    assert result.status == "error"
    assert "timed out" in (result.error or "")
