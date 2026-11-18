import { expect, test } from "@playwright/test";

const devices = [{ uid: "dev:first" }, { uid: "dev:second" }];
const environment = (uid) => ({
  environment_variables: { MODE: `${uid}-device-value` },
  environment_variables_effective: { REGION: `${uid}-effective-value` },
  environment_variables_env_default: { INTERVAL: `${uid}-default-value` },
});

test("inspector masks values, clears on close, and ignores a late response", async ({ page }) => {
  const unexpected = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let release;
  let delayed = false;
  let requested;
  const requestStarted = new Promise((resolve) => { requested = resolve; });
  const gate = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/session") {
      return route.fulfill({ json: { authenticated: true, initialized: true, has_live_session: true, mode: "live" } });
    }
    if (path.endsWith("/stream/events")) return route.fulfill({ status: 204 });
    if (path === "/api/commands") {
      const { command, args } = route.request().postDataJSON();
      if (command === "projects.list") return route.fulfill({ json: { projects: [{ uid: "app:smoke", label: "Synthetic project" }] } });
      if (command === "devices.list") return route.fulfill({ json: { devices, has_more: false } });
      if (command === "devices.get") return route.fulfill({ json: { uid: args.device_uid } });
      if (command === "devices.sessions") return route.fulfill({ json: { sessions: [] } });
      if (command === "devices.latest") return route.fulfill({ json: { events: [] } });
      if (command === "devices.environment") {
        if (delayed) { requested(); await gate; }
        return route.fulfill({ json: environment(args.device_uid) });
      }
      unexpected.push(command);
    } else unexpected.push(path);
    return route.fulfill({ status: 500, json: { error: { message: "Unexpected smoke request" } } });
  });

  await page.goto("/dashboard/projects/app%3Asmoke/devices");
  const content = page.locator("#detail-content");
  const reveal = page.getByRole("button", { name: "Reveal sensitive values" });
  const hide = page.getByRole("button", { name: "Hide sensitive values" });
  const close = page.getByRole("button", { name: "Close details" });
  const firstValues = Object.values(environment("dev:first")).flatMap(Object.values);

  await page.getByRole("button", { name: "Inspect dev:first", exact: true }).click();
  await expect(reveal).toBeVisible();
  for (const name of ["MODE", "REGION", "INTERVAL"]) await expect(content).toContainText(name);
  for (const value of firstValues) await expect(content).not.toContainText(value);
  await reveal.click();
  for (const value of firstValues) await expect(content).toContainText(value);
  await hide.click();
  for (const value of firstValues) await expect(content).not.toContainText(value);
  await reveal.click();
  await close.click();
  await expect(content).toBeEmpty();

  await page.getByRole("button", { name: "Inspect dev:second", exact: true }).click();
  await expect(reveal).toBeVisible();
  for (const value of Object.values(environment("dev:second")).flatMap(Object.values)) {
    await expect(content).not.toContainText(value);
  }
  await close.click();
  delayed = true;
  await page.getByRole("button", { name: "Inspect dev:first", exact: true }).click();
  await requestStarted;
  await close.click();
  await expect(content).toBeEmpty();
  const response = page.waitForResponse((response) =>
    response.url().endsWith("/api/commands") &&
    response.request().postDataJSON().command === "devices.environment");
  release();
  await (await response).finished();
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(content).toBeEmpty();
  await expect(close).not.toBeVisible();
  const storage = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]));
  for (const device of devices) {
    for (const value of Object.values(environment(device.uid)).flatMap(Object.values)) {
      expect(storage).not.toContain(value);
    }
  }
  expect(unexpected).toEqual([]);
  expect(errors).toEqual([]);
});
