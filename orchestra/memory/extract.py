from typing import List, Optional
from pydantic import BaseModel, Field
from llm.provider import LLMProvider
from .store import MemoryEntry

class MemoryExtraction(BaseModel):
    """The structured output of the memory extraction process."""
    approach: str = Field(description="The strategy used to solve the task")
    tools_used: List[str] = Field(description="The specific tools that were most effective")
    outcome: str = Field(description="Whether the task succeeded and why")
    facts: List[str] = Field(description="Key factual insights discovered")
    preferences: List[str] = Field(description="Observed user preferences or constraints")

class MemoryExtractor:
    """Analyzes a completed task to extract long-term memories."""
    
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def extract(self, user_id: str, task_id: str, request: str, 
                      results: List[str], final_response: str) -> MemoryEntry:
        prompt = (
            "You are a memory extraction agent. Your goal is to analyze a completed task "
            "and extract a concise, high-value summary for long-term storage.\n\n"
            f"User Request: {request}\n\n"
            f"Execution Results:\n{chr(10).join(results)}\n\n"
            f"Final Response: {final_response}\n\n"
            "Extract the following:\n"
            "1. Approach: How was this solved? (e.g., 'used search then validated with code')\n"
            "2. Tools: Which tools were critical?\n"
            "3. Outcome: Was it successful? What were the key results?\n"
            "4. Facts: What new facts were discovered that are worth remembering?\n"
            "5. Preferences: Did the user show any specific preferences or constraints?\n\n"
            "Return a structured JSON object."
        )
        
        extraction = await self.llm.complete_structured(prompt, MemoryExtraction)
        
        return MemoryEntry(
            user_id=user_id,
            task_id=task_id,
            request=request,
            approach=extraction.approach,
            tools_used=extraction.tools_used,
            outcome=extraction.outcome,
            facts=extraction.facts,
            preferences=extraction.preferences
        )
