import asyncio
from typing import Type, TypeVar, Any, Dict
from pydantic import BaseModel
from .provider import LLMProvider, LLMResponse

T = TypeVar("T", bound=BaseModel)

class FakeProvider(LLMProvider):
    """A deterministic provider for testing that returns scripted outputs."""
    
    def __init__(self):
        self.scripted_responses: Dict[str, str] = {}
        self.default_response = "This is a fake response from the FakeProvider."

    def set_scripted_response(self, prompt_key: str, response: str):
        """Set a scripted response. The key can be a substring of the actual prompt."""
        self.scripted_responses[prompt_key] = response

    def _find_matching_response(self, prompt: str) -> str:
        """Find a scripted response where the key is contained in the prompt."""
        for key, response in self.scripted_responses.items():
            if key in prompt:
                return response
        return self.default_response

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        content = self._find_matching_response(prompt)
        return LLMResponse(
            content=content,
            tokens_prompt=len(prompt) // 4,
            tokens_completion=len(content) // 4,
            cost=0.0,
            model="fake-model-v1"
        )

    async def complete_structured(self, prompt: str, response_model: Type[T], **kwargs) -> T:
        response_text = self._find_matching_response(prompt)
        try:
            return response_model.model_validate_json(response_text)
        except Exception:
            # Fallback: Create a dummy instance using model_construct (bypasses validation)
            # This is acceptable for a FAKE provider used in testing
            return response_model.model_construct()

    def get_cost_per_token(self, model: str, token_type: str) -> float:
        return 0.0
