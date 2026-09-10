"""Safe local Git adapter integration tests."""

import subprocess
from pathlib import Path

import pytest

from releaseguard.adapters.git_local import RepositoryAccessError, SafeLocalGitAdapter
from releaseguard.domain.models import ChangeStatus


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repository), *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "ReleaseGuard Tests")
    git(repo, "config", "user.email", "tests@example.invalid")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "baseline")
    (repo / "app").mkdir()
    (repo / "app" / "auth.py").write_text("def authorize():\n    return False\n", encoding="utf-8")
    git(repo, "add", "app/auth.py")
    git(repo, "commit", "-m", "change auth")
    return repo


def test_snapshot_resolves_commits_and_collects_stats(repository: Path) -> None:
    adapter = SafeLocalGitAdapter(
        repository_root=repository.parent,
        timeout_seconds=5,
        max_diff_bytes=100_000,
    )

    snapshot = adapter.snapshot(repository, "HEAD^", "HEAD")

    assert len(snapshot.changed_files) == 1
    assert snapshot.changed_files[0].path == "app/auth.py"
    assert snapshot.changed_files[0].status is ChangeStatus.ADDED
    assert snapshot.changed_files[0].additions == 2
    assert snapshot.base_sha == git(repository, "rev-parse", "HEAD^")
    assert snapshot.head_sha == git(repository, "rev-parse", "HEAD")
    assert "authorize" in snapshot.diff_text


def test_snapshot_rejects_path_outside_allowlist(repository: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    adapter = SafeLocalGitAdapter(
        repository_root=other,
        timeout_seconds=5,
        max_diff_bytes=100_000,
    )

    with pytest.raises(RepositoryAccessError, match="outside"):
        adapter.snapshot(repository, "HEAD^", "HEAD")


def test_snapshot_rejects_option_like_ref(repository: Path) -> None:
    adapter = SafeLocalGitAdapter(
        repository_root=repository.parent,
        timeout_seconds=5,
        max_diff_bytes=100_000,
    )

    with pytest.raises(RepositoryAccessError, match="unsupported"):
        adapter.snapshot(repository, "--output=/tmp/not-allowed", "HEAD")


def test_snapshot_rejects_non_git_directory(tmp_path: Path) -> None:
    candidate = tmp_path / "plain-directory"
    candidate.mkdir()
    adapter = SafeLocalGitAdapter(
        repository_root=tmp_path,
        timeout_seconds=5,
        max_diff_bytes=100_000,
    )

    with pytest.raises(RepositoryAccessError, match="Git command failed"):
        adapter.snapshot(candidate, "HEAD^", "HEAD")


def test_snapshot_marks_bounded_diff_as_truncated(repository: Path) -> None:
    adapter = SafeLocalGitAdapter(
        repository_root=repository.parent,
        timeout_seconds=5,
        max_diff_bytes=1_024,
    )
    large_file = repository / "large.txt"
    large_file.write_text("x" * 4_096, encoding="utf-8")
    git(repository, "add", "large.txt")
    git(repository, "commit", "-m", "add large file")

    snapshot = adapter.snapshot(repository, "HEAD^", "HEAD")

    assert snapshot.diff_truncated is True
    assert len(snapshot.diff_text.encode("utf-8")) == 1_024


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/{old => new}/module.py", "src/new/module.py"),
        ("old.py => new.py", "new.py"),
        ("unchanged.py", "unchanged.py"),
    ],
)
def test_normalize_numstat_path(path: str, expected: str) -> None:
    assert SafeLocalGitAdapter._normalize_numstat_path(path) == expected


def test_commit_pinned_source_listing_and_read(repository: Path) -> None:
    adapter = SafeLocalGitAdapter(
        repository_root=repository.parent,
        timeout_seconds=5,
        max_diff_bytes=100_000,
    )
    head_sha = git(repository, "rev-parse", "HEAD")

    manifest = adapter.list_files(repository, head_sha, max_files=100)
    content = adapter.read_text_file(repository, head_sha, "app/auth.py", max_bytes=10_000)

    assert "app/auth.py" in manifest.paths
    assert manifest.commit_sha == head_sha
    assert manifest.truncated is False
    assert "authorize" in content


def test_commit_pinned_source_read_enforces_path_and_size(repository: Path) -> None:
    adapter = SafeLocalGitAdapter(
        repository_root=repository.parent,
        timeout_seconds=5,
        max_diff_bytes=100_000,
    )
    head_sha = git(repository, "rev-parse", "HEAD")

    with pytest.raises(RepositoryAccessError, match="path is not safe"):
        adapter.read_text_file(repository, head_sha, "../secret", max_bytes=10_000)
    with pytest.raises(RepositoryAccessError, match="byte limit"):
        adapter.read_text_file(repository, head_sha, "app/auth.py", max_bytes=4)
    with pytest.raises(RepositoryAccessError, match="commit SHA"):
        adapter.list_files(repository, "HEAD", max_files=100)
