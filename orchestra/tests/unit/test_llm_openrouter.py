import json

import httpx
import pytest

from agents.supervisor import Plan
from llm.factory import build_provider
from llm.openrouter import OpenRouterError, OpenRouterProvider
from llm.routing import load_routing


def test_routing_file_maps_roles_and_costs():
    routing = load_routing()
    assert routing.model_for("supervisor") == "anthropic/claude-3.5-sonnet"
    assert routing.model_for("specialist") == "openai/gpt-4o-mini"
    assert routing.model_for("unknown-role") == routing.default
    assert routing.costs_for("openai/gpt-4o-mini") == (0.15, 0.60)
    assert routing.costs_for("no-such-model") == (0.50, 1.50)


def _provider(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenRouterProvider(api_key="test", client=client, **kwargs)


def _chat_response(content, prompt_tokens=100, completion_tokens=50):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    })


@pytest.mark.asyncio
async def test_complete_returns_content_tokens_and_cost():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return _chat_response("hello")

    provider = _provider(handler)

    response = await provider.complete("hi", role="supervisor")

    assert response.content == "hello"
    assert response.model == "anthropic/claude-3.5-sonnet"
    assert response.tokens_prompt == 100
    assert response.tokens_completion == 50
    expected = (100 * 3.0 + 50 * 15.0) / 1_000_000
    assert abs(response.cost - expected) < 1e-9
    assert seen["auth"] == "Bearer test"
    assert seen["body"]["model"] == "anthropic/claude-3.5-sonnet"


@pytest.mark.asyncio
async def test_structured_output_retries_once_on_bad_json():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return _chat_response("sorry, not json")
        payload = {
            "tasks": [{"id": "t1", "description": "d", "specialist": "writer", "dependencies": []}],
            "reasoning": "r",
            "confidence": 0.8,
        }
        return _chat_response(json.dumps(payload))

    provider = _provider(handler)

    plan = await provider.complete_structured("plan it", Plan, role="supervisor")

    assert plan.tasks[0].id == "t1"
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_fenced_json_is_accepted():
    def handler(request):
        payload = {
            "tasks": [{"id": "t1", "description": "d", "specialist": "writer", "dependencies": []}],
            "reasoning": "r",
            "confidence": 0.5,
        }
        return _chat_response(f"```json\n{json.dumps(payload)}\n```")

    provider = _provider(handler)

    plan = await provider.complete_structured("x", Plan, role="supervisor")

    assert plan.confidence == 0.5


@pytest.mark.asyncio
async def test_missing_key_raises_clearly():
    provider = OpenRouterProvider(api_key="")

    with pytest.raises(OpenRouterError):
        await provider.complete("hi")


def test_factory_selects_openrouter(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert isinstance(build_provider(), OpenRouterProvider)


def test_factory_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    with pytest.raises(ValueError):
        build_provider()
