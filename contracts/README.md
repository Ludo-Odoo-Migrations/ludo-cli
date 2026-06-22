# Public contracts

The stable seam between this public CLI and a (private) LUDO deployment. The CLI
depends **only** on what's here — never on engine code.

- `openapi.yaml` — **Contract A** (REST): the deployment's read-only API now, plus
  job-submission endpoints as they land. *(vendored in P2)*
- `session-event.schema.json` — **Contract B** (events): the lifecycle event envelope
  the CLI consumes when streaming a job. *(vendored in P2)*

**Source of truth is private** (the engine repo). These files are *published copies*,
synced on intentional contract releases — so the private side controls exactly which
schema version becomes public, and when. Do not hand-edit; regenerate from the source.
