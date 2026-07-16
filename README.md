# omg

**omg** is the command-line client for **LUDO** — autonomous Odoo cross-version
migration. It is a **transport-only client**: it talks to the LUDO **gateway** over a
stable API + event stream, and contains **no migration engine and no Odoo
credentials**. Think `kubectl` / `stripe` / `gh` — a thin client for a backend that
runs elsewhere.

```
omg  ──▶  gateway (Contract A REST + Contract B SSE)  ──▶  NATS  ──▶  agent (private)
          public schemas only · no engine code · auth-gated
```

The gateway ([`Ludo-Odoo-Migrations/ludo-gateway`](https://github.com/Ludo-Odoo-Migrations/ludo-gateway)) is the
single public door; `omg` never reaches the agent or the broker directly. You point it at
**your own** deployment's gateway and authenticate; the engine, your Odoo credentials, and
your data never live in this CLI.

## Status

Read commands work against the gateway today (P3); write commands (approve / job submit)
arrive once the gated broker write path is cleared (P4). Build tracked in
[ludo-cli#1](https://github.com/Ludo-Odoo-Migrations/ludo-cli/issues/1).

## Install

```sh
pipx install .        # from a checkout (PyPI release later)
```

## Configure

`omg` needs to know where your gateway is and how to authenticate:

```sh
export LUDO_API_URL=http://10.0.99.1:8080   # your deployment's gateway
export LUDO_API_TOKEN=…                      # bearer token (anon = 404 on tenant data)
```

## Use

```sh
omg version             # client version + gateway health/env
omg migrations          # list your migrations
omg migrations <id>     # one migration's detail
omg events <id>         # stream the migration's resumable event log (SSE)
omg config              # show resolved config (token redacted)
```

## How it's built

- **No engine code.** CI fails the build on any private engine import — `omg` only
  ever speaks the gateway's public contracts under [`contracts/`](contracts/).
- **Public seam.** `contracts/openapi.yaml` (Contract A) and
  `session-event.schema.json` (Contract B) are vendored from the gateway; the source
  of truth is `Ludo-Odoo-Migrations/ludo-gateway`, published on intentional contract releases.

## License

Source-available under the **Business Source License 1.1** (see [`LICENSE`](LICENSE)).
Non-production use is free; there is no Additional Use Grant, so production use requires
a commercial license from the Licensor (wapsol (labs) gmbh) until the Change Date — each
version converts to **Apache-2.0** four years after its release. For alternative
licensing, contact Ashant Chalasani &lt;ach@runludo.com&gt;.
