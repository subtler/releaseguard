# Architecture

## System boundary

ReleaseGuard accepts a local repository path and two Git references. It permits access only below a
configured root, resolves both refs to immutable commits, and returns a structured report with
changed files, provenance-backed findings, static dependency impact, candidate tests, limitations,
and a readiness decision.

```text
CLI / FastAPI
      |
      v
dependency bootstrap -----------------------------------+
      |                                                  |
      v                                                  v
checkpointed LangGraph workflow                   OpenTelemetry
      |
      +--> collect_repository_evidence
      |         |
      |         +--> safe Git adapter --> immutable commits + bounded diff
      |
      +--> analyze_static_impact
      |         |
      |         +--> commit tree --> Python AST import graph
      |                           --> dependents + candidate tests
      |
      +--> retrieve_repository_context
      |         |
      |         +--> BM25 rank + vector rank --> reciprocal-rank fusion
      |                    |                         |
      |                    +--> hashing baseline or local Ollama embeddings
      |
      +--> classify_change_risk --> version-controlled deterministic rules
      |
      +--> verify_evidence ------> provenance + citation invariants
      |
      +--> assemble_report ------> typed readiness contract
      |
      v
local SQLite stage checkpoints
```

## Layers

- `domain`: immutable, framework-independent report, evidence, impact, and policy contracts.
- `application`: report construction, evidence verification, impact analysis, and use cases.
- `ports`: interfaces for repositories and immutable source context.
- `adapters`: shell-free local Git and future provider implementations.
- `workflow`: explicit LangGraph nodes, transitions, checkpointing, and trace boundaries.
- `evaluation`: versioned cases, metrics, and gates.
- `api`, `cli`, and `mcp_server`: delivery mechanisms with no business rules.

## Evidence invariants

Every finding references one or more known evidence IDs. Every evidence record identifies its
repository, immutable commit SHA, locator, collection kind, and content hash when content was
captured. Before report assembly, the verifier rejects duplicate evidence IDs, missing changed-file
evidence, repository/commit mismatches, and dangling finding citations.

## Static impact algorithm

At the resolved head commit, ReleaseGuard lists a bounded tree and reads bounded Python blobs
directly from Git objects. It parses imports with the standard-library AST, builds a reverse module
dependency graph, and walks downstream edges to a fixed depth. Output distinguishes direct and
transitive dependents and selects impacted test modules.

This is deliberately explainable and offline. It does not yet model dynamic imports, reflection,
runtime routing, non-Python languages, or external-service dependencies; those limitations are
returned in the report.

## Retrieval boundary

The current retrieval stage indexes a bounded set of commit-pinned code, configuration, and
documentation files. BM25 and vector ranks are combined with reciprocal-rank fusion. Feature hashing
is the zero-service default; Ollama's local embedding endpoint is an opt-in semantic backend. Both
implement the same port, and every selected context receives a provenance record and content hash.

## Planned model-assisted boundary

Hybrid retrieval and local-model synthesis will be additive stages between static impact and the
verifier. Repository content will remain untrusted data. A model may propose impact claims or tests,
but cannot grant authorization, choose write permissions, bypass budgets, or emit an unverified
finding. Ollama will be the first optional model adapter; the deterministic product remains runnable
without it.
