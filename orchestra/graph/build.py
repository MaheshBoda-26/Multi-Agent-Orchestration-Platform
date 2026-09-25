import asyncio
from typing import List, Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.constants import Send
from .state import GraphState, SubtaskResult
from agents.supervisor import SupervisorAgent, Plan
from agents.specialists import SpecialistAgent, SPECIALIST_CONFIGS
from agents.reviewer import ReviewerAgent
from tools.registry import registry
from tools.permissions import permission_manager
from llm.provider import LLMProvider
from graph.hitl import hitl_manager, ESCALATION_TRIGGERS

class OrchestraGraph:
    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self.supervisor = SupervisorAgent(llm)
        self.specialists = {
            name: SpecialistAgent(config, llm) 
            for name, config in SPECIALIST_CONFIGS.items()
        }
        self.reviewer = ReviewerAgent(llm, threshold=0.75)
        self.workflow = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(GraphState)

        # Nodes
        builder.add_node("supervisor", self.node_supervisor)
        builder.add_node("execute_subtask", self.node_execute_subtask)
        builder.add_node("review", self.node_review)
        builder.add_node("synthesize", self.node_synthesize)

        # Edges
        builder.set_entry_point("supervisor")
        
        # Supervisor -> parallel subtask execution
        builder.add_conditional_edges(
            "supervisor",
            self.route_to_subtasks,
            {
                "execute": "execute_subtask",
                "end": END
            }
        )

        # Subtask -> review
        builder.add_edge("execute_subtask", "review")
        
        # Review -> retry or synthesize
        builder.add_conditional_edges(
            "review",
            self.route_after_review,
            {
                "retry": "execute_subtask",
                "synthesize": "synthesize",
                "escalate": "execute_subtask"  # Will trigger HITL
            }
        )

        builder.add_edge("synthesize", END)

        return builder.compile()

    async def node_supervisor(self, state: GraphState):
        plan = await self.supervisor.create_plan(state["task_description"])
        
        # Check if plan has low confidence (simulated)
        # In real implementation, supervisor would return confidence scores
        # For now, we'll check if it's a complex task
        if len(plan.tasks) > 3:  # Complex plan triggers approval
            hitl_response = await hitl_manager.pause_for_approval(
                state={**state, "task_id": state.get("task_id", "unknown")},
                trigger="low_confidence_plan",
                proposed_action=f"Execute plan with {len(plan.tasks)} subtasks"
            )
            # Handle human response
            if hitl_response.get("action") == "modify":
                # Would need to re-plan - simplified for now
                pass
        
        return {
            "plan": [task.model_dump() for task in plan.tasks],
            "shared_context": plan.reasoning
        }

    def route_to_subtasks(self, state: GraphState):
        tasks = state.get("plan", [])
        if not tasks:
            return "end"
            
        # Find ready tasks (no dependencies or all dependencies completed)
        completed = set(state.get("results", {}).keys())
        ready_tasks = [
            t for t in tasks 
            if not t["dependencies"] or all(d in completed for d in t["dependencies"])
        ]
        
        if not ready_tasks:
            return "end"
            
        return [Send("execute_subtask", t) for t in ready_tasks]

    async def node_execute_subtask(self, task_info: Dict[str, Any]):
        specialist_name = task_info["specialist"]
        agent = self.specialists.get(specialist_name)
        
        if not agent:
            return {"results": {task_info["id"]: SubtaskResult(
                subtask_id=task_info["id"], 
                content="", 
                status="error", 
                error=f"Specialist {specialist_name} not found"
            )}}

        # Check for sensitive tool usage
        # For this baseline, we'll simulate the check
        # In real implementation, the agent would declare tools it wants to use
        sensitive_tool_used = False
        if specialist_name == "code_executor" and "delete" in task_info.get("description", "").lower():
            # Simulate sensitive tool detection
            sensitive_tool_used = True
            # Check if tool is marked sensitive
            if permission_manager.is_sensitive("file_write"):
                hitl_response = await hitl_manager.pause_for_approval(
                    state={"task_id": task_info.get("task_id", "unknown")},
                    trigger="sensitive_tool_requested",
                    proposed_action=f"Write file as part of: {task_info['description']}"
                )
                if hitl_response.get("action") == "reject":
                    return {"results": {task_info["id"]: SubtaskResult(
                        subtask_id=task_info["id"], 
                        content="", 
                        status="error", 
                        error="Human rejected sensitive action"
                    )}}

        max_retries = 2
        for attempt in range(max_retries):
            try:
                res_content = await agent.run(
                    task_description=task_info["description"], 
                    context="Global context"
                )
                return {"results": {task_info["id"]: SubtaskResult(
                    subtask_id=task_info["id"], 
                    content=res_content,
                    retry_count=attempt
                )}}
            except Exception as e:
                if attempt == max_retries - 1:
                    return {"results": {task_info["id"]: SubtaskResult(
                        subtask_id=task_info["id"], 
                        content="", 
                        status="error", 
                        error=str(e),
                        retry_count=attempt + 1
                    )}}
                await asyncio.sleep(1)

    async def node_review(self, state: GraphState):
        # Get the most recent result
        results = state.get("results", {})
        if not results:
            return {"results": {}}
            
        latest_task_id = list(results.keys())[-1]
        latest_result = results[latest_task_id]
        
        if latest_result.status == "error":
            return {"results": {}}
        
        # Find the task info for this result
        plan = state.get("plan", [])
        task_info = next((t for t in plan if t["id"] == latest_task_id), None)
        
        if not task_info:
            return {"results": {}}
        
        # Run reviewer
        review = await self.reviewer.review(
            task_description=task_info["description"],
            specialist_output=latest_result.content,
            specialist_role=task_info["specialist"]
        )
        
        if review.decision == "accept":
            return {"results": {}}
        elif review.decision == "retry":
            # Update result with retry feedback
            updated_result = latest_result.model_copy(update={
                "content": latest_result.content + f"\n\n[REVIEWER FEEDBACK]: {review.feedback}\n{review.retry_instructions}",
                "retry_count": latest_result.retry_count + 1
            })
            return {"results": {latest_task_id: updated_result}}
        else:  # escalate
            # Trigger HITL for escalation
            hitl_response = await hitl_manager.pause_for_approval(
                state={**state, "task_id": state.get("task_id", "unknown")},
                trigger="reviewer_escalate",
                proposed_action=f"Reviewer escalated: {review.feedback}"
            )
            # Store human decision in state
            return {"results": {f"{latest_task_id}_hitl": SubtaskResult(
                subtask_id=f"{latest_task_id}_hitl",
                content=f"Human decision: {hitl_response.get('action', 'unknown')}",
                status="success"
            )}}

    def route_after_review(self, state: GraphState):
        # This is simplified - in real implementation, we'd track review decisions
        # For now, always synthesize if there are results
        results = state.get("results", {})
        if results:
            return "synthesize"
        return "execute_subtask"

    async def node_synthesize(self, state: GraphState):
        all_results = state.get("results", {})
        combined_text = "\n".join([f"Task {k}: {v.content}" for k, v in all_results.items()])
        
        writer = self.specialists["writer"]
        final = await writer.run(
            task_description="Synthesize the final response from subtask results.",
            context=combined_text
        )
        
        return {"final_response": final}
