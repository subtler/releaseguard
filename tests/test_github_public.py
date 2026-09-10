"""Tests for strict public GitHub repository URL handling."""

import pytest

from releaseguard.adapters.git_local import RepositoryAccessError
from releaseguard.adapters.github_public import PublicGitHubImporter


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://github.com/subtler/releaseguard", "https://github.com/subtler/releaseguard.git"),
        (
            "https://github.com/subtler/releaseguard.git",
            "https://github.com/subtler/releaseguard.git",
        ),
        (
            " https://github.com/openai/openai-python/ ",
            "https://github.com/openai/openai-python.git",
        ),
    ],
)
def test_canonicalize_accepts_repository_urls(value: str, expected: str) -> None:
    assert PublicGitHubImporter.canonicalize(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/owner/repository",
        "https://gitlab.com/owner/repository",
        "https://token@github.com/owner/repository",
        "https://github.com/owner/repository/issues/1",
        "https://github.com/owner/repository?tab=readme",
        "file:///tmp/repository",
        "git@github.com:owner/repository.git",
    ],
)
def test_canonicalize_rejects_unsafe_or_non_repository_urls(value: str) -> None:
    with pytest.raises(RepositoryAccessError):
        PublicGitHubImporter.canonicalize(value)
