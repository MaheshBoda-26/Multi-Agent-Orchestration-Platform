import logging
from typing import Any, Dict, List, Optional, Union

from langgraph.graph import StateGraph, END
from langgraph.types import Send

from agents.supervisor import SupervisorAgent
from agents.specialists import SpecialistAgent, SPECIALIST_CONFIGS
from agents.reviewer import ReviewerAgent
from graph.state import GraphState, SubtaskResult
from graph.validate import validate_plan
from graph.approval_nodes import (
    action_approval_payload,
    apply_action_decision,
    apply_plan_decision,
    failure_approval_payload,
    plan_approval_payload,
)
from llm.provider import LLMProvider
from observability.spans import span
from tools.execution import ApprovalRequired, tool_signature
from tools.registry import ToolResult

logger = logging.getLogger(__name__)

# One initial run plus one reviewer-driven retry, per rules.md error handling.
MAX_SUBTASK_ATTEMPTS = 2
# Plans below this confidence pause for human approval once HITL is durable.
LOW_CONFIDENCE_THRESHOLD = 0.6


class OrchestraGraph:
    """Supervisor plans, independent subtasks run in parallel, a reviewer gates
    each output, then a synthesis step writes the final response.

    Flow: supervisor -> dispatch -> (Send execute_subtask xN) -> review -> dispatch
    ... -> synthesize. ``dispatch`` is the single fan-in point that schedules the
    next batch, so no two branches can schedule the same subtask twice.
    """

    def __init__(
        self,
        llm: LLMProvider,
        hitl_enabled: Optional[bool] = None,
        checkpointer: Any = None,
        tool_executor: Any = None,
    ):
        self.llm = llm
        self.checkpointer = checkpointer
        # Async callable(subtask_id=, specialist=, tool_name=, arguments=,
        # approved_signature=) -> ToolResult, provided by the worker.
        self.tool_executor = tool_executor
        # interrupt() needs a checkpointer to pause and resume. Default to on
        # whenever one is attached; callers can still force it off for tests.
        self.hitl_enabled = bool(checkpointer) if hitl_enabled is None else hitl_enabled
        self.supervisor = SupervisorAgent(llm)
        self.specialists = {
            name: SpecialistAgent(config, llm)
            for name, config in SPECIALIST_CONFIGS.items()
        }
        self.reviewer = ReviewerAgent(llm, threshold=0.75)
        self.workflow = self._build_graph()

    # ------------------------------------------------------------------ graph

    def route_after_review(self, state: GraphState) -> str:
        """Order of precedence: pending action, then undecided escalation."""
        pending = [
            info for info in (state.get("pending_approvals") or {}).values()
            if info.get("status") == "pending"
        ]
        if pending:
            return "action_approval"
        if self.hitl_enabled:
            decisions = state.get("failure_decisions") or {}
            for subtask_id, result in (state.get("results") or {}).items():
                if result.status == "escalate" and subtask_id not in decisions:
                    return "failure_approval"
        return "dispatch"

    async def node_action_approval(self, state: GraphState) -> Dict[str, Any]:
        """One interrupt for the first pending sensitive action."""
        pending = {
            signature: info
            for signature, info in (state.get("pending_approvals") or {}).items()
            if info.get("status") == "pending"
        }
        if not pending:
            return {}
        signature, info = next(iter(pending.items()))
        payload = action_approval_payload(
            task_id=str(state.get("task_id", "unknown")),
            subtask_id=str(info.get("subtask_id", "unknown")),
            tool_name=str(info.get("tool", "unknown")),
            arguments=info.get("arguments") or {},
            signature=signature,
        )
        with span("approval.action_gate", tool_name=payload["context"]["tool_name"]):
            decision = interrupt(payload)
        return {"pending_approvals": {signature: apply_action_decision(decision, info)}}

    async def node_failure_approval(self, state: GraphState) -> Dict[str, Any]:
        """Ask a human what to do about a subtask that failed twice."""
        results: Dict[str, SubtaskResult] = state.get("results") or {}
        attempts: Dict[str, int] = state.get("attempts") or {}
        decisions: Dict[str, str] = state.get("failure_decisions") or {}
        target = next(
            (
                sid for sid, result in results.items()
                if result.status == "escalate" and sid not in decisions
            ),
            None,
        )
        if target is None:
            return {}
        result = results[target]
        payload = failure_approval_payload(
            task_id=str(state.get("task_id", "unknown")),
            subtask_id=target,
            error=result.error,
            attempts=attempts.get(target, MAX_SUBTASK_ATTEMPTS),
        )
        with span("approval.failure_gate", subtask_id=target):
            decision = interrupt(payload)
        action = (decision or {}).get("action", "reject")
        if action == "approve":
            return {
                "results": {target: result.model_copy(update={"status": "accepted"})},
                "failure_decisions": {target: "approve"},
            }
        if action == "retry":
            return {
                "results": {target: result.model_copy(update={"status": "retry"})},
                "failure_decisions": {target: "retry"},
            }
        return {"failure_decisions": {target: "reject"}}

    def _build_graph(self) -> Any:
        builder = StateGraph(GraphState)

        # LangGraph's node generics cannot express our partial-state node
        # signatures, so registrations go through an Any-typed alias.
        add_node: Any = builder.add_node
        add_node("supervisor", self.node_supervisor)
        add_node("plan_approval", self.node_plan_approval)
        add_node("dispatch", self.node_dispatch)
        add_node("execute_subtask", self.node_execute_subtask)
        add_node("review", self.node_review)
        add_node("action_approval", self.node_action_approval)
        add_node("failure_approval", self.node_failure_approval)
        add_node("synthesize", self.node_synthesize)

        builder.set_entry_point("supervisor")
        builder.add_edge("supervisor", "plan_approval")
        builder.add_edge("plan_approval", "dispatch")
        builder.add_conditional_edges(
            "dispatch",
            self.route_next_subtasks,
            {"execute_subtask": "execute_subtask", "synthesize": "synthesize"},
        )
        builder.add_edge("execute_subtask", "review")
        builder.add_conditional_edges(
            "review",
            self.route_after_review,
            {
                "action_approval": "action_approval",
                "failure_approval": "failure_approval",
                "dispatch": "dispatch",
            },
        )
        builder.add_edge("action_approval", "dispatch")
        builder.add_edge("failure_approval", "dispatch")
        builder.add_edge("synthesize", END)

        return builder.compile(checkpointer=self.checkpointer)

    # ------------------------------------------------------------- supervisor

    async def node_supervisor(self, state: GraphState) -> Dict[str, Any]:
        description = state["task_description"]
        with span("supervisor.plan", task_id=state.get("task_id")):
            plan = await self.supervisor.create_plan(description)

            errors = validate_plan([t.model_dump() for t in plan.tasks])
            if errors:
                logger.warning("Invalid plan (%s); regenerating once", errors)
                plan = await self.supervisor.create_plan(description, validation_errors=errors)
                errors = validate_plan([t.model_dump() for t in plan.tasks])
                if errors:
                    return {
                        "plan": [],
                        "shared_context": f"Planning failed validation: {errors}",
                    }

        return {
            "plan": [task.model_dump() for task in plan.tasks],
            "plan_confidence": plan.confidence,
            "shared_context": plan.reasoning,
        }

    # --------------------------------------------------------- plan approval

    async def node_plan_approval(self, state: GraphState) -> Dict[str, Any]:
        """Dedicated gate so resume replays only this cheap node, never an LLM."""
        if not self.hitl_enabled:
            return {}
        plan = state.get("plan") or []
        confidence = state.get("plan_confidence", 1.0)
        if not plan or confidence >= LOW_CONFIDENCE_THRESHOLD:
            return {}
        with span("approval.plan_gate", confidence=confidence):
            decision = interrupt(plan_approval_payload(state, confidence))
        return apply_plan_decision(decision, state)

    # --------------------------------------------------------------- dispatch

    async def node_dispatch(self, state: GraphState) -> Dict[str, Any]:
        """Single fan-in point: routing happens in route_next_subtasks."""
        return {}

    def route_next_subtasks(self, state: GraphState) -> Union[List[Send], str]:
        """Schedule the next batch of ready subtasks, or move to synthesis."""
        plan = state.get("plan") or []
        results: Dict[str, SubtaskResult] = state.get("results") or {}
        feedback: Dict[str, str] = state.get("review_feedback") or {}

        if not plan:
            return "synthesize"

        # Reviewer asked for another attempt (review never marks retry past the cap).
        retries = [sid for sid, r in results.items() if r.status == "retry"]

        # New work whose accepted results make its dependencies satisfied.
        def deps_accepted(task: Dict[str, Any]) -> bool:
            for dep in task.get("dependencies") or []:
                dep_result = results.get(dep)
                if dep_result is None or dep_result.status != "accepted":
                    return False
            return True

        ready = [
            t for t in plan
            if t["id"] not in results and deps_accepted(t)
        ]

        sends: List[Send] = []
        for task in ready:
            sends.append(Send("execute_subtask", self._execute_payload(state, task)))
        for sid in retries:
            task = next((t for t in plan if t["id"] == sid), {})
            if not task:
                continue
            payload = self._execute_payload(state, task)
            payload["feedback"] = feedback.get(sid)
            sends.append(Send("execute_subtask", payload))

        if sends:
            return sends

        # Nothing left to schedule: synthesize with whatever succeeded. A valid
        # plan with all dependencies satisfied always reaches synthesis here.
        logger.info("No subtasks left to schedule; synthesizing with %s results", len(results))
        return "synthesize"


    def _execute_payload(self, state: GraphState, task: Dict[str, Any]) -> Dict[str, Any]:
        approvals = {
            signature: info
            for signature, info in (state.get("pending_approvals") or {}).items()
            if info.get("status") in {"approved", "rejected"}
        }
        return {
            "subtask": dict(task),
            "shared_context": state.get("shared_context", ""),
            "task_id": state.get("task_id", "unknown"),
            "approvals": approvals,
        }

    # -------------------------------------------------------------- execution

    async def node_execute_subtask(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        task = payload["subtask"]
        subtask_id = task["id"]
        specialist_name = task["specialist"]
        agent = self.specialists.get(specialist_name)

        if agent is None:
            return {
                "results": {subtask_id: SubtaskResult(
                    subtask_id=subtask_id,
                    content="",
                    status="error",
                    error=f"Specialist {specialist_name} not found",
                )},
            }

        feedback = payload.get("feedback")
        context = payload.get("shared_context", "")
        if feedback:
            context = f"{context}\n\nReviewer feedback from the previous attempt:\n{feedback}"

        task_id = payload.get("task_id", "unknown")
        approvals = payload.get("approvals") or {}
        executor = self._make_executor(task_id, subtask_id, specialist_name, approvals)
        try:
            with span("specialist.run", subtask_id=subtask_id, specialist=specialist_name):
                result = await self._run_specialist(agent, task, context, subtask_id, executor)
        except ApprovalRequired as request:
            # Hand the request to the (single) approval node; the subtask will be
            # re-dispatched with the decision once a human answers.
            return {
                "pending_approvals": {
                    request.signature: {
                        "status": "pending",
                        "subtask_id": subtask_id,
                        "tool": request.tool_name,
                        "arguments": request.arguments,
                    }
                }
            }
        return {"results": {subtask_id: result}}

    def _make_executor(
        self, task_id: str, subtask_id: str, specialist: str, approvals: Dict[str, Any]
    ) -> Any:
        """Bind the worker's tool executor to this subtask and specialist."""
        if self.tool_executor is None:
            return None

        async def executor(tool_call: Any) -> Any:
            signature = tool_signature(subtask_id, tool_call.tool, tool_call.arguments)
            approval = approvals.get(signature) or {}
            if approval.get("status") == "rejected":
                return ToolResult(
                    content="", status="error", error="Rejected by a human reviewer"
                )
            approved_signature = (
                signature if approval.get("status") == "approved" else None
            )
            arguments = approval.get("arguments") or tool_call.arguments
            return await self.tool_executor(
                subtask_id=subtask_id,
                specialist=specialist,
                tool_name=tool_call.tool,
                arguments=arguments,
                approved_signature=approved_signature,
            )

        return executor

    async def _run_specialist(
        self,
        agent: SpecialistAgent,
        task: Dict[str, Any],
        context: str,
        subtask_id: str,
        executor: Any = None,
    ) -> SubtaskResult:
        try:
            content = await agent.run(
                task_description=task["description"],
                context=context,
                executor=executor,
            )
            return SubtaskResult(subtask_id=subtask_id, content=content)
        except ApprovalRequired:
            # The graph needs to interrupt; this is not a typed failure result.
            raise
        except Exception as exc:  # tool/LLM failures are typed results, not crashes
            logger.exception("Specialist %s failed on %s", task["specialist"], subtask_id)
            return SubtaskResult(
                subtask_id=subtask_id,
                content="",
                status="error",
                error=str(exc),
            )

    # ----------------------------------------------------------------- review

    async def node_review(self, state: GraphState) -> Dict[str, Any]:
        """Review every not-yet-reviewed result from the batch that just ran.

        Runs once per super-step because every execute branch fans into it, so
        parallel results are reviewed together against their own subtasks.
        """
        plan = state.get("plan") or []
        results: Dict[str, SubtaskResult] = state.get("results") or {}
        attempts: Dict[str, int] = state.get("attempts") or {}

        updates: Dict[str, SubtaskResult] = {}
        feedback: Dict[str, str] = {}
        attempt_updates: Dict[str, int] = {}

        for task in plan:
            subtask_id = task["id"]
            result = results.get(subtask_id)
            if result is None:
                continue

            if result.status == "error":
                # A specialist crash (tool/LLM failure) gets one different-approach
                # retry, then escalates instead of hanging the run.
                attempts_made = attempts.get(subtask_id, 0) + 1
                attempt_updates[subtask_id] = attempts_made
                if attempts_made < MAX_SUBTASK_ATTEMPTS:
                    updates[subtask_id] = result.model_copy(
                        update={"status": "retry", "retry_count": attempts_made}
                    )
                    feedback[subtask_id] = (
                        f"The previous attempt failed with: {result.error}. "
                        "Try a different approach."
                    )
                else:
                    updates[subtask_id] = result.model_copy(
                        update={"status": "escalate", "retry_count": attempts_made}
                    )
                continue

            if result.status != "success":
                continue  # accepted/retry/escalate already decided

            with span("reviewer.review", subtask_id=subtask_id, specialist=task["specialist"]):
                review = await self.reviewer.review(
                    task_description=task["description"],
                    specialist_output=result.content,
                    specialist_role=task["specialist"],
                )
            feedback[subtask_id] = review.feedback
            attempts_made = attempts.get(subtask_id, 0) + 1
            attempt_updates[subtask_id] = attempts_made

            if review.decision == "accept":
                status = "accepted"
            elif review.decision == "retry":
                status = "retry" if attempts_made < MAX_SUBTASK_ATTEMPTS else "escalate"
            else:
                status = "escalate"

            updates[subtask_id] = result.model_copy(update={
                "status": status,
                "retry_count": attempts_made,
            })
            logger.info(
                "Review of %s: %s (overall=%.2f)",
                subtask_id, status, review.scores.overall(),
            )

        if not updates and not feedback:
            return {}
        return {
            "results": updates,
            "review_feedback": feedback,
            "attempts": attempt_updates,
        }

    # -------------------------------------------------------------- synthesis

    async def node_synthesize(self, state: GraphState) -> Dict[str, Any]:
        results: Dict[str, SubtaskResult] = state.get("results") or {}

        usable = {sid: r for sid, r in results.items() if r.status == "accepted"}
        unusable = {sid: r for sid, r in results.items() if r.status != "accepted"}

        parts = [f"### Subtask {sid}\n{r.content}" for sid, r in usable.items()]
        if not parts:
            parts = [f"### Subtask {sid}\n{r.content}" for sid, r in results.items() if r.content]
        combined = "\n\n".join(parts) or "No usable subtask output was produced."

        context = combined
        if unusable:
            notes = ", ".join(
                f"{sid} ({r.status}{': ' + r.error if r.error else ''})"
                for sid, r in unusable.items()
            )
            context += f"\n\nNote: these subtasks did not complete successfully: {notes}"

        writer = self.specialists["writer"]
        with span("synthesize"):
            final = await writer.run(
                task_description="Synthesize the final response from subtask results.",
                context=context,
            )
        return {"final_response": final}
