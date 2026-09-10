"""Analysis execution port."""

from pathlib import Path
from typing import Protocol

from releaseguard.domain.models import ReadinessReport


class AnalysisRunner(Protocol):
    """Execute one repository comparison."""

    def execute(self, repository: Path, base_ref: str, head_ref: str) -> ReadinessReport:
        """Return a verified readiness report."""
        ...
