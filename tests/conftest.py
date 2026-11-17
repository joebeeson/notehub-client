"""Shared environment isolation for the credential-free unit suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_notehub_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a developer token from changing local app or API test behavior."""
    monkeypatch.delenv("NOTEHUB_TOKEN", raising=False)
