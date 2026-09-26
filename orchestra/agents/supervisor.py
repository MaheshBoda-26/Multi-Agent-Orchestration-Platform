import logging
from typing import List, Optional
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
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Supervisor's confidence that this plan solves the task",
    )


class SupervisorAgent:
    """The orchestrator that plans the task breakdown and assigns specialists."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def create_plan(
        self,
        task_description: str,
        context: str = "",
        validation_errors: Optional[List[str]] = None,
    ) -> Plan:
        prompt = (
            "You are the Orchestra Supervisor. Your goal is to break down a complex task "
            "into a sequence of subtasks that can be handled by specialized agents.\n\n"
            "Available Specialists:\n"
            "- researcher: Web search, info gathering\n"
            "- data_analyst: Data crunching, statistics\n"
            "- writer: Content creation, polishing\n"
            "- code_executor: Python scripting, automation\n\n"
            f"Task: {task_description}\n\n"
        )
        if context:
            prompt += f"Context from earlier steps:\n{context}\n\n"
        if validation_errors:
            prompt += (
                "A previous plan was rejected by the validator for these reasons. "
                "Fix them and return a valid plan:\n"
                + "\n".join(f"- {e}" for e in validation_errors)
                + "\n\n"
            )
        prompt += (
            "Provide a detailed plan with subtasks, specifying the specialist for each "
            "and any dependencies between tasks. Return the plan in structured JSON format."
        )

        plan = await self.llm.complete_structured(prompt, Plan, role="supervisor")
        logger.info(
            "Supervisor created plan with %s subtasks (confidence=%.2f)",
            len(plan.tasks), plan.confidence,
        )
        return plan
