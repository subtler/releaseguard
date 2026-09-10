"""Versioned policy evaluation tests."""

from pathlib import Path

import pytest

from releaseguard.domain.policy import DeterministicRiskPolicy
from releaseguard.evaluation.policy import PolicyEvaluator
from releaseguard.evaluation.retrieval import RetrievalEvaluator


def test_shipped_policy_dataset_passes_all_gates() -> None:
    dataset = Path(__file__).parents[1] / "evals" / "deterministic_policy.json"

    result = PolicyEvaluator(DeterministicRiskPolicy()).evaluate_file(dataset)

    assert result.passed is True
    assert result.case_count == 8
    assert result.status_accuracy == 1
    assert result.category_f1 == 1


def test_evaluator_reports_failed_expectation(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        """[
          {
            "name": "intentionally incorrect expectation",
            "changed_paths": ["README.md"],
            "expected_status": "blocked",
            "expected_categories": ["security"]
          }
        ]""",
        encoding="utf-8",
    )

    result = PolicyEvaluator(DeterministicRiskPolicy()).evaluate_file(dataset)

    assert result.passed is False
    assert result.status_accuracy == 0
    assert result.category_precision == 1
    assert result.category_recall == 0
    assert result.category_f1 == 0


def test_evaluator_rejects_empty_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "empty.json"
    dataset.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="at least one"):
        PolicyEvaluator(DeterministicRiskPolicy()).evaluate_file(dataset)


def test_shipped_retrieval_dataset_passes_recall_and_ranking_gates() -> None:
    dataset = Path(__file__).parents[1] / "evals" / "retrieval.json"

    result = RetrievalEvaluator().evaluate_file(dataset)

    assert result.passed is True
    assert result.case_count == 4
    assert result.recall_at_k == 1
    assert result.mean_reciprocal_rank == 1


def test_retrieval_evaluator_rejects_empty_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "empty-retrieval.json"
    dataset.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="at least one"):
        RetrievalEvaluator().evaluate_file(dataset)
