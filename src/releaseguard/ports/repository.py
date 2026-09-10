"""Repository access port."""

from pathlib import Path
from typing import Protocol

from releaseguard.domain.models import RepositorySnapshot


class RepositoryPort(Protocol):
    """Read-only repository operations required by analysis."""

    def snapshot(self, repository: Path, base_ref: str, head_ref: str) -> RepositorySnapshot:
        """Return an immutable comparison snapshot."""
        ...
