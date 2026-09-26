"""Real-container sandbox checks: code runs, the network is gone, timeouts kill.

Requires a running Docker daemon (pulls python:3.14-slim on first run) and
skips otherwise.
"""
import shutil

import pytest

from tools.sandbox_runner import DockerSandboxRunner

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")
def test_sandbox_runs_code(tmp_path):
    runner = DockerSandboxRunner()

    result = runner.run("print(2 + 2)", workspace=str(tmp_path))

    assert result.exit_code == 0
    assert "4" in result.stdout


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")
def test_sandbox_has_no_network(tmp_path):
    runner = DockerSandboxRunner()
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
        "    print('NETWORK OK')\n"
        "except Exception:\n"
        "    print('NETWORK BLOCKED')\n"
    )

    result = runner.run(code, workspace=str(tmp_path))

    assert "NETWORK BLOCKED" in result.stdout


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")
def test_sandbox_timeout_kills_container(tmp_path):
    runner = DockerSandboxRunner()

    result = runner.run("while True: pass", workspace=str(tmp_path), timeout_seconds=3)

    assert result.timed_out is True
