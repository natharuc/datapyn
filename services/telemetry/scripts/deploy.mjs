import {readFile, writeFile, mkdir} from "node:fs/promises";
import {dirname, relative, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {spawn} from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const domain = "telemetry.datapyn.com", zoneName = "datapyn.com", workerName = "datapyn-telemetry";

export async function verifyHealth(hostname = domain, request = fetch, wait = milliseconds => new Promise(done => setTimeout(done, milliseconds))) {
  for (let attempt = 0; attempt < 12; attempt++) {
    try {
      const response = await request(`https://${hostname}/health`, {headers: {"User-Agent": "DataPyn-Telemetry/1"}, signal: AbortSignal.timeout(8_000)});
      const value = response.ok ? await response.json() : null;
      if (value?.service === workerName && value.schema_version === 1) return;
    } catch { /* A newly attached custom domain may still be provisioning TLS. */ }
    if (attempt < 11) await wait(5_000);
  }
  throw new Error("The telemetry collector was uploaded but its HTTPS health check did not become ready.");
}

export async function resolveDeployment(token, request = fetch) {
  if (!token) throw new Error("Configure CLOUDFLARE_API_TOKEN for the DataPyn account.");
  const api = async path => {
    const response = await request(`https://api.cloudflare.com/client/v4/${path}`, {headers: {Authorization: `Bearer ${token}`}, signal: AbortSignal.timeout(20_000)});
    const value = await response.json();
    if (!response.ok || !value.success) throw new Error(`Cloudflare access failed for ${path.split("?")[0]} (${response.status}). Check the token's account, Workers and DNS permissions.`);
    return value.result;
  };
  const zones = await api(`zones?name=${zoneName}`);
  const matches = zones.filter(zone => zone.name === zoneName);
  if (matches.length !== 1 || !matches[0].account?.id) throw new Error("The token must resolve exactly the datapyn.com zone and its owning account.");
  const zone = matches[0], accountId = zone.account.id;
  if (zone.status !== "active") throw new Error("datapyn.com is not active on Cloudflare yet. Finish the nameserver migration before deploying the custom domain.");
  // Read before write: never replace an unrelated Worker or existing DNS record.
  const [domains, records, scripts] = await Promise.all([
    api(`accounts/${accountId}/workers/domains`),
    api(`zones/${zone.id}/dns_records?name=${domain}`),
    api(`accounts/${accountId}/workers/scripts`),
  ]);
  const existing = domains.find(item => item.hostname === domain);
  if (existing && existing.service !== workerName) throw new Error("The telemetry domain already belongs to another Worker; deployment stopped.");
  if (!existing && records.length) throw new Error("The telemetry domain has existing DNS records; deployment stopped to preserve them.");
  const prior = scripts.find(item => item.id === workerName);
  if (prior && !existing) throw new Error("A Worker with this name already exists without the expected domain. Review ownership before deploying.");
  return {accountId, zoneId: zone.id, domain, workerName};
}

export async function deploy({token = process.env.CLOUDFLARE_API_TOKEN} = {}) {
  const target = await resolveDeployment(token);
  const config = JSON.parse(await readFile(resolve(root, "wrangler.jsonc"), "utf8"));
  // Wrangler discovers the project's tsconfig from the main entry point. An
  // explicit relocated tsconfig is resolved differently by its bundler on Windows.
  delete config.tsconfig;
  const path = resolve(root, ".wrangler/datapyn-production.json");
  await mkdir(dirname(path), {recursive: true});
  const fromConfig = file => relative(dirname(path), resolve(root, file)).replaceAll("\\", "/");
  await writeFile(path, JSON.stringify({...config, account_id: target.accountId, main: fromConfig("src/index.ts"),
    routes: [{pattern: target.domain, custom_domain: true}]}, null, 2));
  const executable = resolve(root, "node_modules/wrangler/bin/wrangler.js");
  const code = await new Promise((yes, no) => {
    const child = spawn(process.execPath, [executable, "deploy", "--config", path], {
      cwd: root, env: {...process.env, CLOUDFLARE_API_TOKEN: token, CLOUDFLARE_ACCOUNT_ID: target.accountId, WRANGLER_SEND_METRICS: "false", CI: "true"}, stdio: "inherit",
    });
    child.once("error", no); child.once("close", yes);
  });
  if (code !== 0) throw new Error("Cloudflare deployment failed; the desktop release must not assume telemetry is ready.");
  await verifyHealth(target.domain);
  console.log(`Telemetry collector deployed at https://${target.domain}`);
  return target;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await deploy().catch(error => {console.error(error.message); process.exitCode = 1;});
}
