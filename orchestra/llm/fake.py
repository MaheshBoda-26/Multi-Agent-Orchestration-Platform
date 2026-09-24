import asyncio
from typing import Type, TypeVar, Any
from pydantic import BaseModel
from .provider import LLMProvider, LLMResponse

T = TypeVar("T", bound=BaseModel)

class FakeProvider(LLMProvider):
    """A deterministic provider for testing that returns scripted outputs."""
    
    def __init__(self):
        self.scripted_responses = {}
        self.default_response = "This is a fake response from the FakeProvider."

    def set_scripted_response(self, prompt: str, response: str):
        self.scripted_responses[prompt] = response

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        content = self.scripted_responses.get(prompt, self.default_response)
        return LLMResponse(
            content=content,
            tokens_prompt=len(prompt) // 4,
            tokens_completion=len(content) // 4,
            cost=0.0,
            model="fake-model-v1"
        )

    async def complete_structured(self, prompt: str, response_model: Type[T], **kwargs) -> T:
        # For a real fake provider, we might parse a scripted JSON string.
        # For simplicity, we'll try to instantiate the model with dummy data
        # or a scripted response if available.
        response_text = self.scripted_responses.get(prompt, "{}")
        try:
            return response_model.model_validate_json(response_text)
        except Exception:
            # Fallback: Create a dummy instance of the model
            return response_model.model_construct()

    def get_cost_per_token(self, model: str, token_type: str) -> float:
        return 0.0
