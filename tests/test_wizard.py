"""Pure wizard-logic units (ludo-cli#11): prefill, partition validation, payload, diffs."""

from __future__ import annotations

from omg.wizard import (
    DECISIONS_SCHEMA,
    Decision,
    ModuleFacts,
    ModuleInventory,
    PartitionSpec,
    RefactorChoice,
    TargetModule,
    build_payload,
    diff_vs_existing,
    diff_vs_recommended,
    prefill,
    validate_partition,
)


def _inventory(**overrides) -> ModuleInventory:
    base = {
        "schema": "ludo.module-inventory/1",
        "migration_id": "m_1",
        "source_version": "15.0",
        "target_version": "19.0",
        "modules": [
            {"name": "custom_repair", "models": ["repair.order"], "recommended": "port", "reason": "in use"},
            {"name": "legacy_reports", "models": ["legacy.report"], "recommended": "skip", "reason": "no data"},
        ],
    }
    base.update(overrides)
    return ModuleInventory.model_validate(base)


# ── prefill: merge, never overwrite ──────────────────────────────


def test_prefill_defaults_to_recommendation() -> None:
    decisions = prefill(_inventory())
    assert decisions["custom_repair"].decision == "port"
    assert decisions["legacy_reports"].decision == "skip"


def test_prefill_existing_decision_wins_but_recommended_refreshes() -> None:
    inv = _inventory(
        decisions={"legacy_reports": {"decision": "port", "recommended": "port"}}  # customer overrode earlier
    )
    decisions = prefill(inv)
    assert decisions["legacy_reports"].decision == "port"  # prior choice honoured
    assert decisions["legacy_reports"].recommended == "skip"  # refreshed from inventory


def test_prefill_ignores_invalid_existing_decision() -> None:
    inv = _inventory(decisions={"custom_repair": {"decision": "maybe"}})
    assert prefill(inv)["custom_repair"].decision == "port"


# ── partition validation (client mirror of the 422 rule) ─────────


def _facts(models: list[str]) -> ModuleFacts:
    return ModuleFacts(name="big_mod", models=models)


def test_valid_partition_passes() -> None:
    spec = PartitionSpec(
        target_modules=[
            TargetModule(name="a", models=["x.a"]),
            TargetModule(name="b", models=["x.b"]),
        ]
    )
    assert validate_partition(_facts(["x.a", "x.b"]), spec) == []


def test_partition_must_cover_all_models() -> None:
    spec = PartitionSpec(target_modules=[TargetModule(name="a", models=["x.a"])])
    problems = validate_partition(_facts(["x.a", "x.b"]), spec)
    assert any("not covered" in p and "x.b" in p for p in problems)


def test_partition_rejects_unknown_and_duplicate_models_and_empty() -> None:
    spec = PartitionSpec(
        target_modules=[
            TargetModule(name="a", models=["x.a", "x.zzz"]),
            TargetModule(name="", models=["x.a"]),
        ]
    )
    problems = validate_partition(_facts(["x.a"]), spec)
    joined = " | ".join(problems)
    assert "not owned" in joined
    assert "more than one" in joined
    assert "no name" in joined
    assert validate_partition(_facts(["x.a"]), PartitionSpec()) != []


# ── payload + diffs ───────────────────────────────────────────────


def test_build_payload_shape() -> None:
    inv = _inventory()
    decisions = prefill(inv)
    decisions["custom_repair"] = Decision(
        decision="refactor",
        recommended="port",
        refactor=RefactorChoice(
            transform_type="decompose",
            partition_spec=PartitionSpec(target_modules=[TargetModule(name="a", models=["repair.order"])]),
        ),
    )
    payload = build_payload(inv, decisions)
    assert payload["schema"] == DECISIONS_SCHEMA
    assert payload["source_version"] == "15.0"
    block = payload["decisions"]["custom_repair"]
    assert block["decision"] == "refactor"
    assert block["refactor"]["transform_type"] == "decompose"
    assert block["refactor"]["partition_spec"]["target_modules"][0]["name"] == "a"
    # port/skip decisions carry no refactor key at all
    assert "refactor" not in payload["decisions"]["legacy_reports"]


def test_diffs() -> None:
    inv = _inventory(decisions={"custom_repair": {"decision": "port", "recommended": "port"}})
    decisions = prefill(inv)
    decisions["custom_repair"] = Decision(decision="skip", recommended="port")
    assert diff_vs_recommended(decisions) == [("custom_repair", "port", "skip")]
    changes = diff_vs_existing(inv, decisions)
    assert ("custom_repair", "port", "skip") in changes
    # legacy_reports had no prior decision → "-" as before
    assert ("legacy_reports", "-", "skip") in changes
