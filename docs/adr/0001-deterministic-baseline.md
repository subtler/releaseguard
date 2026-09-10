# ADR 0001: Keep a deterministic analysis baseline

- **Status:** Accepted
- **Date:** 2026-09-10

## Context

Release-readiness analysis will eventually use probabilistic model reasoning. Without a deterministic
baseline, quality gains are difficult to measure and the service has no useful degraded mode.

## Decision

Implement file/category risk rules, immutable evidence capture, and readiness aggregation before
adding an LLM. Preserve this path as a baseline, fallback, and source of hard safety findings.

## Consequences

- The first milestone is useful without model access.
- Later evaluations can compare model-assisted analysis to a stable baseline.
- Deterministic findings must remain explainable and versioned.
- Rules will not capture semantic impact; that limitation is explicit rather than hidden.

