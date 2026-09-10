"""Deterministic repository fixture for the interactive product demo."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from threading import Lock

from releaseguard.adapters.git_local import RepositoryAccessError


class DemoRepositoryFactory:
    """Create a small two-commit service that demonstrates change-impact analysis."""

    def __init__(self) -> None:
        self._lock = Lock()

    def create(self, workspace_root: Path) -> Path:
        """Return an idempotent demo repository with baseline and candidate tags."""
        workspace = workspace_root.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        repository = workspace / "demo-payment-service"
        with self._lock:
            if self._is_ready(repository):
                return repository
            if repository.exists():
                raise RepositoryAccessError("The demo workspace exists but is not valid.")
            self._build(repository)
        return repository

    def _build(self, repository: Path) -> None:
        (repository / "src" / "payments").mkdir(parents=True)
        (repository / "tests").mkdir()
        self._write(
            repository / "src" / "payments" / "auth.py",
            "def can_refund(role: str) -> bool:\n    return role == 'admin'\n",
        )
        self._write(
            repository / "src" / "payments" / "service.py",
            "from payments.auth import can_refund\n\n"
            "def refund(role: str) -> str:\n"
            "    if not can_refund(role):\n        raise PermissionError\n"
            "    return 'refunded'\n",
        )
        self._write(
            repository / "src" / "payments" / "api.py",
            "from payments.service import refund\n\n"
            "def refund_order(role: str) -> dict[str, str]:\n"
            "    return {'status': refund(role)}\n",
        )
        self._write(
            repository / "tests" / "test_refund.py",
            "from payments.service import refund\n\n"
            "def test_admin_can_refund() -> None:\n    assert refund('admin') == 'refunded'\n",
        )
        self._write(repository / "README.md", "# Demo payment service\n")
        self._git(repository, "init")
        self._git(repository, "symbolic-ref", "HEAD", "refs/heads/main")
        self._git(repository, "add", ".")
        self._commit(repository, "baseline payment service")
        self._git(repository, "tag", "baseline")

        self._write(
            repository / "src" / "payments" / "auth.py",
            "PRIVILEGED_ROLES = {'admin', 'support'}\n\n"
            "def can_refund(role: str) -> bool:\n    return role in PRIVILEGED_ROLES\n",
        )
        self._write(
            repository / "src" / "payments" / "service.py",
            "from payments.auth import can_refund\n\n"
            "def refund(role: str, amount: int = 0) -> str:\n"
            "    if not can_refund(role):\n        raise PermissionError\n"
            "    if amount < 0:\n        raise ValueError('amount must be positive')\n"
            "    return 'refunded'\n",
        )
        self._git(repository, "add", ".")
        self._commit(repository, "expand refund permissions")
        self._git(repository, "tag", "candidate")

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _is_ready(repository: Path) -> bool:
        if not (repository / ".git").is_dir():
            return False
        result = subprocess.run(
            (
                "git",
                "-C",
                str(repository),
                "show-ref",
                "--verify",
                "--quiet",
                "refs/tags/candidate",
            ),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    @staticmethod
    def _git(repository: Path, *args: str) -> None:
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C.UTF-8",
        }
        result = subprocess.run(
            ("git", "-C", str(repository), *args),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        if result.returncode != 0:
            raise RepositoryAccessError("The bundled demo repository could not be prepared.")

    def _commit(self, repository: Path, message: str) -> None:
        self._git(
            repository,
            "-c",
            "user.name=ReleaseGuard Demo",
            "-c",
            "user.email=demo@releaseguard.invalid",
            "commit",
            "-m",
            message,
        )
