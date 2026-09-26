"""Provider selection for the API and worker.

``fake`` (default) is deterministic and used by every test; ``openrouter`` is
the real provider and resolves models per role from config/routing.yaml.
Selecting anything else fails loudly instead of silently faking a run.
"""
import os

from .fake import FakeProvider
from .openrouter import OpenRouterProvider
from .provider import LLMProvider


def build_provider() -> LLMProvider:
    name = os.getenv("LLM_PROVIDER", "fake").strip().lower()
    if name in {"fake", ""}:
        return FakeProvider()
    if name == "openrouter":
        return OpenRouterProvider()
    raise ValueError(
        f"LLM_PROVIDER={name!r} is not implemented. "
        "Use LLM_PROVIDER=fake or LLM_PROVIDER=openrouter."
    )
