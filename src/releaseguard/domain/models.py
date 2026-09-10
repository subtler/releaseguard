"""Framework-independent domain models."""

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    """Immutable base for evidence and report contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ChangeStatus(StrEnum):
    """Git-level file status."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    TYPE_CHANGED = "type_changed"
    UNKNOWN = "unknown"


class RiskLevel(StrEnum):
    """Finding severity ordered by operational impact."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReadinessStatus(StrEnum):
    """Deterministic release-readiness state."""

    READY = "ready"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class EvidenceKind(StrEnum):
    """How an evidence record was collected."""

    CHANGED_FILE = "changed_file"
    DIFF_SUMMARY = "diff_summary"
    POLICY_MATCH = "policy_match"
    RETRIEVED_CONTEXT = "retrieved_context"


class ChangedFile(FrozenModel):
    """A repository-relative change between immutable commits."""

    path: str = Field(min_length=1)
    status: ChangeStatus
    previous_path: str | None = None
    additions: int | None = Field(default=None, ge=0)
    deletions: int | None = Field(default=None, ge=0)
    binary: bool = False

    @model_validator(mode="after")
    def require_previous_path_for_rename(self) -> "ChangedFile":
        """Ensure rename records retain their source locator."""
        if self.status in {ChangeStatus.RENAMED, ChangeStatus.COPIED} and not self.previous_path:
            raise ValueError("previous_path is required for renamed or copied files")
        return self


class RepositorySnapshot(FrozenModel):
    """Immutable comparison material collected from a repository."""

    repository: str
    base_sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    head_sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    changed_files: tuple[ChangedFile, ...]
    diff_text: str
    diff_truncated: bool = False


class Evidence(FrozenModel):
    """Immutable evidence supporting a report claim."""

    id: str
    kind: EvidenceKind
    repository: str
    commit_sha: str
    locator: str
    summary: str
    content_hash: str | None = None

    @classmethod
    def create(
        cls,
        *,
        kind: EvidenceKind,
        repository: str,
        commit_sha: str,
        locator: str,
        summary: str,
        content: str | None = None,
    ) -> "Evidence":
        """Create a stable evidence identifier from immutable fields."""
        content_hash = sha256(content.encode("utf-8")).hexdigest() if content is not None else None
        identity = "\x1f".join(
            (kind.value, repository, commit_sha, locator, summary, content_hash or "")
        )
        evidence_id = f"ev_{sha256(identity.encode('utf-8')).hexdigest()[:16]}"
        return cls(
            id=evidence_id,
            kind=kind,
            repository=repository,
            commit_sha=commit_sha,
            locator=locator,
            summary=summary,
            content_hash=content_hash,
        )


class RiskFinding(FrozenModel):
    """A risk claim with explicit evidence references."""

    id: str
    category: str
    level: RiskLevel
    title: str
    rationale: str
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    recommended_checks: tuple[str, ...] = Field(min_length=1)


class ImpactAssessment(FrozenModel):
    """Static dependency impact derived from an immutable source tree."""

    commit_sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    changed_modules: tuple[str, ...]
    direct_dependents: tuple[str, ...]
    transitive_dependents: tuple[str, ...]
    candidate_tests: tuple[str, ...]
    indexed_file_count: int = Field(ge=0)
    parse_failures: tuple[str, ...]
    limitations: tuple[str, ...]


class SourceManifest(FrozenModel):
    """Bounded immutable repository tree listing."""

    commit_sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    paths: tuple[str, ...]
    truncated: bool = False


class RetrievedContext(FrozenModel):
    """Ranked repository context selected by hybrid retrieval."""

    path: str
    excerpt: str
    content_hash: str
    lexical_rank: int = Field(ge=1)
    vector_rank: int = Field(ge=1)
    fusion_score: float = Field(gt=0)


class ReadinessReport(FrozenModel):
    """Complete deterministic analysis output."""

    analysis_id: str
    repository: str
    base_sha: str
    head_sha: str
    status: ReadinessStatus
    generated_at: datetime
    summary: str
    changed_files: tuple[ChangedFile, ...]
    evidence: tuple[Evidence, ...]
    findings: tuple[RiskFinding, ...]
    impact: ImpactAssessment | None = None
    retrieved_context: tuple[RetrievedContext, ...] = ()
    limitations: tuple[str, ...]

    @classmethod
    def timestamp(cls) -> datetime:
        """Return a timezone-aware UTC timestamp."""
        return datetime.now(UTC)
