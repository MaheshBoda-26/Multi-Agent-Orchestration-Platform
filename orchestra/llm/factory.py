"""Provider selection for the API and worker.

Real providers (OpenRouter / OpenAI / Anthropic) land with the routing layer;
until then the only configured provider is the deterministic FakeProvider, and
selecting anything else fails loudly instead of silently faking a run.
"""
import os

from .fake import FakeProvider
from .provider import LLMProvider


def build_provider() -> LLMProvider:
    name = os.getenv("LLM_PROVIDER", "fake").strip().lower()
    if name in {"fake", ""}:
        return FakeProvider()
    raise ValueError(
        f"LLM_PROVIDER={name!r} is not implemented yet. "
        "Set LLM_PROVIDER=fake until the real provider clients are added."
    )
