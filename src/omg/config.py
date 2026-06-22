"""CLI configuration — the deployment endpoint + auth token.

The transport-only CLI knows only *where* a LUDO deployment is and *how* to
authenticate to it. It never holds Odoo credentials (those live in the
deployment) and imports no engine code.

Resolution order (per field): environment variable, else default.
  LUDO_API_URL    base URL of the deployment's read-only API (Contract A)
  LUDO_API_TOKEN  bearer token for that deployment (optional in dev)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# House rule: address deployments by the loopback alias, never localhost.
DEFAULT_API_URL = "http://10.0.99.1:8000"


@dataclass(frozen=True)
class Config:
    """Resolved CLI config — endpoint + optional bearer token."""

    api_url: str
    token: str | None


def load_config() -> Config:
    """Resolve config from the environment, falling back to defaults."""
    return Config(
        api_url=os.environ.get("LUDO_API_URL", "").strip() or DEFAULT_API_URL,
        token=os.environ.get("LUDO_API_TOKEN", "").strip() or None,
    )
