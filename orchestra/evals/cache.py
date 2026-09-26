"""Prompt-hash LLM response cache (Task 34).

The eval harness replays the same prompts across configs and repeats; caching
the (model, prompt, role) -> response pair keeps the live eval inside its
$30-60 budget. Backed by Postgres when a pool is handed in, by an in-process
dict otherwise (unit tests, dry runs).
"""
import hashlib
import json
from typing import Any, Dict, Optional

import asyncpg

from llm.provider import LLMResponse


def cache_key(model: str, role: Optional[str], prompt: str) -> str:
    payload = json.dumps({"model": model, "role": role, "prompt": prompt})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LLMCache:
    def __init__(self, pool: Optional[asyncpg.Pool] = None) -> None:
        self.pool = pool
        self._memory: Dict[str, str] = {}
        self.hits = 0
        self.misses = 0

    async def get(self, model: str, role: Optional[str], prompt: str) -> Optional[str]:
        key = cache_key(model, role, prompt)
        if key in self._memory:
            self.hits += 1
            return self._memory[key]
        if self.pool is not None:
            async with self.pool.acquire() as conn:
                value = await conn.fetchval(
                    "SELECT response FROM llm_cache WHERE cache_key = $1", key
                )
            if value is not None:
                self._memory[key] = value
                self.hits += 1
                return value
        self.misses += 1
        return None

    async def put(
        self, model: str, role: Optional[str], prompt: str, response: str
    ) -> None:
        key = cache_key(model, role, prompt)
        self._memory[key] = response
        if self.pool is not None:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO llm_cache (cache_key, model, role, prompt, response)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (cache_key) DO NOTHING
                    """,
                    key, model, role, prompt, response,
                )


class CachedProvider:
    """Wraps an LLMProvider: cache lookups around complete/complete_structured.

    Cache hits return a real LLMResponse built from the stored content without
    touching the wrapped provider, so identical eval repeats cost nothing.
    """

    def __init__(self, inner: Any, cache: LLMCache) -> None:
        self._inner = inner
        self._cache = cache

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _model_for(self, kwargs: Dict[str, Any]) -> str:
        model_for = getattr(self._inner, "model_for", None)
        if model_for is not None:
            return model_for(kwargs.get("role"), kwargs.get("model"))
        return "unknown"

    def _cached_llm_response(self, model: str, content: str) -> LLMResponse:
        return LLMResponse(
            content=content,
            tokens_prompt=0,
            tokens_completion=0,
            cost=0.0,
            model=model,
        )

    async def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        model = self._model_for(kwargs)
        role = kwargs.get("role")
        cached = await self._cache.get(model, role, prompt)
        if cached is not None:
            return self._cached_llm_response(model, cached)
        response = await self._inner.complete(prompt, **kwargs)
        await self._cache.put(model, role, prompt, response.content)
        return response

    async def complete_structured(self, prompt: str, response_model: Any, **kwargs: Any) -> Any:
        model = self._model_for(kwargs)
        role = kwargs.get("role")
        cached = await self._cache.get(model, role, prompt)
        if cached is not None:
            return response_model.model_validate_json(cached)
        result = await self._inner.complete_structured(prompt, response_model, **kwargs)
        await self._cache.put(model, role, prompt, result.model_dump_json())
        return result
