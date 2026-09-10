"""Frozen hybrid-retrieval evaluation."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from releaseguard.adapters.embeddings import HashingEmbedder
from releaseguard.application.retrieval import HybridRepositoryRetriever
from releaseguard.domain.models import (
    ChangedFile,
    ChangeStatus,
    RepositorySnapshot,
    SourceManifest,
)


class RetrievalEvaluationCase(BaseModel):
    """One self-contained retrieval relevance judgment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    changed_paths: tuple[str, ...] = Field(min_length=1)
    diff_text: str
    documents: dict[str, str] = Field(min_length=1)
    relevant_paths: frozenset[str] = Field(min_length=1)


class RetrievalCaseResult(BaseModel):
    """Ranks and relevance metrics for one case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    retrieved_paths: tuple[str, ...]
    relevant_paths: frozenset[str]
    recall_at_k: float = Field(ge=0, le=1)
    reciprocal_rank: float = Field(ge=0, le=1)


class RetrievalEvaluationResult(BaseModel):
    """Aggregate retrieval metrics and gate outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    case_count: int
    recall_at_k: float = Field(ge=0, le=1)
    mean_reciprocal_rank: float = Field(ge=0, le=1)
    passed: bool
    cases: tuple[RetrievalCaseResult, ...]


class _DatasetSource:
    def __init__(self, documents: dict[str, str]) -> None:
        self._documents = documents

    def list_files(self, repository: Path, commit_sha: str, *, max_files: int) -> SourceManifest:
        del repository
        paths = tuple(self._documents)[:max_files]
        return SourceManifest(
            commit_sha=commit_sha,
            paths=paths,
            truncated=len(self._documents) > max_files,
        )

    def read_text_file(
        self,
        repository: Path,
        commit_sha: str,
        path: str,
        *,
        max_bytes: int,
    ) -> str:
        del repository, commit_sha
        content = self._documents[path]
        if len(content.encode("utf-8")) > max_bytes:
            raise RuntimeError("evaluation document exceeded configured limit")
        return content


class RetrievalEvaluator:
    """Measure retrieval recall and ranking on frozen, labeled cases."""

    def evaluate_file(
        self,
        dataset: Path,
        *,
        top_k: int = 3,
        min_recall_at_k: float = 1.0,
        min_mean_reciprocal_rank: float = 1.0,
    ) -> RetrievalEvaluationResult:
        """Evaluate the offline default retriever against explicit thresholds."""
        cases = TypeAdapter(tuple[RetrievalEvaluationCase, ...]).validate_json(
            dataset.read_text(encoding="utf-8")
        )
        if not cases:
            raise ValueError("retrieval evaluation dataset must contain at least one case")
        results = tuple(self._evaluate_case(case, top_k) for case in cases)
        recall = sum(result.recall_at_k for result in results) / len(results)
        mrr = sum(result.reciprocal_rank for result in results) / len(results)
        return RetrievalEvaluationResult(
            dataset=str(dataset.resolve()),
            case_count=len(results),
            recall_at_k=recall,
            mean_reciprocal_rank=mrr,
            passed=recall >= min_recall_at_k and mrr >= min_mean_reciprocal_rank,
            cases=results,
        )

    @staticmethod
    def _evaluate_case(case: RetrievalEvaluationCase, top_k: int) -> RetrievalCaseResult:
        source = _DatasetSource(case.documents)
        retriever = HybridRepositoryRetriever(
            source,
            HashingEmbedder(),
            max_manifest_files=len(case.documents),
            max_documents=len(case.documents),
            top_k=top_k,
        )
        snapshot = RepositorySnapshot(
            repository=f"evaluation://{case.name}",
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_files=tuple(
                ChangedFile(path=path, status=ChangeStatus.MODIFIED) for path in case.changed_paths
            ),
            diff_text=case.diff_text,
        )
        bundle = retriever.retrieve(Path("/evaluation"), snapshot)
        retrieved_paths = tuple(context.path for context in bundle.contexts)
        relevant_retrieved = case.relevant_paths.intersection(retrieved_paths)
        recall = len(relevant_retrieved) / len(case.relevant_paths)
        first_rank = next(
            (
                rank
                for rank, path in enumerate(retrieved_paths, start=1)
                if path in case.relevant_paths
            ),
            None,
        )
        reciprocal_rank = 0.0 if first_rank is None else 1 / first_rank
        return RetrievalCaseResult(
            name=case.name,
            retrieved_paths=retrieved_paths,
            relevant_paths=case.relevant_paths,
            recall_at_k=recall,
            reciprocal_rank=reciprocal_rank,
        )
