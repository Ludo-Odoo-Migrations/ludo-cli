# Public contracts — vendored from ludo-init

The stable seam between this public CLI and the LUDO **gateway** (the single public
door over the broker). The CLI depends **only** on what's here — never on the agent
or NATS.

- `openapi.yaml` — **Contract A** (REST + SSE): migrations (list / detail / approve /
  resume) + resumable event stream + health/status.
- `shared-types.yaml` — `Account` / `account_id` / `Money` (referenced by Contract A).
- `session-event.schema.json` — **Contract B** events the CLI consumes when streaming.
- `job-message.schema.json` — **Contract B** job payload (reference).

**Source of truth is [`ludo-init/contracts/`](../../ludo-init/contracts/)** (the cross-repo
hub). These are **vendored copies — do not hand-edit.** Edit the canonical in `ludo-init`,
then re-vendor; drift is enforced by `ludo-init/scripts/check_contract_drift.py`. Governance:
[`ludo-init/contracts/README.md`](../../ludo-init/contracts/README.md).
