"""Explainable deterministic change-risk policy."""

from dataclasses import dataclass
from fnmatch import fnmatch
from hashlib import sha256

from releaseguard.domain.models import (
    ChangedFile,
    Evidence,
    EvidenceKind,
    RepositorySnapshot,
    RiskFinding,
    RiskLevel,
)


@dataclass(frozen=True, slots=True)
class RiskRule:
    """A version-controlled path risk rule."""

    category: str
    level: RiskLevel
    title: str
    patterns: tuple[str, ...]
    rationale: str
    recommended_checks: tuple[str, ...]


DEFAULT_RULES: tuple[RiskRule, ...] = (
    RiskRule(
        category="credentials",
        level=RiskLevel.CRITICAL,
        title="Potential credential or local environment file changed",
        patterns=(".env", ".env.*", "*.pem", "*.key", "*credentials*"),
        rationale="Credential-shaped files can expose secrets or change runtime authority.",
        recommended_checks=(
            "Verify that no secret material is present in the diff or Git history.",
            "Confirm secret scanning passes before merge.",
        ),
    ),
    RiskRule(
        category="security",
        level=RiskLevel.HIGH,
        title="Authentication or authorization surface changed",
        patterns=("*auth*", "*security*", "*permission*", "*policy*", "*rbac*"),
        rationale=(
            "Security-control changes can alter identity, authorization, or policy enforcement."
        ),
        recommended_checks=(
            "Run authorization boundary and negative-permission tests.",
            "Review default-deny behavior and audit events.",
        ),
    ),
    RiskRule(
        category="database",
        level=RiskLevel.HIGH,
        title="Database schema or migration changed",
        patterns=("*migration*", "alembic/*", "*/alembic/*", "*.sql", "*schema*"),
        rationale="Schema changes can affect compatibility, data integrity, and rollback safety.",
        recommended_checks=(
            "Test forward and rollback migrations against representative data.",
            "Check backward compatibility with the currently deployed application version.",
        ),
    ),
    RiskRule(
        category="delivery",
        level=RiskLevel.HIGH,
        title="Build, deployment, or infrastructure configuration changed",
        patterns=(
            ".github/workflows/*",
            "Dockerfile*",
            "docker-compose*",
            "compose.y*ml",
            "infra/*",
            "*/infra/*",
            "terraform/*",
            "*/terraform/*",
            "k8s/*",
            "*/k8s/*",
            "helm/*",
            "*/helm/*",
        ),
        rationale=(
            "Delivery changes can affect build provenance, runtime configuration, or rollout "
            "behavior."
        ),
        recommended_checks=(
            "Validate the built artifact and deployment plan in an isolated environment.",
            "Confirm health checks, rollback, and secret references remain valid.",
        ),
    ),
    RiskRule(
        category="dependencies",
        level=RiskLevel.MEDIUM,
        title="Application dependency set changed",
        patterns=(
            "pyproject.toml",
            "uv.lock",
            "requirements*.txt",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "Cargo.toml",
            "Cargo.lock",
            "go.mod",
            "go.sum",
        ),
        rationale=(
            "Dependency changes can introduce compatibility, licensing, and supply-chain risk."
        ),
        recommended_checks=(
            "Run dependency vulnerability and license checks.",
            "Exercise integration tests using the locked dependency set.",
        ),
    ),
)


class DeterministicRiskPolicy:
    """Classify changed paths using transparent, testable rules."""

    def __init__(self, rules: tuple[RiskRule, ...] = DEFAULT_RULES) -> None:
        self._rules = rules

    def evaluate(
        self, snapshot: RepositorySnapshot, file_evidence: dict[str, Evidence]
    ) -> tuple[RiskFinding, ...]:
        """Return one finding per matched policy category."""
        findings: list[RiskFinding] = []
        for rule in self._rules:
            matches = tuple(file for file in snapshot.changed_files if self._matches(rule, file))
            if not matches:
                continue
            evidence_ids = tuple(file_evidence[file.path].id for file in matches)
            identity = "\x1f".join((rule.category, rule.level.value, *sorted(evidence_ids)))
            findings.append(
                RiskFinding(
                    id=f"risk_{sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                    category=rule.category,
                    level=rule.level,
                    title=rule.title,
                    rationale=rule.rationale,
                    evidence_ids=evidence_ids,
                    recommended_checks=rule.recommended_checks,
                )
            )
        return tuple(findings)

    @staticmethod
    def _matches(rule: RiskRule, changed_file: ChangedFile) -> bool:
        path = changed_file.path.lower()
        return any(fnmatch(path, pattern.lower()) for pattern in rule.patterns)


def evidence_for_changed_file(snapshot: RepositorySnapshot, changed_file: ChangedFile) -> Evidence:
    """Create immutable file-change evidence."""
    line_summary = (
        "binary change"
        if changed_file.binary
        else (f"+{changed_file.additions or 0}/-{changed_file.deletions or 0} lines")
    )
    return Evidence.create(
        kind=EvidenceKind.CHANGED_FILE,
        repository=snapshot.repository,
        commit_sha=snapshot.head_sha,
        locator=changed_file.path,
        summary=f"{changed_file.status.value} file; {line_summary}",
    )
