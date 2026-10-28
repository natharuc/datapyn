import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';

export const ACCOUNT_ID = '10d97e9bda1dd76cde34ad2f54c8c37e';
export const ZONE = 'docfis.com';
export const HOSTNAME = 'painel.docfis.com';
export const WORKER = 'datapyn-telemetry-admin';

export function cloudflare(token, request = fetch) {
  if (!token) throw new Error('Configure CLOUDFLARE_API_TOKEN through a local login or GitHub Actions secret.');
  return async function api(path, options = {}) {
    const response = await request(`https://api.cloudflare.com/client/v4/${path}`, {
      ...options,
      headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
      signal: AbortSignal.timeout(20_000),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      // Do not print API bodies: identity-provider configuration can contain credentials.
      throw new Error(`Cloudflare ${options.method ?? 'GET'} ${path.split('?')[0]} returned HTTP ${response.status}. Check token resource scopes and permissions.`);
    }
    return payload.result;
  };
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
  return results;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv[2] !== 'probe') throw new Error('Expected command: probe');
    console.log(JSON.stringify(await probe(), null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
