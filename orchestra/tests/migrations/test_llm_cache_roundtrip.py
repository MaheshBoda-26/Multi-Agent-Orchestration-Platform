"""DB-backed LLM cache (Phase 9): the llm_cache table survives restarts."""
import pytest

from evals.cache import LLMCache
from llm.fake import FakeProvider

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cache_roundtrip_through_postgres_pool(postgres_pool):
    cache = LLMCache(postgres_pool)
    await cache.put("some-model", "specialist", "hello prompt", "cached reply")

    hit = await cache.get("some-model", "specialist", "hello prompt")
    assert hit == "cached reply"
    assert cache.hits == 1 and cache.misses == 0


@pytest.mark.asyncio
async def test_cached_provider_serves_db_cache_across_instances(postgres_pool):
    """A fresh provider+cache (simulating a restarted process) hits the table."""
    first = FakeProvider()

    class Counting(FakeProvider):
        calls = 0

        async def complete(self, prompt, **kwargs):
            Counting.calls += 1
            return await super().complete(prompt, **kwargs)

    inner = Counting()
    from evals.cache import CachedProvider

    await CachedProvider(first, LLMCache(postgres_pool)).complete(
        "expensive prompt", role="specialist"
    )
    # New instance, same pool: exactly what a repeat or restart looks like.
    second = CachedProvider(inner, LLMCache(postgres_pool))
    response = await second.complete("expensive prompt", role="specialist")

    assert Counting.calls == 0, "second call must come from the DB cache"
    assert response.content == "This is a fake response from the FakeProvider."
    assert response.tokens_prompt == 0 and response.cost == 0.0
    assert second._cache.hits == 1

    await postgres_pool.execute("DELETE FROM llm_cache WHERE prompt = 'expensive prompt'")
