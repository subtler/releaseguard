"""Local embedding adapter tests."""

import json
import math

import httpx
import pytest

from releaseguard.adapters.embeddings import EmbeddingError, HashingEmbedder, OllamaEmbedder


def test_hashing_embedder_is_deterministic_normalized_and_identifier_aware() -> None:
    embedder = HashingEmbedder(dimensions=64)

    first, second, empty = embedder.embed(("releaseGuard auth_policy", "release guard", ""))

    assert first == embedder.embed(("releaseGuard auth_policy",))[0]
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1)
    assert sum(a * b for a, b in zip(first, second, strict=True)) > 0
    assert set(empty) == {0.0}


def test_hashing_embedder_rejects_tiny_vector() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        HashingEmbedder(dimensions=8)


def test_ollama_embedder_calls_local_batch_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/api/embed"
        assert payload["model"] == "embeddinggemma"
        assert payload["truncate"] is False
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0], [0.0, 1.0]]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = OllamaEmbedder(
            base_url="http://127.0.0.1:11434",
            model="embeddinggemma",
            timeout_seconds=5,
            client=client,
        )
        vectors = embedder.embed(("first", "second"))

    assert vectors == ((1.0, 0.0), (0.0, 1.0))


def test_ollama_embedder_fails_closed_on_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"embeddings": [[1.0]]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = OllamaEmbedder(
            base_url="http://127.0.0.1:11434",
            model="embeddinggemma",
            timeout_seconds=5,
            client=client,
        )
        with pytest.raises(EmbeddingError, match="wrong number"):
            embedder.embed(("first", "second"))
