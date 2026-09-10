"""Readiness report construction."""

from hashlib import sha256

from releaseguard.domain.models import (
    Evidence,
    ImpactAssessment,
    ReadinessReport,
    ReadinessStatus,
    RepositorySnapshot,
    RetrievedContext,
    RiskFinding,
    RiskLevel,
)


class ReportAssembler:
    """Build a stable report from already-collected and verified inputs."""

    def assemble(
        self,
        snapshot: RepositorySnapshot,
        evidence: tuple[Evidence, ...],
        findings: tuple[RiskFinding, ...],
        impact: ImpactAssessment | None = None,
        retrieved_context: tuple[RetrievedContext, ...] = (),
        extra_limitations: tuple[str, ...] = (),
    ) -> ReadinessReport:
        """Create the final report without introducing unsupported claims."""
        status = self.readiness_status(findings)
        analysis_identity = (
            f"{snapshot.repository}\x1f{snapshot.base_sha}\x1f{snapshot.head_sha}\x1fv1"
        )
        limitations = [
            "This baseline classifies path and change metadata; it does not yet infer "
            "semantic code impact.",
            "CI results, dependency graphs, architecture records, and runbooks are not "
            "yet collected.",
        ]
        if snapshot.diff_truncated:
            limitations.append(
                "The captured diff exceeded the configured byte limit and was truncated."
            )
        limitations.extend(extra_limitations)
        return ReadinessReport(
            analysis_id=f"analysis_{sha256(analysis_identity.encode('utf-8')).hexdigest()[:16]}",
            repository=snapshot.repository,
            base_sha=snapshot.base_sha,
            head_sha=snapshot.head_sha,
            status=status,
            generated_at=ReadinessReport.timestamp(),
            summary=self.summary(status, len(snapshot.changed_files), len(findings)),
            changed_files=snapshot.changed_files,
            evidence=evidence,
            findings=findings,
            impact=impact,
            retrieved_context=retrieved_context,
            limitations=tuple(limitations),
        )

    @staticmethod
    def readiness_status(findings: tuple[RiskFinding, ...]) -> ReadinessStatus:
        """Fail closed for critical changes and require review for high risk."""
        levels = {finding.level for finding in findings}
        if RiskLevel.CRITICAL in levels:
            return ReadinessStatus.BLOCKED
        if RiskLevel.HIGH in levels:
            return ReadinessStatus.REVIEW_REQUIRED
        return ReadinessStatus.READY

    @staticmethod
    def summary(status: ReadinessStatus, file_count: int, finding_count: int) -> str:
        """Create a deterministic, compact report summary."""
        if status is ReadinessStatus.BLOCKED:
            outcome = "Release is blocked by a critical deterministic policy finding."
        elif status is ReadinessStatus.REVIEW_REQUIRED:
            outcome = "Release requires review because high-risk change surfaces were detected."
        else:
            outcome = "No deterministic release blocker was detected."
        return (
            f"{outcome} Analyzed {file_count} changed files and produced {finding_count} findings."
        )
