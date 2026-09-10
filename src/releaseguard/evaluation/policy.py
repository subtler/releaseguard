"""Deterministic policy evaluation suite."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from releaseguard.application.reporting import ReportAssembler
from releaseguard.domain.models import (
    ChangedFile,
    ChangeStatus,
    ReadinessStatus,
    RepositorySnapshot,
)
from releaseguard.domain.policy import DeterministicRiskPolicy, evidence_for_changed_file


class EvaluationCase(BaseModel):
    """One version-controlled expected policy outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    changed_paths: tuple[str, ...] = Field(min_length=1)
    expected_status: ReadinessStatus
    expected_categories: frozenset[str]


class CaseResult(BaseModel):
    """Observed outcome for one evaluation case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status_correct: bool
    expected_status: ReadinessStatus
    actual_status: ReadinessStatus
    expected_categories: frozenset[str]
    actual_categories: frozenset[str]


class EvaluationResult(BaseModel):
    """Aggregate release-policy quality metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    case_count: int
    status_accuracy: float = Field(ge=0, le=1)
    category_precision: float = Field(ge=0, le=1)
    category_recall: float = Field(ge=0, le=1)
    category_f1: float = Field(ge=0, le=1)
    passed: bool
    cases: tuple[CaseResult, ...]


class PolicyEvaluator:
    """Evaluate transparent risk rules without an external model or service."""

    def __init__(self, policy: DeterministicRiskPolicy) -> None:
        self._policy = policy

    def evaluate_file(
        self,
        dataset: Path,
        *,
        min_status_accuracy: float = 1.0,
        min_category_f1: float = 1.0,
    ) -> EvaluationResult:
        """Run a JSON dataset and enforce explicit quality thresholds."""
        cases = TypeAdapter(tuple[EvaluationCase, ...]).validate_json(
            dataset.read_text(encoding="utf-8")
        )
        if not cases:
            raise ValueError("evaluation dataset must contain at least one case")

        results = tuple(self._evaluate_case(case) for case in cases)
        true_positive = false_positive = false_negative = 0
        for result in results:
            true_positive += len(result.expected_categories & result.actual_categories)
            false_positive += len(result.actual_categories - result.expected_categories)
            false_negative += len(result.expected_categories - result.actual_categories)

        precision = self._safe_ratio(true_positive, true_positive + false_positive)
        recall = self._safe_ratio(true_positive, true_positive + false_negative)
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        accuracy = sum(result.status_correct for result in results) / len(results)
        return EvaluationResult(
            dataset=str(dataset.resolve()),
            case_count=len(results),
            status_accuracy=accuracy,
            category_precision=precision,
            category_recall=recall,
            category_f1=f1,
            passed=accuracy >= min_status_accuracy and f1 >= min_category_f1,
            cases=results,
        )

    def _evaluate_case(self, case: EvaluationCase) -> CaseResult:
        snapshot = RepositorySnapshot(
            repository=f"evaluation://{case.name}",
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_files=tuple(
                ChangedFile(path=path, status=ChangeStatus.MODIFIED) for path in case.changed_paths
            ),
            diff_text="",
        )
        evidence = {
            item.path: evidence_for_changed_file(snapshot, item) for item in snapshot.changed_files
        }
        findings = self._policy.evaluate(snapshot, evidence)
        actual_categories = frozenset(finding.category for finding in findings)
        actual_status = ReportAssembler.readiness_status(findings)
        return CaseResult(
            name=case.name,
            status_correct=actual_status is case.expected_status,
            expected_status=case.expected_status,
            actual_status=actual_status,
            expected_categories=case.expected_categories,
            actual_categories=actual_categories,
        )

    @staticmethod
    def _safe_ratio(numerator: int, denominator: int) -> float:
        return 1.0 if denominator == 0 else numerator / denominator
