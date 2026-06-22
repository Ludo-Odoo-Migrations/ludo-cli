"""omg knowledge — read-only catalogue / renames / stats / trajectories / advise.

Thin Typer wrappers over the deployment's read-only API (Contract A); rich
rendering only, no engine code. Mounted as the ``omg knowledge`` sub-app.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from omg.client import LudoClient
from omg.config import load_config

knowledge_app = typer.Typer(
    name="knowledge",
    help="Read-only introspection of LUDO's recovery surface.",
    no_args_is_help=True,
)
trajectories_app = typer.Typer(name="trajectories", help="Persisted trajectory index.", no_args_is_help=True)
knowledge_app.add_typer(trajectories_app, name="trajectories")

console = Console()


def _client() -> LudoClient:
    return LudoClient(load_config())


@knowledge_app.command("catalogue")
def catalogue(pattern_id: str = typer.Argument("", help="Optional pattern id to print in detail.")) -> None:
    """List the error catalogue, or print one pattern."""
    with _client() as c:
        data = c.knowledge_catalogue(pattern_id or None)
    if pattern_id:
        console.print_json(data=data)
        return
    patterns = data.get("patterns") or []
    table = Table(title=f"Error catalogue — {len(patterns)} patterns")
    table.add_column("id", style="cyan")
    table.add_column("action", style="yellow")
    for e in patterns:
        if isinstance(e, dict):
            table.add_row(str(e.get("id", "?")), str((e.get("remediation") or {}).get("action", "-")))
    console.print(table)


@knowledge_app.command("renames")
def renames() -> None:
    """Rename-map coverage per version pair."""
    with _client() as c:
        data = c.knowledge_renames()
    table = Table(title="Rename pairs")
    table.add_column("pair", style="cyan")
    table.add_column("models", justify="right")
    table.add_column("last modified", style="dim")
    for pair, info in sorted((data or {}).items()):
        table.add_row(pair, str(info.get("count", "")), str(info.get("last_modified", "")))
    console.print(table)


@knowledge_app.command("stats")
def stats(sessions: int = typer.Option(20, "--sessions", "-n", min=1, max=500)) -> None:
    """Catalogue + rename + novel-error stats."""
    with _client() as c:
        console.print_json(data=c.knowledge_stats(sessions))


@trajectories_app.command("search")
def trajectories_search(
    query: str = typer.Argument(..., help="Error message or signature to search for."),
    k: int = typer.Option(3, "--k", min=1, max=20),
    only_resolved: bool = typer.Option(True, "--only-resolved/--include-unresolved"),
) -> None:
    """Query the persisted trajectory index for similar past errors."""
    with _client() as c:
        res = c.knowledge_trajectories_search(query, k=k, only_resolved=only_resolved)
    if res.get("status") not in (None, "ok"):
        console.print(f"[yellow]{res['status']}[/yellow]")
        return
    hits = res.get("hits") or []
    if not hits:
        console.print("[dim]No matches.[/dim]")
        return
    table = Table(title=f"Top {len(hits)} similar trajectories")
    for col in ("Score", "Customer", "Session", "Tool", "Outcome", "Error"):
        table.add_column(col)
    for h in hits:
        table.add_row(
            f"{h.get('score', 0):.2f}",
            str(h.get("customer_id", "")),
            str(h.get("session_id", "")),
            str(h.get("failed_tool", "")),
            str(h.get("terminal_outcome", "")),
            str(h.get("error_signature", ""))[:80],
        )
    console.print(table)


@knowledge_app.command("advise")
def advise(
    error: str = typer.Argument(..., help="Error message to find similar past resolutions for."),
    failed_tool: str = typer.Option("", "--failed-tool", help="Optional tool that produced the error."),
) -> None:
    """Have we seen an error like this before?"""
    with _client() as c:
        res = c.knowledge_advise(error, failed_tool or None)
    if res.get("status") != "ok":
        console.print(f"[yellow]{res.get('status')}[/yellow]")
        return
    if not res.get("has_advice"):
        console.print("[dim]No similar past resolutions.[/dim]")
        return
    console.print(res.get("markdown") or "")
