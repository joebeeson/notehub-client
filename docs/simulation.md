# Simulating Notecard workflows

`notehub_client.simulate` provides local, explicit Notecard queue workflows and the
Notehub API state they produce. Each run uses an ordinary `NotehubClient` through a
local HTTPX transport. It needs no credentials, network, hardware, or runtime extras.

## Start with a named scenario

```python
from notehub_client import simulate

print(simulate.available())  # ("field_lab", "telemetry", "commands", "environment", "sensor")
scenario = simulate.named("telemetry")
# Equivalent: simulate.Scenario.named("telemetry")
```

The package ships five TOML assets:

| Name | Initial conditions |
| --- | --- |
| `field_lab` | Coastal project, two fleets, three devices, seeded readings, queued Notes and commands, and sensor behaviors |
| `telemetry` | One historical event, one queued outbound reading, and one cloud command |
| `commands` | A cloud command awaiting sync and a previously delivered command |
| `environment` | Project, competing fleet, device, and default environment values |
| `sensor` | Seeded drifting readings, telemetry, and a temperature command |

The four compact examples use project `app:demo` and device `dev:temperature`;
`field_lab` declares its own coastal project and device IDs. Loading returns a fresh,
immutable `Scenario`. Fluent methods such as `with_device()`, `with_event()`,
`with_outbound()`, and `with_inbound(delivered=True)` return new scenarios.

## Run real client workflows

```python
from datetime import timedelta
from notehub_client import filters, simulate


async def example():
    with simulate.named("telemetry").start() as run:
        device = run.device("app:demo", "dev:temperature")
        async with run.client() as client:
            # History is already visible; queued Notes become events at sync.
            before = await client.events.collect("app:demo")
            device.queue_many("temperature.qo", ({"celsius": n} for n in range(20, 23)))
            run.advance(timedelta(minutes=1))
            outcome = device.sync()
            events = await client.events.collect(
                "app:demo",
                filters=filters.devices(device.uid).files("temperature.qo"),
            )
            print(len(before), outcome.sent, len(events))  # 1, 4, 5

            await client.notes.add_qi(device.note("commands.qi"), {"action": "sample"})
            device.sync()
            command = device.receive("commands.qi")
            print(command["body"] if command else None)
```

`queue()` and `queue_many()` use the existing body composition converters, including
`to_note_body()` and registered third-party converters. `queue_many()` checks
that the run is open and the destination ends in `.qo` before pulling any
bodies, even if the input is empty. Generators run in caller order, and Notes
successfully queued before a generator failure remain queued.

`sync()` transfers all pending outbound `.qo` Notes into cloud events, transfers
cloud `.qi` Notes onto the device, records a session, and updates the device's
effective environment. Its `SyncResult` counts transfers. Host firmware behavior
can be expressed by your Python code or a bound device behavior. Transferring a
command does not execute it; an explicit `step()` can handle delivered commands.

`receive(file, delete=False)` peeks at the next delivered Note. The default consumes
it; an empty queue returns `None`. Returned Notes and snapshots are immutable.

`advance()` changes the clock; it never starts a sync. Event IDs, Note IDs,
sessions, and timestamps are deterministic for the same initial conditions and
operations. Opaque cursor tokens are run-local identifiers and should not be
asserted as literal strings.

## Give a device behavior

Each device can have one behavior: a callable conforming to
`notehub_client.typing.Behavior`. Each explicit `step()` supplies an immutable
`StepContext` and applies the returned `StepResult`. A behavior can model several
sensors, commands, or state machines internally.

```python
from datetime import timedelta
from notehub_client import simulate

with simulate.named("sensor").start(seed=42) as run:
    device = run.device("app:demo", "dev:temperature")
    first = device.step()  # Produces readings and queues telemetry.qo.
    device.sync()  # Publishes telemetry and delivers the seeded command.
    run.advance(timedelta(minutes=1))
    response = device.step()  # Handles set_temperature and consumes its command.
    device.sync()  # Publishes the response telemetry.
    assert response.consumed
    assert device.readings == response.readings
```

`run.step()` steps all bound devices in scenario device order and returns an
immutable mapping from `(project_uid, device_uid)` to results. Calling
`device.step()` without a binding raises `ValueError`. Steps neither move the
clock nor synchronize. API reads and `advance()` never invoke behaviors.

`StepContext` includes `now`, a per-device `step` number starting at one,
`project_uid`, `device_uid`, current `readings`, device-visible `environment`, and
FIFO delivered `commands`. Commands include `file`, `body`, and the `note` ID.
Environment is the device defaults before its first sync and the synchronized
environment afterward. Pending cloud commands and cloud environment changes only
become visible to behavior after sync.

`StepResult` contains reading updates, device-local `OutboundNote` descriptions,
and consumed command IDs. Fluent `with_readings()`, `with_note()`, and
`consuming()` return new results. Note bodies use the existing composition
adapters. A result cannot change identity or fleet membership, publish inbound
Notes, or consume commands that have not been delivered. Unconsumed commands
remain available on the next step or through `receive()`.

Reading updates merge into stored device readings and are immediately visible to
client device queries. Notes become cloud events at sync. Initial readings can be
set with `with_device(..., readings={"temperature": 20.0, "voltage": 3.7})`, or a
device's TOML `readings` table. Unspecified measurements are omitted; they are not
invented as zero. Temperature and voltage must be finite numbers. Other readings
may contain JSON values; identity, provisioning, membership, and last activity
remain controlled by the simulation.

### Write a callable model

Bind a **factory** so every run gets its own behavior state:

```python
from collections.abc import Mapping
from typing import Any
from notehub_client import simulate
from notehub_client.simulate.behaviors import StepContext, StepResult
from notehub_client.typing import Behavior


def counter(config: Mapping[str, Any], *, seed: int) -> Behavior:
    count = 0
    increment = int(config.get("increment", 1))

    def sample(context: StepContext) -> StepResult:
        nonlocal count
        count += increment
        return StepResult().with_note("counts.qo", {"count": count})

    return sample


scenario = (
    simulate.Scenario()
    .with_project("app:demo")
    .with_device("app:demo", "dev:counter")
    .with_behavior("app:demo", "dev:counter", counter, config={"increment": 2})
)
with scenario.start(seed=42) as run:
    result = run.device("app:demo", "dev:counter").step()
    assert result.outbound[0].body == {"count": 2}
```

Factories implement `BehaviorFactory(config, *, seed) -> Behavior`; configuration
is a detached, recursively immutable JSON mapping. The seed is derived from the
run seed and device identity using a stable digest. Use a private
`random.Random(seed)` when generating random values. Adding an unrelated device
does not change an existing device's random stream. Fresh runs with the same seed,
initial conditions, behavior implementation, and operations reproduce results.
Factories must return fresh callables; global random generators or shared model
instances defeat run isolation.

A result is validated before any library-owned device state changes. Failed steps
do not consume commands, update readings, or queue Notes. A behavior owns its
private state and must manage its own exceptions; arbitrary user code cannot be
rolled back. If `run.step()` fails on a later device, successful earlier device
steps remain applied. Simulation snapshots expose readings and successful step
counts, not private behavior internals.

See [the runnable thermostat example](../examples/simulation_behaviors.py) for a
callable class that handles commands, models temperature, and generates telemetry.

### Name a factory in TOML or a plugin

Version 1 scenarios accept one `[[behaviors]]` entry per device:

```toml
[[behaviors]]
project_uid = "app:demo"
device_uid = "dev:temperature"
name = "sensor"
config = { temperature = 20.0, voltage = 3.7, drift = 0.1, noise = 0.02 }
```

The built-in `sensor` adds `drift` and uniform noise on each step, queues
`telemetry.qo`, and handles `commands.qi` bodies containing `set_temperature`.
`notefile` selects another outbound `.qo` file. Defaults are temperature 20,
voltage 3.7, drift 0.1, noise 0, and notefile `telemetry.qo`. Recognized commands
reset temperature before noise is added; unrelated commands remain delivered.

Applications and tests can supply names without installing a package:

```python
from notehub_client.simulate.behaviors import BehaviorRegistry

registry = BehaviorRegistry({"counter": counter}, plugins=False)
scenario = scenario.with_device("app:demo", "dev:other").with_behavior(
    "app:demo", "dev:other", "counter", config={"increment": 3}
)
with scenario.start(registry=registry) as run:
    run.step()
```

`register(name, factory)` also returns the registry for chaining. Registries are
isolated objects; registration does not change a process-global catalog. Built-in
names are reserved, duplicate local registration fails, and explicit local names
take precedence over installed plugins. `plugins=False` disables installed plugin
discovery while retaining built-ins and local factories.

Installed packages can advertise a factory in their `pyproject.toml`:

```toml
[project.entry-points."notehub_client.simulate.behaviors"]
"acme.thermostat" = "acme_simulation:thermostat"
```

Reference `name = "acme.thermostat"` in TOML or pass that name to
`with_behavior()`. A default registry discovers installed names, and
`registry.available()` lists names without importing their code. Scenario loading
does not resolve factories; starting a run imports only the selected factory and
invokes it with configuration and a device seed. Missing names, ambiguous installed
names, and non-callable entry points produce explicit errors. Plugin import and
factory exceptions propagate to the caller. Plugins are installed Python code;
TOML names do not evaluate Python expressions or expand environment variables.

`simulate.available()` and `simulate.named()` continue to describe packaged
scenarios. Use a behavior registry for factory discovery.

## Author Python or TOML scenarios

Direct typed construction remains available:

```python
from notehub_client.simulate import Device, Project, QueuedNote, Scenario

scenario = Scenario(
    projects=(Project("app:demo"),),
    devices=(Device("app:demo", "dev:temperature"),),
    outbound=(QueuedNote("app:demo", "dev:temperature", "readings.qo", {"celsius": 20}),),
)
# Fluent equivalent:
scenario = (
    Scenario()
    .with_project("app:demo")
    .with_device("app:demo", "dev:temperature")
    .with_outbound("app:demo", "dev:temperature", "readings.qo", {"celsius": 20})
)
```

TOML uses the same field names and constructors. Unknown fields, duplicate identities,
invalid queue suffixes, naive dates, and missing project/device/fleet references fail
at construction. Bodies and environment values are copied recursively.

```toml
scenario_version = 1
start_time = 2025-01-01T00:00:00Z

[[projects]]
uid = "app:demo"
environment = { SAMPLE_INTERVAL = "300" }

[[devices]]
project_uid = "app:demo"
uid = "dev:temperature"
defaults = { SAMPLE_INTERVAL = "900" }

[[events]]
project_uid = "app:demo"
device_uid = "dev:temperature"
file = "temperature.qo"
body = { celsius = 19 }

[[outbound]]
project_uid = "app:demo"
device_uid = "dev:temperature"
file = "temperature.qo"
body = { celsius = 20 }
```

Use `Scenario.from_toml(path)` or `Scenario.from_mapping(data)` for versioned
documents. `events` means already received history; `outbound` means pending
device Notes; `inbound` means cloud Notes awaiting transfer; `device_inbound`
means already delivered Notes. Queue arrays preserve FIFO order.

Optional `when` and `received` values accept aware TOML datetimes; mapping loading
also accepts ISO strings or Unix seconds. Omitted values use the scenario clock.
Explicit event/Note identifiers are supported. TOML has no null scalar; use Python
construction for bodies containing JSON null.

A pytest fixture can load through `pytest-datadir` without custom loaders:

```python
def test_pending_notes(datadir):
    scenario = Scenario.from_toml(datadir / "sensor.toml")
    with scenario.start() as run:
        assert run.device("app:demo", "dev:temperature").sync().sent == 1
```

Place `sensor.toml` in the directory named after the test module. The project's
`tests/unit/test_simulate/sensor.toml` demonstrates this convention.

## Supply scenarios from your own objects

The structural protocol is `notehub_client.typing.ScenarioSource`:

```python
from notehub_client.simulate.converters import resolve_scenario


class Demo:
    def to_scenario(self) -> Scenario:
        return Scenario.named("commands")


definition = Scenario.from_value(Demo())
# Both explicit consumers also support ScenarioSource:
definition = resolve_scenario(Demo())
run = simulate.Simulation(Demo())
run.close()
```

For types you cannot modify, import `scenario_value` from
`notehub_client.simulate.converters` and register `@scenario_value.register(YourType)`.
The resolver checks the converter result. Mappings must contain
`scenario_version = 1`; names and filesystem paths use the explicit loading
methods.

## Package interface

The package root promotes the common authoring and execution interface:
`Scenario`, `Simulation`, `Project`, `Fleet`, `Device`, `Event`, `QueuedNote`,
`named()`, `available()`, and the `behaviors` module.

Specialized public APIs have explicit submodule imports:

| Need | Public location |
| --- | --- |
| Register/resolve an application scenario source | `simulate.converters.scenario_value`, `resolve_scenario` |
| Describe a fault or annotate a synchronization outcome | `simulate.models.Fault`, `SyncResult` |
| Annotate a live device handle | `simulate.simulation.SimulatedDevice` |
| Integrate HTTPX directly | `simulate.transport.SimulationTransport` |
| Type a structural scenario source | `notehub_client.typing.ScenarioSource` |
| Author a device model and its factory | `notehub_client.typing.Behavior`, `BehaviorFactory` |
| Build effects and register named factories | `simulate.behaviors` |

Ordinary workflows obtain device handles, transports, and outcomes from a run's
methods; their types remain available for integrations without package-root exports.

## TUI Demo and Simulation Lab

Install the `tui` extra and run Demo mode:

```console
pip install "notehub-client[tui] @ git+https://github.com/joebeeson/notehub-client.git"
notehub-client-tui --demo
```

**Demo** fills the ordinary browse views with fixed synthetic records; it does not
connect to Notehub or change those records. The Project picker also lists packaged
scenarios as **Simulation · …** projects. Choose one to make that local run the active
project for the ordinary Overview, Events, Devices, and Fleets views; choosing a live
project switches back to the parked live reader. This works without credentials. Press
**6** or choose **Simulation** to open the lab controls for the same active run.

The lab starts a fresh, stateful run from a packaged scenario. Its default is
`field_lab`; the scenario picker also offers `telemetry`, `commands`, `environment`,
and `sensor`. The lab shows device readings, synthetic events, and outbound, cloud
inbound, and delivered command queues. **Advance 5 min**, **Step behaviors**, and
**Sync device** are separate, explicit actions: advance moves only the simulated
clock, step runs the bound behaviors and queues their results, and sync transfers
the selected device's local queues. None of these actions sends Notehub network
traffic. Sync transfers a command to the simulated device; a later explicit step
can handle it.

### A coastal field-lab walkthrough

1. Open **Simulation** with **6**. Select `field_lab`, then choose
   **BUOY-NORTH-014**.
   The scenario seeds this buoy with one `temperature.qo` reading and an `OPS-482`
   `commands.qi` request.
2. Press **Sync device**. The reading becomes a synthetic event, and the command
   moves into the buoy's delivered queue. This updates only the local run.
3. Press **Step behaviors**. The three sensor models each run once; the north buoy
   applies the requested 13 °C setpoint and queues its next reading. Sync the north
   buoy again to add that reading to the local event history.
4. Press **Advance 5 min** whenever you want to move the scenario clock. It does not
   step a behavior or sync a device; each of those remains a separate button press.

The same lab is also available inside the live TUI workspace. Its simulation
controls remain local; other workspaces in a live session continue to read Notehub.

## Use the web simulation lab

Run `notehub-client web` with the `web` extra, then choose **Open simulation lab**
or use **Simulate** from an authenticated dashboard. Start from a packaged scenario
or load a version 1 TOML file. The lab displays the scenario filename after reload,
uses its declared project and device IDs, and exposes explicit clock, step, sync,
command, fault, reset, and playback controls.

Dashboard reads in simulation mode still use ordinary `NotehubClient` facades, wired
to the local simulation transport. They do not contact Notehub. When a live session
is already open, it remains parked in the same server session and **Return to
Notehub** restores it. Simulation-only sessions can end the lab and return to the
workspace chooser. The live token and uploaded TOML are not stored in browser storage.

## Environment and failure workflows

The device starts with its defaults. After sync, precedence is device override,
fleet, project, then defaults. Competing fleets resolve by case-insensitive fleet
label, with UID breaking equal-label ties. Cloud updates are immediately visible
through client reads; `device.environment` changes at the next explicit sync.

Use normal `client.devices.set_environment(device, values)` and
`delete_environment_variable(device, key)` for device changes. The simulation also
supports GET/PUT/DELETE project/fleet `environment_variables` endpoints through
`client.request()`, since the current project/fleet facades expose reads only.

`run.fail_next("GET", "projects", status_code=429, retry_after="7")` injects one
matching HTTP failure. `status_code=None` injects a connection failure. Existing
client error types and observer events are preserved. Fault paths use the encoded
path relative to `/v1/`; faults are applied only to matching requests.

## Supported API behavior and lifecycle

Projects, fleets, device details/inventory, device sessions/latest events, project
and fleet events, inbound queue Notes, and environment reads/writes are supported.
Event queries support repeated identifiers, comma-separated files, device/fleet/
serial/session/sensor selection, captured/uploaded date ranges, system files,
`since` event IDs, and top-level field projection. Sorting supports captured time,
received time (`modified`), device UID, serial, and best ID. Geolocation sorting,
nested projection, and unmodeled device filters return HTTP 501.

Fleet endpoints always retain their path scope. A `fleetUID` query selects
matching memberships within that scope; it cannot include devices or events
outside the endpoint's fleet. Repeated fleet query values match any listed
fleet, while still requiring membership in the endpoint's fleet.

Event and session cursors belong to one run, endpoint, and query. Start with cursor `"0"`,
then pass the returned cursor with the same query and page size. Numbered pages
and sorting work without cursors. Default event order is insertion order.
Device, project, and session lists support numbered pages.

The simulator retains the latest 4,096 issued cursors per run, shared across
clients and queries. A cursor that has been evicted or belongs to a previous run
returns HTTP 400. Start a new traversal explicitly if the saved cursor is no
longer available.

Use `client.events.iter_pages()` when checkpointing a read. Save a nonempty
`next_cursor` only after handling every event on the page. This includes empty
pages and the terminal page if it provides a cursor. Keep the last checkpoint
if the terminal page has no cursor. Keep the same project,
filters, and page size when resuming. If processing stops before the checkpoint
is saved, the page can replay. Persist event IDs or make processing idempotent
when duplicate delivery matters. Include `event` in `selectFields` if you deduplicate
by event ID. See the
[checkpoint example](../examples/event_checkpoints.py) for a simulation that
replays a page within the same run.

Use `client.devices.iter_session_pages(project_uid, device_uid)` to checkpoint
device sessions the same way. Resume with `pagination=filters.cursor(checkpoint)`
and keep the same filters and page size. Notehub can return an existing session
when it changes, so update your stored record for that session UID. Simulated
syncs append a session record in creation order and leave earlier records
as they were. Use `client.devices.list_sessions(..., pagination=filters.page())`
to fetch a numbered page instead.

Clients share one run's state. Each call to `scenario.start()` creates isolated
state. `run.client()` owns both the ordinary client and injected HTTP client.
Advanced callers can use `run.transport()` with their own `httpx.AsyncClient`;
they own that HTTP client's lifecycle. Every request stays local, regardless of
the injected client's base URL.

Closing a client leaves its run usable. Closing a run invalidates handles and
transports. Use one event loop/thread per run; there is no background scheduler.
The model covers queue and environment workflows; firmware commands, physical
radio behavior, DB Notefile replication, cloud routing, and actual host execution
remain outside its fidelity.

