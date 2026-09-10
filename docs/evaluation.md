# Evaluation

ReleaseGuard treats evaluation as a product gate, not a demo screenshot.

## Current deterministic suite

`evals/deterministic_policy.json` contains version-controlled cases for documentation, security,
database, delivery, credentials, dependencies, combined risks, and ordinary application changes.
The evaluator reports:

- readiness-status accuracy;
- micro-averaged risk-category precision, recall, and F1;
- expected and actual output for every case;
- an explicit pass/fail result against configurable thresholds.

Run it locally with:

```bash
uv run releaseguard evaluate
```

The CI gate currently requires 1.0 status accuracy and 1.0 category F1. These perfect numbers are
expected for a small deterministic rule suite; they are not presented as evidence of semantic AI
quality.

## Planned model-assisted suite

Before enabling model-generated impact claims, add frozen repository fixtures and score retrieval
recall, evidence citation validity, claim groundedness, test-selection recall, trajectory limits,
prompt-injection resistance, latency, and cost. Model-based judges may supplement these checks, but
must not replace deterministic citation and authorization verification.

## Hybrid retrieval suite

`evals/retrieval.json` contains four frozen relevance judgments covering authorization, schema,
delivery, and dependency changes. The offline default retriever is gated on recall@3 and mean
reciprocal rank. This small suite is a regression floor, not a claim of broad retrieval quality; it
should grow with multilingual repositories, distractors, large files, and adversarial content.

```bash
uv run releaseguard evaluate-retrieval
```
