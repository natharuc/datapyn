import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {dashboardQueries, assembleDashboard} from '../../services/telemetry-admin/src/analytics.ts';
import {parseFilters} from '../../services/telemetry-admin/src/filters.ts';
import {ACCOUNT_ID} from './telemetry-admin.mjs';

// Request-level scope replaces the binding's automatic account scope. These
// are the same fixed queries as the Worker; no arbitrary SQL is accepted.
export async function checkQueries(token = process.env.CLOUDFLARE_API_TOKEN, request = fetch, now = Date.now()) {
  if (!token) throw new Error('Configure the Cloudflare API token in a private environment or GitHub secret.');
  const filters = parseFilters(new URLSearchParams({period: '7d'}), now);
  const results = await Promise.all(dashboardQueries(filters).map(async (query, index) => {
    let response;
    try {
      response = await request('https://api.cloudflare.com/client/v4/analytics/sql', {
        method: 'POST', headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
        body: JSON.stringify({...query, scope: {accountTag: ACCOUNT_ID}}), signal: AbortSignal.timeout(20_000),
      });
    } catch { throw new Error(`Telemetry query ${index + 1} could not reach Analytics SQL.`); }
    if (!response.ok) throw new Error(`Telemetry query ${index + 1} returned HTTP ${response.status}. Check Account Analytics Read and SQL API dataset access.`);
    let payload;
    try { payload = await response.json(); }
    catch { throw new Error(`Telemetry query ${index + 1} returned invalid JSON.`); }
    if (!Array.isArray(payload.data)) throw new Error(`Telemetry query ${index + 1} returned an invalid result contract.`);
    return payload.data;
  }));
  try { assembleDashboard(filters, ...results, now); }
  catch { throw new Error('The real telemetry query results did not match the validated dashboard contract.'); }
  // Public CI logs contain only checks and row counts, never telemetry rows.
  return {validated: true, queries: results.map((rows, index) => ({query: index + 1, rows: rows.length}))};
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { console.log(JSON.stringify(await checkQueries(), null, 2)); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
