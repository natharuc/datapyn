import assert from "node:assert/strict";
import {test} from "node:test";
import worker from "../src/index.ts";
import {validateBatch, readBatch} from "../src/schema.mjs";

const event = {event: "connection_recovery", version: "1.0.13", platform: "windows", db_type: "sqlserver",
  status: "ready", error_code: "none", duration_ms: 15, attempt: 1, rows_bucket: "none"};
const batch = {schema_version: 1, events: [event]};
function fixture(allowed = true) {
  const points = [], keys = [];
  const env = {EVENTS: {writeDataPoint: point => points.push(point)}, INGEST_LIMIT: {limit: async ({key}) => {keys.push(key); return {success: allowed};}}};
  return {env, points, keys};
}
const request = (value = batch, headers = {}) => new Request("https://telemetry.example.com/v1/events", {
  method: "POST", headers: {"Content-Type": "application/json", ...headers}, body: JSON.stringify(value),
});

test("accepts a bounded desktop batch and stores only known aggregate dimensions", async () => {
  const {env, points, keys} = fixture();
  const response = await worker.fetch(request(batch, {"CF-Connecting-IP": "192.0.2.1"}), env);
  assert.equal(response.status, 204);
  assert.deepEqual(points, [{indexes: ["sqlserver"], blobs: ["connection_recovery", "1.0.13", "windows", "sqlserver", "ready", "none", "none"], doubles: [15, 1]}]);
  assert.deepEqual(keys, ["192.0.2.1"]);
  assert.equal(JSON.stringify(points).includes("192.0.2.1"), false);
});

test("rejects a whole batch containing SQL, paths, tokens or unknown source fields", async () => {
  for (const name of ["sql", "password", "username", "host", "file", "error", "rows", "installation_id"]) {
    const {env, points} = fixture();
    const response = await worker.fetch(request({schema_version: 1, events: [event, {...event, [name]: "private-data"}]}), env);
    assert.equal(response.status, 400); assert.deepEqual(points, []);
    assert.equal((await response.text()).includes("private-data"), false);
  }
});

test("rejects uncontrolled categories and malformed numerical dimensions", () => {
  for (const change of [{db_type: "private-server"}, {version: "private-machine"}, {status: "secret"}, {error_code: "secret"},
    {duration_ms: Infinity}, {duration_ms: -1}, {attempt: 1.5}, {attempt: 11}, {rows_bucket: "salary"}]) {
    assert.throws(() => validateBatch({schema_version: 1, events: [{...event, ...change}]}));
  }
  for (const value of [null, {}, {schema_version: 2, events: [event]}, {...batch, token: "private"}, {schema_version: 1, events: []},
    {schema_version: 1, events: Array.from({length: 51}, () => event)}]) assert.throws(() => validateBatch(value));
});

test("limits collection by source without writing an address to analytics", async () => {
  const {env, points} = fixture(false);
  const response = await worker.fetch(request(), env);
  assert.equal(response.status, 429); assert.equal(response.headers.get("Retry-After"), "60"); assert.deepEqual(points, []);
});

test("streaming body cap also applies without Content-Length", async () => {
  const body = new ReadableStream({start(controller) {controller.enqueue(new TextEncoder().encode("x".repeat(32_769))); controller.close();}});
  const oversized = new Request("https://telemetry.example.com/v1/events", {method: "POST", headers: {"Content-Type": "application/json"}, body, duplex: "half"});
  await assert.rejects(readBatch(oversized));
});

test("declared oversize, non-JSON and compressed bodies never enter analytics", async () => {
  for (const headers of [{"Content-Length": "100000"}, {"Content-Type": "text/plain"}, {"Content-Type": "application/json-evil"}, {"Content-Encoding": "gzip"}]) {
    const {env, points} = fixture();
    const response = await worker.fetch(request(batch, headers), env);
    assert.equal(response.status, 400); assert.deepEqual(points, []);
  }
});

test("health reveals only protocol identity and ingest is POST-only", async () => {
  const {env, points} = fixture();
  const health = await worker.fetch(new Request("https://telemetry.example.com/health"), env);
  assert.deepEqual(await health.json(), {service: "datapyn-telemetry", schema_version: 1});
  assert.equal((await worker.fetch(new Request("https://telemetry.example.com/v1/events"), env)).status, 405);
  assert.equal((await worker.fetch(new Request("https://telemetry.example.com/admin"), env)).status, 404);
  assert.deepEqual(points, []);
});
