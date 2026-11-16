"""Structural request seam used by stateless domain facades."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from ..typing.json import JSONValue
from ..typing.query import QueryValue


@runtime_checkable
class RequestClient(Protocol):
    """Minimum request interface required by resource facades."""

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
        json: JSONValue = None,
        data: str | bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JSONValue:
        """Send a request and return its decoded JSON value."""
        ...


__all__ = ["RequestClient"]
