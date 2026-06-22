# omg

**omg** is the command-line client for **LUDO** — autonomous Odoo cross-version
migration. It is a **transport-only client**: it talks to a LUDO deployment over a
stable API and event stream, and contains **no migration engine and no Odoo
credentials**. Think `kubectl` / `stripe` / `gh` — a thin client for a backend that
runs elsewhere.

```
omg  ──▶  Contract A (REST) + Contract B (events)  ──▶  your LUDO deployment (engine)
          public schemas only · no engine code · auth-gated
```

You point `omg` at **your own** LUDO deployment and authenticate to it; the engine,
your Odoo credentials, and your data never live in this CLI.

## Status

Early scaffold (P1). Read commands work against a deployment's read-only API today;
write commands (migrate / estimate / rollback / …) arrive once the deployment's
job-submission transport lands. Build tracked in
[ludo-omg#1](https://github.com/euroblaze/ludo-omg/issues/1).

## Install

```sh
pipx install .        # from a checkout (PyPI release later)
```

## Configure

`omg` needs to know where your deployment is and how to authenticate:

```sh
export LUDO_API_URL=http://10.0.99.1:8000   # your deployment's API
export LUDO_API_TOKEN=…                      # bearer token (optional in dev)
```

## Use

```sh
omg version          # client version + deployment health
omg status           # recent sessions
omg status <id>      # one session's status
omg config           # show resolved config (token redacted)
```

## How it's built

- **No engine code.** CI fails the build on any private engine import — `omg` only
  ever speaks the public contracts under [`contracts/`](contracts/).
- **Public seam.** `contracts/openapi.yaml` (Contract A) and
  `session-event.schema.json` (Contract B) are vendored copies; the source of truth
  is private and published on intentional contract releases.

## License

Source-available under the **Business Source License 1.1** (see [`LICENSE`](LICENSE)).
Non-production use is free; there is no Additional Use Grant, so production use requires
a commercial license from the Licensor (wapsol (labs) gmbh) until the Change Date — each
version converts to **Apache-2.0** four years after its release. For alternative
licensing, contact Ashant Chalasani &lt;ach@runludo.com&gt;.
