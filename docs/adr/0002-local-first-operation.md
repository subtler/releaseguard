# ADR 0002: Local-first operation

- **Status:** Accepted
- **Date:** 2026-09-10

## Context

The portfolio project should be reproducible with free resources and should not require hosted
infrastructure or a paid model API during development.

## Decision

Support local Git repositories, Docker Compose services, local embeddings, and Ollama-compatible
models first. Keep adapters replaceable so managed services can be added later without changing the
domain or workflow.

## Consequences

- Reviewers can run the project locally.
- Development and deterministic tests do not require credentials.
- Local throughput may be lower than managed inference, but correctness and operational contracts
  remain production-structured.

