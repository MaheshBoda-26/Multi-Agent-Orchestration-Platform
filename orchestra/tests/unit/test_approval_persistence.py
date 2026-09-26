"""Approvals persistence and the decide->resume wiring.

Covers the interrupt-to-row bridge (record_interrupt_approvals), idempotent
upserts keyed {task_id}:{signature}, and resolution recorded before the resume
message is enqueued. DB tests use the shared postgres_pool fixture and skip
without Postgres.
"""
import json
import uuid

import pytest

from api.routes import (
    ApprovalDecision,
    record_interrupt_approvals,
    resolve_approval,
    get_approval,
)
from graph.hitl import hitl_manager


pytestmark = pytest.mark.usefixtures("postgres_pool")


def _interrupt_payload(task_id: str, trigger: str, signature: str | None = None):
    context = {"subtask_id": "t1"}
    if signature:
        context["signature"] = signature
    return hitl_manager.create_interrupt_payload(
        task_id=task_id,
        trigger=trigger,
        context=context,
        proposed_action="do the thing",
    )


class _FakeInterrupt:
    """LangGraph delivers Interrupt objects with a ``value`` attribute."""

    def __init__(self, value):
        self.value = value


@pytest.mark.asyncio
async def test_record_interrupt_creates_pending_row(postgres_pool):
    task_id = str(uuid.uuid4())
    payload = _interrupt_payload(task_id, "low_confidence_plan", signature="sig1")

    ids = await record_interrupt_approvals(
        postgres_pool, [_FakeInterrupt(payload)]
    )

    assert ids == [f"{task_id}:sig1"]
    row = await postgres_pool.fetchrow(
        "SELECT task_id, trigger, status FROM approvals WHERE id = $1", ids[0]
    )
    assert row["task_id"] == task_id
    assert row["trigger"] == "low_confidence_plan"
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_record_interrupt_is_idempotent(postgres_pool):
    task_id = str(uuid.uuid4())
    payload = _interrupt_payload(task_id, "low_confidence_plan", signature="sig2")

    first = await record_interrupt_approvals(postgres_pool, [_FakeInterrupt(payload)])
    second = await record_interrupt_approvals(postgres_pool, [_FakeInterrupt(payload)])

    assert first == second
    count = await postgres_pool.fetchval(
        "SELECT COUNT(*) FROM approvals WHERE id = $1", first[0]
    )
    assert count == 1


@pytest.mark.asyncio
async def test_resolved_approval_is_not_overwritten(postgres_pool):
    """A stale re-pause must not resurrect a decision a human already made."""
    task_id = str(uuid.uuid4())
    payload = _interrupt_payload(task_id, "sensitive_tool_requested", signature="sig3")
    approval_id = (await record_interrupt_approvals(
        postgres_pool, [_FakeInterrupt(payload)]
    ))[0]

    await resolve_approval(postgres_pool, approval_id, ApprovalDecision(action="reject"))
    # Same gate re-pauses later (e.g. worker redelivery) with identical content.
    await record_interrupt_approvals(postgres_pool, [_FakeInterrupt(payload)])

    row = await postgres_pool.fetchrow(
        "SELECT status FROM approvals WHERE id = $1", approval_id
    )
    assert row["status"] == "reject"


@pytest.mark.asyncio
async def test_payload_without_signature_gets_stable_hash_id(postgres_pool):
    task_id = str(uuid.uuid4())
    payload = _interrupt_payload(task_id, "second_failure")

    ids = await record_interrupt_approvals(postgres_pool, [_FakeInterrupt(payload)])

    assert ids and ids[0].startswith(f"{task_id}:")
    approval = await get_approval(postgres_pool, ids[0])
    assert approval is not None
    assert approval.trigger == "second_failure"


@pytest.mark.asyncio
async def test_resolution_round_trips_as_json(postgres_pool):
    task_id = str(uuid.uuid4())
    payload = _interrupt_payload(task_id, "low_confidence_plan", signature="sig5")
    approval_id = (await record_interrupt_approvals(
        postgres_pool, [_FakeInterrupt(payload)]
    ))[0]

    decision = ApprovalDecision(
        action="modify",
        modified_plan=[{"id": "m1", "description": "edited", "specialist": "writer"}],
    )
    await resolve_approval(postgres_pool, approval_id, decision)

    approval = await get_approval(postgres_pool, approval_id)
    assert approval.status == "modify"
    assert approval.resolution["modified_plan"] == decision.modified_plan
    # The worker reads this dict straight out of the row for Command(resume=...).
    json.loads(json.dumps(approval.resolution))
