"""Embeddings interface (Phase 5).

Memory search embeds text with the same provider-agnostic pattern as chat:
the real provider calls OpenRouter's /embeddings endpoint via httpx (no SDK,
no hard-coded model outside routing.yaml), tests use a deterministic fake.
"""
import hashlib
import os
from abc import ABC, abstractmethod
from typing import List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from .routing import Routing, load_routing

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
EMBEDDING_DIMENSIONS = 1536


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Embed one text into a fixed-dimension vector."""
        raise NotImplementedError

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed many texts (one API call when the provider supports it)."""
        raise NotImplementedError


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible /embeddings via OpenRouter (locked decision)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        model: Optional[str] = None,
        routing: Optional[Routing] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = (
            base_url or os.getenv("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._client = client
        # Role "embedding" keeps every model name in routing.yaml.
        self.model = model or (routing or load_routing()).model_for("embedding")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _post_once(self, body: dict) -> httpx.Response:
        url = f"{self.base_url}/embeddings"
        if self._client is not None:
            response = await self._client.post(url, json=body, headers=self._headers())
        else:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=body, headers=self._headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Embeddings {response.status_code}: {response.text[:300]}")
        return response

    async def _post(self, body: dict) -> httpx.Response:
        attempt = retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.5, max=4.0),
            reraise=True,
        )(self._post_once)
        return await attempt(body)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        response = await self._post({
            "model": self.model,
            "input": texts,
            "dimensions": EMBEDDING_DIMENSIONS,
        })
        data = response.json()
        items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in items]
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"Embeddings returned {len(vectors)} vectors for {len(texts)} inputs"
            )
        return vectors

    async def embed(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]


class FakeEmbedding(EmbeddingProvider):
    """Deterministic hash-based vectors: identical text -> identical vector,
    different text -> dissimilar vector. No network, no API key."""

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def _vector(self, text: str) -> List[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand the seed deterministically to `dimensions` floats in [-1, 1].
        vector: List[float] = []
        counter = 0
        while len(vector) < self.dimensions:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for i in range(0, len(digest), 2):
                value = int.from_bytes(digest[i:i + 2], "big") / 65535.0
                vector.append(value * 2.0 - 1.0)
                if len(vector) == self.dimensions:
                    break
            counter += 1
        return vector

    async def embed(self, text: str) -> List[float]:
        return self._vector(text)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._vector(text) for text in texts]


def build_embedding_provider() -> EmbeddingProvider:
    """Fake unless OPENROUTER_API_KEY is set (mirrors llm/factory)."""
    if os.getenv("OPENROUTER_API_KEY"):
        return OpenAIEmbeddingProvider()
    return FakeEmbedding()
