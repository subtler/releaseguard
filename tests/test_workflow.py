"""Checkpointed workflow tests."""

from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from releaseguard.domain.models import (
    ChangedFile,
    ChangeStatus,
    ReadinessStatus,
    RepositorySnapshot,
)
from releaseguard.domain.policy import DeterministicRiskPolicy
from releaseguard.workflow.graph import DurableReleaseWorkflow, ReleaseWorkflow


class FakeRepository:
    def snapshot(self, repository: Path, base_ref: str, head_ref: str) -> RepositorySnapshot:
        assert repository == Path("/safe/repository")
        assert base_ref == "main"
        assert head_ref == "feature"
        return RepositorySnapshot(
            repository=str(repository),
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_files=(ChangedFile(path="app/auth.py", status=ChangeStatus.MODIFIED),),
            diff_text="authorization change",
        )


def test_workflow_runs_explicit_stages_and_checkpoints_state() -> None:
    workflow = ReleaseWorkflow(
        FakeRepository(),
        DeterministicRiskPolicy(),
        checkpointer=InMemorySaver(),
    )

    report = workflow.execute(
        Path("/safe/repository"), "main", "feature", thread_id="workflow-test"
    )

    assert report.status is ReadinessStatus.REVIEW_REQUIRED
    assert workflow.completed_stages("workflow-test") == (
        "collect_repository_evidence",
        "analyze_static_impact",
        "retrieve_repository_context",
        "classify_change_risk",
        "verify_evidence",
        "assemble_report",
    )


def test_durable_workflow_creates_local_checkpoint_database(tmp_path: Path) -> None:
    checkpoint_database = tmp_path / "state" / "checkpoints.sqlite3"
    workflow = DurableReleaseWorkflow(
        FakeRepository(),
        DeterministicRiskPolicy(),
        checkpoint_database,
    )

    report = workflow.execute(Path("/safe/repository"), "main", "feature")

    assert report.status is ReadinessStatus.REVIEW_REQUIRED
    assert checkpoint_database.is_file()
