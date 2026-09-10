"""Immutable source-context port."""

from pathlib import Path
from typing import Protocol

from releaseguard.domain.models import SourceManifest


class CodeContextPort(Protocol):
    """Read bounded source material from a pinned commit."""

    def list_files(self, repository: Path, commit_sha: str, *, max_files: int) -> SourceManifest:
        """List repository-relative paths at an immutable commit."""
        ...

    def read_text_file(
        self,
        repository: Path,
        commit_sha: str,
        path: str,
        *,
        max_bytes: int,
    ) -> str:
        """Read bounded UTF-8 source text from an immutable commit."""
        ...
