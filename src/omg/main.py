"""omg — transport-only CLI for LUDO Odoo migrations.

Talks to the LUDO **gateway** (the single public door over the broker); contains
no engine code and never reaches the agent or NATS directly.

P3 read commands: version, migrations, events, config, modules decide.
P4 write commands: approve, resume, estimate.
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
def approve(
    migration_id: str = typer.Argument(..., help="Migration id to approve and start."),
    idempotency_key: str = typer.Option(
        "", "--idempotency-key", "-k", help="Override the auto-generated Idempotency-Key."
    ),
    stream: bool = typer.Option(False, "--stream", "-s", help="Stream events after approval until session_end."),
) -> None:
    """Approve and start a migration (enqueue the agent job). Result arrives on the event stream.

    The gateway returns 202 immediately; the agent run is observable via `omg events <id>`
    (or --stream). A second approve on the same migration replays safely via idempotency.
    409 = another migration for this account is already running.
    """
    cfg = load_config()
    try:
        with LudoClient(cfg) as client:
            result = client.approve(migration_id, idempotency_key or None)
            console.print(f"[green]accepted[/green] job_id=[cyan]{result.get('job_id', '?')}[/cyan]")
            if stream:
                console.print(f"[dim]streaming {migration_id} ...[/dim]")
                for seq, etype, payload in client.stream_events(migration_id):
                    console.print(f"[dim]{seq:>4}[/dim] [cyan]{etype}[/cyan] {payload}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            _fail(f"409 Conflict: {exc.response.json().get('detail', 'another migration is already running')}")
        _fail(exc)
    except httpx.HTTPError as exc:
        _fail(exc)


@app.command()
def resume(
    migration_id: str = typer.Argument(..., help="Migration id to resume."),
    idempotency_key: str = typer.Option(
        "", "--idempotency-key", "-k", help="Override the auto-generated Idempotency-Key."
    ),
    stream: bool = typer.Option(False, "--stream", "-s", help="Stream events after resume until session_end."),
) -> None:
    """Resume a paused or checkpointed migration. Same contract as approve.

    The agent picks up from its last checkpoint; completed work is not repeated.
    409 = another migration for this account is already running.
    """
    cfg = load_config()
    try:
        with LudoClient(cfg) as client:
            result = client.resume(migration_id, idempotency_key or None)
            console.print(f"[green]accepted[/green] job_id=[cyan]{result.get('job_id', '?')}[/cyan]")
            if stream:
                console.print(f"[dim]streaming {migration_id} ...[/dim]")
                for seq, etype, payload in client.stream_events(migration_id):
                    console.print(f"[dim]{seq:>4}[/dim] [cyan]{etype}[/cyan] {payload}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            _fail(f"409 Conflict: {exc.response.json().get('detail', 'another migration is already running')}")
        _fail(exc)
    except httpx.HTTPError as exc:
        _fail(exc)


@app.command()
def estimate(
    combo: str = typer.Argument(..., help="Edition pair: cc (Community→Community), ce, ec, ee."),
    src_version: int = typer.Argument(..., help="Source Odoo major version (e.g. 15)."),
    tgt_version: int = typer.Argument(..., help="Target Odoo major version (e.g. 18)."),
) -> None:
    """Request a migration cost estimate. Free — may be called before signup.

    COMBO is one of: cc (Community→Community), ce (Community→Enterprise),
    ec (Enterprise→Community), ee (Enterprise→Enterprise).
    SRC_VERSION and TGT_VERSION are Odoo major version numbers (e.g. 15 18).
    """
    valid_combos = {"cc", "ce", "ec", "ee"}
    if combo not in valid_combos:
        _fail(f"Invalid combo {combo!r}. Must be one of: {', '.join(sorted(valid_combos))}")
    if tgt_version < src_version:
        _fail(f"tgt_version ({tgt_version}) cannot be lower than src_version ({src_version})")
    cfg = load_config()
    try:
        with LudoClient(cfg) as client:
            result = client.create_estimate(combo, src_version, tgt_version)
    except httpx.HTTPError as exc:
        _fail(exc)
    console.print_json(data=result)


@app.command()
def config() -> None:
    """Show the resolved CLI config (token redacted)."""
    cfg = load_config()
    console.print({"api_url": cfg.api_url, "token": "***" if cfg.token else None})
