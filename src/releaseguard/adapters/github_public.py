"""Bounded importer for public GitHub repositories used by the web demo."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4

from releaseguard.adapters.git_local import RepositoryAccessError

_SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")


@dataclass(frozen=True, slots=True)
class ImportedRepository:
    """A local, read-only analysis copy of a public GitHub repository."""

    path: Path
    canonical_url: str


class PublicGitHubImporter:
    """Clone a recent, time-bounded view of a public github.com repository."""

    def __init__(self, *, timeout_seconds: float = 45.0, history_depth: int = 50) -> None:
        self._timeout_seconds = timeout_seconds
        self._history_depth = history_depth
        self._lock = Lock()

    def import_repository(self, url: str, workspace_root: Path) -> ImportedRepository:
        """Validate and clone a public GitHub URL into a controlled workspace."""
        canonical_url = self.canonicalize(url)
        workspace = workspace_root.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        repository_key = sha256(canonical_url.encode("utf-8")).hexdigest()[:20]
        target = workspace / f"github-{repository_key}"

        with self._lock:
            if (target / ".git").is_dir():
                return ImportedRepository(
                    path=target, canonical_url=canonical_url.removesuffix(".git")
                )

            partial = workspace / f".clone-{repository_key}-{uuid4().hex}"
            try:
                self._clone(canonical_url, partial)
                if target.exists():
                    shutil.rmtree(partial, ignore_errors=True)
                else:
                    partial.replace(target)
            except (OSError, subprocess.SubprocessError) as exc:
                shutil.rmtree(partial, ignore_errors=True)
                raise RepositoryAccessError(
                    "The public repository could not be imported within the safety limits."
                ) from exc

        return ImportedRepository(path=target, canonical_url=canonical_url.removesuffix(".git"))

    @staticmethod
    def canonicalize(url: str) -> str:
        """Return a credential-free canonical clone URL for a github.com owner/repository pair."""
        value = url.strip()
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise RepositoryAccessError(
                "Use a public URL in the form https://github.com/owner/repository."
            )
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 2:
            raise RepositoryAccessError(
                "Use a repository URL, not a file, pull request, or organization URL."
            )
        owner, repository = parts
        repository = repository.removesuffix(".git")
        if not _SLUG.fullmatch(owner) or not _SLUG.fullmatch(repository):
            raise RepositoryAccessError("The GitHub owner or repository name is not valid.")
        return f"https://github.com/{owner}/{repository}.git"

    def _clone(self, canonical_url: str, target: Path) -> None:
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C.UTF-8",
        }
        result = subprocess.run(
            (
                "git",
                "clone",
                "--depth",
                str(self._history_depth),
                "--no-single-branch",
                "--no-checkout",
                "--",
                canonical_url,
                str(target),
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
            env=env,
        )
        if result.returncode != 0:
            detail = result.stderr.strip()[-1_000:]
            raise RepositoryAccessError(
                f"GitHub import failed: {detail or 'the repository is unavailable'}"
            )
