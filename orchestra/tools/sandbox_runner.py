"""Docker sandbox runner.

Real isolation for code execution: no network, CPU/memory/pids limits, a
read-only root filesystem with one writable tmpfs at /work, the per-task
workspace mounted there, and a hard timeout that kills the container.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import docker

DEFAULT_IMAGE = os.getenv("ORCHESTRA_SANDBOX_IMAGE", "python:3.14-slim")


def default_docker_client() -> Any:
    """docker.from_env(), but honoring a local colima socket if present.

    docker-py ignores the Docker CLI context, so on a colima setup the daemon
    is unreachable unless DOCKER_HOST points at its socket. Inside the worker
    container the mounted /var/run/docker.sock is used instead.
    """
    if not os.getenv("DOCKER_HOST"):
        colima_socket = Path.home() / ".colima" / "default" / "docker.sock"
        if colima_socket.exists():
            os.environ["DOCKER_HOST"] = f"unix://{colima_socket}"
    return docker.from_env()


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class DockerSandboxRunner:
    def __init__(
        self,
        image: Optional[str] = None,
        client_factory: Optional[Callable[[], Any]] = None,
        workspace_root: Optional[str] = None,
    ) -> None:
        self.image = image or DEFAULT_IMAGE
        self._client_factory = client_factory or default_docker_client
        self.workspace_root = workspace_root

    def run(
        self,
        code: str,
        *,
        workspace: Optional[str] = None,
        timeout_seconds: int = 10,
    ) -> SandboxResult:
        client = self._client_factory()
        target = workspace or self.workspace_root
        volumes: Dict[str, Dict[str, str]] = {}
        if target:
            volumes[str(target)] = {"bind": "/work", "mode": "rw"}

        def create() -> Any:
            return client.containers.create(
                self.image,
                ["python", "-c", code],
                network_disabled=True,
                mem_limit="256m",
                nano_cpus=500_000_000,
                pids_limit=64,
                read_only=True,
                # /work is the per-task workspace bind; /tmp stays writable for
                # runtimes that need scratch space under a read-only rootfs.
                tmpfs={"/tmp": "rw,size=64m"},
                working_dir="/work",
                volumes=volumes,
                detach=True,
            )

        try:
            container = create()
        except docker.errors.ImageNotFound:
            client.images.pull(self.image)
            container = create()

        timed_out = False
        exit_code = -1
        try:
            container.start()
            status = container.wait(timeout=timeout_seconds)
            exit_code = int(status.get("StatusCode", -1))
        except Exception:
            timed_out = True
            try:
                container.kill()
            except Exception:
                pass

        stdout = self._logs(container, stdout=True)
        stderr = self._logs(container, stdout=False)
        try:
            container.remove(force=True)
        except Exception:
            pass

        return SandboxResult(
            stdout=stdout, stderr=stderr, exit_code=exit_code, timed_out=timed_out
        )

    @staticmethod
    def _logs(container: Any, *, stdout: bool) -> str:
        try:
            raw = container.logs(stdout=stdout, stderr=not stdout)
        except Exception:
            return ""
        decoded: str = bytes(raw).decode("utf-8", errors="replace")
        return decoded
