"""Deterministic risk policy tests."""

from releaseguard.domain.models import (
    ChangedFile,
    ChangeStatus,
    ReadinessStatus,
    RepositorySnapshot,
    RiskLevel,
)
from releaseguard.domain.policy import DeterministicRiskPolicy, evidence_for_changed_file


def make_snapshot(*paths: str) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository="/safe/repository",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=tuple(ChangedFile(path=path, status=ChangeStatus.MODIFIED) for path in paths),
        diff_text="",
    )


def test_policy_returns_evidence_backed_findings() -> None:
    snapshot = make_snapshot("app/auth/service.py", "alembic/versions/001_add_table.py")
    evidence = {
        item.path: evidence_for_changed_file(snapshot, item) for item in snapshot.changed_files
    }

    findings = DeterministicRiskPolicy().evaluate(snapshot, evidence)

    assert {finding.category for finding in findings} == {"security", "database"}
    assert all(finding.level is RiskLevel.HIGH for finding in findings)
    assert all(finding.evidence_ids for finding in findings)


def test_policy_marks_environment_file_as_critical() -> None:
    snapshot = make_snapshot(".env.production")
    evidence = {
        item.path: evidence_for_changed_file(snapshot, item) for item in snapshot.changed_files
    }

    findings = DeterministicRiskPolicy().evaluate(snapshot, evidence)

    assert len(findings) == 1
    assert findings[0].level is RiskLevel.CRITICAL


def test_readiness_enum_values_are_stable() -> None:
    assert ReadinessStatus.REVIEW_REQUIRED.value == "review_required"
