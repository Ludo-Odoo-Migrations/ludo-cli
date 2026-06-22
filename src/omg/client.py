"""Transport client — talks to a LUDO deployment over Contract A (REST).

Depends only on public HTTP + the vendored contract schemas (contracts/).
No engine import; no Odoo credentials. Read endpoints are available today;
job-submission (write) endpoints land with the deployment's broker ingress
(CLI side tracked in ludo-omg#1, P4).
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from omg.config import Config


class LudoClient:
    """Thin HTTP client over a deployment's read-only API."""

    def __init__(self, config: Config, *, timeout: float = 30.0) -> None:
        headers = {"Accept": "application/json"}
        if config.token:
            headers["Authorization"] = f"Bearer {config.token}"
        self._http = httpx.Client(base_url=config.api_url, headers=headers, timeout=timeout)

    # ── read surface (Contract A) ──────────────────────────────────────
    def healthz(self) -> dict[str, Any]:
        """Liveness + version of the deployment."""
        r = self._http.get("/healthz")
        r.raise_for_status()
        return r.json()

    def list_sessions(self) -> list[dict[str, Any]]:
        """Recent sessions the deployment exposes."""
        r = self._http.get("/sessions")
        r.raise_for_status()
        return r.json()

    def get_session(self, session_id: str) -> dict[str, Any]:
        """One session's status."""
        r = self._http.get(f"/sessions/{session_id}")
        r.raise_for_status()
        return r.json()

    # ── lifecycle ──────────────────────────────────────────────────────
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> LudoClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
