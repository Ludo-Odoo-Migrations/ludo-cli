"""Transport client — talks to a LUDO deployment over Contract A (REST).

Depends only on public HTTP + the vendored contract schemas (contracts/).
No engine import; no Odoo credentials. Read endpoints are available today;
job-submission (write) endpoints land with the deployment's broker ingress
(CLI side tracked in ludo-omg#1, P4).
"""
# Every method returns parsed JSON (Any); the declared return types document the
# shape. Suppress no-any-return file-wide rather than cast at 14 call sites.
# mypy: disable-error-code="no-any-return"

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
    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        r = self._http.get(path, params=clean or None)
        r.raise_for_status()
        return r.json()

    def healthz(self) -> dict[str, Any]:
        """Liveness + version of the deployment."""
        return self._get("/healthz")

    def list_sessions(self) -> list[dict[str, Any]]:
        """Recent sessions the deployment exposes."""
        return self._get("/sessions")

    def get_session(self, session_id: str) -> dict[str, Any]:
        """One session's status."""
        return self._get(f"/sessions/{session_id}")

    # blueprints
    def blueprints(self) -> list[str]:
        """Blueprint keys the deployment has stored."""
        return self._get("/blueprints")

    def blueprint(self, session_id: str) -> dict[str, Any]:
        """One session's blueprint."""
        return self._get(f"/blueprints/{session_id}")

    # wiki
    def wiki_list(self, category: str) -> list[str]:
        """List wiki pages in a category."""
        return self._get("/wiki", {"category": category})

    def wiki_page(self, path: str) -> dict[str, Any]:
        """Read one wiki page (frontmatter + sections)."""
        return self._get("/wiki/page", {"path": path})

    def wiki_lint(self) -> dict[str, Any]:
        """Orphan-page lint result."""
        return self._get("/wiki/lint")

    # knowledge
    def knowledge_catalogue(self, pattern_id: str | None = None) -> dict[str, Any]:
        """The error catalogue, or one pattern in detail."""
        return self._get(f"/knowledge/catalogue/{pattern_id}" if pattern_id else "/knowledge/catalogue")

    def knowledge_renames(self) -> dict[str, Any]:
        """Rename-map coverage per version pair."""
        return self._get("/knowledge/renames")

    def knowledge_stats(self, sessions: int = 20) -> dict[str, Any]:
        """Catalogue + rename + novel-error stats."""
        return self._get("/knowledge/stats", {"sessions": sessions})

    def knowledge_trajectories_search(self, query: str, k: int = 3, only_resolved: bool = True) -> dict[str, Any]:
        """Similarity search over past trajectories."""
        return self._get(
            "/knowledge/trajectories/search",
            {"query": query, "k": k, "only_resolved": str(only_resolved).lower()},
        )

    def knowledge_advise(self, error: str, failed_tool: str | None = None) -> dict[str, Any]:
        """Advisory for an error from past resolutions."""
        return self._get("/knowledge/advise", {"error": error, "failed_tool": failed_tool})

    # surprises
    def surprises(self, customer_id: str | None = None) -> dict[str, int]:
        """Intervention-type summary across sessions."""
        return self._get("/surprises", {"customer_id": customer_id})

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
