"""Shared CLI rendering helpers — one console, one error idiom.

Extracted from ``main.py`` so sub-apps (``omg modules …``) reuse the same
failure rendering instead of growing local copies (CRIE, ludo-cli#11).
"""

from __future__ import annotations

import httpx
import typer
from rich.console import Console

console = Console()


def fail(exc: httpx.HTTPError) -> None:
    """Turn a transport error into a clean message + non-zero exit (no traceback).

    HTTP errors show the status + the server's reason (the gateway puts
    validation detail in the body — e.g. a 422 partition problem).
    """
    if isinstance(exc, httpx.HTTPStatusError):
        console.print(f"[red]error {exc.response.status_code}:[/red] {exc.response.text.strip()[:400]}")
    else:
        console.print(f"[red]cannot reach gateway:[/red] {type(exc).__name__}: {exc}")
    raise typer.Exit(1)
