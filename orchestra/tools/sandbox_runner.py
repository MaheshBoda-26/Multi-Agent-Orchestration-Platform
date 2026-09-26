"""Docker sandbox runner.

Real isolation for code execution: no network, CPU/memory/pids limits, a
read-only root filesystem with one writable tmpfs at /work, the per-task
workspace mounted there, and a hard timeout that kills the container.
"""
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import docker

DEFAULT_IMAGE = os.getenv("ORCHESTRA_SANDBOX_IMAGE", "python:3.14-slim")


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
        self._client_factory = client_factory or docker.from_env
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

        container = client.containers.create(
            self.image,
            ["python", "-c", code],
            network_disabled=True,
            mem_limit="256m",
            nano_cpus=500_000_000,
            pids_limit=64,
            read_only=True,
            tmpfs={"/work": "rw,size=64m"},
            working_dir="/work",
            volumes=volumes,
            detach=True,
        )

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
            return container.logs(stdout=stdout, stderr=not stdout).decode(
                "utf-8", errors="replace"
            )
        except Exception:
            return ""
