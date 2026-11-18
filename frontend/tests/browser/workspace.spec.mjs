import { expect, test } from "@playwright/test";

test("a shared session stops both live streams and reload resumes the retained live client", async ({ page, context, request }) => {
  const errors = [];
  const observe = (tab) => {
    tab.on("pageerror", (error) => errors.push(error.message));
    tab.on("response", (response) => {
      if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
    });
  };
  observe(page);
  const counters = async () => (await request.get("/smoke/state")).json();
  const { secret } = await counters();
  await page.goto(`/dashboard#secret=${secret}`);
  await expect(page.locator("#stream-status")).toContainText("Live");
  const other = await context.newPage();
  observe(other);
  await other.goto("/dashboard");
  await expect(other.locator("#stream-status")).toContainText("Live");
  await expect.poll(async () => (await counters()).active).toBe(2);
  const clients = (await counters()).created;

  await page.locator("#open-simulation").click();
  await page.locator("#scenario-start").click();
  await expect(page.locator("#simulation-exit")).toBeVisible();
  await expect(other.locator("#stream-status")).toContainText("workspace changed; reload to resume");
  await expect.poll(async () => (await counters()).active).toBe(0);
  const stopped = (await counters()).calls;
  // A stale EventSource reconnect is terminal and cannot reach the live client.
  const stale = await context.request.get("/api/projects/app%3Abrowser/stream/events?mode=live");
  expect(stale.status()).toBe(204);
  expect((await counters()).calls).toBe(stopped);

  await page.locator("#simulation-exit").click();
  await expect(page.locator("#stream-status")).toContainText("Live");
  await expect(other.locator("#stream-status")).toContainText("workspace changed; reload to resume");
  await expect.poll(async () => (await counters()).active).toBe(1);
  await other.reload();
  await expect(other.locator("#stream-status")).toContainText("Live");
  await expect.poll(async () => (await counters()).active).toBe(2);
  expect((await counters()).created).toBe(clients);
  await page.close();
  await other.close();
  await expect.poll(async () => (await counters()).active).toBe(0);
  expect(errors).toEqual([]);
});
