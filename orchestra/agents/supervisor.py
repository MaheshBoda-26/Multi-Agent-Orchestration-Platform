import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from llm.provider import LLMProvider

logger = logging.getLogger(__name__)

class Subtask(BaseModel):
    id: str
    description: str
    specialist: str
    dependencies: List[str] = Field(default_factory=list)

class Plan(BaseModel):
    tasks: List[Subtask]
    reasoning: str

class SupervisorAgent:
    """The orchestrator that plans the task breakdown and assigns specialists."""
    
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def create_plan(self, task_description: str) -> Plan:
        prompt = (
            "You are the Orchestra Supervisor. Your goal is to break down a complex task "
            "into a sequence of subtasks that can be handled by specialized agents.\n\n"
            "Available Specialists:\n"
            "- researcher: Web search, info gathering\n"
            "- data_analyst: Data crunching, statistics\n"
            "- writer: Content creation, polishing\n"
            "- code_executor: Python scripting, automation\n\n"
            f"Task: {task_description}\n\n"
            "Provide a detailed plan with subtasks, specifying the specialist for each "
            "and any dependencies between tasks. Return the plan in structured JSON format."
        )
        
        # Use structured output to get a Plan object
        plan = await self.llm.complete_structured(prompt, Plan)
        logger.info(f"Supervisor created plan with {len(plan.tasks)} subtasks")
        return plan
