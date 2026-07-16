"""Shared CLI rendering helpers — one console, one error idiom.

Extracted from ``main.py`` so sub-apps (``omg modules …``) reuse the same
failure rendering instead of growing local copies (CRIE, ludo-cli#11).
"""

from __future__ import annotations

import httpx
import typer
from rich.console import Console

console = Console()


def fail(reason: httpx.HTTPError | str) -> None:
    """Turn a transport error (or a plain reason) into a clean message + non-zero exit.

    HTTP errors show the status + the server's reason (the gateway puts
    validation detail in the body — e.g. a 422 partition problem); a plain
    string renders as-is (client-side validation, pre-request failures).
    """
    if isinstance(reason, str):
        console.print(f"[red]error:[/red] {reason}")
    elif isinstance(reason, httpx.HTTPStatusError):
        console.print(f"[red]error {reason.response.status_code}:[/red] {reason.response.text.strip()[:400]}")
    else:
        console.print(f"[red]cannot reach gateway:[/red] {type(reason).__name__}: {reason}")
    raise typer.Exit(1)
