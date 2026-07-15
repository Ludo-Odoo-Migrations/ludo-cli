"""``omg modules decide`` — the customer port/refactor wizard (ludo-cli#11).

Interactive shell over the pure logic in :mod:`omg.wizard`. Transport-only:
fetches the module inventory from the gateway, walks the customer through a
Port / Refactor / Skip decision per custom module (LUDO's recommendation
pre-selected, reasoning shown), runs the refactor sub-wizard where chosen,
and PATCHes the resulting ``ludo.port-decisions/2`` document back.

Merge, never overwrite: existing decisions (report export / portal) prefill
the wizard and the summary shows exactly what a PATCH would change.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import typer
from rich.prompt import Confirm, Prompt
from rich.table import Table

from omg._ui import console, fail
from omg.client import LudoClient
from omg.config import load_config
from omg.wizard import (
    TRANSFORM_TYPES,
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

modules_app = typer.Typer(
    help="Custom-module decisions for a migration (port / refactor / skip).",
    no_args_is_help=True,
)


@modules_app.command()
def decide(
    migration_id: str = typer.Argument(..., help="Migration id (see `omg migrations`)."),
    output: Path = typer.Option(
        None,
        "--output",
        help="Also write the decisions document (port_decisions.json) locally — byte-identical to the PATCH body.",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Accept every prefilled decision (existing decisions win, else LUDO's recommendation) and submit.",
    ),
) -> None:
    """Decide per custom module: Port, Refactor, or Skip — LUDO advises, you choose."""
    cfg = load_config()
    try:
        with LudoClient(cfg) as client:
            raw = client.get_module_inventory(migration_id)
            inventory = ModuleInventory.model_validate(raw)
            if not inventory.modules:
                console.print("[dim]No custom modules in this migration's inventory — nothing to decide.[/dim]")
                return
            decisions = prefill(inventory)

            if not non_interactive:
                _run_wizard(inventory, decisions)
                _print_summary(inventory, decisions)
                if not Confirm.ask("Submit these decisions?", default=True):
                    console.print("[yellow]Nothing submitted.[/yellow]")
                    return

            payload = build_payload(inventory, decisions)
            body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            if output is not None:
                output.write_text(body, encoding="utf-8")
                console.print(f"wrote [cyan]{output}[/cyan]")
            client.patch_module_decisions(migration_id, payload)
    except httpx.HTTPError as exc:
        fail(exc)
        return
    port = sum(1 for d in decisions.values() if d.decision == "port")
    refactor = sum(1 for d in decisions.values() if d.decision == "refactor")
    skip = sum(1 for d in decisions.values() if d.decision == "skip")
    console.print(f"[green]Decisions saved[/green] — {port} port, {refactor} refactor, {skip} skip.")
    if refactor:
        console.print(
            "[dim]Refactor choices are recorded and advised on; execution is scheduled "
            "with your migration operator (refactor_pending until the transform engine run).[/dim]"
        )


# ── wizard steps ─────────────────────────────────────────────────────


def _run_wizard(inventory: ModuleInventory, decisions: dict[str, Decision]) -> None:
    """Mutates ``decisions`` in place through the interactive flow."""
    console.print(
        f"\n[bold]Module decisions[/bold] — migration [cyan]{inventory.migration_id}[/cyan] "
        f"({inventory.source_version} → {inventory.target_version}), "
        f"{len(inventory.modules)} custom module(s).\n"
        "Not every module has to come along. LUDO recommends; you decide."
    )
    mode = Prompt.ask(
        "Scope",
        choices=["port-only", "refactor"],
        default="port-only",
    )
    for facts in inventory.modules:
        current = decisions[facts.name]
        _print_module(facts, current)
        choices = ["p", "s", "a"] if mode == "port-only" else ["p", "r", "s", "a"]
        # No square brackets in the legend — rich would parse them as markup tags.
        legend = "p=port / s=skip / a=accept" if mode == "port-only" else "p=port / r=refactor / s=skip / a=accept"
        answer = Prompt.ask(legend, choices=choices, default="a")
        if answer == "a":
            continue  # keep the prefill (existing decision or recommendation)
        if answer == "p":
            decisions[facts.name] = Decision(decision="port", recommended=facts.recommended)
        elif answer == "s":
            decisions[facts.name] = Decision(decision="skip", recommended=facts.recommended)
        else:
            refactor = _refactor_subwizard(facts)
            decisions[facts.name] = Decision(decision="refactor", recommended=facts.recommended, refactor=refactor)


def _print_module(facts: ModuleFacts, current: Decision) -> None:
    table = Table(title=f"{facts.name}", show_header=False, title_justify="left")
    table.add_column("fact", style="dim")
    table.add_column("value")
    table.add_row("size", facts.size_band or "-")
    table.add_row("models", ", ".join(facts.models) if facts.models else "-")
    table.add_row("flags", ", ".join(facts.flags) if facts.flags else "-")
    table.add_row("usage", f"{facts.usage_records:,} records" if facts.usage_records is not None else "-")
    effort = (
        f"{facts.effort_hours_low}-{facts.effort_hours_high} h"
        if facts.effort_hours_low is not None and facts.effort_hours_high is not None
        else "-"
    )
    table.add_row("effort / risk", f"{effort} / {facts.risk or '-'}")
    table.add_row("recommended", f"[bold]{facts.recommended}[/bold] — {facts.reason or 'no reason given'}")
    if current.decision != facts.recommended:
        table.add_row("current", f"[yellow]{current.decision}[/yellow] (your earlier choice)")
    console.print(table)


def _refactor_subwizard(facts: ModuleFacts) -> RefactorChoice:
    transform = Prompt.ask(
        "Transform",
        choices=list(TRANSFORM_TYPES),
        default="modernize",
    )
    if transform == "modernize":
        notes = Prompt.ask("Notes for the migration team (optional)", default="")
        return RefactorChoice(transform_type=transform, notes=notes)
    if transform == "decompose":
        spec = _edit_partition(facts)
    else:  # compose
        spec = _compose_partition(facts)
    notes = Prompt.ask("Notes for the migration team (optional)", default="")
    return RefactorChoice(transform_type=transform, partition_spec=spec, notes=notes)


def _edit_partition(facts: ModuleFacts) -> PartitionSpec:
    """Decompose: start from the server's proposal, edit until valid.

    Simple prompt-per-target editing: for each target module the customer
    confirms/edits its name and its comma-separated model list. Loops until
    the partition covers every owned model exactly once.
    """
    proposal = facts.partition_proposal or PartitionSpec(
        target_modules=[TargetModule(name=f"{facts.name}_core", models=list(facts.models))]
    )
    while True:
        count = int(
            Prompt.ask(
                "How many target modules?",
                default=str(max(len(proposal.target_modules), 2)),
            )
        )
        targets: list[TargetModule] = []
        for i in range(count):
            base = proposal.target_modules[i] if i < len(proposal.target_modules) else None
            name = Prompt.ask(f"  target {i + 1} name", default=(base.name if base else f"{facts.name}_{i + 1}"))
            models_default = ", ".join(base.models) if base else ""
            models_raw = Prompt.ask(f"  target {i + 1} models (comma-separated)", default=models_default)
            models = [m.strip() for m in models_raw.split(",") if m.strip()]
            targets.append(TargetModule(name=name, models=models))
        spec = PartitionSpec(target_modules=targets)
        problems = validate_partition(facts, spec)
        if not problems:
            return spec
        console.print("[red]Partition invalid:[/red] " + "; ".join(problems))
        proposal = spec  # keep the edits as the next round's defaults


def _compose_partition(facts: ModuleFacts) -> PartitionSpec:
    """Compose: pick sibling modules to merge + name the service module.

    The partition carries ONE target module; the sibling list is recorded in
    its models-by-provenance on the server side — here the customer confirms
    the group and the merged name.
    """
    group_default = ", ".join(facts.compose_group) if facts.compose_group else facts.name
    group_raw = Prompt.ask("Modules to merge (comma-separated)", default=group_default)
    group = [m.strip() for m in group_raw.split(",") if m.strip()]
    if facts.name not in group:
        group.insert(0, facts.name)
    name = Prompt.ask("Merged service-module name", default=f"{facts.name}_service")
    # The merged module carries this module's models; the server resolves the
    # union across the group when it builds the TransformRequest.
    spec = PartitionSpec(target_modules=[TargetModule(name=name, models=list(facts.models))])
    console.print(f"[dim]merging: {', '.join(group)} → {name}[/dim]")
    return spec


def _print_summary(inventory: ModuleInventory, decisions: dict[str, Decision]) -> None:
    table = Table(title="Summary — your decisions")
    table.add_column("module", style="cyan")
    table.add_column("decision")
    table.add_column("recommended", style="dim")
    table.add_column("transform", style="dim")
    for name, d in sorted(decisions.items()):
        mark = "" if d.decision == d.recommended else " [yellow]*[/yellow]"
        transform = d.refactor.transform_type if d.refactor is not None else "-"
        table.add_row(name, d.decision + mark, d.recommended, transform)
    console.print(table)
    diverging = diff_vs_recommended(decisions)
    if diverging:
        console.print(f"[yellow]*[/yellow] {len(diverging)} choice(s) differ from LUDO's recommendation.")
    changes = diff_vs_existing(inventory, decisions)
    if inventory.decisions:
        if changes:
            console.print("Changes vs decisions already on the migration:")
            for name, before, after in changes:
                console.print(f"  {name}: {before} → {after}")
        else:
            console.print("[dim]No changes vs the decisions already on the migration.[/dim]")
