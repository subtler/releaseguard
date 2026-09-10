"""Application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated ReleaseGuard settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RELEASEGUARD_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    trace_exporter: Literal["none", "console", "otlp"] = "none"
    otlp_endpoint: str = "http://127.0.0.1:4318/v1/traces"
    embedding_provider: Literal["hashing", "ollama"] = "hashing"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_embedding_model: str = "embeddinggemma"
    repository_root: Path = Field(default_factory=Path.cwd)
    checkpoint_database: Path = Path(".releaseguard/checkpoints.sqlite3")
    max_diff_bytes: int = Field(default=1_000_000, ge=1_024, le=10_000_000)
    max_index_files: int = Field(default=5_000, ge=1, le=100_000)
    max_source_file_bytes: int = Field(default=250_000, ge=1_024, le=2_000_000)
    retrieval_max_documents: int = Field(default=500, ge=1, le=5_000)
    retrieval_max_file_bytes: int = Field(default=20_000, ge=1_024, le=250_000)
    retrieval_top_k: int = Field(default=8, ge=1, le=50)
    git_timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    @field_validator("repository_root")
    @classmethod
    def normalize_repository_root(cls, value: Path) -> Path:
        """Resolve the repository allowlist root once at startup."""
        return value.expanduser().resolve()

    @field_validator("checkpoint_database")
    @classmethod
    def normalize_checkpoint_database(cls, value: Path) -> Path:
        """Resolve the local workflow checkpoint database path."""
        return value.expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings."""
    return Settings()
