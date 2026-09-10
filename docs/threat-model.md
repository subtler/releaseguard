# Threat model

## Assets

- repository source and metadata;
- user identity and repository authorization;
- model/tool credentials;
- analysis evidence, reports, approvals, and audit trail;
- worker and database availability.

## Trust boundaries

- API caller to ReleaseGuard;
- ReleaseGuard to a local repository or Git provider;
- workflow to model provider;
- workflow to MCP tools;
- retrieved repository content to model context;
- approval service to any write-capable integration.

Repository files, commit messages, issue text, pull-request comments, retrieved documents, and MCP
results are untrusted data. They must never be interpreted as system instructions or authorization.

## Initial controls

- allow access only beneath a configured repository root;
- resolve user-provided refs to immutable commits;
- execute Git without a shell and with a strict timeout;
- reject option-like or malformed refs;
- cap captured diff size;
- cap repository manifests and individual source reads;
- read source from an immutable Git object rather than the mutable working tree;
- expose read-only operations only;
- verify evidence repository and commit provenance before report assembly;
- return explicit failures rather than silently degrading evidence.

Local SQLite checkpoints may contain source-derived state. The `.releaseguard/` directory is
ignored by Git and should be encrypted or placed on an encrypted volume when repositories contain
sensitive material.

## Controls before model/tool integration

- least-privilege Git provider scopes;
- tenant authorization enforced in tools and storage, not prompts;
- typed tool parameters and result-size limits;
- per-run tool, token, time, and cost budgets;
- provenance and trust classification for context;
- adversarial prompt-injection cases in CI;
- approval with exact action preview for writes;
- idempotency keys and immutable audit events;
- cancellation and emergency-stop behavior.
