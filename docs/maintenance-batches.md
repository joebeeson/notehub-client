# Maintenance batches

Use the source TODOs as entry points and the checks below as the handoff. Take
one implementation slice at a time and preserve unrelated work in the checkout.
Browser smoke and terminal detail pagination can proceed independently. The
reliability and public API batches start with design review because they affect
caller-visible contracts.

## 1. Browser smoke and operator walkthroughs

[Frontend smoke checklist](../frontend/README.md) · [Web API seams](web-api-seams.md)

- **Inspector harness: implemented**. `npm run test:browser --prefix frontend`
  builds and serves the production bundle with synthetic API responses. Chromium
  verifies environment masking, reveal/hide, drawer closure, delayed responses,
  and browser storage. It stays separate from the fast Node tests.
- **Shared-session workflow: implemented**. The separate
  `npm run test:browser:session --prefix frontend` command uses real session
  routes and a synthetic upstream. Two tabs verify live-read cancellation,
  stopped-stream status, terminal stale reconnects, and client reuse plus fresh
  streaming after returning to live mode and reloading the second tab.
- **Walkthroughs** (`web-workflow-docs`). Once the behavior is verified, document
  opening a simulation, returning to a retained live session, and ending a
  simulation-only session. Use tracked screenshots for the steps that benefit
  from them. Check that captures contain only synthetic data.

## 2. Fleet detail pagination

[Terminal pagination follow-up](../src/README.md#ownership-and-testing) · [Terminal guide](tui.md)

- **Fleet devices: implemented**. Numbered Previous/Next navigation reuses the
  detail worker's stale-result checks. Refresh retains the displayed page,
  and returning to a fleet restores its last successful member-device page.
- **Fleet events: implemented**. Reuses bounded cursor history scoped by
  project, fleet, and query. Previous and retained Next pages avoid upstream
  reads; empty pages with a continuation can advance. Refresh validates the
  replacement before discarding usable history, including top-level Events.
- Textual Pilot covers fleet changes, responses arriving after cancellation,
  terminal pages, filtered reads, malformed refreshes, and event navigation at
  80 by 24. Physical terminal rendering remains a separate manual check.

## 3. Portable artifacts and simulation examples

[Catalog exports](../src/notehub_client/catalog/__init__.py) · [Simulation scenarios](../src/notehub_client/simulate/__init__.py) · [Behavior implementation](../src/notehub_client/simulate/behaviors.py)

- **Catalog export: implemented**. The pure `export_artifacts` bundle follows the
  [export design](catalog-export-design.md), with public exports and in-memory
  and explicit file-writing examples. Tests cover selector scalars, recursive
  reference relocation, deterministic output, and semantic round trips. Storage
  convenience APIs remain deferred; converters stay application-owned.
- **Scenario improvements**. Pick a workflow with a specific operator decision
  and show the device or service state that verifies it. Use a fixed seed and
  local transport. Reuse existing fixture coverage for scenario names and
  compare the sequence of meaningful outcomes across repeated runs.
- **Behavior module split**. Assess after the scenario changes reveal whether
  independent responsibilities exist. Preserve the public `simulate.behaviors`
  imports and verify existing packaged scenario references if files move.

## 4. Reliability policies

[OAuth exchange](../src/notehub_client/oauth.py) · [Hosted component runtime](../src/notehub_client/hosting/runtime.py)

- **OAuth cooldown** (`oauth-backoff`). Decide which transient exchange
  failures should delay queued callers and how callers recover. Preserve
  default behavior, cancellation, and the rejection of invalid tokens. Verify
  with a fake clock and concurrent callers. Keep response bodies and
  credentials out of logs and diagnostics.
- **Slow hosted shutdown** (`hosting-shutdown`). Decide what diagnostic to
  emit while waiting for child cleanup or source close. Preserve structured
  ownership and primary-error precedence. Use controlled gates to prove the
  diagnostic appears while the host still owns pending work and that it leaves
  the borrowed client usable.

## 5. Public API and contributor tooling review

[Package exports](../src/notehub_client/__init__.py) · [Wire types](../src/notehub_client/typing/wire.py) · [Resource facades](../src/notehub_client/resources/__init__.py) · [Just recipes](../justfile)

- **Package exports**. Inventory direct imports, star imports, documentation,
  and type-checker usage of `constants` and `typing`. Decide any public-surface
  change explicitly and preserve documented submodule imports.
- **Monitor wire aliases**. Extract the aggregate, routing, condition, or
  source types when a second caller or an editor experience justifies a name.
  Keep the accepted wire values and optional keys intact.
- **Facade construction**. Bring a concrete caller or maintenance problem to
  the review before proposing descriptors, decorators, or mixins. Compare
  type discovery, injected transports, and the lifetime of the owning client.
- **Just recipe repetition**. Change the wrappers only if the result improves
  discoverability or fixes argument forwarding. Verify defaults, flags with
  spaces, and the documented Windows and CI setup paths before adopting a
  shared recipe.
