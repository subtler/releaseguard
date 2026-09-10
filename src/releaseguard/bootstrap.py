"""Dependency construction."""

from releaseguard.adapters.embeddings import HashingEmbedder, OllamaEmbedder
from releaseguard.adapters.git_local import SafeLocalGitAdapter
from releaseguard.application.retrieval import HybridRepositoryRetriever
from releaseguard.config import Settings, get_settings
from releaseguard.domain.policy import DeterministicRiskPolicy
from releaseguard.observability import configure_tracing
from releaseguard.ports.embedding import EmbeddingPort
from releaseguard.workflow.graph import DurableReleaseWorkflow


def build_analyzer(settings: Settings | None = None) -> DurableReleaseWorkflow:
    """Build the analysis use case with production adapters."""
    resolved_settings = settings or get_settings()
    repository_adapter = SafeLocalGitAdapter(
        repository_root=resolved_settings.repository_root,
        timeout_seconds=resolved_settings.git_timeout_seconds,
        max_diff_bytes=resolved_settings.max_diff_bytes,
    )
    embedder: EmbeddingPort
    if resolved_settings.embedding_provider == "ollama":
        embedder = OllamaEmbedder(
            base_url=resolved_settings.ollama_base_url,
            model=resolved_settings.ollama_embedding_model,
            timeout_seconds=resolved_settings.git_timeout_seconds,
        )
    else:
        embedder = HashingEmbedder()
    retriever = HybridRepositoryRetriever(
        repository_adapter,
        embedder,
        max_manifest_files=resolved_settings.max_index_files,
        max_documents=resolved_settings.retrieval_max_documents,
        max_file_bytes=resolved_settings.retrieval_max_file_bytes,
        top_k=resolved_settings.retrieval_top_k,
    )
    return DurableReleaseWorkflow(
        repository_port=repository_adapter,
        policy=DeterministicRiskPolicy(),
        checkpoint_database=resolved_settings.checkpoint_database,
        tracer=configure_tracing(resolved_settings),
        code_context=repository_adapter,
        max_index_files=resolved_settings.max_index_files,
        max_source_file_bytes=resolved_settings.max_source_file_bytes,
        retriever=retriever,
    )
