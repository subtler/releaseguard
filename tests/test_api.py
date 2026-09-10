"""HTTP API tests."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import releaseguard.api as api_module
from releaseguard.adapters.git_local import RepositoryAccessError
from releaseguard.config import get_settings
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
        analysis_id="analysis_test",
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


def test_health_endpoint() -> None:
    get_settings.cache_clear()
    client = TestClient(api_module.create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_analysis_endpoint_returns_typed_report(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(api_module, "build_analyzer", lambda: StubAnalyzer(report()))
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/v1/analyses",
        json={"repository": "/safe/repository", "base_ref": "main", "head_ref": "feature"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_analysis_endpoint_maps_repository_error_to_bad_request(
    monkeypatch: MonkeyPatch,
) -> None:
    analyzer = StubAnalyzer(RepositoryAccessError("unsafe repository"))
    monkeypatch.setattr(api_module, "build_analyzer", lambda: analyzer)
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/v1/analyses",
        json={"repository": "/safe/repository", "base_ref": "main", "head_ref": "feature"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unsafe repository"}
