# Python examples

Run these from the repository root. Every example uses local data and runs
without a Notehub token or connected device.

| Start here if you want to… | Command | What to look for |
| --- | --- | --- |
| Try ordinary client calls against a simulator | `uv run python examples/simulation.py` | Queued readings appear after sync, commands arrive on sync, and removing a device override reveals the inherited value. |
| Resume an event read after an interruption | `uv run python examples/event_checkpoints.py` | A second consumer replays a page, skips the processed event, and saves the cursor after handling the page. |
| Model a device that reacts to commands | `uv run python examples/simulation_behaviors.py` | A thermostat receives a new target and produces three readings as its clock and behavior advance. |
| Run a controller that reacts to incoming events | `uv run python examples/hosted_irrigation.py` | A hosted component queues a pump command, emits an application event, and shows delivery and application as separate steps. |
| Decode historical payloads into a current Python type | `uv run --extra validate python examples/payload_catalog/readings.py` | A catalog selects the older Fahrenheit contract, the decoder upgrades it to Celsius, and sample validation runs separately. |

The [simulation guide](../docs/simulation.md) explains the clock, step, and sync
operations. See [hosting](../docs/hosting.md) for component ownership and
[payload catalogs](../docs/payload-catalog.md) for the TOML and AsyncAPI artifacts.

