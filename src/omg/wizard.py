"""Pure decision-wizard logic for ``omg modules decide`` — no IO, no prompts.

Mirrors the wire shapes of Contract A's module-decision surface
(ludo-agent#601 / #611, ludo-gateway#44):

* ``GET  /api/v1/migrations/{id}/module-inventory`` → :class:`ModuleInventory`
  (``ludo.module-inventory/1``) — module facts + LUDO's recommendation per
  module, plus any existing decisions for prefill.
* ``PATCH /api/v1/migrations/{id}/module-decisions`` ← :func:`build_payload`
  (``ludo.port-decisions/2``) — full-replace, hence idempotent.

The interactive shell (:mod:`omg.decide`) drives these functions; keeping them
pure makes the merge/validation semantics unit-testable and lets the portal
copy them 1:1.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

INVENTORY_SCHEMA = "ludo.module-inventory/1"
DECISIONS_SCHEMA = "ludo.port-decisions/2"

DECISION_VALUES = ("port", "refactor", "skip")
TRANSFORM_TYPES = ("modernize", "decompose", "compose")


class TargetModule(BaseModel):
    """One target module of a decompose/compose partition."""

    name: str
    models: list[str] = Field(default_factory=list)


class PartitionSpec(BaseModel):
    """How source models are re-partitioned across target modules."""

    target_modules: list[TargetModule] = Field(default_factory=list)


class RefactorChoice(BaseModel):
    """The refactor block of a decision (present iff decision == refactor)."""

    transform_type: str  # modernize | decompose | compose
    partition_spec: PartitionSpec | None = None
    notes: str = ""


class Decision(BaseModel):
    """One module's decision as sent to / received from the gateway."""

    decision: str  # port | refactor | skip
    recommended: str = "port"
    refactor: RefactorChoice | None = None


class ModuleFacts(BaseModel):
    """Server-computed facts + advisory for one custom module.

    Tolerant of missing optionals — older inventories may not carry every
    field; the wizard renders a dash for anything absent.
    """

    name: str
    size_band: str = ""
    models: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    usage_records: int | None = None
    effort_hours_low: int | None = None
    effort_hours_high: int | None = None
    risk: str = ""
    recommended: str = "port"
    reason: str = ""
    partition_proposal: PartitionSpec | None = None
    compose_group: list[str] = Field(default_factory=list)


class ModuleInventory(BaseModel):
    """The module-inventory document served by the gateway."""

    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default=INVENTORY_SCHEMA, alias="schema")
    migration_id: str = ""
    source_version: str = ""
    target_version: str = ""
    modules: list[ModuleFacts] = Field(default_factory=list)
    decisions: dict[str, Decision] | None = None


def prefill(inventory: ModuleInventory) -> dict[str, Decision]:
    """Starting decisions for the wizard — merge, never overwrite.

    An existing decision (from the report export or the portal) wins over the
    recommendation; modules without one start at LUDO's recommendation. The
    ``recommended`` field is always refreshed from the current inventory so
    the summary's "differs from recommendation" delta stays truthful.
    """
    existing = inventory.decisions or {}
    out: dict[str, Decision] = {}
    for facts in inventory.modules:
        prior = existing.get(facts.name)
        if prior is not None and prior.decision in DECISION_VALUES:
            out[facts.name] = Decision(
                decision=prior.decision,
                recommended=facts.recommended,
                refactor=prior.refactor,
            )
        else:
            out[facts.name] = Decision(decision=facts.recommended, recommended=facts.recommended)
    return out


def validate_partition(facts: ModuleFacts, spec: PartitionSpec) -> list[str]:
    """Client-side mirror of the server's 422 rule.

    Returns the problems as human-readable strings; empty list = valid.
    A partition must cover every model the module owns, must not invent
    models, must not assign a model twice, and needs named target modules.
    """
    problems: list[str] = []
    owned = set(facts.models)
    assigned: list[str] = []
    for tm in spec.target_modules:
        if not tm.name.strip():
            problems.append("a target module has no name")
        assigned.extend(tm.models)
    seen: set[str] = set()
    for model in assigned:
        if model in seen:
            problems.append(f"model {model} assigned to more than one target module")
        seen.add(model)
    missing = owned - seen
    if missing:
        problems.append("models not covered: " + ", ".join(sorted(missing)))
    unknown = seen - owned
    if unknown:
        problems.append("models not owned by this module: " + ", ".join(sorted(unknown)))
    if not spec.target_modules:
        problems.append("partition has no target modules")
    return problems


def build_payload(inventory: ModuleInventory, decisions: dict[str, Decision]) -> dict[str, object]:
    """The ``ludo.port-decisions/2`` document — the PATCH body and the
    ``--output`` file are byte-identical serialisations of this dict."""
    return {
        "schema": DECISIONS_SCHEMA,
        "customer": inventory.migration_id,
        "source_version": inventory.source_version,
        "target_version": inventory.target_version,
        "decisions": {
            name: d.model_dump(exclude_none=True, exclude_defaults=False) for name, d in sorted(decisions.items())
        },
    }


def diff_vs_recommended(decisions: dict[str, Decision]) -> list[tuple[str, str, str]]:
    """``(module, recommended, chosen)`` rows where the customer diverges."""
    return [(name, d.recommended, d.decision) for name, d in sorted(decisions.items()) if d.decision != d.recommended]


def diff_vs_existing(inventory: ModuleInventory, decisions: dict[str, Decision]) -> list[tuple[str, str, str]]:
    """``(module, before, after)`` rows vs the decisions already on the
    migration — what a PATCH would actually change. New decisions (no prior)
    show ``-`` as before."""
    existing = inventory.decisions or {}
    rows: list[tuple[str, str, str]] = []
    for name, d in sorted(decisions.items()):
        prior = existing.get(name)
        before = prior.decision if prior is not None else "-"
        if before != d.decision:
            rows.append((name, before, d.decision))
    return rows


__all__ = [
    "DECISIONS_SCHEMA",
    "DECISION_VALUES",
    "INVENTORY_SCHEMA",
    "TRANSFORM_TYPES",
    "Decision",
    "ModuleFacts",
    "ModuleInventory",
    "PartitionSpec",
    "RefactorChoice",
    "TargetModule",
    "build_payload",
    "diff_vs_existing",
    "diff_vs_recommended",
    "prefill",
    "validate_partition",
]
