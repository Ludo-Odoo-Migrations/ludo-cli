"""P4 write commands — approve, resume, estimate.

Uses httpx.MockTransport to verify idempotency-key propagation, 409 handling,
and the estimate happy path. Sleep is stubbed so retry paths are instant.
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


# ── approve ──────────────────────────────────────────────────────────────────

def test_approve_sends_idempotency_key() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers.get("Idempotency-Key", ""))
        return httpx.Response(202, json={"accepted": True, "migration_id": "m1", "job_id": "j1"})

    c = _client(httpx.MockTransport(handler))
    result = c.approve("m1")
    assert result["job_id"] == "j1"
    assert seen == ["m1:migrate"]  # auto-generated key


def test_approve_custom_idempotency_key() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers.get("Idempotency-Key", ""))
        return httpx.Response(202, json={"accepted": True, "migration_id": "m1", "job_id": "j2"})

    c = _client(httpx.MockTransport(handler))
    c.approve("m1", idempotency_key="custom-key-123")
    assert seen == ["custom-key-123"]


def test_approve_409_raises() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "another migration is already running for this account"})

    c = _client(httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        c.approve("m1")
    assert exc_info.value.response.status_code == 409


def test_approve_retries_transient_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503)
        return httpx.Response(202, json={"accepted": True, "migration_id": "m1", "job_id": "j3"})

    c = _client(httpx.MockTransport(handler))
    result = c.approve("m1")
    assert result["job_id"] == "j3"
    assert calls["n"] == 2


# ── resume ───────────────────────────────────────────────────────────────────

def test_resume_auto_key() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers.get("Idempotency-Key", ""))
        return httpx.Response(202, json={"accepted": True, "migration_id": "m2", "job_id": "j4"})

    c = _client(httpx.MockTransport(handler))
    result = c.resume("m2")
    assert result["job_id"] == "j4"
    assert seen == ["m2:migrate:resume"]


# ── estimate ─────────────────────────────────────────────────────────────────

def test_create_estimate_happy_path() -> None:
    payload_seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        payload_seen.append(json.loads(req.content))
        return httpx.Response(
            201,
            json={
                "id": "est_abc",
                "combo": "ce",
                "src_version": 15,
                "tgt_version": 18,
                "amount_cents": 120000,
                "currency": "EUR",
            },
        )

    c = _client(httpx.MockTransport(handler))
    result = c.create_estimate("ce", 15, 18)
    assert result["id"] == "est_abc"
    assert payload_seen[0] == {"combo": "ce", "src_version": 15, "tgt_version": 18}
