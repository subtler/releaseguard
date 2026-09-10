"""Free local embedding adapters."""

import math
import re
from hashlib import sha256
from itertools import pairwise

import httpx
from pydantic import BaseModel, ConfigDict


class EmbeddingError(RuntimeError):
    """Raised when an embedding backend violates its contract."""


class HashingEmbedder:
    """Deterministic local feature hashing for a zero-service vector baseline."""

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions < 32:
            raise ValueError("embedding dimensions must be at least 32")
        self._dimensions = dimensions

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        """Map identifier-aware token features into normalized vectors."""
        return tuple(self._embed_one(text) for text in texts)

    def _embed_one(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self._dimensions
        tokens = self._tokens(text)
        features = (*tokens, *(f"{left}::{right}" for left, right in pairwise(tokens)))
        for feature in features:
            digest = sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4]) % self._dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return tuple(vector)
        return tuple(value / norm for value in vector)

    @staticmethod
    def _tokens(text: str) -> tuple[str, ...]:
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        return tuple(token.lower() for token in re.findall(r"[A-Za-z0-9]+", expanded))


class _OllamaEmbedResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    embeddings: list[list[float]]


class OllamaEmbedder:
    """Use Ollama's local `/api/embed` endpoint for semantic embeddings."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api/embed"
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        """Embed one batch and validate count, dimensions, and finite values."""
        payload = {"model": self._model, "input": list(texts), "truncate": False}
        try:
            if self._client is not None:
                response = self._client.post(self._url, json=payload, timeout=self._timeout_seconds)
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.post(self._url, json=payload)
            response.raise_for_status()
            parsed = _OllamaEmbedResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingError("local Ollama embedding request failed") from exc

        vectors = tuple(tuple(value for value in vector) for vector in parsed.embeddings)
        if len(vectors) != len(texts):
            raise EmbeddingError("embedding backend returned the wrong number of vectors")
        dimensions = {len(vector) for vector in vectors}
        if not vectors or dimensions == {0} or len(dimensions) != 1:
            raise EmbeddingError("embedding backend returned inconsistent vector dimensions")
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise EmbeddingError("embedding backend returned non-finite values")
        return vectors
