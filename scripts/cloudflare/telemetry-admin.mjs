import {fileURLToPath} from 'node:url';
import {dirname, relative, resolve} from 'node:path';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';

export const ACCOUNT_ID = '10d97e9bda1dd76cde34ad2f54c8c37e';
export const ZONE = 'datapyn.com';
export const HOSTNAME = 'painel.datapyn.com';
export const LEGACY_ZONE = 'docfis.com';
export const LEGACY_HOSTNAME = 'painel.docfis.com';
export const WORKER = 'datapyn-telemetry-admin';
export const APP_NAME = 'DataPyn telemetry admin';
export const POLICY_NAME = 'DataPyn administrators';
export const OTP_NAME = 'DataPyn administrator OTP';
const serviceRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../services/telemetry-admin');
const accountPath = `accounts/${ACCOUNT_ID}`;

function credentials(token, accessToken) {
  const workerToken = token || accessToken;
  if (!workerToken) throw new Error('Configure CLOUDFLARE_API_TOKEN or CLOUDFLARE_ADMIN_API_TOKEN through private environment variables or GitHub Actions secrets.');
  return {workerToken, accessToken: accessToken || token};
}

function failureDetails(status, payload, path) {
  const errors = Array.isArray(payload?.errors) ? payload.errors.slice(0, 32) : [];
  const entries = errors.flatMap(error => [error, ...(Array.isArray(error?.error_chain) ? error.error_chain.slice(0, 8) : [])]);
  const apiCodes = [...new Set(entries.map(error => error?.code).filter(code => Number.isSafeInteger(code) && code >= 0))].slice(0, 32);
  const documentationUrls = [...new Set(entries.flatMap(error => {
    if (typeof error?.documentation_url !== 'string') return [];
    try {
      const url = new URL(error.documentation_url);
      return url.origin === 'https://developers.cloudflare.com' && url.pathname.length <= 512 ? [`${url.origin}${url.pathname}`] : [];
    } catch { return []; }
  }))].slice(0, 8);
  // Messages are inspected only to select fixed diagnostic labels. Never retain
  // or interpolate messages: an API error can contain identities or credentials.
  const messages = entries.map(error => typeof error?.message === 'string' ? error.message.slice(0, 2048) : '').join(' ');
  let classification = 'apiFailure';
  const organizationEndpoint = /^(?:accounts|zones)\/[^/?#]+\/access\/organizations(?:\?|$)/.test(path);
  if (organizationEndpoint && /(?:\b(?:organi[sz]ation|org)\b.{0,80}\b(?:does not exist|not found|not configured|not initialized|has not been (?:created|configured))\b|\b(?:account|zone)\b.{0,60}\b(?:does not have|has no)\b.{0,40}\b(?:organi[sz]ation|org)\b|\bno (?:access |zero[ -]trust )?organi[sz]ation\b|\borganization_not_(?:found|configured)\b)/i.test(messages)) classification = 'orgNotConfigured';
  else if (/\b(?:invalid|expired|revoked|unknown) (?:access |api |bearer )?token\b|\btoken (?:is |has )?(?:invalid|expired|revoked)\b|\bvalid (?:user-level )?authentication not found\b/i.test(messages)) classification = 'authentication';
  else if (/\b(?:insufficient|missing|lacks?|required)\b.{0,50}\b(?:permission|scope)s?\b|\bpermission denied\b|\bunauthorized to access requested resource\b/i.test(messages)) classification = 'permission';
  else if (status === 403) classification = 'permission';
  else if (status === 401) classification = 'authentication';
  return {apiCodes, classification, documentationUrls};
}

export class CloudflareApiError extends Error {
  constructor(path, method, httpStatus, apiCodes = [], classification = 'apiFailure', documentationUrls = []) {
    const status = httpStatus === null ? 'no HTTP response' : `HTTP ${httpStatus}`;
    super(`Cloudflare ${method} ${path.split('?')[0]} returned ${status}; classification=${classification}; API codes=${apiCodes.length ? apiCodes.join(',') : 'none'}.${documentationUrls.length ? ` Documentation: ${documentationUrls.join(', ')}` : ''}`);
    this.name = 'CloudflareApiError';
    this.httpStatus = httpStatus;
    this.apiCodes = apiCodes;
    this.classification = classification;
    this.documentationUrls = documentationUrls;
  }
}

async function requestJson(path, token, request, options = {}, requireEnvelope = true) {
  const method = options.method ?? 'GET';
  let response;
  try {
    response = await request(`https://api.cloudflare.com/client/v4/${path}`, {
      ...options,
      headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
      signal: AbortSignal.timeout(20_000),
    });
  } catch { throw new CloudflareApiError(path, method, null, [], 'transport'); }
  let value;
  try { value = await response.json(); }
  catch { throw new CloudflareApiError(path, method, response.status, [], 'invalidResponse'); }
  if (!response.ok || value?.success === false) {
    const {apiCodes, classification, documentationUrls} = failureDetails(response.status, value, path);
    throw new CloudflareApiError(path, method, response.status, apiCodes, classification, documentationUrls);
  }
  if (!value || typeof value !== 'object' || (requireEnvelope && value.success !== true)) {
    throw new CloudflareApiError(path, method, response.status, [], 'invalidResponse');
  }
  return value;
}

function diagnostic(error) {
  if (error instanceof CloudflareApiError) return {error: error.message, httpStatus: error.httpStatus, apiCodes: error.apiCodes, classification: error.classification, documentationUrls: error.documentationUrls};
  if (error instanceof AccessScopeError) return {error: error.message, httpStatus: null, apiCodes: error.apiCodes, classification: 'accessScopeUnavailable', attempts: error.attempts};
  return {error: 'The Cloudflare diagnostic could not validate this resource.', httpStatus: null, apiCodes: [], classification: 'invalidResponse'};
}

export function cloudflare(token, request = fetch, accessToken) {
  const selected = credentials(token, accessToken);
  async function payload(path, options = {}) {
    const isAccess = /^(?:accounts|zones)\/[^/?#]+\/access(?:\/|\?|$)/.test(path);
    return requestJson(path, isAccess ? selected.accessToken : selected.workerToken, request, options);
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

class AccessScopeError extends Error {
  constructor(accountError, zoneError) {
    const attempts = [{scope: 'account', ...diagnostic(accountError)}, {scope: 'zone', ...diagnostic(zoneError)}];
    const detail = attempts.map(item => `${item.scope}: HTTP ${item.httpStatus ?? 'none'}, ${item.classification}, API codes=${item.apiCodes.join(',') || 'none'}`).join('; ');
    super(`Neither account nor verified ${ZONE} zone scope could read the Access organization (${detail}). The cause remains unresolved; no resources were changed.`);
    this.name = 'AccessScopeError';
    this.attempts = attempts;
    this.apiCodes = [...new Set(attempts.flatMap(item => item.apiCodes))];
  }
}

async function resolveAccessScope(api, verifiedZoneId) {
  const path = `${accountPath}/access`;
  try { return {accessPath: path, scope: 'account', organization: await api(`${path}/organizations`)}; }
  catch (accountError) {
    // The legacy zone endpoints are documented by the same Access API. Use
    // them only after verifying the exact active zone and only for permission
    // refusals. Never interpret a failed organization read as an empty account.
    if (!verifiedZoneId || !(accountError instanceof CloudflareApiError) || accountError.httpStatus !== 403 || accountError.classification !== 'permission') throw accountError;
    const zonePath = `zones/${verifiedZoneId}/access`;
    try { return {accessPath: zonePath, scope: 'zone', organization: await api(`${zonePath}/organizations`)}; }
    catch (zoneError) { throw new AccessScopeError(accountError, zoneError); }
  }
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

function overlapsTarget(app, hostname = HOSTNAME) {
  return domainsOf(app).some(domain => {
    const host = domain.split('/')[0];
    return host === hostname || (host.startsWith('*.') && hostname.endsWith(host.slice(1)));
  });
}

function issuerOf(organization) {
  const domain = organization?.auth_domain?.replace(/^https:\/\//, '').replace(/\/$/, '');
  if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com$/.test(domain ?? '')) {
    throw new Error('A Zero Trust organization with a valid auth_domain is required. Complete Zero Trust Free setup in Cloudflare; this script does not create subscriptions or change billing.');
  }
  return `https://${domain}`;
}

export function validateApplication(app, policies, provider, emails, expectedHostname = HOSTNAME) {
  if (![HOSTNAME, LEGACY_HOSTNAME].includes(expectedHostname)
      || app?.name !== APP_NAME || app?.domain !== expectedHostname || app?.type !== 'self_hosted'
      || !/^[a-f0-9]{64}$/.test(app.aud ?? '') || domainsOf(app).some(domain => domain !== expectedHostname)
      || (app.destinations ?? []).some(item => item.type !== 'public' || item.uri !== expectedHostname)
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
  const value = await requestJson(`analytics/sql/introspection?account_tag=${ACCOUNT_ID}&dataset_name=events.analyticsEngine.datapyn_telemetry&include_columns=true`, token, request, {}, false);
  const dataset = (value.datasets ?? value.result?.datasets ?? []).find(item => item.name === 'events.analyticsEngine.datapyn_telemetry');
  if (!dataset || !Array.isArray(dataset.columns)) throw new Error('Analytics SQL did not return the expected telemetry dataset schema.');
  const columns = dataset.columns.map(item => item.name).filter(name => typeof name === 'string');
  return {columns, sampleWeightColumn: columns.includes('sampleInterval') ? 'sampleInterval' : columns.includes('_sample_interval') ? '_sample_interval' : null};
}

export async function probe(token = process.env.CLOUDFLARE_API_TOKEN, request = fetch, accessToken = process.env.CLOUDFLARE_ADMIN_API_TOKEN) {
  if (token && typeof token === 'object') ({token = process.env.CLOUDFLARE_API_TOKEN, request = fetch, accessToken = process.env.CLOUDFLARE_ADMIN_API_TOKEN} = token);
  const selected = credentials(token, accessToken);
  const api = cloudflare(selected.workerToken, request, selected.accessToken);
  const results = [];
  let verifiedZoneId;
  try {
    const zones = await api(`zones?name=${ZONE}`);
    const matching = zones.filter(item => item.name === ZONE);
    const zone = matching[0];
    if (matching.length === 1 && zone.status === 'active' && zone.account?.id === ACCOUNT_ID) verifiedZoneId = zone.id;
    results.push({check: 'zone', ok: true, ...(zone ? {found: true, active: zone.status === 'active', expectedAccount: zone.account?.id === ACCOUNT_ID} : {found: false})});
  } catch (error) { results.push({check: 'zone', ok: false, ...diagnostic(error)}); }
  let access;
  try {
    access = await resolveAccessScope(api, verifiedZoneId);
    const configured = !!access.organization?.auth_domain;
    results.push({check: 'organization', ok: true, scope: access.scope, configured, teamDomain: access.organization?.auth_domain,
      ...(!configured ? {classification: 'orgNotConfigured'} : {})});
  } catch (error) { results.push({check: 'organization', ok: false, ...diagnostic(error)}); }
  const checks = [
    ['identityProviders', access && `${access.accessPath}/identity_providers`, result => ({types: result.map(item => item.type)})],
    ['accessApplications', access && `${access.accessPath}/apps`, result => ({matchingApplications: result.filter(item => item.domain === HOSTNAME).map(item => ({id: item.id, type: item.type}))})],
    ['workerDomains', `${accountPath}/workers/domains`, result => ({matchingDomains: result.filter(item => item.hostname === HOSTNAME).map(item => ({service: item.service}))})],
  ];
  results.push(...await Promise.all(checks.map(async ([name, path, summarize]) => {
    if (!path) return {check: name, ok: false, skipped: true, httpStatus: null, apiCodes: [], classification: 'accessScopeUnavailable', error: 'Skipped because the Access organization scope could not be verified.'};
    try { return {check: name, ok: true, ...summarize(await api(path))}; }
    catch (error) { return {check: name, ok: false, ...diagnostic(error)}; }
  })));
  try { results.push({check: 'analyticsSchema', ok: true, ...await inspectAnalytics(selected.workerToken, request)}); }
  catch (error) { results.push({check: 'analyticsSchema', ok: false, ...diagnostic(error)}); }
  return results;
}

export async function prepareDeployment({token = process.env.CLOUDFLARE_API_TOKEN, accessToken = process.env.CLOUDFLARE_ADMIN_API_TOKEN, emails = process.env.TELEMETRY_ADMIN_EMAILS, request = fetch} = {}) {
  const authorizedEmails = parseEmails(emails);
  const api = cloudflare(token, request, accessToken);
  const zones = await api.all(`zones?name=${ZONE}`);
  const matches = zones.filter(zone => zone.name === ZONE);
  if (matches.length !== 1 || matches[0].status !== 'active' || matches[0].account?.id !== ACCOUNT_ID) {
    throw new Error(`The token must resolve exactly the active ${ZONE} zone in the telemetry dataset account. No alternative domain will be deployed.`);
  }
  const zone = matches[0];
  // Read all existing resources before the first mutation. Never replace an
  // unrelated DNS record, custom domain, Worker or Access application.
  const [domains, records, scripts, access] = await Promise.all([
    api.all(`${accountPath}/workers/domains`), api.all(`zones/${zone.id}/dns_records?name=${HOSTNAME}`),
    api.all(`${accountPath}/workers/scripts`), resolveAccessScope(api, zone.id),
  ]);
  const issuer = issuerOf(access.organization);
  const [providers, applications] = await Promise.all([
    api.all(`${access.accessPath}/identity_providers`), api.all(`${access.accessPath}/apps`),
  ]);
  const domain = domains.find(item => item.hostname === HOSTNAME);
  const legacyAtHost = domains.find(item => item.hostname === LEGACY_HOSTNAME);
  const legacyDomain = legacyAtHost?.service === WORKER ? legacyAtHost : undefined;
  const migrationIndicated = !!legacyDomain || applications.some(item => item.name === APP_NAME && overlapsTarget(item, LEGACY_HOSTNAME));
  const script = scripts.find(item => item.id === WORKER);
  if (domain && (domain.service !== WORKER || (domain.zone_id && domain.zone_id !== zone.id))) {
    throw new Error(`${HOSTNAME} belongs to another Worker or zone; deployment stopped.`);
  }
  if ((!domain && records.length) || (script && !domain && !legacyDomain)
      || domains.some(item => item.service === WORKER && ![HOSTNAME, LEGACY_HOSTNAME].includes(item.hostname))
      || ((domain || legacyDomain) && !script)
      || domains.filter(item => item.hostname === HOSTNAME).length > 1
      || (migrationIndicated && domains.filter(item => item.hostname === LEGACY_HOSTNAME).length > 1)) throw new Error('Existing DNS or Worker ownership is ambiguous; deployment stopped to preserve existing services.');
  const overlapping = applications.filter(item => overlapsTarget(item));
  const legacyApplications = migrationIndicated ? applications.filter(item => overlapsTarget(item, LEGACY_HOSTNAME)) : [];
  const namedElsewhere = applications.some(item => item.name === APP_NAME && !overlapsTarget(item) && !overlapsTarget(item, LEGACY_HOSTNAME));
  if (overlapping.length > 1 || legacyApplications.length > 1 || namedElsewhere || (overlapping.length && legacyApplications.length)
      || [...overlapping, ...legacyApplications].some(item => ![HOSTNAME, LEGACY_HOSTNAME].includes(item.domain) || item.name !== APP_NAME || item.type !== 'self_hosted')) {
    throw new Error('An unrelated or overlapping Access application already covers the dashboard; deployment stopped.');
  }
  let application = overlapping[0] ?? legacyApplications[0];
  let provider;
  let applicationPolicies;
  if (application) {
    provider = providers.find(item => application.allowed_idps?.length === 1 && item.id === application.allowed_idps[0]);
    applicationPolicies = await api.all(`${access.accessPath}/apps/${application.id}/policies`);
    validateApplication(application, applicationPolicies, provider, authorizedEmails, application.domain);
    if (application.domain === LEGACY_HOSTNAME && !applicationPolicies[0]?.id) throw new Error('The legacy Access policy identifier is required to preserve authorization during migration.');
  } else {
    const namedProvider = providers.find(item => item.name === OTP_NAME);
    if (namedProvider && namedProvider.type !== 'onetimepin') throw new Error('The managed OTP name belongs to another identity provider; deployment stopped.');
    provider = namedProvider ?? providers.find(item => item.type === 'onetimepin');
  }
  let legacy;
  let legacyCleanupStatus = 'notApplicable';
  if (legacyDomain || legacyApplications.length) {
    if (!legacyDomain || !application || !legacyDomain.id) throw new Error('The legacy dashboard cannot be migrated without verified Worker domain and Access ownership.');
    const oldZones = await api.all(`zones?name=${LEGACY_ZONE}`);
    const matchingOldZones = oldZones.filter(item => item.name === LEGACY_ZONE);
    const oldZone = matchingOldZones[0];
    if (matchingOldZones.length !== 1 || oldZone.status !== 'active' || oldZone.account?.id !== ACCOUNT_ID || legacyDomain.zone_id !== oldZone.id
        || (legacyDomain.environment !== undefined && legacyDomain.environment !== 'production')) {
      throw new Error('The legacy dashboard zone and Worker domain must belong to the telemetry account before any migration or cleanup.');
    }
    const oldRecords = await api.all(`zones/${oldZone.id}/dns_records?name=${LEGACY_HOSTNAME}`);
    legacy = {domain: legacyDomain, zoneId: oldZone.id, records: oldRecords.filter(record => record.name === LEGACY_HOSTNAME && ['A', 'AAAA', 'CNAME'].includes(record.type))};
    if (legacy.records.some(record => !record.id || typeof record.content !== 'string')) throw new Error('Legacy DNS ownership snapshot is incomplete; migration stopped.');
    // Workers custom domains use a proxied discard-address origin. Never
    // adopt a real A/AAAA/CNAME origin solely because it shares the hostname.
    if (legacy.records.some(record => record.type !== 'AAAA' || record.content !== '100::' || record.proxied !== true)) {
      throw new Error('Legacy DNS has address records without a verified Worker-managed origin; migration stopped before any write.');
    }
  } else if (domain && application?.domain === HOSTNAME && !legacyAtHost && !applications.some(item => overlapsTarget(item, LEGACY_HOSTNAME))) {
    // A previous process may have detached the old domain before it could clean
    // DNS. No cross-run ownership snapshot exists, so detect but never delete
    // such remnants. Unrelated services and unavailable legacy scopes do not
    // become permanent dependencies of normal deployments to datapyn.com.
    legacyCleanupStatus = 'unverified';
    try {
      const oldZones = await api.all(`zones?name=${LEGACY_ZONE}`);
      const candidates = oldZones.filter(item => item.name === LEGACY_ZONE && item.status === 'active' && item.account?.id === ACCOUNT_ID);
      if (candidates.length === 1) {
        const remnants = await api.all(`zones/${candidates[0].id}/dns_records?name=${LEGACY_HOSTNAME}`);
        if (remnants.some(item => item.name === LEGACY_HOSTNAME && ['A','AAAA','CNAME'].includes(item.type))) {
          throw new Error('Legacy dashboard address records remain without a current Worker ownership snapshot; the new dashboard is protected, but cleanup is pending explicit DNS ownership review.');
        }
        legacyCleanupStatus = 'verifiedAbsent';
      }
    } catch (error) { if (!(error instanceof CloudflareApiError)) throw error; }
  }
  return {api, authorizedEmails, zoneId: zone.id, issuer, provider, application, applicationPolicies, legacy, legacyCleanupStatus, accessPath: access.accessPath};
}

export async function ensureAccess(target) {
  const {api, authorizedEmails, accessPath} = target;
  let provider = target.provider;
  let app = target.application;
  if (!provider) provider = await api(`${accessPath}/identity_providers`, {method: 'POST', body: JSON.stringify({name: OTP_NAME, type: 'onetimepin', config: {}})});
  if (provider?.type !== 'onetimepin' || !provider.id) throw new Error('Cloudflare did not return a valid OTP identity provider.');
  if (!app) app = await api(`${accessPath}/apps`, {method: 'POST', body: JSON.stringify({
    name: APP_NAME, domain: HOSTNAME, type: 'self_hosted', session_duration: '8h',
    allowed_idps: [provider.id], auto_redirect_to_identity: true, http_only_cookie_attribute: true,
    options_preflight_bypass: false, allow_authenticate_via_warp: false,
    policies: [{name: POLICY_NAME, decision: 'allow', include: authorizedEmails.map(email => ({email: {email}})), require: [], exclude: []}],
  })});
  else if (app.domain === LEGACY_HOSTNAME) {
    // Move the validated application rather than creating a second allowlist.
    // Keep its policy identifier, email selectors and identity provider intact.
    await api(`${accessPath}/apps/${app.id}`, {method: 'PUT', body: JSON.stringify({
      name: APP_NAME, domain: HOSTNAME, type: 'self_hosted', session_duration: app.session_duration ?? '8h',
      allowed_idps: [provider.id], auto_redirect_to_identity: true, http_only_cookie_attribute: true,
      options_preflight_bypass: false, allow_authenticate_via_warp: false,
      ...(app.destinations?.length ? {destinations: app.destinations.map(item => ({...item, uri: HOSTNAME}))} : {}),
      ...(app.self_hosted_domains?.length ? {self_hosted_domains: [HOSTNAME]} : {}),
      policies: target.applicationPolicies.map(policy => ({id: policy.id, precedence: Number.isInteger(policy.precedence) ? policy.precedence : 1})),
    })});
  }
  if (!app?.id) throw new Error('Cloudflare did not return an Access application identifier.');
  // Re-read persisted authorization, not just the creation response.
  const [savedApp, savedPolicies, savedProvider] = await Promise.all([
    api(`${accessPath}/apps/${app.id}`), api.all(`${accessPath}/apps/${app.id}/policies`),
    api(`${accessPath}/identity_providers/${provider.id}`),
  ]);
  validateApplication(savedApp, savedPolicies, savedProvider, authorizedEmails);
  if (app.domain === LEGACY_HOSTNAME && (savedApp.aud !== app.aud || savedPolicies[0]?.id !== target.applicationPolicies[0].id)) {
    throw new Error('The migrated Access application changed its audience or policy identity; deployment stopped.');
  }
  return {issuer: target.issuer, audience: savedApp.aud};
}

function dnsIdentity(record) {
  return JSON.stringify([record.id, record.name, record.type, record.content, record.proxied ?? null, record.ttl ?? null]);
}

export async function cleanupLegacy(target) {
  if (!target.legacy) return {legacyCleaned: false, legacyCleanupStatus: target.legacyCleanupStatus};
  const {api, legacy} = target;
  const domains = await api.all(`${accountPath}/workers/domains`);
  const destination = domains.find(item => item.hostname === HOSTNAME);
  if (!destination || destination.service !== WORKER || destination.zone_id !== target.zoneId
      || (destination.environment !== undefined && destination.environment !== 'production')) {
    throw new Error('The destination custom domain must belong to the telemetry Worker before legacy cleanup.');
  }
  const previous = domains.find(item => item.hostname === LEGACY_HOSTNAME);
  if (previous && (previous.id !== legacy.domain.id || previous.service !== WORKER || previous.zone_id !== legacy.zoneId
      || (previous.environment !== undefined && previous.environment !== 'production'))) {
    throw new Error('The legacy custom domain changed ownership after preflight; cleanup stopped.');
  }
  // Wrangler may already detach the old domain while replacing custom routes.
  // The pre-deploy snapshot still proves ownership for this invocation only.
  if (previous) await api(`${accountPath}/workers/domains/${encodeURIComponent(previous.id)}`, {method: 'DELETE'});
  const remainingDomains = await api.all(`${accountPath}/workers/domains`);
  if (remainingDomains.some(item => item.hostname === LEGACY_HOSTNAME)) throw new Error('The legacy custom domain is still attached; DNS cleanup stopped.');
  const current = await api.all(`zones/${legacy.zoneId}/dns_records?name=${LEGACY_HOSTNAME}`);
  const addressRecords = current.filter(record => record.name === LEGACY_HOSTNAME && ['A', 'AAAA', 'CNAME'].includes(record.type));
  const snapshots = new Map(legacy.records.map(record => [record.id, dnsIdentity(record)]));
  if (addressRecords.some(record => snapshots.get(record.id) !== dnsIdentity(record))) {
    throw new Error('Legacy DNS changed after the ownership snapshot; no remaining DNS records were deleted.');
  }
  for (const record of addressRecords) await api(`zones/${legacy.zoneId}/dns_records/${encodeURIComponent(record.id)}`, {method: 'DELETE'});
  const remainingRecords = await api.all(`zones/${legacy.zoneId}/dns_records?name=${LEGACY_HOSTNAME}`);
  if (remainingRecords.some(record => record.name === LEGACY_HOSTNAME && ['A', 'AAAA', 'CNAME'].includes(record.type))) {
    throw new Error('Legacy address records remain after cleanup; the new dashboard is protected but cleanup needs review.');
  }
  return {legacyCleaned: true, legacyCleanupStatus: 'completed'};
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
  const environment = {...process.env};
  delete environment.CLOUDFLARE_ADMIN_API_TOKEN;
  const code = await new Promise((done, fail) => {
    const child = spawn(process.execPath, [executable, 'deploy', '--config', configPath], {
      cwd: serviceRoot, shell: false, stdio: 'inherit',
      env: {...environment, CLOUDFLARE_API_TOKEN: token, CLOUDFLARE_ACCOUNT_ID: ACCOUNT_ID, WRANGLER_SEND_METRICS: 'false', CI: 'true'},
    });
    child.once('error', fail); child.once('close', done);
  });
  if (code !== 0) throw new Error('Cloudflare dashboard deployment failed.');
}

export async function deploy({token = process.env.CLOUDFLARE_API_TOKEN, accessToken = process.env.CLOUDFLARE_ADMIN_API_TOKEN, emails = process.env.TELEMETRY_ADMIN_EMAILS,
  request = fetch, run = runWrangler, save = async (path, config) => {
    await mkdir(dirname(path), {recursive: true}); await writeFile(path, JSON.stringify(config, null, 2));
  }, sourceConfig} = {}) {
  const selected = credentials(token, accessToken);
  const target = await prepareDeployment({token: selected.workerToken, accessToken: selected.accessToken, emails, request});
  const config = sourceConfig ?? JSON.parse(await readFile(resolve(serviceRoot, 'wrangler.jsonc'), 'utf8'));
  // Validate local configuration before creating even the Access application.
  const configPath = resolve(serviceRoot, '.wrangler/admin-production.json');
  productionConfig(config, {issuer: target.issuer, audience: '0'.repeat(64)}, configPath);
  const access = await ensureAccess(target);
  await save(configPath, productionConfig(config, access, configPath));
  await run(configPath, selected.workerToken);
  const settings = await target.api(`${accountPath}/workers/scripts/${WORKER}/subdomain`);
  if (settings?.enabled !== false || settings?.previews_enabled !== false) throw new Error('workers.dev or preview URLs are still enabled; deployment is not considered protected.');
  await verifyProtection(access.issuer, request);
  const cleanup = await cleanupLegacy(target);
  return {hostname: HOSTNAME, worker: WORKER, accessProtected: true, workersDevDisabled: true, ...cleanup};
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (!['probe', 'deploy'].includes(process.argv[2])) throw new Error('Expected command: probe or deploy');
    console.log(JSON.stringify(process.argv[2] === 'probe' ? await probe() : await deploy(), null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
