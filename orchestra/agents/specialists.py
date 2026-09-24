from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from llm.provider import LLMProvider, LLMResponse

class AgentConfig(BaseModel):
    name: str
    role: str
    instructions: str
    allowed_tools: List[str]
    model_override: Optional[str] = None

class SpecialistAgent:
    """A specialized agent with a specific role and set of tools."""
    
    def __init__(self, config: AgentConfig, llm: LLMProvider):
        self.config = config
        self.llm = llm

    async def run(self, task_description: str, context: str, tool_results: Optional[Dict[str, Any]] = None) -> str:
        # Build the prompt with role and instructions
        prompt = (
            f"Role: {self.config.role}\n"
            f"Instructions: {self.config.instructions}\n\n"
            f"Context: {context}\n"
            f"Task: {task_description}\n"
        )
        
        if tool_results:
            prompt += "\nTool Results:\n" + str(tool_results)
            
        prompt += "\n\nPlease provide your final response based on the above."
        
        response = await self.llm.complete(prompt)
        return response.content

# Definitions for the 4 required specialists
SPECIALIST_CONFIGS = {
    "researcher": AgentConfig(
        name="researcher",
        role="Expert Researcher",
        instructions="Find accurate, up-to-date information using web search and HTTP tools. Synthesize findings into a structured report with sources.",
        allowed_tools=["web_search", "http_get", "file_read"]
    ),
    "data_analyst": AgentConfig(
        name="data_analyst",
        role="Data Analysis Specialist",
        instructions="Analyze provided datasets or files. Use the code executor to perform calculations, generate statistics, and create data summaries.",
        allowed_tools=["code_execute", "file_read", "file_write"]
    ),
    "writer": AgentConfig(
        name="writer",
        role="Professional Content Writer",
        instructions="Transform technical findings or analysis into polished, high-quality documents. Ensure clarity, correct tone, and proper formatting.",
        allowed_tools=["file_read", "file_write"]
    ),
    "code_executor": AgentConfig(
        name="code_executor",
        role="Software Engineering Agent",
        instructions="Write and execute Python code to solve technical problems or automate tasks. Verify your code works before submitting.",
        allowed_tools=["code_execute", "file_read", "file_write"]
    )
}
