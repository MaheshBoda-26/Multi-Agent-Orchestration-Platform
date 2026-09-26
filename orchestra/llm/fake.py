import json
from typing import Any, Dict, Type, TypeVar
from pydantic import BaseModel
from .provider import LLMProvider, LLMResponse

T = TypeVar("T", bound=BaseModel)


def _default_plan() -> str:
    return json.dumps({
        "tasks": [
            {
                "id": "t1",
                "description": "Gather information for the request",
                "specialist": "researcher",
                "dependencies": [],
            },
            {
                "id": "t2",
                "description": "Write up the final answer",
                "specialist": "writer",
                "dependencies": ["t1"],
            },
        ],
        "reasoning": "Research first, then write the answer.",
        "confidence": 0.9,
    })


DEFAULT_RESPONSES: Dict[str, str] = {
    # Supervisor planning prompt
    "Orchestra Supervisor": _default_plan(),
    # Reviewer prompt
    "quality reviewer evaluating": json.dumps({
        "scores": {"correctness": 0.9, "completeness": 0.9, "format": 0.9, "sources": 0.8},
        "feedback": "Output is accurate and complete.",
        "decision": "accept",
        "retry_instructions": "",
    }),
    # Memory extraction prompt
    "memory extraction agent": json.dumps({
        "approach": "Researched the topic, then wrote a summary.",
        "tools_used": ["web_search"],
        "outcome": "Success",
        "facts": ["Default fake fact for tests."],
        "preferences": [],
    }),
    # Memory retrieval prompt
    "past experiences for the user": json.dumps({
        "relevant_past_tasks": [],
        "suggested_approach": "No relevant past tasks found. Proceed with standard planning.",
        "known_constraints": [],
    }),
}


class FakeProvider(LLMProvider):
    """A deterministic provider for testing that returns scripted outputs."""

    def __init__(self) -> None:
        self.scripted_responses: Dict[str, str] = {}
        self.default_responses: Dict[str, str] = dict(DEFAULT_RESPONSES)
        self.default_response = "This is a fake response from the FakeProvider."

    def set_scripted_response(self, prompt_key: str, response: str) -> None:
        """Set a scripted response. The key can be a substring of the actual prompt."""
        self.scripted_responses[prompt_key] = response

    def _find_matching_response(self, prompt: str) -> str:
        """User-scripted responses win; built-in defaults keep demo runs working."""
        for key, response in self.scripted_responses.items():
            if key in prompt:
                return response
        for key, response in self.default_responses.items():
            if key in prompt:
                return response
        return self.default_response

    async def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        content = self._find_matching_response(prompt)
        return LLMResponse(
            content=content,
            tokens_prompt=len(prompt) // 4,
            tokens_completion=len(content) // 4,
            cost=0.0,
            model="fake-model-v1",
        )

    async def complete_structured(self, prompt: str, response_model: Type[T], **kwargs: Any) -> T:
        response_text = self._find_matching_response(prompt)
        try:
            return response_model.model_validate_json(response_text)
        except Exception:
            # Fallback: Create a dummy instance using model_construct (bypasses validation)
            # This is acceptable for a FAKE provider used in testing
            return response_model.model_construct()

    def get_cost_per_token(self, model: str, token_type: str) -> float:
        return 0.0
