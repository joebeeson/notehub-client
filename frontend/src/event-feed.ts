import type { Json } from "./presentation";

type EventRecord = Record<string, Json>;
const feedLimit = 100;
const maxDateSeconds = 8.64e12;

export function eventFeedTime(record: EventRecord): number | undefined {
  for (const value of [record.received, record.when]) {
    if (typeof value === "number" && Math.abs(value) <= maxDateSeconds) return value;
  }
  return undefined;
}

export function mergeEventFeed(
  previous: readonly EventRecord[],
  batch: readonly EventRecord[],
): EventRecord[] {
  const records = new Map<string | symbol, EventRecord>();
  for (const record of [...previous, ...batch]) {
    const uid = record.event;
    records.set(typeof uid === "string" && uid.length ? uid : Symbol(), record);
  }
  return [...records.values()].sort((a, b) => {
    const left = eventFeedTime(a) ?? -Infinity;
    const right = eventFeedTime(b) ?? -Infinity;
    return left === right ? 0 : right - left;
  }).slice(0, feedLimit);
}
