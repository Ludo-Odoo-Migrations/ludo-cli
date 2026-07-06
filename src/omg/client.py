"""Transport client — talks to the LUDO **gateway** over Contract A (REST + SSE).

The gateway (euroblaze/ludo-gateway) is the single public door in front of the
broker. This client depends only on public HTTP + the vendored contract schemas
(contracts/). No engine import, no NATS, no Odoo credentials. Write commands
(approve / job submit) land in P4 once the gated broker write path is cleared.
"""
# Every method returns parsed JSON (Any); the declared return types document the
# shape. Suppress no-any-return file-wide rather than cast at every call site.
# mypy: disable-error-code="no-any-return"

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from types import TracebackType
from typing import Any, TypeVar

import httpx
from ludo_shared import decode_sse

from omg.config import Config

T = TypeVar("T")

# Retry/backoff (per agentix/docs/contracts-consumer-guide.md). Retry ONLY transient
# failures: connect/timeout (httpx.TransportError) + 429 + 5xx. 4xx (except 429) never retry.
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_BASE = 0.5  # seconds
_RETRY_CAP = 30.0  # seconds


def _transient_status(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _TRANSIENT_STATUS


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, httpx.TransportError) or _transient_status(exc)


def _retry_after(exc: BaseException) -> float | None:
    """Honor a `Retry-After: <seconds>` header on a 429/503, if present + numeric."""
    if isinstance(exc, httpx.HTTPStatusError):
        raw = exc.response.headers.get("Retry-After", "").strip()
        if raw.isdigit():
            return float(raw)
    return None


def _backoff(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with jitter; a server `Retry-After` wins when given."""
    if retry_after is not None:
        return min(_RETRY_CAP, retry_after)
    return min(_RETRY_CAP, _RETRY_BASE * (2**attempt)) + random.uniform(0, _RETRY_BASE)


class LudoClient:
    """Thin HTTP client over the gateway's public API."""

    def __init__(self, config: Config, *, timeout: float = 30.0, max_retries: int = 3) -> None:
        headers = {"Accept": "application/json"}
        if config.token:
            headers["Authorization"] = f"Bearer {config.token}"
        self._http = httpx.Client(base_url=config.api_url, headers=headers, timeout=timeout)
        self._max_retries = max_retries

    def _with_retry(self, fn: Callable[[], T]) -> T:
        """Call `fn`, retrying transient failures with bounded exponential backoff.

        Reads are idempotent, so safe to replay. Future write endpoints (approve/resume, 202)
        MUST send the same Idempotency-Key across retries so a replay can't double-submit.
        """
        for attempt in range(self._max_retries + 1):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 — re-raised unless transient + budget left
                if attempt >= self._max_retries or not _is_transient(exc):
                    raise
                time.sleep(_backoff(attempt, _retry_after(exc)))
        raise AssertionError("unreachable")  # loop either returns or raises

    # ── read surface (Contract A) ──────────────────────────────────────
    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}

        def call() -> Any:
            r = self._http.get(path, params=clean or None)
            r.raise_for_status()
            return r.json()

        return self._with_retry(call)

    def healthz(self) -> dict[str, Any]:
        """Gateway liveness — ``{"ok": true}``."""
        return self._get("/healthz")

    def system_status(self) -> dict[str, Any]:
        """Gateway environment — ``{app_env, broker_mode}``."""
        return self._get("/system/status")

    def list_migrations(self) -> dict[str, Any]:
        """The caller's migrations — ``{"items": [...]}`` (tenant-scoped)."""
        return self._get("/api/v1/migrations")

    def get_migration(self, migration_id: str) -> dict[str, Any]:
        """One migration's detail (404 if out of scope / not found)."""
        return self._get(f"/api/v1/migrations/{migration_id}")

    def stream_events(self, migration_id: str, last_event_id: int | None = None) -> Iterator[tuple[int, str, Any]]:
        """Stream the migration's resumable Contract B SSE.

        Yields ``(seq, type, payload)`` per event; resumes from ``last_event_id``
        (the stream sequence) when given. Ends on ``session_end``.

        Auto-reconnects on a transient drop: re-opens from the last seen ``seq`` via the
        ``Last-Event-ID`` header (the gateway replays only later events; dedupe by ``seq``)
        with bounded exponential backoff. The failure budget resets whenever an event
        arrives, so a long, healthy stream never exhausts it.
        """
        url = f"/api/v1/migrations/{migration_id}/events"
        seq = last_event_id
        failures = 0
        while True:
            headers = {"Accept": "text/event-stream"}
            if seq is not None:
                headers["Last-Event-ID"] = str(seq)
            try:
                with self._http.stream("GET", url, headers=headers, timeout=None) as resp:
                    if resp.is_error:
                        # Streaming body isn't read yet; load it so raise_for_status works
                        # instead of throwing ResponseNotRead.
                        resp.read()
                        resp.raise_for_status()
                    # One canonical SSE codec (vendored ludo_shared). Contract A is SSE
                    # (id:/event:/data:), not NDJSON — see contracts/README.md.
                    for ev_seq, etype, payload in decode_sse(resp.iter_lines()):
                        seq = ev_seq
                        failures = 0  # progress — reset the reconnect budget
                        yield (ev_seq, etype, payload)
                        if etype == "session_end":
                            return
                # Clean close without session_end → treat as a drop and resume below.
            except Exception as exc:  # noqa: BLE001 — re-raised unless transient + budget left
                if not _is_transient(exc) or failures >= self._max_retries:
                    raise
            failures += 1
            time.sleep(_backoff(failures - 1))

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
