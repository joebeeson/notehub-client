"""Replay an interrupted page and resume using a simulated Notehub client."""

import asyncio

from notehub_client import filters, simulate


async def main() -> None:
    """Save each cursor after processing its page and ignore replayed event IDs."""
    scenario = simulate.named("telemetry")
    project = scenario.projects[0].uid
    device = scenario.devices[0].uid
    for celsius in (20, 21):
        scenario = scenario.with_event(project, device, "temperature.qo", {"celsius": celsius})
    checkpoint = "0"
    processed: set[str] = set()

    with scenario.start() as run:
        async with run.client() as first:
            async for page in first.events.iter_pages(
                project, pagination=filters.cursor(checkpoint, page_size=2)
            ):
                processed.add(page["events"][0]["event"])
                print("Stopped after processing one event, before saving its cursor")
                break

        async with run.client() as restarted:
            async for page in restarted.events.iter_pages(
                project, pagination=filters.cursor(checkpoint, page_size=2)
            ):
                for event in page["events"]:
                    uid = event["event"]
                    if uid not in processed:
                        print("Processed", uid)
                        processed.add(uid)
                    else:
                        print("Skipped replay", uid)
                checkpoint = page.get("next_cursor") or checkpoint
            if checkpoint != "0":
                print("Saved the last returned cursor")


if __name__ == "__main__":
    asyncio.run(main())
