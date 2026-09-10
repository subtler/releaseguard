"""Deterministic report-input verification."""

from releaseguard.domain.models import Evidence, EvidenceKind, RepositorySnapshot, RiskFinding


class EvidenceVerificationError(RuntimeError):
    """Raised when a report claim is not supported by valid evidence."""


class EvidenceVerifier:
    """Validate evidence provenance before a readiness report is emitted."""

    def verify(
        self,
        snapshot: RepositorySnapshot,
        evidence: tuple[Evidence, ...],
        findings: tuple[RiskFinding, ...],
    ) -> None:
        """Raise with all detected invariant failures."""
        errors: list[str] = []
        evidence_ids = [item.id for item in evidence]
        known_ids = set(evidence_ids)
        if len(evidence_ids) != len(known_ids):
            errors.append("evidence identifiers must be unique")

        expected_paths = {item.path for item in snapshot.changed_files}
        evidenced_paths = {
            item.locator for item in evidence if item.kind is EvidenceKind.CHANGED_FILE
        }
        missing_paths = sorted(expected_paths - evidenced_paths)
        if missing_paths:
            errors.append(f"changed files lack evidence: {', '.join(missing_paths)}")

        for item in evidence:
            if item.repository != snapshot.repository:
                errors.append(f"evidence {item.id} references a different repository")
            if item.commit_sha != snapshot.head_sha:
                errors.append(f"evidence {item.id} references a different commit")

        for finding in findings:
            missing_ids = sorted(set(finding.evidence_ids) - known_ids)
            if missing_ids:
                errors.append(
                    f"finding {finding.id} references unknown evidence: {', '.join(missing_ids)}"
                )

        if errors:
            raise EvidenceVerificationError("; ".join(errors))
