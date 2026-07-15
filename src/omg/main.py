"""omg — transport-only CLI for LUDO Odoo migrations.

Talks to the LUDO **gateway** (the single public door over the broker); contains
no engine code and never reaches the agent or NATS directly. Read commands work
today; write commands (approve / job submit) land in P4 once the gated broker
write path is cleared.
"""

from __future__ import annotations

import httpx
import typer
from rich.table import Table

from omg import __version__
from omg._ui import console, fail as _fail
from omg.client import LudoClient
from omg.config import load_config
from omg.decide import modules_app

app = typer.Typer(
    name="omg",
    help="omg — CLI client for LUDO Odoo migrations (transport-only).",
    no_args_is_help=True,
)
app.add_typer(modules_app, name="modules")


@app.command()
def version() -> None:
    """Show the omg client version and, if reachable, gateway health + env."""
    console.print(f"omg {__version__}")
    cfg = load_config()
    try:
        with LudoClient(cfg) as client:
            health = client.healthz()
            status = client.system_status()
        console.print(f"gateway [cyan]{cfg.api_url}[/cyan]: {health} {status}")
    except Exception as exc:  # unreachable gateway is informational, not fatal
        console.print(f"[yellow]gateway {cfg.api_url} unreachable:[/yellow] {type(exc).__name__}: {exc}")


@app.command()
def migrations(migration_id: str = typer.Argument("", help="Migration id; empty lists your migrations.")) -> None:
    """List your migrations, or show one migration's detail (gateway, tenant-scoped)."""
    cfg = load_config()
    try:
        with LudoClient(cfg) as client:
            if migration_id:
                console.print_json(data=client.get_migration(migration_id))
                return
            data = client.list_migrations()
    except httpx.HTTPError as exc:
        _fail(exc)
    items = data.get("items") or []
    if not items:
        console.print("[dim]No migrations.[/dim]")
        return
    table = Table(title=f"Migrations ({len(items)})")
    table.add_column("id", style="cyan")
    table.add_column("state", justify="right")
    table.add_column("account")
    for m in items:
        table.add_row(str(m.get("id", "")), str(m.get("state_index", m.get("state", ""))), str(m.get("account_id", "")))
    console.print(table)


@app.command()
def events(
    migration_id: str = typer.Argument(..., help="Migration id to stream."),
    resume_from: int = typer.Option(0, "--resume-from", help="Resume from this stream seq (Last-Event-ID)."),
) -> None:
    """Stream a migration's resumable event log (Contract B SSE) until it ends."""
    cfg = load_config()
    try:
        with LudoClient(cfg) as client:
            for seq, etype, payload in client.stream_events(migration_id, last_event_id=resume_from or None):
                console.print(f"[dim]{seq:>4}[/dim] [cyan]{etype}[/cyan] {payload}")
    except httpx.HTTPError as exc:
        _fail(exc)


@app.command()
def config() -> None:
    """Show the resolved CLI config (token redacted)."""
    cfg = load_config()
    console.print({"api_url": cfg.api_url, "token": "***" if cfg.token else None})
