"""OpenRouter provider: one OpenAI-compatible endpoint, per-role models.

Agents pass the role they act as (supervisor / reviewer / specialist / ...)
and the provider resolves the model from config/routing.yaml, so no model name
is hard-coded anywhere else. Structured output is prompt-constrained JSON with
one repair retry; no provider SDK is needed.
"""
import json
import os
import re
from typing import Any, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from .provider import LLMProvider, LLMResponse
from .routing import Routing, load_routing

T = TypeVar("T", bound=BaseModel)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter cannot produce a usable response."""


class OpenRouterProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        routing: Optional[Routing] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = (
            base_url
            or os.getenv("OPENROUTER_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.routing = routing or load_routing()
        self._client = client
        # Last call's usage, read by RecordingLLMProvider for structured calls.
        self.last_usage: Optional[LLMResponse] = None

    # ------------------------------------------------------------------ pricing

    def model_for(self, role: Optional[str], override: Optional[str] = None) -> str:
        if override:
            return override
        return self.routing.model_for(role)

    def cost_for(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        prompt_price, completion_price = self.routing.costs_for(model)
        return (prompt_tokens * prompt_price + completion_tokens * completion_price) / 1_000_000

    def get_cost_per_token(self, model: str, token_type: str) -> float:
        prompt_price, completion_price = self.routing.costs_for(model)
        price = prompt_price if token_type == "prompt" else completion_price
        return price / 1_000_000

    # ------------------------------------------------------------------- calls

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/orchestra",
            "X-Title": "Orchestra",
        }

    async def _post_once(self, body: dict) -> httpx.Response:
        url = f"{self.base_url}/chat/completions"
        if self._client is not None:
            response = await self._client.post(url, json=body, headers=self._headers())
        else:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(url, json=body, headers=self._headers())
        if response.status_code >= 400:
            raise OpenRouterError(
                f"OpenRouter {response.status_code}: {response.text[:300]}"
            )
        return response

    async def _post(self, body: dict) -> httpx.Response:
        attempts = retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.5, max=4.0),
            reraise=True,
        )(self._post_once)
        return await attempts(body)

    async def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        if not self.api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set")

        model = self.model_for(kwargs.get("role"), kwargs.get("model"))
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        http_response = await self._post(body)
        data = http_response.json()

        choices = data.get("choices") or []
        if not choices:
            raise OpenRouterError(f"OpenRouter returned no choices: {data}")
        content = choices[0].get("message", {}).get("content") or ""
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        llm_response = LLMResponse(
            content=content,
            tokens_prompt=prompt_tokens,
            tokens_completion=completion_tokens,
            cost=self.cost_for(model, prompt_tokens, completion_tokens),
            model=model,
        )
        self.last_usage = llm_response
        return llm_response

    async def complete_structured(
        self, prompt: str, response_model: Type[T], **kwargs: Any
    ) -> T:
        schema = json.dumps(response_model.model_json_schema())
        instruction = (
            f"{prompt}\n\nReturn ONLY minified JSON matching this schema, no prose:\n{schema}"
        )
        last_error: Optional[Exception] = None
        for _ in range(2):
            response = await self.complete(instruction, **kwargs)
            text = _strip_fences(response.content)
            try:
                return response_model.model_validate_json(text)
            except Exception as exc:  # noqa: BLE001 - retried, then raised
                last_error = exc
                instruction = (
                    f"{prompt}\n\nYour previous reply was not valid JSON for the "
                    f"expected schema ({exc}). Return ONLY valid JSON."
                )
        raise OpenRouterError(f"structured output failed validation: {last_error}")


def _strip_fences(text: str) -> str:
    match = _JSON_FENCE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()
