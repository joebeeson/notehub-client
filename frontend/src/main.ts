import "@ui-sdk/web/timeline";
import "@ui-sdk/web/dialog";
import "@ui-sdk/web/drawer";
import "@ui-sdk/web/field";
import "@ui-sdk/web/input";
import "@ui-sdk/web/password-input";
import "@ui-sdk/web/command";
import "@ui-sdk/web/toggle";
import "./style.css";
import "./details.css";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type RecordValue = Record<string, Json>;
type SimulationSnapshot = { now: string; events: RecordValue[]; devices: Record<string, Record<string, RecordValue>> };
type CommandName =
  | "projects.list" | "projects.get" | "fleets.list" | "devices.list" | "devices.get"
  | "devices.sessions" | "devices.latest" | "devices.environment" | "devices.for_fleet"
  | "events.list" | "events.for_fleet" | "routes.list" | "jobs.list" | "monitors.list"
  | "usage.get" | "organizations.list" | "organizations.get"
  | "organizations.balance_history" | "billing_accounts.list" | "billing_accounts.get"
  | "billing_accounts.balance_history";

const app = document.querySelector<HTMLDivElement>("#app")!;
let requestedProject = "";
let simulationControlQueue: Promise<void> = Promise.resolve();
const state: {
  project: string;
  projects: RecordValue[];
  view: string;
  stream?: EventSource;
  events: RecordValue[];
  checkedAt?: number;
  streamError?: string;
  pageNum: number;
  eventCursor: string;
  eventCursors: string[];
  eventFilters: RecordValue;
  nextCursor?: string;
  loadId: number;
  detailId: number;
  mode: "live" | "simulation";
  hasLiveSession: boolean;
  generation: number;
  seed: number;
  scenarioName?: string;
  simulationProjects: { uid: string; label?: string }[];
  simulationNotice: string;
  snapshot?: SimulationSnapshot;
  simulationTimer?: number;
  simulationPlaying: boolean;
  statusTimer?: number;
  simulationProject: string;
  simulationDevice: string;
} = { project: "", projects: [], view: "overview", events: [], pageNum: 1, eventCursor: "0", eventCursors: ["0"], eventFilters: {}, loadId: 0, detailId: 0, mode: "live", hasLiveSession: false, generation: 0, seed: 0, simulationProjects: [], simulationNotice: "", simulationPlaying: false, simulationProject: "", simulationDevice: "" };

const views: { id: string; label: string; command?: CommandName; key?: string }[] = [
  { id: "overview", label: "Command center" },
  { id: "fleets", label: "Fleets", command: "fleets.list", key: "fleets" },
  { id: "devices", label: "Devices", command: "devices.list", key: "devices" },
  { id: "events", label: "Events", command: "events.list", key: "events" },
  { id: "routes", label: "Routes", command: "routes.list" },
  { id: "jobs", label: "Jobs", command: "jobs.list", key: "jobs" },
  { id: "monitors", label: "Monitors", command: "monitors.list" },
  { id: "usage", label: "Usage", command: "usage.get", key: "data" },
  { id: "organizations", label: "Organizations", command: "organizations.list", key: "organizations" },
  { id: "billing", label: "Billing accounts", command: "billing_accounts.list", key: "billing_accounts" },
];

function escape(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!);
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || `Request failed (${response.status})`);
  return body as T;
}

async function command<T extends Json>(name: CommandName, args: RecordValue = {}): Promise<T> {
  return api<T>("/api/commands", { method: "POST", body: JSON.stringify({ command: name, args }) });
}

function showWorkspaceChoice(): void {
  app.innerHTML = '<main class="auth"><div class="eyebrow">LOCAL WORKSPACE</div><h1>Choose how to explore Notehub</h1><p>Connect a Notehub account or open an isolated simulation. The simulation needs no credentials or hardware.</p><button id="workspace-live">Connect to Notehub</button> <button id="workspace-sim">Open simulation lab</button><form id="workspace-token" hidden><ui-field><ui-field-label>Personal Access Token</ui-field-label><input id="token" type="password" required autocomplete="off"/><ui-field-error id="workspace-error"></ui-field-error></ui-field><button>Connect</button></form></main>';
  document.querySelector("#workspace-live")!.addEventListener("click", () => { document.querySelector<HTMLFormElement>("#workspace-token")!.hidden = false; document.querySelector<HTMLInputElement>("#token")!.focus(); });
  document.querySelector("#workspace-sim")!.addEventListener("click", () => { void chooseSimulation(); });
  document.querySelector<HTMLFormElement>("#workspace-token")!.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api("/api/session/token", { method: "POST", body: JSON.stringify({ token: document.querySelector<HTMLInputElement>("#token")!.value }) }); state.hasLiveSession = true; await enter(); }
    catch (error) { document.querySelector("#workspace-error")!.textContent = (error as Error).message; }
  });
}

async function chooseSimulation(): Promise<void> {
  stopSimulationPlayback();
  await simulationControlQueue;
  state.stream?.close();
  state.stream = undefined;
  try {
    const catalog = await api<{ scenarios: { name: string; devices: number; projects: number }[] }>("/api/simulations");
    app.innerHTML = '<main class="auth scenario-picker"><div class="eyebrow">LOCAL SIMULATION</div><h1>Choose a scenario</h1><p>Run a deterministic Notehub workspace with no device, credential, or network access.</p><form id="scenario-form"><ui-field><ui-field-label>Starting point</ui-field-label><select id="scenario-choice">' + catalog.scenarios.map((item) => '<option value="' + escape(item.name) + '">' + escape(item.name) + ' · ' + item.projects + ' projects / ' + item.devices + ' devices</option>').join("") + '</select></ui-field><ui-field><ui-field-label>Random seed</ui-field-label><input id="scenario-seed" type="number" step="1" value="0"/></ui-field><ui-field><ui-field-label>Scenario file <span class="field-optional">Optional · TOML</span></ui-field-label><input id="scenario-file" type="file" accept=".toml,text/plain"/><button id="scenario-file-clear" class="button-secondary" type="button" hidden>Use packaged scenario</button></ui-field><p class="scenario-help">Choose a packaged scenario or add a TOML file. A file uses its declared project and device IDs, and its filename stays with the run.</p><div class="scenario-actions"><button id="scenario-cancel" class="button-secondary" type="button">' + (state.mode === 'simulation' ? 'Return to simulation' : state.hasLiveSession ? 'Return to dashboard' : 'Back') + '</button><button id="scenario-start" type="submit">Start simulation</button></div><p id="scenario-error" role="alert"></p></form></main>';
    document.querySelector("#scenario-cancel")!.addEventListener("click", () => {
      if (state.mode === "simulation") renderSimulationLab();
      else if (state.hasLiveSession) { void enter(); }
      else showWorkspaceChoice();
    });
    document.querySelector<HTMLInputElement>("#scenario-file")!.addEventListener("change", (event) => {
      const hasFile = !!(event.currentTarget as HTMLInputElement).files?.length;
      document.querySelector<HTMLSelectElement>("#scenario-choice")!.disabled = hasFile;
      document.querySelector<HTMLButtonElement>("#scenario-file-clear")!.hidden = !hasFile;
    });
    document.querySelector<HTMLButtonElement>("#scenario-file-clear")!.addEventListener("click", () => {
      document.querySelector<HTMLInputElement>("#scenario-file")!.value = "";
      document.querySelector<HTMLSelectElement>("#scenario-choice")!.disabled = false;
      document.querySelector<HTMLButtonElement>("#scenario-file-clear")!.hidden = true;
    });
    document.querySelector<HTMLFormElement>("#scenario-form")!.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = document.querySelector<HTMLButtonElement>("#scenario-start")!;
      submit.disabled = true;
      submit.textContent = "Starting\u2026";
      try {
        const file = document.querySelector<HTMLInputElement>("#scenario-file")!.files?.[0];
        const seed = Number(document.querySelector<HTMLInputElement>("#scenario-seed")!.value);
        if (!Number.isSafeInteger(seed)) throw new Error("Seed must be a whole number within the safe integer range.");
        const body = file ? { toml: await file.text(), filename: file.name, seed } : { name: document.querySelector<HTMLSelectElement>("#scenario-choice")!.value, seed };
        const started = await api<{ projects: { uid: string; label?: string }[]; devices: { project_uid: string; uid: string }[] }>("/api/simulation/start", { method: "POST", body: JSON.stringify(body) });
        state.simulationNotice = "";
        state.simulationProjects = started.projects;
        state.simulationProject = started.projects[0]?.uid || "";
        state.simulationDevice = started.devices.find((device) => device.project_uid === state.simulationProject)?.uid || "";
        await boot();
      } catch (error) { document.querySelector("#scenario-error")!.textContent = (error as Error).message; }
      finally { submit.disabled = false; submit.textContent = "Start simulation"; }
    });
  } catch (error) {
    app.innerHTML = '<main class="auth"><div class="eyebrow">LOCAL SIMULATION</div><h1>Scenarios unavailable</h1><p role="alert">' + escape((error as Error).message) + '</p><button id="scenario-retry">Try again</button></main>';
    document.querySelector("#scenario-retry")!.addEventListener("click", () => { void chooseSimulation(); });
  }
}

function stopSimulationPlayback(): void {
  state.simulationPlaying = false;
  if (state.simulationTimer !== undefined) window.clearTimeout(state.simulationTimer);
  state.simulationTimer = undefined;
  const button = document.querySelector<HTMLButtonElement>("#simulation-play");
  if (button) button.textContent = "Play";
}

async function leaveSimulation(): Promise<void> {
  stopSimulationPlayback();
  await simulationControlQueue;
  try {
    if (state.hasLiveSession) {
      await api("/api/simulation/stop", { method: "POST" });
      state.mode = "live";
      await enter();
    } else {
      await api("/api/session", { method: "DELETE" });
      location.reload();
    }
  } catch (error) {
    const element = document.querySelector("#simulation-error");
    if (element) element.textContent = (error as Error).message;
  }
}

function simulationAction(action: string, args: Record<string, Json> = {}): Promise<boolean> {
  const execute = async (): Promise<boolean> => {
    try {
      const result = await api<{ generation: number; result: Json; snapshot: SimulationSnapshot }>("/api/simulation/control", { method: "POST", body: JSON.stringify({ action, generation: state.generation, ...args }) });
      state.generation = result.generation; state.snapshot = result.snapshot;
      if (action === "advance") state.simulationNotice = `Advanced the clock by ${Number(args.seconds ?? 60)} seconds.`;
      else if (action === "step") {
        const count = Array.isArray(result.result) ? result.result.length : 0;
        state.simulationNotice = count ? `Stepped ${count} bound device${count === 1 ? "" : "s"}.` : "No device behavior is bound in this project.";
      } else if (action === "sync") state.simulationNotice = "Project devices synchronized.";
      else if (action === "cycle") state.simulationNotice = "Advanced time, stepped bound devices, and synchronized this project.";
      else if (action === "command") state.simulationNotice = "Command queued for the selected device.";
      else if (action === "fault") state.simulationNotice = "One matching API request will receive the queued fault.";
      else if (action === "reset") state.simulationNotice = "Scenario state restored to its starting point.";
      renderSimulationLab();
      return true;
    } catch (error) { const element = document.querySelector("#simulation-error"); if (element) element.textContent = (error as Error).message; }
    return false;
  };
  const result = simulationControlQueue.then(execute, execute);
  simulationControlQueue = result.then(() => undefined, () => undefined);
  return result;
}

function renderSimulationLab(): void {
  const snapshot = state.snapshot;
  if (!snapshot) return;
  const deviceEntries = Object.entries(snapshot.devices).flatMap(([projectUid, devices]) =>
    Object.entries(devices).map(([uid, value]) => ({ projectUid, uid, value })));
  const projectOptions = state.simulationProjects.map((project) => '<option value="' + escape(project.uid) + '"' + (project.uid === state.simulationProject ? ' selected' : '') + '>' + escape(project.label || project.uid) + '</option>').join("");
  const selectedDevices = deviceEntries.filter((device) => device.projectUid === state.simulationProject);
  const hasDevices = selectedDevices.length > 0;
  if (!selectedDevices.some((device) => device.uid === state.simulationDevice)) {
    state.simulationDevice = selectedDevices[0]?.uid || "";
  }
  const deviceRows = selectedDevices.map(({ uid, value }) => {
    const readings = value.readings && typeof value.readings === "object" && !Array.isArray(value.readings)
      ? Object.entries(value.readings) : [];
    const readingRows = readings.length
      ? readings.map(([name, reading]) => '<div class="reading"><span>' + escape(name) + '</span><strong>' + escape(reading) + '</strong></div>').join("")
      : '<p class="simulation-empty">No readings yet. Step this device to create its first sample.</p>';
    const outbound = Array.isArray(value.outbound) ? value.outbound.length : 0;
    const pendingCommands = Array.isArray(value.inbound) ? value.inbound.length : 0;
    const deliveredCommands = Array.isArray(value.device_inbound) ? value.device_inbound.length : 0;
    return '<article class="simulation-device"><div class="device-card-head"><div><div class="eyebrow">DEVICE</div><h3>' + escape(uid) + '</h3></div><span class="device-steps">' + escape(value.steps || 0) + ' steps</span></div><div class="reading-list">' + readingRows + '</div><div class="device-queues"><span title="Outgoing Notecard events">To Notehub<strong>' + outbound + '</strong></span><span title="Commands waiting for device sync">Pending<strong>' + pendingCommands + '</strong></span><span title="Commands already delivered to the device">On device<strong>' + deliveredCommands + '</strong></span></div></article>';
  }).join("");
  const deviceContent = deviceRows || '<div class="simulation-empty-card"><strong>No devices in this project</strong><span>You can still advance the simulation clock. Add a device to enable stepping, syncing, and command queues.</span></div>';
  const projectEvents = snapshot.events.filter((event) => event.app === state.simulationProject);
  const events = projectEvents.slice(-20).reverse().map((event) => '<article class="simulation-event"><div><strong>' + escape(event.file) + '</strong><span>' + escape(event.device) + '</span></div><pre>' + escape(JSON.stringify(event.body, null, 2)) + '</pre></article>').join("");
  const deviceOptions = selectedDevices.map(({ uid }) => {
    return '<option value="' + escape(uid) + '"' + (uid === state.simulationDevice ? ' selected' : '') + '>' + escape(uid) + '</option>';
  }).join("");
  app.innerHTML = '<main class="main simulation-lab"><header class="topbar"><div><div class="eyebrow">SIMULATION / ' + escape(state.scenarioName) + '</div><h1>Scenario workbench</h1></div><div class="simulation-tools"><ui-field><ui-field-label>Project</ui-field-label><select id="simulation-project">' + projectOptions + '</select></ui-field><button id="scenario-change" class="button-secondary">Change scenario</button><button id="simulation-reset" class="button-secondary">Reset</button><button id="simulation-exit" class="button-secondary">' + (state.hasLiveSession ? 'Return to Notehub' : 'End simulation') + '</button></div></header><section class="simulation-clock"><div><div class="eyebrow">SIMULATION CLOCK</div><h2>' + escape(snapshot.now) + '</h2><p>Seed ' + state.seed + ' <span>·</span> Only explicit controls move time or device state.</p></div><div class="simulation-controls"><button id="simulation-advance" class="button-secondary">Advance 1 min</button><button id="simulation-step" class="button-secondary"' + (hasDevices ? '' : ' disabled') + '>Step project</button><button id="simulation-sync" class="button-secondary"' + (hasDevices ? '' : ' disabled') + '>Sync project</button><button id="simulation-play" class="button-primary">' + (state.simulationPlaying ? 'Pause' : 'Play') + '</button></div></section><section class="simulation-layout"><div class="simulation-devices"><div class="section-heading"><div><div class="eyebrow">PROJECT DEVICES</div><h2>Current state</h2></div><span>' + selectedDevices.length + (selectedDevices.length === 1 ? ' device' : ' devices') + '</span></div><div class="record-grid">' + deviceContent + '</div></div><div class="simulation-side"><section class="panel"><div class="section-heading"><div><div class="eyebrow">SYNC OUTPUT</div><h2>Recent events</h2></div><span>' + projectEvents.length + '</span></div>' + (events || '<p class="simulation-empty">Step and sync a device to see its emitted events.</p>') + '</section><section class="panel"><div class="section-heading"><div><div class="eyebrow">DEVICE INPUT</div><h2>Queue a command</h2></div></div>' + (hasDevices ? '' : '<p class="simulation-empty">This project has no device to receive commands.</p>') + '<form id="simulation-command" class="simulation-form"><ui-field><ui-field-label>Device</ui-field-label><select name="device"' + (hasDevices ? '' : ' disabled') + '>' + deviceOptions + '</select></ui-field><ui-field><ui-field-label>Command body</ui-field-label><textarea name="body"' + (hasDevices ? '' : ' disabled') + '>{"set_temperature":22}</textarea></ui-field><button class="button-primary"' + (hasDevices ? '' : ' disabled') + '>Queue command</button></form></section><details class="panel fault-panel"><summary>Inject an API fault</summary><form id="simulation-fault" class="simulation-form"><ui-field><ui-field-label>Method</ui-field-label><select name="method"><option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option></select></ui-field><ui-field><ui-field-label>API path</ui-field-label><input name="path" placeholder="projects" required/></ui-field><ui-field><ui-field-label>Status code</ui-field-label><input name="status" type="number" min="400" max="599" value="500"/></ui-field><button class="button-secondary">Queue one-shot fault</button></form></details><p id="simulation-error" class="simulation-error" role="alert" aria-live="polite"></p></div></section></main>';
  if (state.simulationNotice) {
    const notice = document.createElement("p");
    notice.className = "simulation-notice";
    notice.setAttribute("aria-live", "polite");
    notice.textContent = state.simulationNotice;
    document.querySelector(".simulation-clock")!.insertAdjacentElement("afterend", notice);
  }
  document.querySelector<HTMLSelectElement>("#simulation-project")!.addEventListener("change", (event) => {
    state.simulationProject = (event.currentTarget as HTMLSelectElement).value;
    const first = deviceEntries.find((device) => device.projectUid === state.simulationProject);
    state.simulationDevice = first?.uid || "";
    renderSimulationLab();
  });
  document.querySelector<HTMLSelectElement>("#simulation-command select[name=device]")!.addEventListener("change", (event) => {
    state.simulationDevice = (event.currentTarget as HTMLSelectElement).value;
  });
  document.querySelector("#simulation-advance")!.addEventListener("click", () => { void simulationAction("advance", { seconds: 60 }); });
  document.querySelector("#simulation-step")!.addEventListener("click", () => { void simulationAction("step", { project_uid: state.simulationProject }); });
  document.querySelector("#simulation-sync")!.addEventListener("click", () => { void simulationAction("sync", { project_uid: state.simulationProject }); });
  document.querySelector("#simulation-reset")!.addEventListener("click", () => { void simulationAction("reset"); });
  document.querySelector("#simulation-play")!.addEventListener("click", () => {
    if (state.simulationPlaying) {
      stopSimulationPlayback();
      document.querySelector("#simulation-play")!.textContent = "Play";
      return;
    }
    state.simulationPlaying = true;
    document.querySelector("#simulation-play")!.textContent = "Pause";
    const cycle = async (): Promise<void> => {
      if (!state.simulationPlaying) return;
      if (document.hidden) {
        stopSimulationPlayback();
        const button = document.querySelector("#simulation-play");
        if (button) button.textContent = "Play";
        return;
      }
      const ok = await simulationAction("cycle", { seconds: 60, project_uid: state.simulationProject });
      if (!ok) { stopSimulationPlayback(); return; }
      if (!state.simulationPlaying) return;
      const button = document.querySelector("#simulation-play");
      if (button) button.textContent = "Pause";
      state.simulationTimer = window.setTimeout(() => { void cycle(); }, 1000);
    };
    state.simulationTimer = window.setTimeout(() => { void cycle(); }, 1000);
  });
  document.querySelector("#scenario-change")!.addEventListener("click", () => { void chooseSimulation(); });
  document.querySelector("#simulation-exit")!.addEventListener("click", () => { void leaveSimulation(); });
  document.querySelector<HTMLFormElement>("#simulation-command")?.addEventListener("submit", async (event) => { event.preventDefault(); const form = new FormData(event.currentTarget as HTMLFormElement); try { await simulationAction("command", { project_uid: state.simulationProject, device_uid: String(form.get("device")), note: { file: "commands.qi", body: JSON.parse(String(form.get("body"))) } }); } catch (error) { document.querySelector("#simulation-error")!.textContent = (error as Error).message; } });
  document.querySelector<HTMLFormElement>("#simulation-fault")!.addEventListener("submit", async (event) => { event.preventDefault(); const form = new FormData(event.currentTarget as HTMLFormElement); await simulationAction("fault", { method: String(form.get("method")), path: String(form.get("path")), status_code: Number(form.get("status")) }); });
}

function records(value: Json, key?: string): RecordValue[] {
  const rows = key && value && !Array.isArray(value) && typeof value === "object"
    ? value[key] : value;
  return Array.isArray(rows) ? rows.filter((row): row is RecordValue => !!row && typeof row === "object" && !Array.isArray(row)) : [];
}

function title(row: RecordValue): string {
  return String(row.label || row.name || row.best_id || row.uid || row.job_uid || row.device || row.event || "Record");
}

function route(view = state.view, project = state.project): string {
  const path = ["organizations", "billing"].includes(view)
    ? `/dashboard/account/${view}`
    : `/dashboard/projects/${encodeURIComponent(project)}/${view}`;
  if (view !== "events") return path;
  const query = new URLSearchParams();
  if (state.eventFilters.deviceUID) query.set("device", String(state.eventFilters.deviceUID));
  if (state.eventFilters.files) query.set("file", String(state.eventFilters.files));
  return path + (query.size ? `?${query}` : "");
}

function navigate(view: string, project = state.project): void {
  state.loadId += 1;
  if (project !== state.project) {
    state.eventFilters = {};
    state.events = [];
  }
  state.view = view;
  state.project = project;
  state.pageNum = 1;
  state.eventCursor = "0";
  state.eventCursors = ["0"];
  history.pushState(null, "", route());
  shell();
  loadView();
}

function restoreRoute(): void {
  const parts = location.pathname.split("/").filter(Boolean);
  if (parts[1] === "account" && views.some((view) => view.id === parts[2])) state.view = parts[2];
  if (parts[1] === "projects" && parts[2] && views.some((view) => view.id === parts[3])) {
    const project = decodeURIComponent(parts[2]);
    if (state.projects.some((item) => item.uid === project)) state.project = project;
    state.view = parts[3];
  }
  const query = new URLSearchParams(location.search);
  state.eventFilters = {};
  if (state.view === "events") {
    if (query.get("device")) state.eventFilters.deviceUID = query.get("device")!;
    if (query.get("file")) state.eventFilters.files = query.get("file")!;
  }
}

function maskSensitive(value: Json, reveal = false): Json {
  if (reveal || !value || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((item) => maskSensitive(item));
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key,
    /password|passwd|passphrase|secret|token|credential|private.?key|api.?key|access.?key/i.test(key)
      ? "••••••••" : maskSensitive(item),
  ]));
}

type Favorite = { projectUid: string; deviceUid: string };
const favoriteKey = "notehub-control:favorites:v1";
function favorites(): Favorite[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(favoriteKey) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is Favorite =>
      !!item && typeof item.projectUid === "string" && typeof item.deviceUid === "string").slice(0, 100);
  } catch { return []; }
}
function isFavorite(projectUid: string, deviceUid: string): boolean {
  return favorites().some((item) => item.projectUid === projectUid && item.deviceUid === deviceUid);
}
function setFavorite(projectUid: string, deviceUid: string, enabled: boolean): void {
  const remaining = favorites().filter((item) => item.projectUid !== projectUid || item.deviceUid !== deviceUid);
  if (enabled) remaining.unshift({ projectUid, deviceUid });
  localStorage.setItem(favoriteKey, JSON.stringify(remaining.slice(0, 100)));
}

function shell(): void {
  app.innerHTML = `
    <div class="shell">
      <aside class="rail">
        <div class="brand"><span class="brand-mark">N</span><div><strong>NOTEHUB</strong><small>CONTROL / LOCAL</small></div></div>
        <div class="rail-label">PROJECT</div>
        ${state.projects.length ? '<label class="project-label" for="project">Project</label><select id="project" aria-label="Selected project"></select>' : '<p class="rail-empty">No accessible projects</p>'}
        <nav aria-label="Dashboard views">
          ${[["WORKSPACE", ["overview", "events", "fleets", "devices"]], ["OPERATIONS", ["routes", "jobs", "monitors", "usage"]], ["ACCOUNT", ["organizations", "billing"]]].filter(([group]) => state.projects.length || group === "ACCOUNT").map(([group, ids]) => `<div class="nav-group"><div class="rail-label">${group}</div>${(ids as string[]).map((id) => { const view = views.find((item) => item.id === id)!; return `<a href="${route(id)}" data-view="${id}" aria-current="${id === state.view ? "page" : "false"}" class="nav-link ${id === state.view ? "active" : ""}">${escape(view.label)}</a>`; }).join("")}</div>`).join("")}
        </nav>
        <div class="rail-foot"><span class="status-dot"></span> Local session <button id="logout">Sign out</button></div>
      </aside>
      <main class="main">
        <header class="topbar"><div class="eyebrow">${["organizations", "billing"].includes(state.view) ? "ACCOUNT" : escape(state.project)} <span>/</span> ${escape(state.view.toUpperCase())}</div><div class="top-actions"><button id="open-simulation" class="simulate-entry">Simulate</button><button id="search" aria-label="Search or go to a view">Search or go to… <kbd>Ctrl K</kbd></button><span id="stream-status">● Connecting</span><span id="newest-event">Newest event: —</span><button id="copy-link">Copy link</button><button id="refresh">↻ Refresh</button></div></header>
        <div id="content"></div>
      </main>
    </div>
    <ui-drawer id="detail-drawer" side="right"><ui-drawer-backdrop hidden></ui-drawer-backdrop><ui-drawer-content hidden><ui-drawer-title>Record inspector</ui-drawer-title><ui-drawer-description>Read-only Notehub details</ui-drawer-description><div id="detail-content"></div><ui-drawer-close><button class="dialog-close" aria-label="Close details">Close</button></ui-drawer-close></ui-drawer-content></ui-drawer>
    <ui-dialog id="command-dialog"><ui-dialog-backdrop hidden></ui-dialog-backdrop><ui-dialog-content hidden><ui-dialog-title>Search or go to</ui-dialog-title><ui-dialog-description>Navigate views and projects</ui-dialog-description><ui-command><ui-command-input><input aria-label="Search destinations" placeholder="Search views or projects" /></ui-command-input><ui-command-empty>No destinations found.</ui-command-empty><ui-command-list><ui-command-group><ui-command-group-label>Views</ui-command-group-label>${views.filter((view) => state.projects.length || ["organizations", "billing"].includes(view.id)).map((view) => `<ui-command-item value="view:${view.id}">${escape(view.label)}</ui-command-item>`).join("")}</ui-command-group><ui-command-group><ui-command-group-label>Projects</ui-command-group-label>${state.projects.map((project) => `<ui-command-item value="project:${escape(project.uid)}">${escape(title(project))} · ${escape(project.uid)}</ui-command-item>`).join("")}</ui-command-group></ui-command-list></ui-command></ui-dialog-content></ui-dialog>`;
  const select = document.querySelector<HTMLSelectElement>("#project");
  if (select) {
    select.innerHTML = state.projects.map((p) => `<option value="${escape(p.uid)}" ${p.uid === state.project ? "selected" : ""}>${escape(title(p))}</option>`).join("");
    select.addEventListener("change", () => { localStorage.setItem("notehub:project", select.value); navigate("overview", select.value); startStream(); });
  }
  document.querySelectorAll<HTMLAnchorElement>("[data-view]").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    navigate(link.dataset.view!);
  }));
  const palette = document.querySelector<HTMLElement>("#command-dialog")! as HTMLElement & { open: boolean };
  document.querySelector("#search")!.addEventListener("click", () => { palette.open = true; });
  document.querySelectorAll("ui-command-item").forEach((item) => item.addEventListener("action", () => {
    const value = item.getAttribute("value") || "";
    palette.open = false;
    if (value.startsWith("view:")) navigate(value.slice(5));
    if (value.startsWith("project:")) { const project = value.slice(8); localStorage.setItem("notehub:project", project); navigate("overview", project); startStream(); }
  }));
  document.querySelector("#refresh")!.addEventListener("click", loadView);
  document.querySelector("#open-simulation")!.addEventListener("click", () => { void chooseSimulation(); });
  document.querySelector("#copy-link")!.addEventListener("click", async () => {
    await navigator.clipboard.writeText(location.href);
    const button = document.querySelector("#copy-link")!;
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = "Copy link"; }, 1800);
  });
  document.querySelector("#logout")!.addEventListener("click", async () => { stopSimulationPlayback(); await api("/api/session", { method: "DELETE" }); location.reload(); });
}

function status(): void {
  const el = document.querySelector("#stream-status");
  if (!el) return;
  if (!state.project) { el.textContent = "○ No project stream"; return; }
  const age = state.checkedAt ? Math.round(Date.now() / 1000 - state.checkedAt) : undefined;
  el.textContent = state.streamError ? `● Stream error: ${state.streamError}` : age === undefined ? "● Connecting" : `● Live · checked ${age}s ago`;
  el.classList.toggle("error", !!state.streamError || (age !== undefined && age > 90));
  const newest = document.querySelector("#newest-event");
  const received = Math.max(...state.events.map((event) => Number(event.received || 0)), 0);
  if (newest) newest.textContent = received ? `Newest event: ${new Date(received * 1000).toLocaleTimeString()}` : "Newest event: —";
}

function startStream(): void {
  state.stream?.close();
  state.checkedAt = undefined;
  state.streamError = undefined;
  if (!state.project) { status(); return; }
  const stream = new EventSource(`/api/projects/${encodeURIComponent(state.project)}/stream/events`);
  state.stream = stream;
  stream.addEventListener("batch", (message) => {
    const data = JSON.parse((message as MessageEvent).data) as { events: RecordValue[]; checked_at: number };
    const identity = (event: RecordValue) => String(event.event || JSON.stringify(event));
    const existing = new Set(state.events.map(identity));
    state.events = [...data.events.filter((event) => !existing.has(identity(event))), ...state.events].slice(0, 100);
    state.checkedAt = data.checked_at;
    state.streamError = undefined;
    status();
    if (state.view === "overview") {
      const feed = document.querySelector("#event-feed");
      if (feed) { feed.innerHTML = eventFeed(state.events); bindEventFeed(feed); }
    }
  });
  stream.addEventListener("heartbeat", (message) => { state.checkedAt = JSON.parse((message as MessageEvent).data).checked_at; state.streamError = undefined; status(); });
  stream.addEventListener("error", () => { state.streamError = "reconnecting"; status(); });
  status();
}

function eventFeed(events: RecordValue[]): string {
  if (!events.length) return '<div class="empty">No recent events yet. Monitoring will continue.</div>';
  return `<ui-timeline feed aria-label="Recent Notehub events">${events.slice(0, 18).map((event, index) => {
    const time = Number(event.received || event.when || 0);
    const date = time ? new Date(time * 1000) : null;
    return `<ui-timeline-item value="${escape(event.event || index)}"><ui-timeline-marker></ui-timeline-marker><ui-timeline-connector></ui-timeline-connector><ui-timeline-title>${escape(event.file || event.req || "Event")}</ui-timeline-title><ui-timeline-time><time datetime="${date?.toISOString() || ""}">${date?.toLocaleTimeString() || "Time unknown"}</time></ui-timeline-time><ui-timeline-description>${escape(event.device || event.best_id || "Notehub")} · <button data-event="${index}">Inspect event</button></ui-timeline-description></ui-timeline-item>`;
  }).join("")}</ui-timeline>`;
}

function bindEventFeed(root: Element): void {
  root.querySelectorAll<HTMLButtonElement>("[data-event]").forEach((button) => button.addEventListener("click", () => {
    void showDetail(state.events[Number(button.dataset.event)]);
  }));
}

async function loadOverview(): Promise<void> {
  const content = document.querySelector<HTMLDivElement>("#content")!;
  const loadId = ++state.loadId;
  content.innerHTML = '<div class="loading">Loading project operations…</div>';
  const names: CommandName[] = ["projects.get", "devices.list"];
  const results = await Promise.allSettled(names.map((name) => command<Json>(name, { project_uid: state.project, page_size: 50 })));
  if (loadId !== state.loadId) return;
  const project = results[0].status === "fulfilled" ? results[0].value as RecordValue : {};
  const count = (index: number, key?: string): string => results[index].status === "fulfilled" ? String(records(results[index].value, key).length) : "—";
  const failed = results.filter((result) => result.status === "rejected").length;
  content.innerHTML = `
    <section class="hero"><div><div class="eyebrow">LIVE PROJECT / ${escape(state.project)}</div><h1>${escape(project.label || "Project command center")}</h1><p>Fleet signals, device inventory, route posture, and incoming events in one local view.</p></div><div class="hero-state"><span class="pulse"></span><strong>MONITORING</strong><small>${failed ? `${failed} sources unavailable` : "Read-only / connected"}</small></div></section>
    <section class="metrics" aria-label="Project summary">
      ${[["FLEETS", "View"], ["DEVICES / FIRST PAGE", count(1, "devices")], ["ROUTES", "View"], ["MONITORS", "View"], ["JOBS", "View"]].map(([label, value]) => `<div class="metric"><small>${label}</small><strong>${value}</strong><span>${value === "—" ? "Unavailable" : "Open view for details"}</span></div>`).join("")}
    </section>
    <div class="columns"><section class="panel activity"><div class="panel-head"><div><div class="eyebrow">INCOMING SIGNAL</div><h2>Event activity</h2></div><button data-jump="events">Explore events ↗</button></div><div id="event-feed">${eventFeed(state.events)}</div></section><section class="panel"><div class="panel-head"><div><div class="eyebrow">OPERATIONS MAP</div><h2>Project surfaces</h2></div></div><div class="surface-list">${views.filter((view) => !["overview", "organizations", "billing"].includes(view.id)).map((view) => `<button data-jump="${view.id}"><span>${escape(view.label)}</span><span>↗</span></button>`).join("")}</div><div class="favorites"><div class="eyebrow">ON THIS BROWSER / FAVORITES</div>${favorites().filter((item) => item.projectUid === state.project).map((item) => `<button data-favorite="${escape(item.deviceUid)}">${escape(item.deviceUid)} ↗</button>`).join("") || '<p>No favorite devices in this project yet.</p>'}</div></section></div>`;
  content.querySelectorAll<HTMLButtonElement>("[data-jump]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.jump!)));
  const feed = content.querySelector("#event-feed");
  if (feed) bindEventFeed(feed);
  content.querySelectorAll<HTMLButtonElement>("[data-favorite]").forEach((button) => button.addEventListener("click", async () => {
    const uid = button.dataset.favorite!;
    navigate("devices");
    try { const device = await command<RecordValue>("devices.get", { project_uid: state.project, device_uid: uid }); await showDetail(device); }
    catch { alert("This favorite is unavailable in the selected project."); }
  }));
}

function detailRows(row: RecordValue): string {
  return Object.entries(maskSensitive(row) as RecordValue).map(([key, value]) => `<div class="detail-row"><dt>${escape(key)}</dt><dd>${typeof value === "object" ? `<pre>${escape(JSON.stringify(value, null, 2))}</pre>` : escape(value)}</dd></div>`).join("");
}

async function showDetail(row: RecordValue): Promise<void> {
  const detailId = ++state.detailId;
  const content = document.querySelector<HTMLDivElement>("#detail-content")!;
  const uid = String(row.uid || "");
  content.innerHTML = `<div class="eyebrow">RECORD INSPECTOR</div><h2>${escape(title(row))}</h2>${state.view === "devices" && uid ? `<ui-toggle id="favorite" ${isFavorite(state.project, uid) ? "default-pressed" : ""}><button type="button" aria-label="Favorite ${escape(title(row))}">☆ Favorite on this browser</button></ui-toggle>` : ""}<dl>${detailRows(row)}</dl><div id="related" class="loading">Loading related reads…</div>`;
  const drawer = document.querySelector<HTMLElement>("#detail-drawer")! as HTMLElement & { open: boolean };
  drawer.open = true;
  content.querySelector("#favorite")?.addEventListener("pressedchange", (event) => {
    setFavorite(state.project, uid, (event as CustomEvent<{ value: boolean }>).detail.value);
  });
  const reads: [string, CommandName, RecordValue][] = [];
  if (typeof row.device === "string" && row.device) reads.push(
    ["Source device", "devices.get", { project_uid: state.project, device_uid: row.device }],
  );
  if (state.view === "devices" && uid) reads.push(
    ["Device", "devices.get", { project_uid: state.project, device_uid: uid }],
    ["Sessions", "devices.sessions", { project_uid: state.project, device_uid: uid }],
    ["Latest events", "devices.latest", { project_uid: state.project, device_uid: uid }],
    ["Environment", "devices.environment", { project_uid: state.project, device_uid: uid }],
  );
  if (state.view === "fleets" && uid) reads.push(
    ["Fleet devices", "devices.for_fleet", { project_uid: state.project, fleet_uid: uid, page_size: 50 }],
    ["Fleet events", "events.for_fleet", { project_uid: state.project, fleet_uid: uid }],
  );
  if (state.view === "organizations" && uid) reads.push(
    ["Organization", "organizations.get", { organization_uid: uid }],
    ["Balance history", "organizations.balance_history", { organization_uid: uid }],
  );
  if (state.view === "billing" && uid) reads.push(
    ["Billing account", "billing_accounts.get", { billing_account_uid: uid }],
    ["Balance history", "billing_accounts.balance_history", { billing_account_uid: uid }],
  );
  if (!reads.length) { content.querySelector("#related")?.remove(); return; }
  const results = await Promise.allSettled(reads.map(([, name, args]) => command<Json>(name, args)));
  if (detailId !== state.detailId) return;
  const related = content.querySelector<HTMLDivElement>("#related");
  if (!related) return;
  related.className = "related";
  related.innerHTML = results.map((result, index) => `<section><h3>${escape(reads[index][0])}</h3>${result.status === "fulfilled" ? `<pre>${escape(JSON.stringify(maskSensitive(result.value as Json), null, 2))}</pre>${reads[index][0] === "Environment" ? `<button data-reveal="${index}">Reveal sensitive values</button>` : ""}` : `<p class="error">${escape(result.reason)}</p>`}</section>`).join("");
  related.querySelectorAll<HTMLButtonElement>("[data-reveal]").forEach((button) => button.addEventListener("click", () => {
    const index = Number(button.dataset.reveal);
    const result = results[index];
    if (result.status === "fulfilled") {
      button.previousElementSibling!.textContent = JSON.stringify(result.value, null, 2);
      button.remove();
    }
  }));
}

const columns: Record<string, [string, string][]> = {
  devices: [["best_id", "Device"], ["uid", "UID"], ["serial_number", "Serial"], ["last_activity", "Last activity"]],
  fleets: [["label", "Fleet"], ["uid", "UID"]],
  events: [["received", "Received"], ["device", "Device"], ["file", "File"], ["event", "Event ID"]],
  routes: [["label", "Route"], ["type", "Type"], ["disabled", "Disabled"], ["uid", "UID"]],
  jobs: [["name", "Job"], ["job_uid", "UID"], ["last_run_status", "Last run"], ["created", "Created"]],
  monitors: [["name", "Monitor"], ["source_type", "Source"], ["uid", "UID"]],
  organizations: [["name", "Organization"], ["uid", "UID"]],
  billing: [["name", "Billing account"], ["uid", "UID"]],
};

function cell(row: RecordValue, key: string): string {
  const value = row[key];
  if (key === "received" && typeof value === "number") return escape(new Date(value * 1000).toLocaleString());
  if (key === "disabled" && typeof value === "boolean") return value ? "Disabled" : "Enabled";
  return escape(value ?? "—");
}

function table(rows: RecordValue[], view: string): string {
  const fields = columns[view] || [["uid", "Record"]];
  return `<div class="table-scroll"><table><thead><tr>${fields.map(([, label]) => `<th scope="col">${label}</th>`).join("")}<th scope="col">Details</th></tr></thead><tbody>${rows.map((row, index) => `<tr>${fields.map(([key]) => `<td>${cell(row, key)}</td>`).join("")}<td><button data-row="${index}" aria-label="Inspect ${escape(title(row))}">Inspect ↗</button></td></tr>`).join("")}</tbody></table></div>`;
}

function eventFilterForm(): string {
  return `<form id="event-filters" class="filter-bar"><ui-field><ui-field-label>Device UID</ui-field-label><ui-input><input name="device" value="${escape(state.eventFilters.deviceUID || "")}" placeholder="dev:…" /></ui-input></ui-field><ui-field><ui-field-label>Notefile</ui-field-label><ui-input><input name="file" value="${escape(state.eventFilters.files || "")}" placeholder="sensor.qo" /></ui-input></ui-field><button type="submit">Apply filters</button><button type="button" id="clear-filters">Clear</button></form>`;
}

async function loadResource(): Promise<void> {
  const view = views.find((item) => item.id === state.view)!;
  const content = document.querySelector<HTMLDivElement>("#content")!;
  const loadId = ++state.loadId;
  content.innerHTML = `<div class="loading">Loading ${escape(view.label.toLowerCase())}…</div>`;
  try {
    const result = await command<Json>(view.command!, { project_uid: state.project, page_size: 50, ...(view.id === "devices" ? { page_num: state.pageNum } : {}), ...(view.id === "events" ? { cursor: state.eventCursor, filters: state.eventFilters } : {}) });
    if (loadId !== state.loadId) return;
    const rows = records(result, view.key);
    if (view.id === "events" && result && typeof result === "object" && !Array.isArray(result)) state.nextCursor = String(result.next_cursor || "");
    const hasMore = !!(result && typeof result === "object" && !Array.isArray(result) && result.has_more);
    content.innerHTML = `<section class="section-title"><div><div class="eyebrow">${["organizations", "billing"].includes(view.id) ? "ACCOUNT" : escape(state.project)}</div><h1>${escape(view.label)}</h1><p>${rows.length} record${rows.length === 1 ? "" : "s"} in this response · Select a record to inspect.</p></div></section>
      ${view.id === "events" ? eventFilterForm() : ""}
      ${rows.length ? table(rows, view.id) : `<div class="empty">No records returned for this view.</div>`}
      ${["events", "devices"].includes(view.id) ? `<div class="pager"><span>${view.id === "devices" ? `Page ${state.pageNum}` : `Cursor page ${state.eventCursors.length}`}</span><button id="previous" ${(view.id === "devices" ? state.pageNum : state.eventCursors.length) > 1 ? "" : "disabled"}>Previous</button><button id="next" ${hasMore ? "" : "disabled"}>Next</button></div>` : ""}
      ${view.id === "usage" && !rows.length ? `<div class="panel"><pre>${escape(JSON.stringify(result, null, 2))}</pre></div>` : ""}`;
    content.querySelectorAll<HTMLButtonElement>("[data-row]").forEach((button) => button.addEventListener("click", () => { void showDetail(rows[Number(button.dataset.row)]); }));
    content.querySelector<HTMLFormElement>("#event-filters")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget as HTMLFormElement);
      state.eventFilters = {};
      if (form.get("device")) state.eventFilters.deviceUID = String(form.get("device"));
      if (form.get("file")) state.eventFilters.files = String(form.get("file"));
      state.eventCursors = ["0"];
      state.eventCursor = "0";
      history.pushState(null, "", route());
      loadResource();
    });
    content.querySelector("#clear-filters")?.addEventListener("click", () => { state.eventFilters = {}; state.eventCursors = ["0"]; state.eventCursor = "0"; history.pushState(null, "", route()); loadResource(); });
    content.querySelector("#previous")?.addEventListener("click", () => { if (view.id === "devices") state.pageNum -= 1; else { state.eventCursors.pop(); state.eventCursor = state.eventCursors.at(-1) || "0"; } loadResource(); });
    content.querySelector("#next")?.addEventListener("click", () => { if (view.id === "devices") state.pageNum += 1; else { state.eventCursor = state.nextCursor || state.eventCursor; state.eventCursors.push(state.eventCursor); } loadResource(); });
  } catch (error) {
    if (loadId !== state.loadId) return;
    content.innerHTML = `<div class="error-panel"><h2>Could not load ${escape(view.label)}</h2><p>${escape((error as Error).message)}</p><button id="retry">Retry</button></div>`;
    content.querySelector("#retry")!.addEventListener("click", loadResource);
  }
}

function loadView(): void {
  if (!state.project && !["organizations", "billing"].includes(state.view)) return;
  if (state.view === "overview") void loadOverview(); else void loadResource();
}

async function boot(): Promise<void> {
  const fragment = new URLSearchParams(location.hash.slice(1));
  const secret = fragment.get("secret");
  if (secret) {
    requestedProject = fragment.get("project") || "";
    history.replaceState(null, "", location.pathname + location.search);
    await api("/api/session/bootstrap", { method: "POST", headers: { "X-Launch-Secret": secret } });
  }
  const session = await api<{ authenticated: boolean; has_live_session: boolean; initialized: boolean; mode?: string }>("/api/session");
  state.hasLiveSession = session.has_live_session;
  if (!session.initialized) {
    app.innerHTML = '<div class="error-panel full"><h2>Open the launch URL</h2><p>Use the dashboard URL printed by <code>notehub-client web</code> to start a local session.</p></div>';
    return;
  }
  if (session.mode === "simulation") {
    const current = await api<{ scenario: string | null; label: string | null; live_session: boolean; seed: number; generation: number; projects: { uid: string; label?: string }[]; devices: { project_uid: string; uid: string }[]; snapshot: SimulationSnapshot }>("/api/simulation");
    state.mode = "simulation"; state.scenarioName = current.label || current.scenario || "Scenario";
    state.hasLiveSession = current.live_session;
    state.seed = current.seed; state.generation = current.generation; state.snapshot = current.snapshot;
    state.simulationProjects = current.projects;
    state.simulationProject = current.projects[0]?.uid || "";
    state.simulationDevice = current.devices.find((device) => device.project_uid === state.simulationProject)?.uid || "";
    renderSimulationLab();
    return;
  }
  if (!session.authenticated) { showWorkspaceChoice(); return; }
  await enter();
}

async function enter(): Promise<void> {
  app.innerHTML = '<div class="loading full">Connecting to Notehub…</div>';
  try {
    const result = await command<Json>("projects.list", { page_size: 100 });
    state.projects = records(result, "projects");
    const preferred = requestedProject || localStorage.getItem("notehub:project") || "";
    state.project = state.projects.find((project) => project.uid === preferred)?.uid as string || state.projects[0]?.uid as string || "";
    restoreRoute();
    if (!state.project && !["organizations", "billing"].includes(state.view)) state.view = "organizations";
    if (location.pathname === "/dashboard" || !state.project) history.replaceState(null, "", route());
    shell(); startStream(); loadView();
    if (state.statusTimer === undefined) state.statusTimer = window.setInterval(status, 5000);
  } catch (error) { app.innerHTML = `<div class="error-panel full"><h2>Could not load projects</h2><p>${escape((error as Error).message)}</p><button id="retry">Retry</button></div>`; document.querySelector("#retry")!.addEventListener("click", enter); }
}

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    const palette = document.querySelector<HTMLElement>("#command-dialog") as (HTMLElement & { open: boolean }) | null;
    if (palette) palette.open = true;
  }
});
window.addEventListener("popstate", () => {
  const previousProject = state.project;
  restoreRoute();
  if (previousProject !== state.project) { state.events = []; startStream(); }
  shell();
  loadView();
});
void boot().catch((error) => { app.innerHTML = `<div class="error-panel full"><h2>Session unavailable</h2><p>${escape((error as Error).message)}</p><p>Reopen the launch URL printed by the web command.</p></div>`; });
