"""ReleaseGuard HTTP API."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, ConfigDict, Field

from releaseguard import __version__
from releaseguard.adapters.git_local import RepositoryAccessError
from releaseguard.bootstrap import build_analyzer
from releaseguard.domain.models import ReadinessReport


class AnalysisRequest(BaseModel):
    """Request for a local repository comparison."""

    model_config = ConfigDict(extra="forbid")

    repository: Path
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)


def create_app() -> FastAPI:
    """Create an isolated FastAPI application."""
    app = FastAPI(
        title="ReleaseGuard API",
        version=__version__,
        description="Evidence-grounded change-impact and release-readiness analysis",
    )
    analyzer = build_analyzer()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy", "version": __version__}

    @app.post("/api/v1/analyses", response_model=ReadinessReport)
    async def create_analysis(request: AnalysisRequest) -> ReadinessReport:
        try:
            return await run_in_threadpool(
                analyzer.execute,
                request.repository,
                request.base_ref,
                request.head_ref,
            )
        except RepositoryAccessError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    FastAPIInstrumentor.instrument_app(app)
    return app
