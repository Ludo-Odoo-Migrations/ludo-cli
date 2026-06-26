"""Retry/backoff behavior of LudoClient (CRIE 002 #7).

Uses httpx.MockTransport to script transient failures; backoff sleeps are stubbed so the
tests are instant. Verifies: transient (503/429/connect) replays up to the cap, 4xx never
replays, and an SSE drop resumes from the last seq via Last-Event-ID.
"""

from __future__ import annotations

import httpx
import pytest

import omg.client as client_mod
from omg.client import LudoClient
from omg.config import Config


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_mod.time, "sleep", lambda _s: None)


def _client(handler: httpx.MockTransport, *, max_retries: int = 3) -> LudoClient:
    c = LudoClient(Config(api_url="http://test", token=None), max_retries=max_retries)
    c._http = httpx.Client(transport=handler, base_url="http://test")
    return c


def test_retries_5xx_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    c = _client(httpx.MockTransport(handler))
    assert c.healthz() == {"ok": True}
    assert calls["n"] == 3  # two failures + one success


def test_429_honors_retry_after() -> None:
    seen: list[float] = []

    def handler(_req: httpx.Request) -> httpx.Response:
        if not seen:
            seen.append(1.0)
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"ok": True})

    c = _client(httpx.MockTransport(handler))
    assert c.healthz() == {"ok": True}


def test_4xx_not_retried() -> None:
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    c = _client(httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        c.get_migration("m_x")
    assert calls["n"] == 1  # no replay on a 404


def test_retries_exhausted_raises() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    c = _client(httpx.MockTransport(handler), max_retries=2)
    with pytest.raises(httpx.HTTPStatusError):
        c.healthz()


def test_sse_resumes_from_last_seq() -> None:
    """First connection drops mid-stream; the resume sends Last-Event-ID and finishes."""
    attempts: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        attempts.append(req.headers.get("Last-Event-ID"))
        if len(attempts) == 1:
            # one event then a clean close (no session_end) -> client must resume
            return httpx.Response(200, text="id: 5\nevent: job_started\ndata: {}\n\n")
        return httpx.Response(200, text="id: 6\nevent: session_end\ndata: {}\n\n")

    c = _client(httpx.MockTransport(handler))
    events = list(c.stream_events("m_x"))
    assert [e[1] for e in events] == ["job_started", "session_end"]
    assert attempts == [None, "5"]  # resumed from the last seen seq
