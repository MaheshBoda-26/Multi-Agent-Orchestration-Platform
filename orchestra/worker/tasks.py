"""Celery entrypoints for graph runs.

`run_task` is durable: if the worker is killed mid-run, Celery redelivers the
message (late ack) and this function notices the existing LangGraph checkpoint,
so `ainvoke(None, config)` continues from the last completed super-step rather
than repeating finished work.
"""
import asyncio
import functools
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import asyncpg
from langchain_core.runnables import RunnableConfig

from api import repository, run_metadata
from graph.build import OrchestraGraph
from graph.checkpointer import create_checkpointer
from llm.factory import build_provider
from llm.recording import RecordingLLMProvider, RunRecorder
from migrations import run_migrations
from observability.context import set_current_task_id
from observability.setup import configure_tracing, flush_tracing
from observability.spans import span
from tools.bootstrap import build_tool_registry
from tools.execution import execute_tool
from worker.celery_app import celery_app

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql://orchestra:orchestra@localhost:5432/orchestra"


def _database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def initial_state(task_id: str, description: str) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "task_description": description,
        "plan": None,
        "results": {},
        "attempts": {},
        "review_feedback": {},
        "shared_context": "",
        "final_response": None,
    }


def _serialize_results(results: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        for key, value in results.items()
    }


@celery_app.task(name="orchestra.run_task")
def run_task(task_id: str, description: str) -> None:
    """Run (or resume) a task's graph and persist the outcome."""
    asyncio.run(_run_task_async(task_id, description))


async def _run_task_async(task_id: str, description: str) -> None:
    pool: Optional[asyncpg.Pool] = None
    ckpt_pool = None
    try:
        pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=5)
        await run_migrations(pool)
        configure_tracing(_database_url())
        set_current_task_id(task_id)

        task_uuid = uuid.UUID(task_id)
        row = await repository.get_task(pool, task_uuid)
        if row is None:
            logger.warning("Task %s disappeared before it ran; skipping", task_id)
            return

        ckpt_pool, checkpointer = await create_checkpointer(_database_url())
        # Every task gets its own jailed workspace, registry and audited executor.
        registry = build_tool_registry(task_id, search_backend=os.getenv("SEARCH_BACKEND"))
        tool_executor = functools.partial(execute_tool, registry, pool, task_id=task_id)
        recorder = RunRecorder()
        provider = RecordingLLMProvider(build_provider(), recorder)
        graph = OrchestraGraph(
            provider, checkpointer=checkpointer, tool_executor=tool_executor
        )
        config: RunnableConfig = {"configurable": {"thread_id": task_id}}

        await repository.set_task_status(pool, task_uuid, "running")
        has_checkpoint = await checkpointer.aget_tuple(config) is not None

        run_id = await run_metadata.latest_run_id(pool, task_uuid)
        if run_id is None:
            run_id = uuid.uuid4()
            await run_metadata.start_run(pool, run_id, task_uuid, description)

        started = time.monotonic()
        with span("task.run"):
            if has_checkpoint:
                logger.info("Resuming task %s from its last checkpoint", task_id)
                # durability="sync" commits every super-step before the next one
                # starts; the default (async) loses recent writes on SIGKILL.
                final_state = await graph.workflow.ainvoke(None, config, durability="sync")
            else:
                final_state = await graph.workflow.ainvoke(
                    initial_state(task_id, description), config, durability="sync"
                )
        flush_tracing()

        plan = final_state.get("plan") or []
        if plan:
            await repository.save_task_plan(pool, task_uuid, plan)

        results: Dict[str, Any] = final_state.get("results") or {}
        await repository.complete_task(pool, task_uuid, {
            "final_response": final_state.get("final_response"),
            "subtasks": _serialize_results(results),
        })
        await run_metadata.complete_run(
            pool, run_id,
            prompt_tokens=recorder.prompt_tokens,
            completion_tokens=recorder.completion_tokens,
            cost_usd=recorder.cost_usd,
            latency_ms=int((time.monotonic() - started) * 1000),
            model_breakdown=recorder.model_breakdown,
        )
        logger.info("Task %s completed in %.2fs", task_id, time.monotonic() - started)
    except Exception as exc:
        logger.exception("Task %s failed", task_id)
        if pool is not None:
            task_uuid = uuid.UUID(task_id)
            try:
                await repository.fail_task(pool, task_uuid, str(exc))
                run_id = await run_metadata.latest_run_id(pool, task_uuid)
                if run_id is not None:
                    await run_metadata.fail_run(pool, run_id, str(exc))
            except Exception:
                logger.exception("Could not record the failure for task %s", task_id)
        raise
    finally:
        set_current_task_id(None)
        if ckpt_pool is not None:
            await ckpt_pool.close()
        if pool is not None:
            await pool.close()
