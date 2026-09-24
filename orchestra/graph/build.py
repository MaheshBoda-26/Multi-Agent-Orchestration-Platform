import asyncio
from typing import List, Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.constants import Send
from .state import GraphState, SubtaskResult
from agents.supervisor import SupervisorAgent, Plan
from agents.specialists import SpecialistAgent, SPECIALIST_CONFIGS
from tools.registry import registry
from llm.provider import LLMProvider

class OrchestraGraph:
    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self.supervisor = SupervisorAgent(llm)
        self.specialists = {
            name: SpecialistAgent(config, llm) 
            for name, config in SPECIALIST_CONFIGS.items()
        }
        self.workflow = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(GraphState)

        # Nodes
        builder.add_node("supervisor", self.node_supervisor)
        builder.add_node("execute_subtask", self.node_execute_subtask)
        builder.add_node("synthesize", self.node_synthesize)

        # Edges
        builder.set_entry_point("supervisor")
        
        # Supervisor decides how to fan out to subtasks
        builder.add_conditional_edges(
            "supervisor",
            self.route_to_subtasks,
            {
                "execute": "execute_subtask",
                "end": END
            }
        )

        # Subtasks return to synthesize after completion
        builder.add_edge("execute_subtask", "synthesize")
        builder.add_edge("synthesize", END)

        return builder.compile()

    async def node_supervisor(self, state: GraphState):
        plan = await self.supervisor.create_plan(state["task_description"])
        return {
            "plan": [task.model_dump() for task in plan.tasks],
            "shared_context": plan.reasoning
        }

    def route_to_subtasks(self, state: GraphState):
        # Parallel fan-out logic using LangGraph Send
        # For this baseline, we send all tasks that have no dependencies
        tasks = state["plan"]
        ready_tasks = [t for t in tasks if not t["dependencies"]]
        
        if not ready_tasks:
            return "end"
            
        # Return a list of Send objects to trigger parallel execution
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

        # Execution with retry logic (simplified baseline)
        max_retries = 2
        for attempt in range(max_retries):
            try:
                # Mock tool results for the walking skeleton
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

    async def node_synthesize(self, state: GraphState):
        # Combine results into a final response
        all_results = state["results"]
        combined_text = "\n".join([f"Task {k}: {v.content}" for k, v in all_results.items()])
        
        # Use a writer agent to polish the final result
        writer = self.specialists["writer"]
        final = await writer.run(
            task_description="Synthesize the final response from subtask results.",
            context=combined_text
        )
        
        return {"final_response": final}
