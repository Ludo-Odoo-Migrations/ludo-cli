# Public contracts — vendored from agentix

The stable seam between this public CLI and the LUDO **gateway** (the single public
door over the broker). The CLI depends **only** on what's here — never on the agent
or NATS.

- `openapi.yaml` — **Contract A** (REST + SSE): migrations (list / detail / approve /
  resume) + resumable event stream + health/status.
- `shared-types.yaml` — `Account` / `account_id` / `Money` (referenced by Contract A).
- `session-event.schema.json` — **Contract B** events the CLI consumes when streaming.
- `job-message.schema.json` — **Contract B** job payload (reference).

**Source of truth is [`agentix/contracts/`](../../agentix/contracts/)** (the cross-repo
hub). These are **vendored copies — do not hand-edit.** Edit the canonical in `agentix`,
then re-vendor; drift is enforced by `agentix/scripts/check_contract_drift.py`. Governance:
`agentix/docs/contracts.md`.
