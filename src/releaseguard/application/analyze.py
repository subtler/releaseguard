"""Synchronous change-analysis use case."""

from pathlib import Path

from releaseguard.application.reporting import ReportAssembler
from releaseguard.application.verification import EvidenceVerifier
from releaseguard.domain.models import Evidence, EvidenceKind, ReadinessReport
from releaseguard.domain.policy import DeterministicRiskPolicy, evidence_for_changed_file
from releaseguard.ports.repository import RepositoryPort


class AnalyzeChange:
    """Coordinate evidence collection and deterministic risk analysis."""

    def __init__(self, repository_port: RepositoryPort, policy: DeterministicRiskPolicy) -> None:
        self._repository_port = repository_port
        self._policy = policy
        self._verifier = EvidenceVerifier()
        self._assembler = ReportAssembler()

    def execute(self, repository: Path, base_ref: str, head_ref: str) -> ReadinessReport:
        """Analyze one immutable repository comparison."""
        snapshot = self._repository_port.snapshot(repository, base_ref, head_ref)
        file_evidence = {
            changed_file.path: evidence_for_changed_file(snapshot, changed_file)
            for changed_file in snapshot.changed_files
        }
        diff_evidence = Evidence.create(
            kind=EvidenceKind.DIFF_SUMMARY,
            repository=snapshot.repository,
            commit_sha=snapshot.head_sha,
            locator=f"{snapshot.base_sha}...{snapshot.head_sha}",
            summary=f"Git comparison containing {len(snapshot.changed_files)} changed files",
            content=snapshot.diff_text,
        )
        findings = self._policy.evaluate(snapshot, file_evidence)
        evidence = (*file_evidence.values(), diff_evidence)
        self._verifier.verify(snapshot, evidence, findings)
        return self._assembler.assemble(snapshot, evidence, findings)
