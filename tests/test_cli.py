"""Command-line interface tests."""

from datetime import UTC, datetime
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

import releaseguard.cli as cli_module
from releaseguard.adapters.git_local import RepositoryAccessError
from releaseguard.domain.models import ReadinessReport, ReadinessStatus


class StubAnalyzer:
    def __init__(self, result: ReadinessReport | Exception) -> None:
        self.result = result

    def execute(self, repository: Path, base_ref: str, head_ref: str) -> ReadinessReport:
        assert repository == Path("/safe/repository")
        assert base_ref == "main"
        assert head_ref == "feature"
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def report() -> ReadinessReport:
    return ReadinessReport(
        analysis_id="analysis_cli_test",
        repository="/safe/repository",
        base_sha="a" * 40,
        head_sha="b" * 40,
        status=ReadinessStatus.READY,
        generated_at=datetime.now(UTC),
        summary="No deterministic release blocker was detected.",
        changed_files=(),
        evidence=(),
        findings=(),
        limitations=(),
    )


def test_cli_prints_report(monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli_module, "build_analyzer", lambda: StubAnalyzer(report()))

    exit_code = cli_module.main(
        [
            "analyze",
            "--repository",
            "/safe/repository",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"analysis_id": "analysis_cli_test"' in captured.out
    assert captured.err == ""


def test_cli_returns_failure_for_repository_error(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    error = RepositoryAccessError("repository is outside the configured repository root")
    monkeypatch.setattr(cli_module, "build_analyzer", lambda: StubAnalyzer(error))

    exit_code = cli_module.main(
        [
            "analyze",
            "--repository",
            "/safe/repository",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "analysis failed:" in captured.err


def test_cli_evaluate_prints_passing_metrics(capsys: CaptureFixture[str]) -> None:
    dataset = Path(__file__).parents[1] / "evals" / "deterministic_policy.json"

    exit_code = cli_module.main(["evaluate", "--dataset", str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"passed": true' in captured.out


def test_cli_evaluate_reports_invalid_dataset(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    missing_dataset = tmp_path / "missing.json"

    exit_code = cli_module.main(["evaluate", "--dataset", str(missing_dataset)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "evaluation failed:" in captured.err


def test_cli_evaluate_retrieval_prints_passing_metrics(
    capsys: CaptureFixture[str],
) -> None:
    dataset = Path(__file__).parents[1] / "evals" / "retrieval.json"

    exit_code = cli_module.main(["evaluate-retrieval", "--dataset", str(dataset)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"mean_reciprocal_rank": 1.0' in captured.out
