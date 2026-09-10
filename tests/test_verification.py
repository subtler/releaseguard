"""Evidence-verification tests."""

import pytest

from releaseguard.application.verification import EvidenceVerificationError, EvidenceVerifier
from releaseguard.domain.models import (
    ChangedFile,
    ChangeStatus,
    Evidence,
    EvidenceKind,
    RepositorySnapshot,
    RiskFinding,
    RiskLevel,
)


def snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        repository="/safe/repository",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=(ChangedFile(path="app/auth.py", status=ChangeStatus.MODIFIED),),
        diff_text="security change",
    )


def evidence(item_snapshot: RepositorySnapshot) -> Evidence:
    return Evidence.create(
        kind=EvidenceKind.CHANGED_FILE,
        repository=item_snapshot.repository,
        commit_sha=item_snapshot.head_sha,
        locator="app/auth.py",
        summary="Changed file",
    )


def test_verifier_accepts_grounded_finding() -> None:
    item_snapshot = snapshot()
    item_evidence = evidence(item_snapshot)
    finding = RiskFinding(
        id="risk_security",
        category="security",
        level=RiskLevel.HIGH,
        title="Security change",
        rationale="Authorization behavior changed.",
        evidence_ids=(item_evidence.id,),
        recommended_checks=("Run authorization tests.",),
    )

    EvidenceVerifier().verify(item_snapshot, (item_evidence,), (finding,))


def test_verifier_rejects_missing_file_and_unknown_finding_evidence() -> None:
    item_snapshot = snapshot()
    diff_evidence = Evidence.create(
        kind=EvidenceKind.DIFF_SUMMARY,
        repository=item_snapshot.repository,
        commit_sha=item_snapshot.head_sha,
        locator="comparison",
        summary="Diff",
    )
    finding = RiskFinding(
        id="risk_security",
        category="security",
        level=RiskLevel.HIGH,
        title="Security change",
        rationale="Authorization behavior changed.",
        evidence_ids=("ev_missing",),
        recommended_checks=("Run authorization tests.",),
    )

    with pytest.raises(EvidenceVerificationError, match=r"lack evidence.*unknown evidence"):
        EvidenceVerifier().verify(item_snapshot, (diff_evidence,), (finding,))


def test_verifier_rejects_duplicate_and_wrong_provenance() -> None:
    item_snapshot = snapshot()
    wrong = Evidence.create(
        kind=EvidenceKind.CHANGED_FILE,
        repository="/another/repository",
        commit_sha="c" * 40,
        locator="app/auth.py",
        summary="Changed file",
    )

    with pytest.raises(EvidenceVerificationError, match=r"unique.*different repository"):
        EvidenceVerifier().verify(item_snapshot, (wrong, wrong), ())
