import abc
from typing import Any, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMResponse(BaseModel):
    content: str
    tokens_prompt: int
    tokens_completion: int
    cost: float
    model: str


class LLMProvider(abc.ABC):
    """Abstract base class for LLM providers.

    Every model call in the system goes through this interface so tests can
    swap in FakeProvider and costs are always recorded in one place.
    """

    @abc.abstractmethod
    async def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """Generate a text completion."""
        raise NotImplementedError

    @abc.abstractmethod
    async def complete_structured(
        self, prompt: str, response_model: Type[T], **kwargs: Any
    ) -> T:
        """Generate a structured completion matching the provided Pydantic model."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_cost_per_token(self, model: str, token_type: str) -> float:
        """Cost per token for a model and token type ('prompt' or 'completion')."""
        raise NotImplementedError
