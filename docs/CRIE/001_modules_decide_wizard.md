# CRIE 001 — omg modules decide (ludo-cli#11)

Date: 2026-07-15. Scope: the customer port/refactor decision wizard.

## Actions

- Extracted `_fail` + `Console` from `main.py` into `src/omg/_ui.py`; `main.py` and
  `decide.py` share one error idiom (was about to be duplicated).
- Wizard logic kept pure in `src/omg/wizard.py` (no IO): prefill/merge, partition
  validation, payload build, diffs. The portal (ludo-webapps#118) copies these
  semantics 1:1 instead of re-inventing them client-side.
- Advisory brain NOT re-implemented here — recommendations arrive server-computed in
  the module inventory (ludo-agent#611). One brain, N surfaces.
- Transport reuse: `LudoClient._with_retry`/`_get` extended with one `_patch` helper;
  no second HTTP stack, no questionary dependency (rich.prompt only, zero new deps).
- CI gained a test job (`uv run --with pytest`) — pytest stays out of the runtime
  lock; the pre-existing test file now actually runs in CI.

## Savings

- ~10 lines deduplicated now (`_fail`); ~150-200 lines avoided by consuming
  server-side recommendations instead of duplicating the advisor; ~50 lines avoided
  by reusing the retry/backoff client core.

## References

- src/omg/wizard.py, src/omg/decide.py, src/omg/_ui.py, src/omg/client.py
- Contract shapes: ludo.module-inventory/1 (GET), ludo.port-decisions/2 (PATCH)
