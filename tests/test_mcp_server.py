"""Read-only MCP server contract tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp.types import CallToolResult

from releaseguard.domain.models import ReadinessReport, ReadinessStatus
from releaseguard.mcp_server import create_mcp_server


class StubAnalyzer:
    def execute(self, repository: Path, base_ref: str, head_ref: str) -> ReadinessReport:
        assert repository == Path("/safe/repository")
        assert base_ref == "main"
        assert head_ref == "feature"
        return ReadinessReport(
            analysis_id="analysis_mcp_test",
            repository=str(repository),
            base_sha="a" * 40,
            head_sha="b" * 40,
            status=ReadinessStatus.READY,
            generated_at=datetime.now(UTC),
            summary="Ready",
            changed_files=(),
            evidence=(),
            findings=(),
            limitations=(),
        )


@pytest.mark.asyncio
async def test_mcp_exposes_one_explicitly_read_only_structured_tool() -> None:
    server = create_mcp_server(analyzer=StubAnalyzer())

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == ["analyze_local_change"]
    assert tools[0].annotations is not None
    assert tools[0].annotations.read_only_hint is True
    assert tools[0].annotations.destructive_hint is False
    assert tools[0].output_schema is not None


@pytest.mark.asyncio
async def test_mcp_tool_returns_structured_readiness_report() -> None:
    server = create_mcp_server(analyzer=StubAnalyzer())

    result = await server.call_tool(
        "analyze_local_change",
        {
            "repository": "/safe/repository",
            "base_ref": "main",
            "head_ref": "feature",
        },
    )

    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["analysis_id"] == "analysis_mcp_test"
