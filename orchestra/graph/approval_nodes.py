"""Replay-safe human approval.

LangGraph replays an interrupted node when the run resumes, so interrupt()
calls live in dedicated nodes that never call an LLM or a tool. A resume only
re-runs the cheap gate and applies the human's decision.

Decisions:
- approve          continue (for plan gates: execute the plan as-is)
- modify           apply the human's edited plan / arguments, then continue
- reject           end the run with an explanatory final response
- take_over        mark the task for a human and end the agent's run
"""
import logging
from typing import Any, Dict, List, Optional

from graph.hitl import hitl_manager
from graph.validate import validate_plan
from observability.spans import span

logger = logging.getLogger(__name__)


def plan_approval_payload(state: Dict[str, Any], confidence: float) -> Dict[str, Any]:
    plan = state.get("plan") or []
    return hitl_manager.create_interrupt_payload(
        task_id=str(state.get("task_id", "unknown")),
        trigger="low_confidence_plan",
        context={
            "plan_confidence": confidence,
            "plan": plan,
            "task_description": state.get("task_description"),
        },
        proposed_action=f"Execute plan with {len(plan)} subtasks",
    )


def action_approval_payload(
    task_id: str,
    subtask_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    signature: str,
    trigger: str = "sensitive_tool_requested",
) -> Dict[str, Any]:
    return hitl_manager.create_interrupt_payload(
        task_id=task_id,
        trigger=trigger,
        context={
            "subtask_id": subtask_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "signature": signature,
        },
        proposed_action=f"Run sensitive tool {tool_name} on subtask {subtask_id}",
    )


def failure_approval_payload(
    task_id: str, subtask_id: str, error: Optional[str], attempts: int
) -> Dict[str, Any]:
    return hitl_manager.create_interrupt_payload(
        task_id=task_id,
        trigger="second_failure",
        context={
            "subtask_id": subtask_id,
            "error": error,
            "attempts": attempts,
        },
        proposed_action=(
            f"Subtask {subtask_id} failed {attempts} times. Approve the partial "
            "output, retry once more, or reject the subtask."
        ),
    )


def apply_plan_decision(
    decision: Optional[Dict[str, Any]], state: Dict[str, Any]
) -> Dict[str, Any]:
    """Turn a human decision on the plan gate into a state update."""
    decision = decision or {}
    action = decision.get("action", "approve")
    plan = state.get("plan") or []

    if action == "approve":
        return {}

    if action == "modify":
        modified = decision.get("plan") or plan
        errors = validate_plan(modified)
        if errors:
            return {
                "plan": [],
                "final_response": (
                    "The human-modified plan failed validation "
                    f"({'; '.join(errors)}), so the run stopped."
                ),
            }
        return {"plan": modified, "shared_context": "Plan modified by a human."}

    if action == "take_over":
        return {
            "plan": [],
            "human_takeover": True,
            "final_response": "A human took over this run; the agent has stopped.",
        }

    # reject (or anything unrecognised) stops the run with a clear response.
    return {
        "plan": [],
        "final_response": "The plan was rejected by a human reviewer; the run stopped.",
    }


def apply_action_decision(
    decision: Optional[Dict[str, Any]], pending: Dict[str, Any]
) -> Dict[str, Any]:
    """Turn a human decision on a sensitive action into the updated pending entry."""
    entry = dict(pending)
    decision = decision or {}
    action = decision.get("action", "reject")
    entry["decision"] = decision
    if action in {"approve", "modify"}:
        entry["status"] = "approved"
        if decision.get("arguments") is not None:
            entry["arguments"] = decision["arguments"]
    else:
        entry["status"] = "rejected"
    return entry


def apply_failure_decision(
    decision: Optional[Dict[str, Any]], subtask_id: str
) -> Dict[str, Any]:
    """Human decision on a repeatedly failing subtask."""
    action = (decision or {}).get("action", "reject")
    if action == "approve":
        return {"accept_subtask": subtask_id}
    if action == "retry":
        return {"retry_subtask": subtask_id}
    return {"reject_subtask": subtask_id}


class ApprovalGate:
    """Interrupt helpers kept together for testability."""

    @staticmethod
    def with_span(name: str, **attrs: Any):
        return span(name, **attrs)


async def collect_pending(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        info
        for info in (state.get("pending_approvals") or {}).values()
        if info.get("status") == "pending"
    ]
