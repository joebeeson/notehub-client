from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

from notehub_client import NotehubClient
from notehub_client.filters import EventFilters

if TYPE_CHECKING:
    from notehub_client.typing.query import QueryValue


@dataclass(frozen=True, slots=True)
class FleetFilter:
    """Application-defined filters can implement the structural protocol."""

    fleet_uids: tuple[str, ...]

    def to_query_params(self) -> dict[str, QueryValue]:
        return {"fleetUID": self.fleet_uids}


@pytest.mark.asyncio
@respx.mock
async def test_custom_filter_and_array_values_reach_httpx_as_repeated_query_keys() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/events").mock(
        return_value=httpx.Response(200, json={"events": [], "has_more": False})
    )
    async with NotehubClient("pat") as client:
        await client.events.list(
            "app:test",
            filters=FleetFilter(("fleet:one", "fleet:two")),
            deviceUID=("dev:one", "dev:two"),
        )

    query = route.calls[0].request.url.params
    assert query.get_list("fleetUID") == ["fleet:one", "fleet:two"]
    assert query.get_list("deviceUID") == ["dev:one", "dev:two"]


@pytest.mark.asyncio
@respx.mock
async def test_filter_parameter_collisions_are_rejected_before_request() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/events")
    async with NotehubClient("pat") as client:
        with pytest.raises(ValueError, match="specified twice"):
            await client.events.list(
                "app:test", filters=EventFilters(device_uids=("dev:1",)), deviceUID="dev:2"
            )
    assert not route.called
