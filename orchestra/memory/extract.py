"""Backwards-compatible import surface: MemoryExtractor lives in retrieve.py
since Phase 5 rewired both sides onto the pgvector store."""
from memory.retrieve import (  # noqa: F401
    MemoryContext,
    MemoryExtraction,
    MemoryExtractor,
)
