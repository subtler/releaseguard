# Read-only MCP server

ReleaseGuard includes a local Model Context Protocol server built with the official Python SDK v2.
It exposes exactly one tool: `analyze_local_change`.

The tool accepts a repository path plus base and head refs and returns the same structured,
verified readiness report as the CLI and HTTP API. Its MCP annotations declare it read-only,
non-destructive, idempotent, and closed-world. No repository mutation tools are registered.

Run the local stdio server with:

```bash
uv run releaseguard-mcp
```

The repository-root allowlist, immutable ref resolution, bounded reads, timeouts, evidence verifier,
and local checkpoints all remain active when analysis is invoked through MCP. Repository text and
tool results are untrusted data; they never grant authorization or change server instructions.

Only stdio is documented for the local build. A future network transport must add authentication,
tenant authorization, rate limits, and transport-level security before it is considered safe.
