"""Safe, read-only local Git adapter."""

import os
import re
import subprocess
from collections.abc import Sequence
from io import BufferedReader
from pathlib import Path
from threading import Lock, Thread

from releaseguard.domain.models import ChangedFile, ChangeStatus, RepositorySnapshot, SourceManifest


class RepositoryAccessError(RuntimeError):
    """Raised when repository evidence cannot be collected safely."""


_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@{}~^+\-]*$")
_STATUS_MAP = {
    "A": ChangeStatus.ADDED,
    "M": ChangeStatus.MODIFIED,
    "D": ChangeStatus.DELETED,
    "R": ChangeStatus.RENAMED,
    "C": ChangeStatus.COPIED,
    "T": ChangeStatus.TYPE_CHANGED,
}


class SafeLocalGitAdapter:
    """Collect bounded Git evidence without shell execution or writes."""

    def __init__(
        self, *, repository_root: Path, timeout_seconds: float, max_diff_bytes: int
    ) -> None:
        self._repository_root = repository_root.expanduser().resolve()
        self._timeout_seconds = timeout_seconds
        self._max_diff_bytes = max_diff_bytes
        self._validation_lock = Lock()
        self._validated_repositories: set[Path] = set()

    def snapshot(self, repository: Path, base_ref: str, head_ref: str) -> RepositorySnapshot:
        """Resolve refs and collect changed paths, line counts, and a bounded diff."""
        repo = self._resolve_repository(repository)
        base_sha = self._resolve_ref(repo, base_ref)
        head_sha = self._resolve_ref(repo, head_ref)
        comparison = f"{base_sha}...{head_sha}"
        changed_files = self._changed_files(repo, comparison)
        line_stats = self._line_stats(repo, comparison)
        enriched = tuple(
            self._with_stats(file, line_stats.get(file.path)) for file in changed_files
        )
        diff_bytes = self._git_bytes(
            repo,
            ("diff", "--no-ext-diff", "--no-color", "--find-renames", comparison),
            output_limit=self._max_diff_bytes + 1,
        )
        truncated = len(diff_bytes) > self._max_diff_bytes
        bounded_diff = diff_bytes[: self._max_diff_bytes].decode("utf-8", errors="replace")
        return RepositorySnapshot(
            repository=str(repo),
            base_sha=base_sha,
            head_sha=head_sha,
            changed_files=enriched,
            diff_text=bounded_diff,
            diff_truncated=truncated,
        )

    def list_files(self, repository: Path, commit_sha: str, *, max_files: int) -> SourceManifest:
        """List a bounded immutable repository tree for structure analysis."""
        repo = self._resolve_repository(repository)
        self._validate_commit_sha(commit_sha)
        byte_limit = min(max_files * 4_096, 20_000_000) + 1
        output = self._git_bytes(
            repo,
            ("ls-tree", "-r", "-z", "--name-only", commit_sha),
            output_limit=byte_limit,
        )
        byte_truncated = len(output) == byte_limit
        paths = output.decode("utf-8", errors="replace").rstrip("\x00").split("\x00")
        if not output:
            paths = []
        count_truncated = len(paths) > max_files
        return SourceManifest(
            commit_sha=commit_sha,
            paths=tuple(paths[:max_files]),
            truncated=byte_truncated or count_truncated,
        )

    def read_text_file(
        self,
        repository: Path,
        commit_sha: str,
        path: str,
        *,
        max_bytes: int,
    ) -> str:
        """Read a bounded blob from a pinned commit without touching the working tree."""
        repo = self._resolve_repository(repository)
        self._validate_commit_sha(commit_sha)
        self._validate_repository_path(path)
        content = self._git_bytes(
            repo,
            ("cat-file", "blob", f"{commit_sha}:{path}"),
            output_limit=max_bytes + 1,
        )
        if len(content) > max_bytes:
            raise RepositoryAccessError(f"source file exceeds the {max_bytes}-byte limit")
        return content.decode("utf-8", errors="replace")

    def _resolve_repository(self, repository: Path) -> Path:
        candidate = repository.expanduser().resolve()
        if candidate != self._repository_root and self._repository_root not in candidate.parents:
            raise RepositoryAccessError("repository is outside the configured repository root")
        if not candidate.is_dir():
            raise RepositoryAccessError("repository directory does not exist")
        with self._validation_lock:
            if candidate in self._validated_repositories:
                return candidate
        inside = self._git_text(candidate, ("rev-parse", "--is-inside-work-tree")).strip()
        if inside != "true":
            raise RepositoryAccessError("path is not a Git working tree")
        with self._validation_lock:
            self._validated_repositories.add(candidate)
        return candidate

    def _resolve_ref(self, repository: Path, ref: str) -> str:
        if not _SAFE_REF.fullmatch(ref):
            raise RepositoryAccessError("Git reference contains unsupported characters")
        resolved = self._git_text(
            repository, ("rev-parse", "--verify", f"{ref}^{{commit}}")
        ).strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", resolved):
            raise RepositoryAccessError("Git reference did not resolve to a commit")
        return resolved

    @staticmethod
    def _validate_commit_sha(commit_sha: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit_sha):
            raise RepositoryAccessError("commit SHA is not immutable or valid")

    @staticmethod
    def _validate_repository_path(path: str) -> None:
        parts = path.split("/")
        if not path or path.startswith("/") or "\x00" in path or ".." in parts:
            raise RepositoryAccessError("repository path is not safe")

    def _changed_files(self, repository: Path, comparison: str) -> tuple[ChangedFile, ...]:
        output = self._git_bytes(
            repository,
            ("diff", "--name-status", "-z", "--find-renames", comparison),
            output_limit=self._max_diff_bytes,
        )
        tokens = (
            output.decode("utf-8", errors="replace").rstrip("\x00").split("\x00") if output else []
        )
        files: list[ChangedFile] = []
        index = 0
        while index < len(tokens):
            status_token = tokens[index]
            index += 1
            status = _STATUS_MAP.get(status_token[:1], ChangeStatus.UNKNOWN)
            if status in {ChangeStatus.RENAMED, ChangeStatus.COPIED}:
                if index + 1 >= len(tokens):
                    raise RepositoryAccessError("Git returned an incomplete rename record")
                previous_path, path = tokens[index], tokens[index + 1]
                index += 2
                files.append(ChangedFile(path=path, previous_path=previous_path, status=status))
                continue
            if index >= len(tokens):
                raise RepositoryAccessError("Git returned an incomplete file status record")
            files.append(ChangedFile(path=tokens[index], status=status))
            index += 1
        return tuple(files)

    def _line_stats(
        self, repository: Path, comparison: str
    ) -> dict[str, tuple[int | None, int | None, bool]]:
        output = self._git_text(repository, ("diff", "--numstat", "--find-renames", comparison))
        stats: dict[str, tuple[int | None, int | None, bool]] = {}
        for line in output.splitlines():
            parts = line.split("\t", maxsplit=2)
            if len(parts) != 3:
                continue
            additions_text, deletions_text, path = parts
            binary = additions_text == "-" or deletions_text == "-"
            additions = None if binary else int(additions_text)
            deletions = None if binary else int(deletions_text)
            normalized_path = self._normalize_numstat_path(path)
            stats[normalized_path] = (additions, deletions, binary)
        return stats

    @staticmethod
    def _normalize_numstat_path(path: str) -> str:
        if " => " not in path:
            return path
        if "{" in path and "}" in path:
            prefix, remainder = path.split("{", maxsplit=1)
            middle, suffix = remainder.split("}", maxsplit=1)
            _, new = middle.split(" => ", maxsplit=1)
            return f"{prefix}{new}{suffix}"
        return path.rsplit(" => ", maxsplit=1)[-1]

    @staticmethod
    def _with_stats(
        changed_file: ChangedFile,
        stats: tuple[int | None, int | None, bool] | None,
    ) -> ChangedFile:
        if stats is None:
            return changed_file
        additions, deletions, binary = stats
        return changed_file.model_copy(
            update={"additions": additions, "deletions": deletions, "binary": binary}
        )

    def _git_text(self, repository: Path, args: Sequence[str]) -> str:
        return self._git_bytes(repository, args, output_limit=self._max_diff_bytes).decode(
            "utf-8", errors="replace"
        )

    def _git_bytes(self, repository: Path, args: Sequence[str], *, output_limit: int) -> bytes:
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C.UTF-8",
        }
        try:
            process = subprocess.Popen(
                ("git", "-C", str(repository), *args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            raise RepositoryAccessError("Git command could not complete") from exc

        if process.stdout is None or process.stderr is None:
            process.kill()
            raise RepositoryAccessError("Git command streams were unavailable")
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        stdout_thread = Thread(
            target=self._drain_stream,
            args=(process.stdout, stdout_buffer, output_limit),
            daemon=True,
        )
        stderr_thread = Thread(
            target=self._drain_stream,
            args=(process.stderr, stderr_buffer, 4_096),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            return_code = process.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            stdout_thread.join()
            stderr_thread.join()
            raise RepositoryAccessError("Git command could not complete") from exc
        stdout_thread.join()
        stderr_thread.join()
        if return_code != 0:
            message = bytes(stderr_buffer).decode("utf-8", errors="replace").strip()
            raise RepositoryAccessError(f"Git command failed: {message or 'unknown error'}")
        return bytes(stdout_buffer)

    @staticmethod
    def _drain_stream(stream: BufferedReader, target: bytearray, limit: int) -> None:
        """Drain a subprocess stream while retaining only a bounded prefix."""
        while chunk := stream.read(65_536):
            remaining = limit - len(target)
            if remaining > 0:
                target.extend(chunk[:remaining])
        stream.close()
