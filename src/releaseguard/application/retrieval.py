"""Bounded hybrid repository retrieval."""

import math
import re
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from releaseguard.domain.models import (
    Evidence,
    EvidenceKind,
    RepositorySnapshot,
    RetrievedContext,
)
from releaseguard.ports.code_context import CodeContextPort
from releaseguard.ports.embedding import EmbeddingPort


@dataclass(frozen=True, slots=True)
class RetrievalBundle:
    """Ranked contexts, their provenance records, and declared limitations."""

    contexts: tuple[RetrievedContext, ...]
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Document:
    path: str
    content: str


class HybridRepositoryRetriever:
    """Fuse BM25 lexical ranking with pluggable vector similarity using RRF."""

    _SUPPORTED_SUFFIXES = (".py", ".md", ".toml", ".yaml", ".yml", ".json")

    def __init__(
        self,
        source: CodeContextPort,
        embedder: EmbeddingPort,
        *,
        max_manifest_files: int,
        max_documents: int = 500,
        max_file_bytes: int = 20_000,
        top_k: int = 8,
        rrf_constant: int = 60,
    ) -> None:
        self._source = source
        self._embedder = embedder
        self._max_manifest_files = max_manifest_files
        self._max_documents = max_documents
        self._max_file_bytes = max_file_bytes
        self._top_k = top_k
        self._rrf_constant = rrf_constant

    def retrieve(self, repository: Path, snapshot: RepositorySnapshot) -> RetrievalBundle:
        """Retrieve commit-pinned context relevant to changed paths and diff terms."""
        manifest = self._source.list_files(
            repository, snapshot.head_sha, max_files=self._max_manifest_files
        )
        changed_paths = {item.path for item in snapshot.changed_files}
        candidate_paths = [
            path
            for path in manifest.paths
            if path.endswith(self._SUPPORTED_SUFFIXES)
            and path not in changed_paths
            and not self._is_generated_or_lockfile(path)
        ][: self._max_documents]
        documents: list[_Document] = []
        skipped: list[str] = []
        for path in candidate_paths:
            try:
                content = self._source.read_text_file(
                    repository,
                    snapshot.head_sha,
                    path,
                    max_bytes=self._max_file_bytes,
                )
            except RuntimeError:
                skipped.append(path)
                continue
            documents.append(_Document(path=path, content=content))

        query = "\n".join((*sorted(changed_paths), snapshot.diff_text[:5_000]))
        contexts = self._rank(query, tuple(documents))
        evidence = tuple(
            Evidence.create(
                kind=EvidenceKind.RETRIEVED_CONTEXT,
                repository=snapshot.repository,
                commit_sha=snapshot.head_sha,
                locator=context.path,
                summary=f"Hybrid retrieval context ranked for {len(changed_paths)} changed files",
                content=next(doc.content for doc in documents if doc.path == context.path),
            )
            for context in contexts
        )
        limitations = [
            "Retrieval indexes a bounded set of text source and documentation files.",
        ]
        if manifest.truncated or len(candidate_paths) == self._max_documents:
            limitations.append("Retrieval reached a configured repository or document limit.")
        if skipped:
            limitations.append("Some retrieval candidates could not be read within safety limits.")
        return RetrievalBundle(contexts, evidence, tuple(limitations))

    def _rank(self, query: str, documents: tuple[_Document, ...]) -> tuple[RetrievedContext, ...]:
        if not documents or not self._tokens(query):
            return ()
        lexical_scores = self._bm25(query, documents)
        vectors = self._embedder.embed((query, *(doc.content for doc in documents)))
        if len(vectors) != len(documents) + 1:
            raise ValueError("embedding backend changed batch cardinality")
        query_vector, document_vectors = vectors[0], vectors[1:]
        if any(len(vector) != len(query_vector) for vector in document_vectors):
            raise ValueError("embedding backend returned inconsistent dimensions")
        vector_scores = tuple(self._cosine(query_vector, vector) for vector in document_vectors)
        lexical_ranks = self._ranks(lexical_scores, documents)
        vector_ranks = self._ranks(vector_scores, documents)
        fused = [
            (
                1 / (self._rrf_constant + lexical_ranks[index])
                + 1 / (self._rrf_constant + vector_ranks[index]),
                document.path,
                index,
            )
            for index, document in enumerate(documents)
            if lexical_scores[index] > 0 or vector_scores[index] > 0
        ]
        selected = sorted(fused, key=lambda item: (-item[0], item[1]))[: self._top_k]
        return tuple(
            RetrievedContext(
                path=documents[index].path,
                excerpt=self._excerpt(documents[index].content),
                content_hash=sha256(documents[index].content.encode("utf-8")).hexdigest(),
                lexical_rank=lexical_ranks[index],
                vector_rank=vector_ranks[index],
                fusion_score=score,
            )
            for score, _, index in selected
        )

    @classmethod
    def _bm25(cls, query: str, documents: tuple[_Document, ...]) -> tuple[float, ...]:
        query_terms = set(cls._tokens(query))
        tokenized = [cls._tokens(f"{document.path} {document.content}") for document in documents]
        average_length = sum(map(len, tokenized)) / len(tokenized)
        document_frequency = {
            term: sum(term in tokens for tokens in tokenized) for term in query_terms
        }
        scores: list[float] = []
        for tokens in tokenized:
            counts = Counter(tokens)
            score = 0.0
            for term in query_terms:
                frequency = counts[term]
                if frequency == 0:
                    continue
                inverse_frequency = math.log(
                    1
                    + (len(documents) - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / average_length)
                score += inverse_frequency * frequency * 2.5 / denominator
            scores.append(score)
        return tuple(scores)

    @staticmethod
    def _ranks(scores: tuple[float, ...], documents: tuple[_Document, ...]) -> dict[int, int]:
        order = sorted(
            range(len(scores)), key=lambda index: (-scores[index], documents[index].path)
        )
        return {document_index: rank for rank, document_index in enumerate(order, start=1)}

    @staticmethod
    def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)

    @staticmethod
    def _tokens(text: str) -> tuple[str, ...]:
        return tuple(token.lower() for token in re.findall(r"[A-Za-z0-9]+", text))

    @staticmethod
    def _excerpt(content: str, limit: int = 800) -> str:
        compact = "\n".join(line.rstrip() for line in content.strip().splitlines())
        return compact[:limit]

    @staticmethod
    def _is_generated_or_lockfile(path: str) -> bool:
        name = path.rsplit("/", maxsplit=1)[-1]
        return (
            name.endswith(".lock")
            or name in {"package-lock.json", "uv.lock"}
            or any(part in {"dist", "build", "node_modules", ".venv"} for part in path.split("/"))
        )
