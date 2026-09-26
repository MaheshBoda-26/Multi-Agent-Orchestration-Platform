"""Celery entrypoints for graph runs.

`run_task` is durable: if the worker is killed mid-run, Celery redelivers the
message (late ack) and this function notices the existing LangGraph checkpoint,
so `ainvoke(None, config)` continues from the last completed super-step rather
than repeating finished work.

`resume_task` applies a human decision recorded by the API: it replays the
paused interrupt node with `Command(resume=decision)`, which is cheap (approval
nodes never call an LLM), and then drives the graph to completion.
"""
import asyncio
import functools
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import asyncpg
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from api import repository, run_metadata
from api.routes import record_interrupt_approvals
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


@celery_app.task(name="orchestra.resume_task")
def resume_task(task_id: str, approval_id: str) -> None:
    """Resume a paused graph with the decision a human recorded on an approval."""
    asyncio.run(_resume_task_async(task_id, approval_id))


async def _resume_task_async(task_id: str, approval_id: str) -> None:
    pool: Optional[asyncpg.Pool] = None
    try:
        pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=5)
        await run_migrations(pool)
        configure_tracing(_database_url())
        set_current_task_id(task_id)
        task_uuid = uuid.UUID(task_id)

        row = await pool.fetchrow(
            "SELECT resolution FROM approvals WHERE id = $1", approval_id
        )
        if row is None or row["resolution"] is None:
            logger.warning(
                "Approval %s has no recorded decision; not resuming task %s",
                approval_id, task_id,
            )
            return
        resolution = row["resolution"]
        if isinstance(resolution, str):
            resolution = json.loads(resolution)

        task_row = await repository.get_task(pool, task_uuid)
        description = (task_row or {}).get("request") or "resumed task"
        await repository.set_task_status(pool, task_uuid, "running")
        await _run_graph(
            pool, task_uuid, description, resume_command=Command(resume=resolution)
        )
    except Exception:
        logger.exception("Resume of task %s failed", task_id)
        if pool is not None:
            try:
                task_uuid = uuid.UUID(task_id)
                await repository.fail_task(
                    pool, task_uuid, "resume failed after human decision"
                )
            except Exception:
                logger.exception("Could not record the resume failure for %s", task_id)
        raise
    finally:
        set_current_task_id(None)
        if pool is not None:
            await pool.close()


async def _run_task_async(task_id: str, description: str) -> None:
    pool: Optional[asyncpg.Pool] = None
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

        await repository.set_task_status(pool, task_uuid, "running")
        await _run_graph(pool, task_uuid, description)
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
        if pool is not None:
            await pool.close()


async def _run_graph(
    pool: asyncpg.Pool,
    task_uuid: uuid.UUID,
    description: str,
    resume_command: Optional[Command] = None,
) -> None:
    """Drive one graph run (fresh, crash-resume, or human-resume) to a stop.

    A stop is either completion or a pause: when the graph ends on an
    interrupt, the pending decision is persisted as approvals rows, the task is
    marked ``awaiting_human`` and nothing else happens until the API hands the
    decision to :func:`resume_task`.
    """
    ckpt_pool, checkpointer = await create_checkpointer(_database_url())
    try:
        # Every task gets its own jailed workspace, registry and audited executor.
        registry = build_tool_registry(
            str(task_uuid), search_backend=os.getenv("SEARCH_BACKEND")
        )
        tool_executor = functools.partial(
            execute_tool, registry, pool, task_id=str(task_uuid)
        )
        recorder = RunRecorder()
        provider = RecordingLLMProvider(build_provider(), recorder)
        graph = OrchestraGraph(
            provider, checkpointer=checkpointer, tool_executor=tool_executor
        )
        config: RunnableConfig = {"configurable": {"thread_id": str(task_uuid)}}

        has_checkpoint = await checkpointer.aget_tuple(config) is not None
        run_id = await run_metadata.latest_run_id(pool, task_uuid)
        if run_id is None:
            run_id = uuid.uuid4()
            await run_metadata.start_run(pool, run_id, task_uuid, description)

        started = time.monotonic()
        with span("task.run"):
            if resume_command is not None:
                invoke_input: Any = resume_command
            elif has_checkpoint:
                logger.info("Resuming task %s from its last checkpoint", task_uuid)
                invoke_input = None
            else:
                invoke_input = initial_state(str(task_uuid), description)
            # durability="sync" commits every super-step before the next one
            # starts; the default (async) loses recent writes on SIGKILL.
            final_state = await graph.workflow.ainvoke(
                invoke_input, config, durability="sync"
            )
        flush_tracing()

        interrupts = (
            final_state.get("__interrupt__") if isinstance(final_state, dict) else None
        )
        if interrupts:
            await record_interrupt_approvals(pool, interrupts)
            await repository.set_task_status(pool, task_uuid, "awaiting_human")
            await run_metadata.mark_paused(pool, run_id)
            logger.info("Task %s paused awaiting a human decision", task_uuid)
            return

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
        logger.info("Task %s completed in %.2fs", task_uuid, time.monotonic() - started)
    finally:
        await ckpt_pool.close()
