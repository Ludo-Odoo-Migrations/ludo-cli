"""CLI tests for `omg modules decide` (ludo-cli#11) — scripted input, mocked client."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from omg.main import app

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(output: str) -> str:
    """Strip rich's ANSI codes so substring assertions are stable."""
    return _ANSI.sub("", output)


INVENTORY: dict[str, Any] = {
    "schema": "ludo.module-inventory/1",
    "migration_id": "m_1",
    "source_version": "15.0",
    "target_version": "19.0",
    "modules": [
        {
            "name": "custom_repair",
            "size_band": "large",
            "models": ["repair.order", "repair.line"],
            "flags": ["uses_old_api"],
            "usage_records": 4321,
            "effort_hours_low": 8,
            "effort_hours_high": 16,
            "risk": "medium",
            "recommended": "port",
            "reason": "in use",
            "partition_proposal": {
                "target_modules": [
                    {"name": "repair_core", "models": ["repair.order"]},
                    {"name": "repair_lines", "models": ["repair.line"]},
                ]
            },
        },
        {
            "name": "legacy_reports",
            "size_band": "thin",
            "models": ["legacy.report"],
            "recommended": "skip",
            "reason": "no data",
        },
    ],
}


class FakeClient:
    """Stands in for LudoClient — records the PATCH body."""

    inventory: dict[str, Any] = INVENTORY
    patched: list[tuple[str, dict[str, Any]]] = []
    inventory_error: Exception | None = None
    patch_error: Exception | None = None

    def __init__(self, cfg: Any, **kwargs: Any) -> None:
        pass

    def get_module_inventory(self, migration_id: str) -> dict[str, Any]:
        if FakeClient.inventory_error is not None:
            raise FakeClient.inventory_error
        return FakeClient.inventory

    def patch_module_decisions(self, migration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if FakeClient.patch_error is not None:
            raise FakeClient.patch_error
        FakeClient.patched.append((migration_id, payload))
        return {"migration_id": migration_id}

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        pass


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.inventory = INVENTORY
    FakeClient.patched = []
    FakeClient.inventory_error = None
    FakeClient.patch_error = None
    monkeypatch.setattr("omg.decide.LudoClient", FakeClient)
    monkeypatch.setattr("omg.decide.load_config", lambda: object())


def test_non_interactive_accepts_recommendations() -> None:
    result = runner.invoke(app, ["modules", "decide", "m_1", "--non-interactive"])
    assert result.exit_code == 0, result.output
    assert len(FakeClient.patched) == 1
    _, payload = FakeClient.patched[0]
    assert payload["schema"] == "ludo.port-decisions/2"
    assert payload["decisions"]["custom_repair"]["decision"] == "port"
    assert payload["decisions"]["legacy_reports"]["decision"] == "skip"
    assert "1 port, 0 refactor, 1 skip" in plain(result.output)


def test_interactive_override_and_confirm() -> None:
    # port-only mode; accept module 1; override module 2 to port; confirm submit.
    result = runner.invoke(app, ["modules", "decide", "m_1"], input="port-only\na\np\ny\n")
    assert result.exit_code == 0, result.output
    _, payload = FakeClient.patched[0]
    assert payload["decisions"]["legacy_reports"]["decision"] == "port"
    assert "differ from LUDO's recommendation" in plain(result.output)


def test_refactor_decompose_flow_records_partition() -> None:
    # refactor mode; module 1 -> refactor/decompose, accept proposal (2 targets,
    # default names + models), no notes; module 2 accept; confirm.
    scripted = "\n".join(
        [
            "refactor",  # mode
            "r",  # custom_repair -> refactor
            "decompose",  # transform
            "2",  # target count (default from proposal)
            "",  # target 1 name (default repair_core)
            "",  # target 1 models (default repair.order)
            "",  # target 2 name (default repair_lines)
            "",  # target 2 models (default repair.line)
            "",  # notes
            "a",  # legacy_reports accept (skip)
            "y",  # submit
        ]
    )
    result = runner.invoke(app, ["modules", "decide", "m_1"], input=scripted + "\n")
    assert result.exit_code == 0, result.output
    _, payload = FakeClient.patched[0]
    block = payload["decisions"]["custom_repair"]
    assert block["decision"] == "refactor"
    assert block["refactor"]["transform_type"] == "decompose"
    names = [t["name"] for t in block["refactor"]["partition_spec"]["target_modules"]]
    assert names == ["repair_core", "repair_lines"]
    assert "refactor" in plain(result.output)


def test_invalid_partition_reprompts_until_valid() -> None:
    # First partition misses repair.line -> re-prompt; second attempt valid.
    scripted = "\n".join(
        [
            "refactor",
            "r",
            "decompose",
            "1",  # one target
            "only_core",  # name
            "repair.order",  # models — MISSING repair.line -> invalid
            "2",  # retry: two targets
            "",  # name default (only_core kept as round default)
            "",  # models default (repair.order)
            "part_two",  # second target name
            "repair.line",  # second target models
            "",  # notes
            "a",  # legacy_reports
            "y",
        ]
    )
    result = runner.invoke(app, ["modules", "decide", "m_1"], input=scripted + "\n")
    assert result.exit_code == 0, result.output
    assert "Partition invalid" in plain(result.output)
    _, payload = FakeClient.patched[0]
    targets = payload["decisions"]["custom_repair"]["refactor"]["partition_spec"]["target_modules"]
    covered = sorted(m for t in targets for m in t["models"])
    assert covered == ["repair.line", "repair.order"]


def test_output_file_byte_identical_to_patch_body(tmp_path) -> None:
    out = tmp_path / "port_decisions.json"
    result = runner.invoke(app, ["modules", "decide", "m_1", "--non-interactive", "--output", str(out)])
    assert result.exit_code == 0, result.output
    _, payload = FakeClient.patched[0]
    assert json.loads(out.read_text(encoding="utf-8")) == payload
    assert out.read_text(encoding="utf-8") == json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def test_decline_submits_nothing() -> None:
    result = runner.invoke(app, ["modules", "decide", "m_1"], input="port-only\na\na\nn\n")
    assert result.exit_code == 0, result.output
    assert FakeClient.patched == []
    assert "Nothing submitted" in plain(result.output)


def test_server_422_rendered_with_reason() -> None:
    request = httpx.Request("PATCH", "http://gw/api/v1/migrations/m_1/module-decisions")
    response = httpx.Response(422, request=request, text='{"detail": "partition does not cover repair.line"}')
    FakeClient.patch_error = httpx.HTTPStatusError("422", request=request, response=response)
    result = runner.invoke(app, ["modules", "decide", "m_1", "--non-interactive"])
    assert result.exit_code == 1
    assert "422" in plain(result.output)
    assert "repair.line" in plain(result.output)


def test_prefill_from_existing_decisions_shows_changes() -> None:
    FakeClient.inventory = dict(INVENTORY)
    FakeClient.inventory["decisions"] = {"legacy_reports": {"decision": "port", "recommended": "skip"}}
    # Accept everything: legacy_reports keeps the customer's earlier "port".
    result = runner.invoke(app, ["modules", "decide", "m_1"], input="port-only\na\na\ny\n")
    assert result.exit_code == 0, result.output
    _, payload = FakeClient.patched[0]
    assert payload["decisions"]["legacy_reports"]["decision"] == "port"
    # custom_repair had no prior decision -> it IS a change vs the stored blob
    assert "custom_repair: - → port" in plain(result.output)


def test_empty_inventory_is_a_noop() -> None:
    FakeClient.inventory = {**INVENTORY, "modules": []}
    result = runner.invoke(app, ["modules", "decide", "m_1"])
    assert result.exit_code == 0
    assert FakeClient.patched == []
    assert "nothing to decide" in plain(result.output)
