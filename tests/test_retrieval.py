"""Hybrid repository retrieval tests."""

from pathlib import Path

from releaseguard.adapters.embeddings import HashingEmbedder
from releaseguard.application.retrieval import HybridRepositoryRetriever
from releaseguard.domain.models import (
    ChangedFile,
    ChangeStatus,
    EvidenceKind,
    RepositorySnapshot,
    SourceManifest,
)


class FakeSource:
    def __init__(self, files: dict[str, str], *, truncated: bool = False) -> None:
        self.files = files
        self.truncated = truncated

    def list_files(self, repository: Path, commit_sha: str, *, max_files: int) -> SourceManifest:
        del repository
        return SourceManifest(
            commit_sha=commit_sha,
            paths=tuple(self.files)[:max_files],
            truncated=self.truncated,
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
        content = self.files[path]
        if len(content) > max_bytes:
            raise RuntimeError("too large")
        return content


def test_hybrid_retrieval_ranks_relevant_context_and_creates_evidence() -> None:
    source = FakeSource(
        {
            "src/shop/auth.py": "def authorize(role): return role == 'admin'",
            "docs/security.md": "Authorization roles and default-deny access policy.",
            "docs/billing.md": "Invoices, pricing, and payment reconciliation.",
            "uv.lock": "ignored lock file",
        }
    )
    retriever = HybridRepositoryRetriever(
        source,
        HashingEmbedder(dimensions=64),
        max_manifest_files=100,
        top_k=2,
    )
    snapshot = RepositorySnapshot(
        repository="/safe/repository",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=(ChangedFile(path="src/shop/auth.py", status=ChangeStatus.MODIFIED),),
        diff_text="authorization role changed to default deny",
    )

    bundle = retriever.retrieve(Path("/safe/repository"), snapshot)

    assert bundle.contexts[0].path == "docs/security.md"
    assert all(context.path != "src/shop/auth.py" for context in bundle.contexts)
    assert all(item.kind is EvidenceKind.RETRIEVED_CONTEXT for item in bundle.evidence)
    assert bundle.evidence[0].content_hash == bundle.contexts[0].content_hash


def test_hybrid_retrieval_declares_limits_and_skips_oversized_files() -> None:
    source = FakeSource(
        {
            "src/change.py": "changed",
            "docs/large.md": "x" * 2_000,
        },
        truncated=True,
    )
    retriever = HybridRepositoryRetriever(
        source,
        HashingEmbedder(),
        max_manifest_files=2,
        max_documents=1,
        max_file_bytes=1_024,
    )
    snapshot = RepositorySnapshot(
        repository="/safe/repository",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=(ChangedFile(path="src/change.py", status=ChangeStatus.MODIFIED),),
        diff_text="changed",
    )

    bundle = retriever.retrieve(Path("/safe/repository"), snapshot)

    assert bundle.contexts == ()
    assert any("limit" in limitation for limitation in bundle.limitations)
    assert any("could not be read" in limitation for limitation in bundle.limitations)
