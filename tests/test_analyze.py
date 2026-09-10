"""Analysis use-case tests."""

from pathlib import Path

from releaseguard.application.analyze import AnalyzeChange
from releaseguard.domain.models import (
    ChangedFile,
    ChangeStatus,
    ReadinessStatus,
    RepositorySnapshot,
)
from releaseguard.domain.policy import DeterministicRiskPolicy


class FakeRepository:
    def __init__(self, snapshot: RepositorySnapshot) -> None:
        self.snapshot_result = snapshot

    def snapshot(self, repository: Path, base_ref: str, head_ref: str) -> RepositorySnapshot:
        assert repository == Path("/safe/repository")
        assert base_ref == "main"
        assert head_ref == "feature"
        return self.snapshot_result


def test_analysis_blocks_credential_shaped_change() -> None:
    snapshot = RepositorySnapshot(
        repository="/safe/repository",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=(
            ChangedFile(path=".env", status=ChangeStatus.ADDED, additions=1, deletions=0),
        ),
        diff_text="+SECRET=redacted",
    )
    analyzer = AnalyzeChange(FakeRepository(snapshot), DeterministicRiskPolicy())

    report = analyzer.execute(Path("/safe/repository"), "main", "feature")

    assert report.status is ReadinessStatus.BLOCKED
    assert report.findings[0].category == "credentials"
    assert report.findings[0].evidence_ids[0] in {item.id for item in report.evidence}
    assert report.base_sha == "a" * 40
    assert report.head_sha == "b" * 40


def test_analysis_is_ready_when_no_high_risk_rule_matches() -> None:
    snapshot = RepositorySnapshot(
        repository="/safe/repository",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=(ChangedFile(path="docs/usage.md", status=ChangeStatus.MODIFIED),),
        diff_text="documentation change",
    )
    analyzer = AnalyzeChange(FakeRepository(snapshot), DeterministicRiskPolicy())

    report = analyzer.execute(Path("/safe/repository"), "main", "feature")

    assert report.status is ReadinessStatus.READY
    assert report.findings == ()
