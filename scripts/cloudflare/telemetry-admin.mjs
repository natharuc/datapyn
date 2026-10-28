import {fileURLToPath} from 'node:url';
import {dirname, relative, resolve} from 'node:path';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';

export const ACCOUNT_ID = '10d97e9bda1dd76cde34ad2f54c8c37e';
export const ZONE = 'docfis.com';
export const HOSTNAME = 'painel.docfis.com';
export const WORKER = 'datapyn-telemetry-admin';
export const APP_NAME = 'DataPyn telemetry admin';
export const POLICY_NAME = 'DataPyn administrators';
export const OTP_NAME = 'DataPyn administrator OTP';
const serviceRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../services/telemetry-admin');
const accountPath = `accounts/${ACCOUNT_ID}`;

export function cloudflare(token, request = fetch) {
  if (!token) throw new Error('Configure CLOUDFLARE_API_TOKEN through a private environment variable or GitHub Actions secret.');
  async function payload(path, options = {}) {
    const response = await request(`https://api.cloudflare.com/client/v4/${path}`, {
      ...options,
      headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
      signal: AbortSignal.timeout(20_000),
    });
    let payload;
    try { payload = await response.json(); }
    catch { throw new Error(`Cloudflare ${options.method ?? 'GET'} ${path.split('?')[0]} returned an invalid API response.`); }
    if (!response.ok || !payload.success) {
      // Do not print API bodies: identity-provider configuration can contain credentials.
      throw new Error(`Cloudflare ${options.method ?? 'GET'} ${path.split('?')[0]} returned HTTP ${response.status}. Check token resource scopes and permissions.`);
    }
    return payload;
  }
  const api = async (path, options = {}) => (await payload(path, options)).result;
  api.all = async path => {
    const results = [];
    for (let page = 1; page <= 100; page++) {
      const separator = path.includes('?') ? '&' : '?';
      const value = await payload(`${path}${separator}per_page=100&page=${page}`);
      if (!Array.isArray(value.result)) throw new Error('Cloudflare returned an invalid resource list.');
      results.push(...value.result);
      if (value.result_info?.total_pages !== undefined) {
        if (page >= value.result_info.total_pages) return results;
      } else if (value.result.length < 100) return results;
    }
    throw new Error('Cloudflare pagination exceeded its safety limit; deployment stopped.');
  };
  return api;
}

export function parseEmails(value) {
  if (!value?.trim()) throw new Error('Configure TELEMETRY_ADMIN_EMAILS as a private environment variable or GitHub Actions secret.');
  const raw = value.trim();
  let emails;
  try { emails = raw.startsWith('[') ? JSON.parse(raw) : raw.split(/[,;\s]+/); }
  catch { throw new Error('TELEMETRY_ADMIN_EMAILS contains invalid JSON.'); }
  if (!Array.isArray(emails) || !emails.length || emails.length > 50 || emails.some(email =>
    typeof email !== 'string' || email.length > 254 || !/^[a-z0-9._%+-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$/i.test(email))) {
    throw new Error('TELEMETRY_ADMIN_EMAILS must contain between 1 and 50 exact email addresses, without wildcards.');
  }
  return [...new Set(emails.map(email => email.toLowerCase()))].sort();
}

function domainsOf(app) {
  return [app.domain, ...(app.self_hosted_domains ?? []), ...(app.destinations ?? []).map(item => item.uri)]
    .filter(item => typeof item === 'string').map(item => item.replace(/^https?:\/\//, '').toLowerCase());
}

function overlapsTarget(app) {
  return domainsOf(app).some(domain => {
    const host = domain.split('/')[0];
    return host === HOSTNAME || (host.startsWith('*.') && HOSTNAME.endsWith(host.slice(1)));
  });
}

function issuerOf(organization) {
  const domain = organization?.auth_domain?.replace(/^https:\/\//, '').replace(/\/$/, '');
  if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com$/.test(domain ?? '')) {
    throw new Error('A Zero Trust organization with a valid auth_domain is required. Complete Zero Trust Free setup in Cloudflare; this script does not create subscriptions or change billing.');
  }
  return `https://${domain}`;
}

export function validateApplication(app, policies, provider, emails) {
  if (app?.name !== APP_NAME || app?.domain !== HOSTNAME || app?.type !== 'self_hosted'
      || !/^[a-f0-9]{64}$/.test(app.aud ?? '') || domainsOf(app).some(domain => domain !== HOSTNAME)
      || (app.destinations ?? []).some(item => item.type !== 'public' || item.uri !== HOSTNAME)
      || app.allow_authenticate_via_warp === true || app.options_preflight_bypass === true
      || app.allowed_idps?.length !== 1 || app.allowed_idps[0] !== provider?.id || provider?.type !== 'onetimepin') {
    throw new Error('Existing Access application differs from the exact protected hostname, OTP provider, or security settings; deployment stopped without changing it.');
  }
  const policy = policies?.[0];
  if (policies?.length !== 1 || policy.decision !== 'allow' || !Array.isArray(policy.include)
      || (policy.require?.length ?? 0) !== 0 || (policy.exclude?.length ?? 0) !== 0
      || policy.include.some(rule => Object.keys(rule).length !== 1 || !rule.email
        || Object.keys(rule.email).length !== 1 || typeof rule.email.email !== 'string')) {
    throw new Error('Existing Access policies must contain exactly one allow policy with exact emails; bypass, service access, groups and Everyone are refused.');
  }
  const authorized = [...new Set(policy.include.map(rule => rule.email.email.toLowerCase()))].sort();
  if (JSON.stringify(authorized) !== JSON.stringify(emails)) {
    throw new Error('Existing Access policy email allowlist differs from TELEMETRY_ADMIN_EMAILS; review it explicitly before deploying.');
  }
}

export async function inspectAnalytics(token, request = fetch) {
  const response = await request(`https://api.cloudflare.com/client/v4/analytics/sql/introspection?account_tag=${ACCOUNT_ID}&dataset_name=events.analyticsEngine.datapyn_telemetry&include_columns=true`, {
    headers: {Authorization: `Bearer ${token}`}, signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) throw new Error(`Analytics SQL schema inspection returned HTTP ${response.status}; Account Analytics Read is required for this metadata probe.`);
  const value = await response.json();
  const dataset = (value.datasets ?? value.result?.datasets ?? []).find(item => item.name === 'events.analyticsEngine.datapyn_telemetry');
  if (!dataset || !Array.isArray(dataset.columns)) throw new Error('Analytics SQL did not return the expected telemetry dataset schema.');
  const columns = dataset.columns.map(item => item.name).filter(name => typeof name === 'string');
  return {columns, sampleWeightColumn: columns.includes('sampleInterval') ? 'sampleInterval' : columns.includes('_sample_interval') ? '_sample_interval' : null};
}

export async function probe(token = process.env.CLOUDFLARE_API_TOKEN, request = fetch) {
  const api = cloudflare(token, request);
  const checks = [
    ['zone', `zones?name=${ZONE}`, result => {
      const zone = result.find(item => item.name === ZONE);
      return zone ? {found: true, active: zone.status === 'active', expectedAccount: zone.account?.id === ACCOUNT_ID} : {found: false};
    }],
    ['organization', `accounts/${ACCOUNT_ID}/access/organizations`, result => ({configured: !!result.auth_domain, teamDomain: result.auth_domain})],
    ['identityProviders', `accounts/${ACCOUNT_ID}/access/identity_providers`, result => ({types: result.map(item => item.type)})],
    ['accessApplications', `accounts/${ACCOUNT_ID}/access/apps`, result => ({matchingApplications: result.filter(item => item.domain === HOSTNAME).map(item => ({id: item.id, type: item.type}))})],
    ['workerDomains', `accounts/${ACCOUNT_ID}/workers/domains`, result => ({matchingDomains: result.filter(item => item.hostname === HOSTNAME).map(item => ({service: item.service}))})],
  ];
  const results = await Promise.all(checks.map(async ([name, path, summarize]) => {
    try { return {check: name, ok: true, ...summarize(await api(path))}; }
    catch (error) { return {check: name, ok: false, error: error.message}; }
  }));
  try { results.push({check: 'analyticsSchema', ok: true, ...await inspectAnalytics(token, request)}); }
  catch (error) { results.push({check: 'analyticsSchema', ok: false, error: error.message}); }
  return results;
}

export async function prepareDeployment({token = process.env.CLOUDFLARE_API_TOKEN, emails = process.env.TELEMETRY_ADMIN_EMAILS, request = fetch} = {}) {
  const authorizedEmails = parseEmails(emails);
  const api = cloudflare(token, request);
  const zones = await api.all(`zones?name=${ZONE}`);
  const matches = zones.filter(zone => zone.name === ZONE);
  if (matches.length !== 1 || matches[0].status !== 'active' || matches[0].account?.id !== ACCOUNT_ID) {
    throw new Error('The token must resolve exactly the active docfis.com zone in the telemetry dataset account. No alternative domain will be deployed.');
  }
  const zone = matches[0];
  // Read all existing resources before the first mutation. Never replace an
  // unrelated DNS record, custom domain, Worker or Access application.
  const [domains, records, scripts, organization, providers, applications] = await Promise.all([
    api.all(`${accountPath}/workers/domains`), api.all(`zones/${zone.id}/dns_records?name=${HOSTNAME}`),
    api.all(`${accountPath}/workers/scripts`), api(`${accountPath}/access/organizations`),
    api.all(`${accountPath}/access/identity_providers`), api.all(`${accountPath}/access/apps`),
  ]);
  const issuer = issuerOf(organization);
  const domain = domains.find(item => item.hostname === HOSTNAME);
  const script = scripts.find(item => item.id === WORKER);
  if (domain && (domain.service !== WORKER || (domain.zone_id && domain.zone_id !== zone.id))) {
    throw new Error('painel.docfis.com belongs to another Worker or zone; deployment stopped.');
  }
  if ((!domain && records.length) || (script && !domain)
      || domains.some(item => item.service === WORKER && item.hostname !== HOSTNAME)
      || (domain && !script)) throw new Error('Existing DNS or Worker ownership is ambiguous; deployment stopped to preserve existing services.');
  const overlapping = applications.filter(overlapsTarget);
  const namedElsewhere = applications.some(item => item.name === APP_NAME && !overlapsTarget(item));
  if (overlapping.length > 1 || namedElsewhere || (overlapping.length &&
      (overlapping[0].domain !== HOSTNAME || overlapping[0].name !== APP_NAME || overlapping[0].type !== 'self_hosted'))) {
    throw new Error('An unrelated or overlapping Access application already covers the dashboard; deployment stopped.');
  }
  let application = overlapping[0];
  let provider;
  if (application) {
    provider = providers.find(item => application.allowed_idps?.length === 1 && item.id === application.allowed_idps[0]);
    const policies = await api.all(`${accountPath}/access/apps/${application.id}/policies`);
    validateApplication(application, policies, provider, authorizedEmails);
  } else {
    const namedProvider = providers.find(item => item.name === OTP_NAME);
    if (namedProvider && namedProvider.type !== 'onetimepin') throw new Error('The managed OTP name belongs to another identity provider; deployment stopped.');
    provider = namedProvider ?? providers.find(item => item.type === 'onetimepin');
  }
  return {api, token, authorizedEmails, zoneId: zone.id, issuer, provider, application};
}

export async function ensureAccess(target) {
  const {api, authorizedEmails} = target;
  let provider = target.provider;
  let app = target.application;
  if (!provider) provider = await api(`${accountPath}/access/identity_providers`, {method: 'POST', body: JSON.stringify({name: OTP_NAME, type: 'onetimepin', config: {}})});
  if (provider?.type !== 'onetimepin' || !provider.id) throw new Error('Cloudflare did not return a valid OTP identity provider.');
  if (!app) app = await api(`${accountPath}/access/apps`, {method: 'POST', body: JSON.stringify({
    name: APP_NAME, domain: HOSTNAME, type: 'self_hosted', session_duration: '8h',
    allowed_idps: [provider.id], auto_redirect_to_identity: true, http_only_cookie_attribute: true,
    options_preflight_bypass: false, allow_authenticate_via_warp: false,
    policies: [{name: POLICY_NAME, decision: 'allow', include: authorizedEmails.map(email => ({email: {email}})), require: [], exclude: []}],
  })});
  if (!app?.id) throw new Error('Cloudflare did not return an Access application identifier.');
  // Re-read persisted authorization, not just the creation response.
  const [savedApp, savedPolicies, savedProvider] = await Promise.all([
    api(`${accountPath}/access/apps/${app.id}`), api.all(`${accountPath}/access/apps/${app.id}/policies`),
    api(`${accountPath}/access/identity_providers/${provider.id}`),
  ]);
  validateApplication(savedApp, savedPolicies, savedProvider, authorizedEmails);
  return {issuer: target.issuer, audience: savedApp.aud};
}

export function productionConfig(config, access, configPath) {
  if (issuerOf({auth_domain: access.issuer}) !== access.issuer || !/^[a-f0-9]{64}$/.test(access.audience ?? '')) {
    throw new Error('A validated Cloudflare Access issuer and application audience are required.');
  }
  if (config.name !== WORKER || config.account_id !== ACCOUNT_ID || config.main !== 'src/index.ts'
      || config.assets?.directory !== './public' || config.assets.binding !== 'ASSETS' || config.assets.run_worker_first !== true
      || config.analytics?.binding !== 'ANALYTICS_SQL' || config.observability?.enabled !== false) {
    throw new Error('The dashboard source configuration differs from the reviewed secure service configuration.');
  }
  const fromConfig = file => relative(dirname(configPath), resolve(serviceRoot, file)).replaceAll('\\', '/');
  const result = {...config, $schema: fromConfig('node_modules/wrangler/config-schema.json'), main: fromConfig('src/index.ts'), account_id: ACCOUNT_ID, workers_dev: false, preview_urls: false,
    assets: {...config.assets, directory: fromConfig('public'), run_worker_first: true},
    vars: {ACCESS_TEAM_DOMAIN: access.issuer, ACCESS_AUD: access.audience, CLOUDFLARE_ACCOUNT_ID: ACCOUNT_ID},
    routes: [{pattern: HOSTNAME, custom_domain: true}]};
  delete result.route;
  delete result.tsconfig;
  return result;
}

class ProtectionError extends Error {
  constructor(message, retryable = false) { super(message); this.retryable = retryable; }
}

export async function verifyProtection(issuer, request = fetch, {
  attempts = 12, wait = milliseconds => new Promise(done => setTimeout(done, milliseconds)),
} = {}) {
  if (!Number.isInteger(attempts) || attempts < 1 || attempts > 12) throw new Error('Protection verification allows between 1 and 12 attempts.');
  for (let attempt = 0; attempt < attempts; attempt++) {
    const results = await Promise.allSettled(['/', '/api/dashboard'].flatMap(path => ['GET', 'HEAD'].map(async method => {
      let response;
      try {
        response = await request(`https://${HOSTNAME}${path}`, {method, redirect: 'manual', signal: AbortSignal.timeout(8_000)});
      } catch { throw new ProtectionError('The dashboard DNS or TLS endpoint is not ready yet.', true); }
      if ([401, 403].includes(response.status)) return;
      if ([301, 302, 303, 307, 308].includes(response.status)) {
        let location;
        try { location = new URL(response.headers.get('Location') ?? '', `https://${HOSTNAME}`); }
        catch { throw new ProtectionError('The deployed interface or API returned an invalid authentication redirect.'); }
        if (location.origin === issuer && location.pathname.startsWith('/cdn-cgi/access/')) return;
      }
      if ([404, 429, 502, 503, 504].includes(response.status)) {
        throw new ProtectionError('The dashboard route is temporarily unavailable while DNS or TLS is being provisioned.', true);
      }
      throw new ProtectionError('The deployed interface or API did not deny anonymous access through the expected Cloudflare Access organization.');
    })));
    const failures = results.filter(result => result.status === 'rejected').map(result => result.reason);
    if (!failures.length) return;
    // Wait for every check before deciding: a transient HEAD failure must not
    // hide a successful anonymous GET or a redirect to an unrelated issuer.
    const permanentFailure = failures.find(error => !error.retryable);
    if (permanentFailure) throw permanentFailure;
    if (attempt < attempts - 1) await wait(5_000);
  }
  throw new Error('The dashboard was deployed but DNS/TLS or its protected route did not become ready within the bounded verification window. Anonymous access has not been verified.');
}

async function runWrangler(configPath, token) {
  const executable = resolve(serviceRoot, 'node_modules/wrangler/bin/wrangler.js');
  const code = await new Promise((done, fail) => {
    const child = spawn(process.execPath, [executable, 'deploy', '--config', configPath], {
      cwd: serviceRoot, shell: false, stdio: 'inherit',
      env: {...process.env, CLOUDFLARE_API_TOKEN: token, CLOUDFLARE_ACCOUNT_ID: ACCOUNT_ID, WRANGLER_SEND_METRICS: 'false', CI: 'true'},
    });
    child.once('error', fail); child.once('close', done);
  });
  if (code !== 0) throw new Error('Cloudflare dashboard deployment failed.');
}

export async function deploy({token = process.env.CLOUDFLARE_API_TOKEN, emails = process.env.TELEMETRY_ADMIN_EMAILS,
  request = fetch, run = runWrangler, save = async (path, config) => {
    await mkdir(dirname(path), {recursive: true}); await writeFile(path, JSON.stringify(config, null, 2));
  }, sourceConfig} = {}) {
  const target = await prepareDeployment({token, emails, request});
  const config = sourceConfig ?? JSON.parse(await readFile(resolve(serviceRoot, 'wrangler.jsonc'), 'utf8'));
  // Validate local configuration before creating even the Access application.
  const configPath = resolve(serviceRoot, '.wrangler/admin-production.json');
  productionConfig(config, {issuer: target.issuer, audience: '0'.repeat(64)}, configPath);
  const access = await ensureAccess(target);
  await save(configPath, productionConfig(config, access, configPath));
  await run(configPath, token);
  const settings = await target.api(`${accountPath}/workers/scripts/${WORKER}/subdomain`);
  if (settings?.enabled !== false || settings?.previews_enabled !== false) throw new Error('workers.dev or preview URLs are still enabled; deployment is not considered protected.');
  await verifyProtection(access.issuer, request);
  return {hostname: HOSTNAME, worker: WORKER, accessProtected: true, workersDevDisabled: true};
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (!['probe', 'deploy'].includes(process.argv[2])) throw new Error('Expected command: probe or deploy');
    console.log(JSON.stringify(process.argv[2] === 'probe' ? await probe() : await deploy(), null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
