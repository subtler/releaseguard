# ADR 0003: checkpointed bounded workflow

- Status: accepted
- Date: 2026-09-10

## Context

Change-impact analysis will eventually include retrieval and model-assisted synthesis. Treating that
process as one opaque agent call would make failures difficult to resume, inspect, evaluate, or
constrain.

## Decision

Use an explicit LangGraph state machine with named stages and a local SQLite checkpointer. The
current graph is linear and bounded: collect repository evidence, analyze static impact, retrieve
repository context, classify risk, verify evidence, and assemble the report. Every stage has typed
state and a fixed transition.

SQLite is the zero-service local backend. The checkpointer boundary permits PostgreSQL in a hosted
environment later without changing domain contracts. New model or tool stages must retain explicit
budgets, stopping conditions, and verifier gates.

## Consequences

- interrupted work has durable stage-level state;
- trajectories can be inspected and evaluated;
- deterministic verification remains separate from probabilistic synthesis;
- checkpoint files contain repository-derived data and must be treated as sensitive;
- SQLite is appropriate for this single-machine build, not a claim of multi-worker scalability.
