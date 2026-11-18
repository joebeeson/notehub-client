import assert from "node:assert/strict";
import test from "node:test";
import { eventFeedTime, mergeEventFeed } from "../src/event-feed.ts";

test("replaces events by UID across and within batches without duplicating a replay", () => {
  const original = { event: "event-a", received: 10, body: { status: "pending" } };
  const updated = { event: "event-a", received: 10, body: { status: "active" } };
  const final = { event: "event-a", received: 10, body: { status: "resolved" } };
  const newer = { event: "event-b", received: 20 };
  const previous = [newer, original];
  const batch = [updated, newer, final];

  const merged = mergeEventFeed(previous, batch);
  assert.deepEqual(merged, [newer, final]);
  assert.deepEqual(mergeEventFeed(merged, batch), merged);
  assert.deepEqual(previous, [newer, original]);
});

test("orders by event time and keeps distinct records without UIDs", () => {
  const captureOnly = { when: 15 };
  const otherCapture = { when: 15 };
  const received = { event: "event-a", received: 10, when: 90 };
  const undated = { body: { temperature: 19 } };
  const merged = mergeEventFeed([received, undated], [captureOnly, otherCapture]);

  assert.deepEqual(merged, [captureOnly, otherCapture, received, undated]);
  assert.equal(eventFeedTime({ received: "invalid", when: 0 }), 0);
  assert.equal(eventFeedTime({ received: 1e20 }), undefined);
});

test("retains the 100 newest records across catch-up batches", () => {
  const events = Array.from({ length: 150 }, (_, received) => ({ event: String(received), received }));
  const previous = mergeEventFeed([], events.slice(0, 100));
  const merged = mergeEventFeed(previous, events.slice(100));

  assert.deepEqual(merged, events.slice(-100).reverse());
});
