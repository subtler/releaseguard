# ReleaseGuard

**Evidence-grounded change-impact and release-readiness analysis for software changes.**

ReleaseGuard answers a practical engineering question: *what could this change break, which tests
should run, and is the evidence strong enough to release?* It analyzes an immutable Git comparison,
builds a static dependency graph, classifies risky change surfaces, verifies every finding against
repository evidence, and emits a typed readiness report.

The current product is local-first, fully offline, and does **not** call OpenAI or any other hosted
model API. Model-assisted analysis will be an optional, verifier-bounded layer—not a requirement for
the trustworthy baseline.

## Why this is not another chat demo

- **Commit-pinned evidence:** refs are resolved to immutable SHAs before analysis.
- **Read-only tool boundary:** Git runs without a shell, with an allowlisted root, timeouts, and
  bounded output.
- **Structure-aware impact:** Python imports are parsed from Git objects to identify direct and
  transitive dependents plus candidate tests.
- **Bounded workflow:** six named LangGraph stages have fixed transitions and local SQLite
  checkpoints.
- **Hybrid retrieval:** BM25 and vector rankings are fused with RRF; the vector backend is either a
  zero-service hashing baseline or optional local Ollama embeddings.
- **Fail-closed verification:** reports cannot contain dangling citations or cross-commit evidence.
- **Evaluation gate:** a versioned dataset reports accuracy, precision, recall, and F1 in CI.
- **Vendor-neutral traces:** OpenTelemetry can stay off, print locally, or export to a self-hosted
  OTLP collector.
- **Read-only MCP:** the official Python SDK v2 exposes one structured analysis tool over local
  stdio, with non-destructive tool annotations.

## Architecture

```text
CLI / HTTP API
      |
      v
collect immutable Git evidence
      |
      v
build static import impact graph
      |
      v
retrieve relevant code and runbooks
      |
      v
classify deterministic release risk
      |
      v
verify provenance and finding citations
      |
      v
assemble typed readiness report

Every stage --> SQLite checkpoint + OpenTelemetry span
```

See [the architecture document](docs/architecture.md) for boundaries, invariants, and the planned
model-assisted layer.

## Quick start

Prerequisites: Python 3.12+, Git, and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
cp .env.example .env
```

Set `RELEASEGUARD_REPOSITORY_ROOT` in `.env` to the parent directory containing repositories that
ReleaseGuard may inspect. Then analyze two refs:

```bash
uv run releaseguard analyze \
  --repository /path/to/repository \
  --base-ref main \
  --head-ref feature/my-change
```

Start the local API:

```bash
uv run uvicorn releaseguard.api:create_app --factory --host 127.0.0.1 --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analyses \
  -H 'content-type: application/json' \
  -d '{
    "repository": "/path/to/repository",
    "base_ref": "main",
    "head_ref": "feature/my-change"
  }'
```

## Quality gates

Run the same checks as CI:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=releaseguard --cov-report=term-missing
uv run releaseguard evaluate
uv run releaseguard evaluate-retrieval
```

The shipped deterministic evaluation currently contains eight focused cases and requires 100%
readiness accuracy and 1.0 risk-category F1. This validates the transparent policy rules; it is not
misrepresented as semantic-model performance. A separate four-case frozen retrieval benchmark
gates recall@3 and mean reciprocal rank. See [evaluation](docs/evaluation.md).

## Read-only MCP

Run the local stdio server:

```bash
uv run releaseguard-mcp
```

It exposes only `analyze_local_change`; there are no write or repository-mutation tools. See the
[MCP boundary](docs/mcp.md).

## Local observability

Tracing is off by default. No data leaves the machine unless explicitly configured.

```bash
# Print spans locally
RELEASEGUARD_TRACE_EXPORTER=console uv run releaseguard analyze ...

# Or export to a local/self-hosted OpenTelemetry collector
RELEASEGUARD_TRACE_EXPORTER=otlp \
RELEASEGUARD_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces \
uv run releaseguard analyze ...
```

## Implemented and planned

- [x] Typed domain model and deterministic analyzer
- [x] Safe local Git adapter with immutable, bounded source reads
- [x] Structure-aware Python dependency impact and candidate-test selection
- [x] Explicit LangGraph workflow with local SQLite checkpoints
- [x] Evidence-provenance and citation verifier
- [x] Hybrid BM25/vector retrieval with RRF and frozen retrieval evaluation
- [x] Optional semantic embeddings through local Ollama
- [x] Read-only MCP server using the official Python SDK v2
- [x] CLI and FastAPI interfaces
- [x] Versioned evaluation dataset and CI quality gates
- [x] OpenTelemetry tracing with no-op, console, and OTLP modes
- [ ] Language-agnostic parsing via tree-sitter
- [ ] Persistent incremental retrieval index for very large repositories
- [ ] Optional local generative model for evidence-bounded synthesis
- [ ] Adversarial retrieval, trajectory, and groundedness evaluation suite
- [ ] Reviewer-facing web interface
- [ ] PostgreSQL checkpointer for multi-worker operation

## Honest limitations

The current analyzer is strongest on Python repositories with conventional imports. Static analysis
cannot see dynamic imports, runtime configuration, external services, or behavior hidden behind
reflection. It does not execute tests or claim that a `ready` result proves safety. Instead, it makes
the evidence, known gaps, and required human review explicit.

## Documentation

- [Architecture](docs/architecture.md)
- [Evaluation](docs/evaluation.md)
- [Read-only MCP](docs/mcp.md)
- [Threat model](docs/threat-model.md)
- [ADR 0001: deterministic baseline](docs/adr/0001-deterministic-baseline.md)
- [ADR 0002: local-first operation](docs/adr/0002-local-first-operation.md)
- [ADR 0003: checkpointed bounded workflow](docs/adr/0003-checkpointed-bounded-workflow.md)

## License

MIT
