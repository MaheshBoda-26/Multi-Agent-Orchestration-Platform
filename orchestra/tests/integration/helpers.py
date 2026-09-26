"""Shared helpers for integration tests that need Postgres, Redis and a worker.

The broker is isolated on its own Redis DB (default /15) and flushed before
use, so unacked messages left behind by killed workers cannot leak between
tests.
"""
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

import asyncpg

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
TEST_BROKER_URL = os.getenv(
    "TEST_CELERY_BROKER_URL", REDIS_URL.rsplit("/", 1)[0] + "/15"
)
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://orchestra:orchestra@localhost:5432/orchestra"
)
ORCHESTRA_ROOT = Path(__file__).resolve().parents[2]


def _redis_client():
    import redis

    return redis.Redis.from_url(TEST_BROKER_URL, socket_connect_timeout=1)


def redis_available() -> bool:
    """Ping the isolated broker DB and flush it so tests start clean."""
    try:
        client = _redis_client()
        client.ping()
        client.flushdb()
        return True
    except Exception:
        return False


async def postgres_available() -> bool:
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.close()
        return True
    except Exception:
        return False


def spawn_worker(
    env_overrides: Dict[str, str],
    log_file: Path,
    pool: str = "solo",
) -> subprocess.Popen:
    """Start a real Celery worker subprocess on the isolated broker DB."""
    env = dict(os.environ)
    env.update({
        "CELERY_BROKER_URL": TEST_BROKER_URL,
        "DATABASE_URL": DATABASE_URL,
        "LLM_PROVIDER": "fake",
        "PYTHONUNBUFFERED": "1",
        **env_overrides,
    })
    output = open(log_file, "w", encoding="utf-8")
    return subprocess.Popen(
        [
            sys.executable, "-m", "celery",
            "-A", "worker.celery_app", "worker",
            f"--pool={pool}", "--loglevel=info", "--without-gossip",
        ],
        cwd=ORCHESTRA_ROOT,
        env=env,
        stdout=output,
        stderr=subprocess.STDOUT,
    )


def wait_for_worker(log_file: Path, timeout: float = 45.0) -> bool:
    """Wait for the worker's 'ready.' banner line (control-ping is flaky)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if log_file.exists() and "ready." in log_file.read_text(errors="ignore"):
            return True
        time.sleep(0.5)
    return False


def stop_worker(proc: Optional[subprocess.Popen]) -> None:
    if proc is not None and proc.poll() is None:
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)


async def wait_for_status(
    pool: asyncpg.Pool,
    task_id: uuid.UUID,
    status: str,
    timeout: float = 90.0,
) -> bool:
    """Wait until the task row reaches one specific status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = await pool.fetchval("SELECT status FROM tasks WHERE id = $1", task_id)
        if current == status:
            return True
        time.sleep(0.5)
    return False


async def wait_for_terminal(
    pool: asyncpg.Pool, task_id: uuid.UUID, timeout: float = 90.0
) -> Optional[str]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = await pool.fetchval("SELECT status FROM tasks WHERE id = $1", task_id)
        if status in {"completed", "failed", "cancelled"}:
            return status
        time.sleep(0.5)
    return None


async def cleanup_task(pool: asyncpg.Pool, task_id: uuid.UUID) -> None:
    """Remove a test task and every row it produced."""
    await pool.execute("DELETE FROM run_metadata WHERE task_id = $1", task_id)
    await pool.execute("DELETE FROM tasks WHERE id = $1", task_id)
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        await pool.execute(f"DELETE FROM {table} WHERE thread_id = $1", str(task_id))
