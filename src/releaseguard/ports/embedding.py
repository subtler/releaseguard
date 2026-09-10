"""Text-embedding port."""

from typing import Protocol


class EmbeddingPort(Protocol):
    """Create comparable vectors for repository text and queries."""

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        """Embed an ordered batch without changing its cardinality."""
        ...
