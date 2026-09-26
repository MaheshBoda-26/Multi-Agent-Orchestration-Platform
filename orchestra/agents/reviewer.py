from typing import Optional
from pydantic import BaseModel, Field
from llm.provider import LLMProvider

class ReviewScore(BaseModel):
    correctness: float = Field(ge=0.0, le=1.0, description="Factual accuracy and logical validity")
    completeness: float = Field(ge=0.0, le=1.0, description="Addresses all aspects of the task")
    format: float = Field(ge=0.0, le=1.0, description="Structure, clarity, and presentation")
    sources: float = Field(ge=0.0, le=1.0, description="Quality and citation of sources")
    
    def overall(self) -> float:
        return (self.correctness + self.completeness + self.format + self.sources) / 4.0

class ReviewResult(BaseModel):
    scores: ReviewScore
    feedback: str
    decision: str = Field(description="accept, retry, or escalate")
    retry_instructions: Optional[str] = None

class ReviewerAgent:
    """Evaluates specialist output against a quality rubric."""
    
    def __init__(self, llm: LLMProvider, threshold: float = 0.75):
        self.llm = llm
        self.threshold = threshold

    async def review(self, task_description: str, specialist_output: str, specialist_role: str) -> ReviewResult:
        prompt = (
            f"You are a quality reviewer evaluating the output of a {specialist_role} specialist.\n\n"
            f"Original Task: {task_description}\n\n"
            f"Specialist Output:\n{specialist_output}\n\n"
            "Evaluate the output on four dimensions (0.0 to 1.0 each):\n"
            "1. Correctness: Factual accuracy, logical validity, no hallucinations\n"
            "2. Completeness: Addresses all aspects of the requested task\n"
            "3. Format: Clear structure, professional presentation, proper formatting\n"
            "4. Sources: Quality of citations, evidence provided, source diversity\n\n"
            f"Threshold for acceptance: {self.threshold}\n\n"
            "Provide structured scores, detailed feedback, and a decision: "
            "'accept' if overall >= threshold, 'retry' if close but needs improvement, "
            "'escalate' if fundamentally flawed. If retry, include specific retry instructions."
        )
        
        result = await self.llm.complete_structured(prompt, ReviewResult)
        
        # Safety check: if LLM returns decision that doesn't match scores, override
        if result.decision == "accept" and result.scores.overall() < self.threshold:
            result.decision = "retry"
            result.retry_instructions = f"Overall score {result.scores.overall():.2f} below threshold {self.threshold}. Please improve quality."
        elif result.decision == "escalate" and result.scores.overall() >= self.threshold:
            result.decision = "accept"
            
        return result
