"""Provider wrapper that records usage and emits one span per LLM call.

The worker wraps the selected provider with this, so per-run tokens, cost and
model breakdown are collected in exactly one place and every call is traced.
"""
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel

from llm.provider import LLMProvider, LLMResponse
from observability.spans import span

T = TypeVar("T", bound=BaseModel)


class RunRecorder:
    """Accumulates LLM usage for one run."""

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd = 0.0
        self.model_breakdown: Dict[str, Dict[str, float]] = {}
        self.models: List[str] = []

    def record(self, response: LLMResponse) -> None:
        self.prompt_tokens += response.tokens_prompt
        self.completion_tokens += response.tokens_completion
        self.cost_usd += response.cost
        entry = self.model_breakdown.setdefault(
            response.model, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        )
        entry["calls"] += 1
        entry["prompt_tokens"] += response.tokens_prompt
        entry["completion_tokens"] += response.tokens_completion
        entry["cost_usd"] += response.cost


class RecordingLLMProvider(LLMProvider):
    def __init__(self, delegate: LLMProvider, recorder: RunRecorder) -> None:
        self.delegate = delegate
        self.recorder = recorder

    def _record(
        self,
        response: Optional[LLMResponse],
        call_kind: str,
        role: Any,
        model_hint: Any = None,
    ) -> None:
        if response is not None:
            self.recorder.record(response)
        with span(
            f"llm.{call_kind}",
            model=(response.model if response else model_hint),
            role=role,
            tokens_prompt=(response.tokens_prompt if response else None),
            tokens_completion=(response.tokens_completion if response else None),
            cost_usd=(response.cost if response else None),
        ):
            pass

    async def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        response = await self.delegate.complete(prompt, **kwargs)
        self._record(response, "complete", kwargs.get("role"))
        return response

    async def complete_structured(
        self, prompt: str, response_model: Type[T], **kwargs: Any
    ) -> T:
        result = await self.delegate.complete_structured(prompt, response_model, **kwargs)
        # Providers that support usage tracking expose last_usage; structured
        # calls may include one repair retry, so the last call is what we price.
        usage = getattr(self.delegate, "last_usage", None)
        self._record(
            usage if isinstance(usage, LLMResponse) else None,
            "complete_structured",
            kwargs.get("role"),
            model_hint=kwargs.get("model"),
        )
        return result

    def get_cost_per_token(self, model: str, token_type: str) -> float:
        return self.delegate.get_cost_per_token(model, token_type)
