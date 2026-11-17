# Host application components

`notehub_client.hosting.ComponentHost` gives an application-owned async callable
a managed lifetime, a supplied event iterator, the existing Notehub client and
payload decoder, and an awaited output sink. The application keeps its settings,
domain state, and decisions. A component can coordinate a device, fleet, or
larger system.

## Run one controller

```python
from notehub_client import hosting


async def controller(context: hosting.ComponentContext) -> None:
    async for event in context.events:
        if should_stop_pump(event):
            await context.client.notes.add_qi(
                context.scope.project_uid,
                "dev:pump",
                "commands.qi",
                {"action": "stop"},
            )
            await context.emit(PumpStopRequested("dev:pump"))


await hosting.ComponentHost(client, observer=observer).run(
    controller,
    name="irrigation",
    scope=hosting.ComponentScope(project_uid="app:farm", fleet_uid="fleet:east"),
    events=client.events.iter("app:farm"),
    emit=application_event_sink,
)
```

Configured callable objects work the same way. Put persistent application state
and loaded configuration on the controller instance; the host reuses that object
and calls it once per run. The host puts scope metadata on emitted
`ComponentEmission` records but does not filter inputs or automatically add
device identity to payloads.

`context.events` is the single iterator acquired from the provided source. It is
pull based and preserves source ordering and event identity. The run owns and
closes that iterator on completion, failure, or cancellation; it does not close
the client or services behind the source. Each run needs a distinct iterator.
Sharing one iterator does not broadcast events. `client.events.iter(...)` is a
finite paginated history traversal; continuous delivery requires an adapter or
source supplied by the application.

Use `context.payloads.decode(event, as_type=YourType)` to apply the client’s
configured catalog, cattrs bindings, and upgrades. Decoding remains explicit.
Use normal client operations for commands; emitted application events are
delivered to the supplied sink and are not Notehub event records.

## Lifetimes and concurrent controllers

`context.spawn(coro, name=...)` starts a managed child. Child failure follows
`asyncio.TaskGroup` behavior and propagates with its original exception. When
the component returns normally, the host cancels and awaits its remaining managed
children. Caller cancellation also cancels those children and closes the event
iterator. Child cleanup may still emit while the run is shutting down; emitting
or spawning after the run closes raises `RuntimeError`.

One `run()` call hosts one component. Compose runs with a caller-owned
`asyncio.TaskGroup` and supply a separate event iterator to each:

```python
async with asyncio.TaskGroup() as tasks:
    tasks.create_task(host.run(water_controller, ...))
    tasks.create_task(host.run(pump_controller, ...))
```

Provide the same observer to the client and host to see request, iteration, and
component lifecycle activity in one diagnostics stream. Observer callbacks are
best effort. Component, source, client, and output sink failures propagate to
the caller. Emission awaits the sink directly, so the sink provides backpressure;
concurrent child emissions may overlap and the sink should serialize them if
needed.

## Local irrigation example

Run `uv run python examples/hosted_irrigation.py` for a credential-free example
that binds water-level payloads to a dataclass, filters project events by sensor,
file, and fleet, queues a pump command once at a high-water threshold, emits an
application event, and then explicitly synchronizes and steps a simulated pump.
Command queueing, delivery, and simulated application are shown as separate
actions. The example controller and pump policy are ordinary user code.
