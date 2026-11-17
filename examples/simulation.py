"""Run the packaged offline telemetry, commands, and environment examples."""

import asyncio
from datetime import timedelta

from notehub_client import filters, simulate


async def main() -> None:
    """Exercise ordinary facade calls against three local scenarios."""
    with simulate.named("telemetry").start() as run:
        device = run.device("app:demo", "dev:temperature")
        async with run.client() as client:
            device.queue_many("temperature.qo", ({"celsius": n} for n in (20, 21)))
            run.advance(timedelta(seconds=30))
            print("Sync:", device.sync())
            readings = await client.events.collect(
                "app:demo", filters=filters.files("temperature.qo")
            )
            print("Readings:", [e["body"] for e in readings])

    with simulate.named("commands").start() as run:
        device = run.device("app:demo", "dev:temperature")
        print("Previously delivered:", device.receive("commands.qi"))
        device.sync()
        print("Newly delivered:", device.receive("commands.qi"))

    with simulate.named("environment").start() as run:
        device = run.device("app:demo", "dev:temperature")
        async with run.client() as client:
            device.sync()
            print("Override:", device.environment)
            await client.devices.delete_environment_variable(device, "SAMPLE_INTERVAL")
            device.sync()
            print("Inherited:", device.environment)


if __name__ == "__main__":
    asyncio.run(main())
