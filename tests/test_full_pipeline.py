"""Full local ReleaseGuard pipeline test."""

import subprocess
from pathlib import Path

from releaseguard.bootstrap import build_analyzer
from releaseguard.config import Settings
from releaseguard.domain.models import ReadinessStatus


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repository), *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_full_pipeline_pins_git_builds_impact_and_checkpoints(tmp_path: Path) -> None:
    repository = tmp_path / "service"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.name", "ReleaseGuard Tests")
    git(repository, "config", "user.email", "tests@example.invalid")
    for directory in ("src/shop", "tests"):
        (repository / directory).mkdir(parents=True, exist_ok=True)
    (repository / "src/shop/models.py").write_text("class Order: pass\n", encoding="utf-8")
    (repository / "src/shop/service.py").write_text(
        "from shop.models import Order\n", encoding="utf-8"
    )
    (repository / "src/shop/api.py").write_text(
        "from shop.service import create_order\n", encoding="utf-8"
    )
    (repository / "tests/test_service.py").write_text(
        "from shop.service import create_order\n", encoding="utf-8"
    )
    git(repository, "add", ".")
    git(repository, "commit", "-m", "baseline")
    (repository / "src/shop/models.py").write_text(
        "class Order:\n    status = 'pending'\n", encoding="utf-8"
    )
    git(repository, "add", "src/shop/models.py")
    git(repository, "commit", "-m", "change order model")

    checkpoint_database = tmp_path / "releaseguard" / "checkpoints.sqlite3"
    analyzer = build_analyzer(
        Settings(
            repository_root=tmp_path,
            checkpoint_database=checkpoint_database,
            max_diff_bytes=100_000,
            max_index_files=100,
            max_source_file_bytes=10_000,
        )
    )

    report = analyzer.execute(repository, "HEAD^", "HEAD")

    assert report.status is ReadinessStatus.READY
    assert report.base_sha == git(repository, "rev-parse", "HEAD^")
    assert report.head_sha == git(repository, "rev-parse", "HEAD")
    assert report.impact is not None
    assert report.impact.direct_dependents == ("src/shop/service.py",)
    assert report.impact.transitive_dependents == (
        "src/shop/api.py",
        "tests/test_service.py",
    )
    assert report.impact.candidate_tests == ("tests/test_service.py",)
    assert checkpoint_database.is_file()
