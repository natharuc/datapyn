import assert from "node:assert/strict";
import {test} from "node:test";
import {resolveDeployment, verifyHealth} from "../scripts/deploy.mjs";

function apiFixture({zones, domains = [], records = [], scripts = [], denied = false} = {}) {
  const calls = [];
  const request = async (url, options) => {
    calls.push({url, options});
    const path = new URL(url).pathname;
    const result = path.endsWith("/zones") ? zones ?? [{id: "zone", name: "datapyn.com", status: "active", account: {id: "own-account"}}]
      : path.endsWith("/workers/domains") ? domains : path.endsWith("/dns_records") ? records : scripts;
    return Response.json({success: !denied, result}, {status: denied ? 403 : 200});
  };
  return {request, calls};
}

test("deployment derives the account from the exact domain with read-only checks", async () => {
  const fixture = apiFixture();
  assert.deepEqual(await resolveDeployment("test-token", fixture.request), {accountId: "own-account", zoneId: "zone", domain: "telemetry.datapyn.com", workerName: "datapyn-telemetry"});
  assert.equal(fixture.calls.length, 4);
  assert.ok(fixture.calls.every(call => !call.options.method || call.options.method === "GET"));
});

test("deployment refuses an ambiguous, inaccessible or pending zone", async () => {
  for (const options of [{zones: []}, {denied: true}, {zones: [{name: "another.com", account: {id: "other"}}]},
    {zones: [{name: "datapyn.com", status: "pending", account: {id: "own-account"}}]}]) {
    await assert.rejects(resolveDeployment("test-token", apiFixture(options).request));
  }
});

test("deployment preserves unrelated Worker names, domains and DNS records", async () => {
  for (const options of [{domains: [{hostname: "telemetry.datapyn.com", service: "another-service"}]}, {records: [{type: "A", content: "192.0.2.1"}]},
    {scripts: [{id: "datapyn-telemetry"}]}]) await assert.rejects(resolveDeployment("test-token", apiFixture(options).request));
  const own = apiFixture({domains: [{hostname: "telemetry.datapyn.com", service: "datapyn-telemetry"}], records: [{type: "AAAA"}], scripts: [{id: "datapyn-telemetry"}]});
  assert.equal((await resolveDeployment("test-token", own.request)).accountId, "own-account");
});

test("publication waits for the collector protocol on the HTTPS custom domain", async () => {
  let calls = 0, waits = 0;
  await verifyHealth("telemetry.example.com", async (url, options) => {
    assert.equal(url, "https://telemetry.example.com/health");
    assert.equal(options.headers["User-Agent"], "DataPyn-Telemetry/1");
    return ++calls < 2 ? new Response(null, {status: 503}) : Response.json({service: "datapyn-telemetry", schema_version: 1});
  }, async () => {waits++;});
  assert.equal(calls, 2); assert.equal(waits, 1);
  await assert.rejects(verifyHealth("telemetry.example.com", async () => Response.json({service: "another-app", schema_version: 1}), async () => {}));
});
