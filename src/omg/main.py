"""omg — transport-only CLI for LUDO Odoo migrations.

Talks to a LUDO deployment over its public API; contains no engine code.
Read commands work against the deployment's read-only API today; write
commands (migrate/estimate/rollback/...) arrive in P4 once the deployment's
job-ingress (broker) transport lands — they will submit jobs and stream
Contract B events, never run an engine in-process.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from omg import __version__
from omg.client import LudoClient
from omg.config import load_config
from omg.knowledge import knowledge_app

app = typer.Typer(
    name="omg",
    help="omg — CLI client for LUDO Odoo migrations (transport-only).",
    no_args_is_help=True,
)
app.add_typer(knowledge_app, name="knowledge")
console = Console()


@app.command()
def version() -> None:
    """Show the omg client version and, if reachable, deployment health."""
    console.print(f"omg {__version__}")
    cfg = load_config()
    try:
        with LudoClient(cfg) as client:
            health = client.healthz()
        console.print(f"deployment [cyan]{cfg.api_url}[/cyan]: {health}")
    except Exception as exc:  # unreachable deployment is informational, not fatal
        console.print(f"[yellow]deployment {cfg.api_url} unreachable:[/yellow] {type(exc).__name__}: {exc}")


@app.command()
def status(session_id: str = typer.Argument("", help="Session id; empty lists recent sessions.")) -> None:
    """Read migration/session status from the deployment (read-only API)."""
    cfg = load_config()
    with LudoClient(cfg) as client:
        data: object = client.get_session(session_id) if session_id else client.list_sessions()
    console.print_json(data=data)


@app.command()
def blueprints(session_id: str = typer.Argument("", help="Session id; empty lists blueprint keys.")) -> None:
    """List stored blueprints, or show one session's blueprint."""
    cfg = load_config()
    with LudoClient(cfg) as client:
        data: object = client.blueprint(session_id) if session_id else client.blueprints()
    console.print_json(data=data)


@app.command()
def wiki(
    path: str = typer.Argument("", help="Wiki page path (e.g. episodic/customers/x.md); empty lists a category."),
    category: str = typer.Option("customers", "--category", "-c", help="Category to list when no path is given."),
) -> None:
    """List wiki pages in a category, or read one page."""
    cfg = load_config()
    with LudoClient(cfg) as client:
        data: object = client.wiki_page(path) if path else client.wiki_list(category)
    console.print_json(data=data)


@app.command()
def surprises(customer_id: str = typer.Option("", "--customer", help="Scope to one customer (account_id).")) -> None:
    """Intervention-type summary across sessions (the human-touchpoint metric)."""
    cfg = load_config()
    with LudoClient(cfg) as client:
        data = client.surprises(customer_id or None)
    if not data:
        console.print("[dim]No interventions recorded.[/dim]")
        return
    table = Table(title="Surprises (intervention types)")
    table.add_column("type", style="cyan")
    table.add_column("count", justify="right")
    for kind, count in sorted(data.items()):
        table.add_row(kind, str(count))
    console.print(table)


@app.command()
def config() -> None:
    """Show the resolved CLI config (token redacted)."""
    cfg = load_config()
    console.print({"api_url": cfg.api_url, "token": "***" if cfg.token else None})
