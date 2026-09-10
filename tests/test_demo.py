"""Tests for the bundled interactive demonstration repository."""

from pathlib import Path

from releaseguard.bootstrap import build_analyzer
from releaseguard.config import Settings
from releaseguard.demo import DemoRepositoryFactory
from releaseguard.domain.models import ReadinessStatus


def test_demo_explains_permission_change_and_affected_tests(tmp_path: Path) -> None:
    repository = DemoRepositoryFactory().create(tmp_path)
    analyzer = build_analyzer(
        Settings(
            repository_root=tmp_path,
            checkpoint_database=tmp_path / "checkpoints.sqlite3",
            max_diff_bytes=100_000,
            max_index_files=100,
            max_source_file_bytes=10_000,
        )
    )

    report = analyzer.execute(repository, "baseline", "candidate")

    assert report.status is ReadinessStatus.REVIEW_REQUIRED
    assert {item.path for item in report.changed_files} == {
        "src/payments/auth.py",
        "src/payments/service.py",
    }
    assert {finding.category for finding in report.findings} == {"security"}
    assert report.impact is not None
    assert report.impact.direct_dependents == (
        "src/payments/api.py",
        "tests/test_refund.py",
    )
    assert report.impact.transitive_dependents == ()
    assert report.impact.candidate_tests == ("tests/test_refund.py",)


def test_demo_creation_is_idempotent(tmp_path: Path) -> None:
    factory = DemoRepositoryFactory()

    first = factory.create(tmp_path)
    second = factory.create(tmp_path)

    assert first == second
