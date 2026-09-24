import abc
from typing import Any, Dict, List, Optional, Type, TypeVar, Generic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class LLMResponse(BaseModel):
    content: str
    tokens_prompt: int
    tokens_completion: int
    cost: float
    model: str

class LLMProvider(abc.ABC):
    """Abstract base class for LLM providers."""

    @abc.abstractmethod
    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a text completion."""
        pass

    @abc.abstractmethod
    async def complete_structured(self, prompt: str, response_model: Type[T], **kwargs) -> T:
        """Generate a structured completion matching the provided Pydantic model."""
        pass

    @abc.abstractmethod
    def get_cost_per_token(self, model: str, token_type: str) -> float:
        """Return the cost per token for a given model and token type ('prompt' or 'completion')."""
        pass
