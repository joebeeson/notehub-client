"""Authentication value validation."""

from __future__ import annotations

import re

__all__ = ["validate_bearer_token"]

_BEARER_TOKEN = re.compile(r"[A-Za-z0-9\-._~+/]+=*")


def validate_bearer_token(value: object) -> str:
    """Return a valid Bearer token or raise ``ValueError``.

    Validation follows the Bearer token character grammar accepted by the
    Notehub client. The token is returned unchanged.
    """
    if not isinstance(value, str) or _BEARER_TOKEN.fullmatch(value) is None:
        raise ValueError("Bearer token contains invalid characters")
    return value
