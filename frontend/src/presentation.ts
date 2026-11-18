export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

const MASK = "••••••••";
const environmentMaps = new Set([
  "environment",
  "environment_variables",
  "environment_variables_effective",
  "environment_variables_env_default",
]);
const credentialName = /authorization|password|passwd|passphrase|secret|token|credential|private.?key|api.?key|access.?key/i;

export function maskSensitive(value: Json): Json {
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map(maskSensitive);
  return Object.fromEntries(Object.entries(value).map(([key, item]) => {
    if (environmentMaps.has(key.toLowerCase())) {
      const masked = item !== null && typeof item === "object" && !Array.isArray(item)
        ? Object.fromEntries(Object.keys(item).map((name) => [name, MASK]))
        : MASK;
      return [key, masked];
    }
    return [key, credentialName.test(key) ? MASK : maskSensitive(item)];
  }));
}
