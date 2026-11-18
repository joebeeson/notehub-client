import assert from "node:assert/strict";
import test from "node:test";
import { maskSensitive } from "../src/presentation.ts";

test("masks every environment value while retaining names and ordinary record data", () => {
  const source = {
    environment_variables: { MODE: "active" },
    environment_variables_effective: { OTHER: "inherited" },
    environment_variables_env_default: { MODE: "default" },
    body: [{ temperature: 21, authorization: "synthetic-value", environment: { REGION: "local" } }],
  };
  const original = structuredClone(source);
  assert.deepEqual(maskSensitive(source), {
    environment_variables: { MODE: "••••••••" },
    environment_variables_effective: { OTHER: "••••••••" },
    environment_variables_env_default: { MODE: "••••••••" },
    body: [{ temperature: 21, authorization: "••••••••", environment: { REGION: "••••••••" } }],
  });
  assert.deepEqual(source, original);
});
