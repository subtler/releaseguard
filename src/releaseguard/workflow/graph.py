"""Explicit, checkpointed ReleaseGuard analysis workflow."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from operator import add
from pathlib import Path
from typing import Annotated, Any, TypedDict, cast
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from opentelemetry import trace
from opentelemetry.trace import Tracer

from releaseguard.application.impact import PythonImpactAnalyzer
from releaseguard.application.reporting import ReportAssembler
from releaseguard.application.retrieval import HybridRepositoryRetriever
from releaseguard.application.verification import EvidenceVerifier
from releaseguard.domain.models import (
    Evidence,
    EvidenceKind,
    ImpactAssessment,
    ReadinessReport,
    RepositorySnapshot,
    RetrievedContext,
    RiskFinding,
)
from releaseguard.domain.policy import DeterministicRiskPolicy, evidence_for_changed_file
from releaseguard.ports.code_context import CodeContextPort
from releaseguard.ports.repository import RepositoryPort


class WorkflowState(TypedDict, total=False):
    """JSON-serializable state persisted after every workflow stage."""

    repository: str
    base_ref: str
    head_ref: str
    snapshot: dict[str, Any]
    evidence: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    impact: dict[str, Any]
    retrieved_context: list[dict[str, Any]]
    retrieval_evidence: list[dict[str, Any]]
    retrieval_limitations: list[str]
    report: dict[str, Any]
    completed_stages: Annotated[list[str], add]


CompiledReleaseGraph = CompiledStateGraph[
    WorkflowState,
    None,
    WorkflowState,
    WorkflowState,
]


class ReleaseWorkflow:
    """Run bounded analysis stages with optional durable checkpoints."""

    def __init__(
        self,
        repository_port: RepositoryPort,
        policy: DeterministicRiskPolicy,
        *,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        tracer: Tracer | None = None,
        impact_analyzer: PythonImpactAnalyzer | None = None,
        retriever: HybridRepositoryRetriever | None = None,
    ) -> None:
        self._repository_port = repository_port
        self._policy = policy
        self._verifier = EvidenceVerifier()
        self._assembler = ReportAssembler()
        self._tracer = tracer or trace.get_tracer("releaseguard.workflow")
        self._impact_analyzer = impact_analyzer
        self._retriever = retriever
        self._graph = self._build_graph(checkpointer)

    def execute(
        self,
        repository: Path,
        base_ref: str,
        head_ref: str,
        *,
        thread_id: str | None = None,
    ) -> ReadinessReport:
        """Execute the graph once and return its verified report."""
        resolved_thread_id = thread_id or f"releaseguard_{uuid4().hex}"
        with self._tracer.start_as_current_span("releaseguard.analysis") as span:
            span.set_attribute("releaseguard.thread_id", resolved_thread_id)
            output = cast(
                WorkflowState,
                self._graph.invoke(
                    {
                        "repository": str(repository),
                        "base_ref": base_ref,
                        "head_ref": head_ref,
                        "completed_stages": [],
                    },
                    {"configurable": {"thread_id": resolved_thread_id}},
                ),
            )
            report = ReadinessReport.model_validate(output["report"])
            span.set_attribute("releaseguard.analysis_id", report.analysis_id)
            span.set_attribute("releaseguard.readiness", report.status.value)
            span.set_attribute("releaseguard.finding_count", len(report.findings))
            return report

    def completed_stages(self, thread_id: str) -> tuple[str, ...]:
        """Return the latest persisted stage trail for a workflow thread."""
        snapshot = self._graph.get_state({"configurable": {"thread_id": thread_id}})
        values = cast(WorkflowState, snapshot.values)
        return tuple(values.get("completed_stages", ()))

    def _build_graph(self, checkpointer: BaseCheckpointSaver[Any] | None) -> CompiledReleaseGraph:
        builder = StateGraph(WorkflowState)
        builder.add_node("collect_repository_evidence", self._collect_repository_evidence)
        builder.add_node("analyze_static_impact", self._analyze_static_impact)
        builder.add_node("retrieve_repository_context", self._retrieve_repository_context)
        builder.add_node("classify_change_risk", self._classify_change_risk)
        builder.add_node("verify_evidence", self._verify_evidence)
        builder.add_node("assemble_report", self._assemble_report)
        builder.add_edge(START, "collect_repository_evidence")
        builder.add_edge("collect_repository_evidence", "analyze_static_impact")
        builder.add_edge("analyze_static_impact", "retrieve_repository_context")
        builder.add_edge("retrieve_repository_context", "classify_change_risk")
        builder.add_edge("classify_change_risk", "verify_evidence")
        builder.add_edge("verify_evidence", "assemble_report")
        builder.add_edge("assemble_report", END)
        return builder.compile(checkpointer=checkpointer)

    def _collect_repository_evidence(self, state: WorkflowState) -> WorkflowState:
        with self._tracer.start_as_current_span("releaseguard.collect_evidence") as span:
            snapshot = self._repository_port.snapshot(
                Path(state["repository"]), state["base_ref"], state["head_ref"]
            )
            span.set_attribute("releaseguard.changed_file_count", len(snapshot.changed_files))
            span.set_attribute("releaseguard.diff_truncated", snapshot.diff_truncated)
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "completed_stages": ["collect_repository_evidence"],
        }

    def _analyze_static_impact(self, state: WorkflowState) -> WorkflowState:
        if self._impact_analyzer is None:
            return {"completed_stages": ["analyze_static_impact"]}
        with self._tracer.start_as_current_span("releaseguard.analyze_static_impact") as span:
            snapshot = RepositorySnapshot.model_validate(state["snapshot"])
            impact = self._impact_analyzer.analyze(Path(state["repository"]), snapshot)
            span.set_attribute(
                "releaseguard.impact.direct_dependent_count", len(impact.direct_dependents)
            )
            span.set_attribute(
                "releaseguard.impact.candidate_test_count", len(impact.candidate_tests)
            )
        return {
            "impact": impact.model_dump(mode="json"),
            "completed_stages": ["analyze_static_impact"],
        }

    def _retrieve_repository_context(self, state: WorkflowState) -> WorkflowState:
        if self._retriever is None:
            return {"completed_stages": ["retrieve_repository_context"]}
        with self._tracer.start_as_current_span("releaseguard.retrieve_context") as span:
            snapshot = RepositorySnapshot.model_validate(state["snapshot"])
            bundle = self._retriever.retrieve(Path(state["repository"]), snapshot)
            span.set_attribute("releaseguard.retrieval.result_count", len(bundle.contexts))
        return {
            "retrieved_context": [item.model_dump(mode="json") for item in bundle.contexts],
            "retrieval_evidence": [item.model_dump(mode="json") for item in bundle.evidence],
            "retrieval_limitations": list(bundle.limitations),
            "completed_stages": ["retrieve_repository_context"],
        }

    def _classify_change_risk(self, state: WorkflowState) -> WorkflowState:
        with self._tracer.start_as_current_span("releaseguard.classify_risk") as span:
            snapshot = RepositorySnapshot.model_validate(state["snapshot"])
            file_evidence = {
                changed_file.path: evidence_for_changed_file(snapshot, changed_file)
                for changed_file in snapshot.changed_files
            }
            diff_evidence = Evidence.create(
                kind=EvidenceKind.DIFF_SUMMARY,
                repository=snapshot.repository,
                commit_sha=snapshot.head_sha,
                locator=f"{snapshot.base_sha}...{snapshot.head_sha}",
                summary=f"Git comparison containing {len(snapshot.changed_files)} changed files",
                content=snapshot.diff_text,
            )
            findings = self._policy.evaluate(snapshot, file_evidence)
            retrieval_evidence = tuple(
                Evidence.model_validate(item) for item in state.get("retrieval_evidence", [])
            )
            evidence = (*file_evidence.values(), diff_evidence, *retrieval_evidence)
            span.set_attribute("releaseguard.finding_count", len(findings))
        return {
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "findings": [item.model_dump(mode="json") for item in findings],
            "completed_stages": ["classify_change_risk"],
        }

    def _verify_evidence(self, state: WorkflowState) -> WorkflowState:
        with self._tracer.start_as_current_span("releaseguard.verify_evidence") as span:
            snapshot = RepositorySnapshot.model_validate(state["snapshot"])
            evidence = tuple(Evidence.model_validate(item) for item in state["evidence"])
            findings = tuple(RiskFinding.model_validate(item) for item in state["findings"])
            self._verifier.verify(snapshot, evidence, findings)
            span.set_attribute("releaseguard.evidence_count", len(evidence))
        return {"completed_stages": ["verify_evidence"]}

    def _assemble_report(self, state: WorkflowState) -> WorkflowState:
        snapshot = RepositorySnapshot.model_validate(state["snapshot"])
        evidence = tuple(Evidence.model_validate(item) for item in state["evidence"])
        findings = tuple(RiskFinding.model_validate(item) for item in state["findings"])
        impact_data = state.get("impact")
        impact = ImpactAssessment.model_validate(impact_data) if impact_data else None
        retrieved_context = tuple(
            RetrievedContext.model_validate(item) for item in state.get("retrieved_context", [])
        )
        report = self._assembler.assemble(
            snapshot,
            evidence,
            findings,
            impact,
            retrieved_context,
            tuple(state.get("retrieval_limitations", [])),
        )
        return {
            "report": report.model_dump(mode="json"),
            "completed_stages": ["assemble_report"],
        }


class DurableReleaseWorkflow:
    """Open a local SQLite checkpointer for each isolated workflow execution."""

    def __init__(
        self,
        repository_port: RepositoryPort,
        policy: DeterministicRiskPolicy,
        checkpoint_database: Path,
        tracer: Tracer | None = None,
        code_context: CodeContextPort | None = None,
        max_index_files: int = 5_000,
        max_source_file_bytes: int = 250_000,
        retriever: HybridRepositoryRetriever | None = None,
    ) -> None:
        self._repository_port = repository_port
        self._policy = policy
        self._checkpoint_database = checkpoint_database
        self._tracer = tracer
        self._impact_analyzer = (
            PythonImpactAnalyzer(
                code_context,
                max_files=max_index_files,
                max_file_bytes=max_source_file_bytes,
            )
            if code_context is not None
            else None
        )
        self._retriever = retriever

    def execute(self, repository: Path, base_ref: str, head_ref: str) -> ReadinessReport:
        """Run an analysis with durable stage-level checkpoints."""
        self._checkpoint_database.parent.mkdir(parents=True, exist_ok=True)
        with self._checkpointer() as checkpointer:
            workflow = ReleaseWorkflow(
                self._repository_port,
                self._policy,
                checkpointer=checkpointer,
                tracer=self._tracer,
                impact_analyzer=self._impact_analyzer,
                retriever=self._retriever,
            )
            return workflow.execute(repository, base_ref, head_ref)

    @contextmanager
    def _checkpointer(self) -> Iterator[SqliteSaver]:
        with SqliteSaver.from_conn_string(str(self._checkpoint_database)) as checkpointer:
            yield checkpointer
