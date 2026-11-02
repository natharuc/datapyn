import test from 'node:test';
import assert from 'node:assert/strict';
import {checkQueries} from './telemetry-admin-sql.mjs';
import {readFile} from 'node:fs/promises';
import {resolve, dirname} from 'node:path';
import {probe, cloudflare, CloudflareApiError, ACCOUNT_ID, HOSTNAME, LEGACY_HOSTNAME, LEGACY_ZONE, WORKER, APP_NAME, OTP_NAME, parseEmails,
  prepareDeployment, validateApplication, productionConfig, verifyProtection, deploy} from './telemetry-admin.mjs';

test('real-query diagnostic uses fixed account scope without logging telemetry rows', async () => {
  const requests = [];
  const results = await checkQueries('test-token', async (url, options) => {
    requests.push([url, JSON.parse(options.body)]);
    return Response.json({data: [], rows: 0});
  }, Date.parse('2026-10-28T12:00:00Z'));
  assert.equal(results.validated, true);
  assert.equal(requests.length, 4);
  for (const [url, body] of requests) {
    assert.equal(url, 'https://api.cloudflare.com/client/v4/analytics/sql');
    assert.deepEqual(body.scope, {accountTag: ACCOUNT_ID});
    assert.match(body.query, /FROM events\.analyticsEngine\.datapyn_telemetry/);
    assert.match(body.query, /blob2 != 'dev'/);
    assert.equal(body.params.start, '2026-10-21T12:00:00.000Z');
  }
  assert.equal(JSON.stringify(results).includes('test-token'), false);
  await assert.rejects(checkQueries('test-token', async () => Response.json({error: 'do-not-log'}, {status: 403})), error =>
    /HTTP 403/.test(error.message) && !error.message.includes('do-not-log'));
});

test('probe uses exact requested zone and emits no identity-provider secrets', async () => {
  const paths = [];
  const request = async (url, options) => {
    paths.push(url);
    assert.equal(options.headers.Authorization, 'Bearer test-token');
    let result = [];
    if (url.includes('/zones?')) result = [{name: 'datapyn.com', status: 'active', account: {id: ACCOUNT_ID}}];
    if (url.endsWith('/organizations')) result = {auth_domain: 'example.cloudflareaccess.com'};
    if (url.endsWith('/identity_providers')) result = [{type: 'onetimepin', config: {client_secret: 'do-not-print'}}];
    return Response.json({success: true, result});
  };
  const results = await probe('test-token', request);
  assert.equal(results[0].expectedAccount, true);
  assert.equal(results[0].active, true);
  assert.match(paths[0], /zones\?name=datapyn.com$/);
  assert.ok(!JSON.stringify(results).includes('do-not-print'));
});

test('missing and forbidden credentials fail without echoing response bodies', async () => {
  assert.throws(() => cloudflare(''), /Configure/);
  const results = await probe('test-token', async () => Response.json({success:false, errors:[{message:'sensitive'}]}, {status:403}));
  assert.ok(results.every(item => item.ok === false));
  assert.ok(!JSON.stringify(results).includes('sensitive'));
});

const email = 'admin@example.com';
const audience = 'a'.repeat(64);
const issuer = 'https://test.cloudflareaccess.com';
const baseApp = () => ({id: 'app-id', name: APP_NAME, domain: HOSTNAME, type: 'self_hosted', aud: audience,
  allowed_idps: ['otp-id'], allow_authenticate_via_warp: false, options_preflight_bypass: false});
const baseProvider = () => ({id: 'otp-id', name: OTP_NAME, type: 'onetimepin', config: {}});
const basePolicies = () => [{name: 'DataPyn administrators', decision: 'allow', include: [{email: {email}}], require: [], exclude: []}];
const config = JSON.parse(await readFile(new URL('../../services/telemetry-admin/wrangler.jsonc', import.meta.url), 'utf8'));

function fixture(overrides = {}) {
  const state = {
    zones: [{id: 'zone-id', name: 'datapyn.com', status: 'active', account: {id: ACCOUNT_ID}}],
    domains: [], records: [], legacyZones: [], legacyRecords: [], scripts: [], organization: {auth_domain: 'test.cloudflareaccess.com'},
    providers: [], apps: [], policies: basePolicies(), subdomain: {enabled: false, previews_enabled: false}, ...overrides,
  };
  const calls = [];
  const request = async (url, options = {}) => {
    const parsed = new URL(url);
    const path = parsed.pathname.replace('/client/v4/', '');
    const method = options.method ?? 'GET';
    calls.push({path, method, body: options.body, authorization: options.headers?.Authorization});
    if (parsed.hostname === HOSTNAME) return new Response(null, {status: 302, headers: {Location: `${issuer}/cdn-cgi/access/login/${HOSTNAME}`}});
    const wrap = result => Response.json({success: true, result});
    if (path === 'analytics/sql/introspection') return Response.json({datasets: [{name: 'events.analyticsEngine.datapyn_telemetry', columns: [{name: 'timestamp'}, {name: 'sampleInterval'}]}]});
    if (path === 'zones') return wrap(parsed.searchParams.get('name') === LEGACY_ZONE ? state.legacyZones : state.zones);
    if (path.endsWith('/workers/domains')) return wrap(state.domains);
    if (method === 'DELETE' && path.includes('/workers/domains/')) {
      const domainId = path.split('/').at(-1);
      state.domains = state.domains.filter(item => item.id !== domainId);
      if (state.autoDeleteLegacyDns) state.legacyRecords = state.legacyRecords.filter(item => !['A','AAAA','CNAME'].includes(item.type));
      return wrap({id: domainId});
    }
    if (path.endsWith('/dns_records')) return wrap(parsed.searchParams.get('name') === LEGACY_HOSTNAME ? state.legacyRecords : state.records);
    if (method === 'DELETE' && path.includes('/dns_records/')) {
      const recordId = path.split('/').at(-1);
      state.legacyRecords = state.legacyRecords.filter(item => item.id !== recordId);
      return wrap({id: recordId});
    }
    if (path.endsWith('/workers/scripts')) return wrap(state.scripts);
    if (path.endsWith('/access/organizations')) return wrap(state.organization);
    if (path.endsWith('/identity_providers/otp-id')) return wrap(state.providers[0]);
    if (path.endsWith('/access/identity_providers')) {
      if (method === 'POST') state.providers.push({...JSON.parse(options.body), id: 'otp-id'});
      return wrap(method === 'POST' ? state.providers.at(-1) : state.providers);
    }
    if (path.endsWith('/access/apps/app-id/policies')) return wrap(state.policies);
    if (path.endsWith('/access/apps/app-id')) {
      if (method === 'PUT') state.apps[0] = {...state.apps[0], ...JSON.parse(options.body)};
      return wrap(state.apps[0]);
    }
    if (path.endsWith('/access/apps')) {
      if (method === 'POST') {
        const value = JSON.parse(options.body);
        state.policies = value.policies;
        state.apps.push({...value, id: 'app-id', aud: audience});
      }
      return wrap(method === 'POST' ? state.apps.at(-1) : state.apps);
    }
    if (path.endsWith(`/workers/scripts/${WORKER}/subdomain`)) return wrap(state.subdomain);
    throw new Error(`Unmocked request: ${path}`);
  };
  return {state, calls, request};
}

test('email allowlist is private, normalized and exact, with sanitized failures', () => {
  assert.deepEqual(parseEmails('Admin@Example.com,second@example.com\nadmin@example.com'), [email, 'second@example.com']);
  assert.deepEqual(parseEmails('  admin@example.com\r\n'), [email]);
  assert.deepEqual(parseEmails('\n admin@example.com second@example.com \t\n'), [email, 'second@example.com']);
  assert.deepEqual(parseEmails('["admin@example.com"]'), [email]);
  for (const value of ['', '*@example.com', 'example.com', '["secret-identity@example.com"']) {
    assert.throws(() => parseEmails(value), error => !error.message.includes('secret-identity'));
  }
});

test('preflight reads every resource before creating anything', async () => {
  const fake = fixture();
  const target = await prepareDeployment({token: 'test', emails: email, request: fake.request});
  assert.equal(target.issuer, issuer);
  for (const suffix of ['/workers/domains', '/dns_records', '/workers/scripts', '/access/organizations', '/access/identity_providers', '/access/apps']) {
    assert.ok(fake.calls.some(call => call.path.endsWith(suffix)));
  }
  assert.ok(fake.calls.every(call => call.method === 'GET'));
});

test('preflight refuses missing, inactive, duplicate or foreign-account datapyn.com zones', async () => {
  for (const zones of [[], [{name: 'docfis.com', status: 'active', account: {id: ACCOUNT_ID}}],
    [{name: 'datapyn.com', status: 'pending', account: {id: ACCOUNT_ID}}],
    [{name: 'datapyn.com', status: 'active', account: {id: 'another-account'}}],
    [1, 2].map(() => ({name: 'datapyn.com', status: 'active', account: {id: ACCOUNT_ID}}))]) {
    const fake = fixture({zones});
    await assert.rejects(prepareDeployment({token: 'test', emails: email, request: fake.request}), /active datapyn.com/);
    assert.ok(fake.calls.every(call => call.method === 'GET'));
  }
});

test('preflight preserves unrelated DNS, domains, Workers, wildcard and path Access apps', async () => {
  for (const overrides of [
    {records: [{name: HOSTNAME, type: 'CNAME', content: 'another-service.example.com'}]},
    {domains: [{hostname: HOSTNAME, service: 'another-worker'}]},
    {scripts: [{id: WORKER}]},
    {domains: [{hostname: 'other.datapyn.com', service: WORKER}]},
    {apps: [{...baseApp(), name: 'Another app'}]},
    {apps: [{...baseApp(), domain: `${HOSTNAME}/api`}]},
    {apps: [{...baseApp(), domain: '*.datapyn.com'}]},
    {apps: [{...baseApp(), domain: 'other.datapyn.com'}]},
  ]) {
    const fake = fixture(overrides);
    await assert.rejects(prepareDeployment({token: 'test', emails: email, request: fake.request}));
    assert.ok(fake.calls.every(call => call.method === 'GET'));
  }
});

test('missing Zero Trust organization refuses billing setup or any mutation', async () => {
  const fake = fixture({organization: {}});
  await assert.rejects(prepareDeployment({token: 'test', emails: email, request: fake.request}), /Zero Trust Free setup/);
  assert.ok(fake.calls.every(call => call.method === 'GET'));
});

test('Access validation rejects every wider policy and alternate authentication path', () => {
  validateApplication(baseApp(), basePolicies(), baseProvider(), [email]);
  for (const policies of [
    [], [...basePolicies(), ...basePolicies()], [{decision: 'bypass', include: [{everyone: {}}]}],
    [{decision: 'non_identity', include: [{any_valid_service_token: {}}]}],
    [{decision: 'allow', include: [{everyone: {}}]}],
    [{decision: 'allow', include: [{group: {id: 'group-id'}}]}],
    [{decision: 'allow', include: [{email: {email: 'another@example.com'}}]}],
    [{decision: 'allow', include: [{email: {email}}, {email_domain: {domain: 'example.com'}}]}],
  ]) assert.throws(() => validateApplication(baseApp(), policies, baseProvider(), [email]));
  for (const changes of [{aud: 'bad-audience'}, {allowed_idps: ['otp-id', 'other']}, {allow_authenticate_via_warp: true},
    {options_preflight_bypass: true}, {domain: 'other.datapyn.com'}, {self_hosted_domains: ['another.example.com']}]) {
    assert.throws(() => validateApplication({...baseApp(), ...changes}, basePolicies(), baseProvider(), [email]));
  }
});

test('new deployment creates scoped OTP and exact email policy, with no token in generated config', async () => {
  const fake = fixture();
  let saved, executed;
  const result = await deploy({token: 'secret-api-token', emails: email, request: fake.request, sourceConfig: config,
    save: async (path, value) => {saved = {path, value};}, run: async (path, token) => {executed = {path, token};}});
  assert.equal(result.hostname, HOSTNAME);
  assert.equal(saved.value.workers_dev, false);
  assert.equal(saved.value.preview_urls, false);
  assert.equal(saved.value.assets.run_worker_first, true);
  assert.deepEqual(saved.value.routes, [{pattern: HOSTNAME, custom_domain: true}]);
  assert.equal(saved.value.vars.ACCESS_AUD, audience);
  assert.equal(saved.value.vars.ACCESS_TEAM_DOMAIN, issuer);
  assert.equal(resolve(dirname(saved.path), saved.value.main), resolve(dirname(saved.path), '../src/index.ts'));
  assert.equal(resolve(dirname(saved.path), saved.value.assets.directory), resolve(dirname(saved.path), '../public'));
  assert.ok(!JSON.stringify(saved.value).includes('secret-api-token'));
  assert.ok(!JSON.stringify(saved.value).includes(email));
  assert.equal(executed.token, 'secret-api-token');
  assert.deepEqual(fake.state.policies[0].include, [{email: {email}}]);
  assert.deepEqual(fake.calls.filter(call => call.method === 'POST').map(call => call.path.split('/').at(-1)), ['identity_providers', 'apps']);
});

test('rerun reuses validated resources without changing existing authorization', async () => {
  const fake = fixture({providers: [baseProvider()], apps: [baseApp()],
    domains: [{hostname: HOSTNAME, service: WORKER, zone_id: 'zone-id'}], scripts: [{id: WORKER}]});
  await deploy({token: 'test', emails: email, request: fake.request, sourceConfig: config, save: async () => {}, run: async () => {}});
  assert.ok(fake.calls.every(call => call.method !== 'POST'));
  assert.ok(fake.calls.some(call => call.path.endsWith('/apps/app-id/policies')));
});

test('invalid local configuration is rejected before Access writes', async () => {
  const fake = fixture();
  await assert.rejects(deploy({token: 'test', emails: email, request: fake.request, sourceConfig: {...config, assets: {...config.assets, run_worker_first: false}},
    save: async () => assert.fail('must not save'), run: async () => assert.fail('must not deploy')}), /source configuration/);
  assert.ok(fake.calls.every(call => call.method === 'GET'));
});

test('production config forces disabled public alternatives and only the requested domain', () => {
  const value = productionConfig({...config, workers_dev: true, preview_urls: true, route: 'other.example.com/*'},
    {issuer, audience}, 'C:/project/.wrangler/admin-production.json');
  assert.equal(value.workers_dev, false);
  assert.equal(value.preview_urls, false);
  assert.equal(value.route, undefined);
  assert.deepEqual(value.routes, [{pattern: HOSTNAME, custom_domain: true}]);
});

test('anonymous UI and API GET/HEAD accept only Access redirects or unauthorized status', async () => {
  const methods = [];
  await verifyProtection(issuer, async (url, options) => {methods.push([new URL(url).pathname, options.method]); return new Response(null, {status: 401});});
  assert.deepEqual(methods, [['/', 'GET'], ['/', 'HEAD'], ['/api/dashboard', 'GET'], ['/api/dashboard', 'HEAD']]);
  for (const response of [new Response('{}', {status: 200}), new Response(null, {status: 302, headers: {Location: 'https://evil.example/cdn-cgi/access/login'}}),
    new Response(null, {status: 302, headers: {Location: `${issuer}/unrelated`}})]) {
    await assert.rejects(verifyProtection(issuer, async () => response), /did not deny anonymous/);
  }
});

test('protection verification retries initial DNS/TLS and temporary route failures with a fixed bound', async () => {
  let round = 0;
  const waits = [];
  const request = async () => {
    if (round === 0) throw new TypeError('fetch failed');
    if (round === 1) return new Response(null, {status: 503});
    return new Response(null, {status: 403});
  };
  await verifyProtection(issuer, request, {attempts: 3, wait: async milliseconds => {waits.push(milliseconds); round++;}});
  assert.deepEqual(waits, [5000, 5000]);
  let calls = 0;
  await assert.rejects(verifyProtection(issuer, async () => {calls++; return new Response(null, {status: 503});},
    {attempts: 2, wait: async () => {}}), /Anonymous access has not been verified/);
  assert.equal(calls, 8);
});

test('a simultaneous transport failure cannot hide public data or an incorrect redirect', async () => {
  for (const unsafe of [new Response('{}', {status: 200}), new Response(null, {status: 302, headers: {Location: 'https://unrelated.cloudflareaccess.com/cdn-cgi/access/login'}})]) {
    await assert.rejects(verifyProtection(issuer, async (url, options) => {
      if (options.method === 'HEAD') throw new TypeError('fetch failed');
      return unsafe;
    }, {wait: async () => assert.fail('must not retry an anonymous success or unrelated redirect')}), /did not deny anonymous/);
  }
});

test('enabled workers.dev or preview URL fails post-deploy verification', async () => {
  for (const subdomain of [{enabled: true, previews_enabled: false}, {enabled: false, previews_enabled: true}, {enabled: false}]) {
    const fake = fixture({subdomain});
    await assert.rejects(deploy({token: 'test', emails: email, request: fake.request, sourceConfig: config,
      save: async () => {}, run: async () => {}}), /still enabled/);
  }
});

test('probe introspects only fixed dataset metadata and never prints configured identities', async () => {
  const fake = fixture({providers: [{...baseProvider(), config: {secret: 'private-value'}}],
    apps: [{...baseApp(), policies: basePolicies()}]});
  const results = await probe('test', fake.request);
  const schema = results.find(item => item.check === 'analyticsSchema');
  assert.deepEqual(schema.columns, ['timestamp', 'sampleInterval']);
  assert.equal(schema.sampleWeightColumn, 'sampleInterval');
  assert.ok(!JSON.stringify(results).includes(email));
  assert.ok(!JSON.stringify(results).includes('private-value'));
  assert.ok(fake.calls.every(call => call.method === 'GET'));
});

test('split credentials route Access reads and writes to the admin token while Wrangler and infrastructure keep the worker token', async () => {
  const fake = fixture();
  let saved, executedToken;
  const result = await deploy({token: 'worker-test-secret', accessToken: 'access-test-secret', emails: email, request: fake.request, sourceConfig: config,
    save: async (_path, value) => {saved = value;}, run: async (_path, value) => {executedToken = value;}});
  assert.equal(executedToken, 'worker-test-secret');
  const apiCalls = fake.calls.filter(call => call.path.startsWith('accounts/') || call.path.startsWith('zones'));
  assert.ok(apiCalls.some(call => call.path.includes('/access/') && call.method === 'POST'));
  assert.ok(apiCalls.some(call => call.path.endsWith('/subdomain')));
  for (const call of apiCalls) {
    assert.equal(call.authorization, `Bearer ${call.path.includes('/access/') ? 'access-test-secret' : 'worker-test-secret'}`, call.path);
  }
  for (const secret of ['worker-test-secret', 'access-test-secret', email]) {
    assert.equal(JSON.stringify(saved).includes(secret), false);
    assert.equal(JSON.stringify(result).includes(secret), false);
  }
});

test('split probe uses worker credentials for DNS and Analytics metadata and Access credentials only for Access', async () => {
  const fake = fixture();
  const results = await probe({token: 'worker-probe', accessToken: 'access-probe', request: fake.request});
  assert.ok(results.every(check => check.ok));
  for (const call of fake.calls) {
    assert.equal(call.authorization, `Bearer ${call.path.includes('/access/') ? 'access-probe' : 'worker-probe'}`, call.path);
  }
  assert.equal(JSON.stringify(results).includes('worker-probe'), false);
  assert.equal(JSON.stringify(results).includes('access-probe'), false);
  const legacy = await probe('worker-probe', fake.request, 'access-probe');
  assert.ok(legacy.every(check => check.ok));
});

test('single-token callers retain compatibility for either the original token or the admin token', async () => {
  for (const options of [{token: 'only-worker', accessToken: ''}, {token: '', accessToken: 'only-admin'}]) {
    const fake = fixture();
    const expected = options.token || options.accessToken;
    let executedToken;
    await deploy({...options, emails: email, request: fake.request, sourceConfig: config,
      save: async () => {}, run: async (_path, token) => {executedToken = token;}});
    assert.equal(executedToken, expected);
    for (const call of fake.calls.filter(call => call.path.startsWith('accounts/') || call.path.startsWith('zones'))) {
      assert.equal(call.authorization, `Bearer ${expected}`, call.path);
    }
    const checks = await probe({...options, request: fake.request});
    assert.ok(checks.every(check => check.ok));
  }
});

test('paginated Access lists retain admin routing on every page without routing similarly named Worker paths to Access', async () => {
  const calls = [];
  const api = cloudflare('workers-token', async (url, options) => {
    const parsed = new URL(url);
    calls.push([parsed.pathname, parsed.searchParams.get('page'), options.headers.Authorization]);
    return Response.json({success: true, result: [{id: `page-${parsed.searchParams.get('page')}`}], result_info: {total_pages: 2}});
  }, 'access-token');
  assert.equal((await api.all(`accounts/${ACCOUNT_ID}/access/apps`)).length, 2);
  assert.equal((await api.all(`accounts/${ACCOUNT_ID}/workers/domains`)).length, 2);
  await api(`accounts/${ACCOUNT_ID}/workers/scripts/access/metadata`);
  assert.deepEqual(calls.map(call => call[2]), ['Bearer access-token', 'Bearer access-token', 'Bearer workers-token', 'Bearer workers-token', 'Bearer workers-token']);
  assert.deepEqual(calls.slice(0, 2).map(call => call[1]), ['1', '2']);
});

test('API diagnostics distinguish missing organization, permission and invalid token without retaining raw errors', async () => {
  const orgPath = `accounts/${ACCOUNT_ID}/access/organizations`;
  const cases = [
    {status: 403, path: orgPath, code: 10000, message: 'Authentication error', classification: 'permission'},
    {status: 403, path: orgPath, code: 9109, message: 'Unauthorized to access requested resource', classification: 'permission'},
    {status: 403, path: orgPath, code: 9109, message: 'Invalid access token', classification: 'authentication'},
    {status: 401, path: orgPath, code: 10000, message: 'Authentication error', classification: 'authentication'},
    {status: 403, path: orgPath, code: 12100, message: 'Access organization does not exist', classification: 'orgNotConfigured'},
    {status: 403, path: orgPath, code: 12100, message: 'Account has no Zero Trust organization', classification: 'orgNotConfigured'},
    {status: 404, path: `accounts/${ACCOUNT_ID}/workers/domains`, code: 12100, message: 'Organization does not exist', classification: 'apiFailure'},
  ];
  for (const entry of cases) {
    const api = cloudflare('never-echo-worker', async () => Response.json({success: false, errors: [{code: entry.code, message: `${entry.message}; private-identity@example.com private-credential`}], result: {secret: 'raw-body-secret'}}, {status: entry.status}), 'never-echo-admin');
    await assert.rejects(api(entry.path), error => {
      assert.ok(error instanceof CloudflareApiError);
      assert.equal(error.httpStatus, entry.status);
      assert.deepEqual(error.apiCodes, [entry.code]);
      assert.equal(error.classification, entry.classification);
      for (const secret of ['private-identity@example.com', 'private-credential', 'raw-body-secret', 'never-echo-worker', 'never-echo-admin']) {
        assert.equal(`${error.message} ${JSON.stringify(error)}`.includes(secret), false);
      }
      return true;
    });
  }
});

test('probe publishes only numeric API codes and fixed cause labels, including nested codes', async () => {
  const checks = await probe({token: 'workers-secret', accessToken: 'access-secret', request: async url => {
    const organization = new URL(url).pathname.endsWith('/access/organizations');
    return Response.json({success: false, errors: [{code: 10000, message: organization ? 'Organization not configured: personal@example.com' : 'Authentication error: personal@example.com', error_chain: [{code: 9109, message: 'private upstream credential'}, {code: 'do-not-output'}]}]}, {status: 403});
  }});
  for (const check of checks) {
    if (check.skipped) { assert.equal(check.classification, 'accessScopeUnavailable'); continue; }
    assert.equal(check.ok, false); assert.equal(check.httpStatus, 403);
    assert.deepEqual(check.apiCodes, [10000, 9109]);
    assert.equal(check.classification, check.check === 'organization' ? 'orgNotConfigured' : 'permission');
  }
  assert.doesNotMatch(JSON.stringify(checks), /personal@example|private upstream|do-not-output|workers-secret|access-secret/);
});

test('transport and malformed JSON diagnostics suppress exceptions and response text', async () => {
  const network = await probe({token: 'test', request: async () => {throw new Error('private transport token');}});
  assert.ok(network.every(check => check.skipped || (check.classification === 'transport' && check.httpStatus === null)));
  const malformed = await probe({token: 'test', request: async () => new Response('private non-JSON response', {status: 403})});
  assert.ok(malformed.every(check => check.skipped || (check.classification === 'invalidResponse' && check.httpStatus === 403)));
  assert.doesNotMatch(JSON.stringify([...network, ...malformed]), /private transport|private non-JSON/);
});

test('account permission refusal falls back to the verified zone and uses that Access prefix consistently for all reads and writes', async () => {
  const fake = fixture(), calls = [];
  const request = async (url, options) => {
    const path = new URL(url).pathname.replace('/client/v4/', '');
    calls.push({path, method: options.method ?? 'GET', authorization: options.headers?.Authorization});
    if (path === `accounts/${ACCOUNT_ID}/access/organizations`) return Response.json({success: false, errors: [{code: 10000, message: 'Authentication error'}]}, {status: 403});
    return fake.request(url, options);
  };
  const result = await deploy({token: 'worker-token', accessToken: 'admin-token', emails: email, request, sourceConfig: config,
    save: async () => {}, run: async (_path, token) => assert.equal(token, 'worker-token')});
  assert.equal(result.accessProtected, true);
  const accessCalls = calls.filter(call => call.path.includes('/access/'));
  assert.equal(accessCalls[0].path, `accounts/${ACCOUNT_ID}/access/organizations`);
  assert.ok(accessCalls.length > 6);
  for (const call of accessCalls.slice(1)) {
    assert.ok(call.path.startsWith('zones/zone-id/access/'), call.path);
    assert.equal(call.authorization, 'Bearer admin-token');
  }
  assert.ok(accessCalls.some(call => call.path === 'zones/zone-id/access/apps/app-id/policies'));
  assert.deepEqual(accessCalls.filter(call => call.method === 'POST').map(call => call.path), ['zones/zone-id/access/identity_providers', 'zones/zone-id/access/apps']);
  const checks = await probe({token: 'worker-token', accessToken: 'admin-token', request});
  assert.equal(checks.find(check => check.check === 'organization').scope, 'zone');
  assert.ok(checks.every(check => check.ok));
});

test('zone-scoped fallback validates existing policies instead of assuming that failed account listing means no application', async () => {
  const fake = fixture({providers: [baseProvider()], apps: [baseApp()], policies: [{decision: 'bypass', include: [{everyone: {}}]}]});
  const request = async (url, options) => new URL(url).pathname.endsWith(`/accounts/${ACCOUNT_ID}/access/organizations`)
    ? Response.json({success: false, errors: [{code: 10000, message: 'Authentication error'}]}, {status: 403})
    : fake.request(url, options);
  await assert.rejects(deploy({token: 'test', accessToken: 'admin', emails: email, request, sourceConfig: config,
    save: async () => assert.fail('must not save'), run: async () => assert.fail('must not publish')}), /exactly one allow policy/);
  assert.ok(fake.calls.some(call => call.path === 'zones/zone-id/access/apps/app-id/policies'));
  assert.ok(fake.calls.every(call => call.method === 'GET'));
});

test('refusal from both Access scopes is reported as unresolved without identity lists or mutations', async () => {
  const fake = fixture(), attempts = [];
  const request = async (url, options) => {
    const path = new URL(url).pathname.replace('/client/v4/', '');
    if (path.endsWith('/access/organizations')) {
      attempts.push(path);
      return Response.json({success: false, errors: [{code: 10000, message: 'Authentication error private-token personal@example.com'}]}, {status: 403});
    }
    return fake.request(url, options);
  };
  await assert.rejects(deploy({token: 'original', accessToken: 'admin', emails: email, request, sourceConfig: config,
    save: async () => assert.fail('must not save'), run: async () => assert.fail('must not publish')}), error => {
    assert.equal(error.name, 'AccessScopeError'); assert.equal(error.attempts.length, 2);
    assert.deepEqual(error.attempts.map(attempt => [attempt.scope, attempt.httpStatus, attempt.classification]), [['account', 403, 'permission'], ['zone', 403, 'permission']]);
    assert.doesNotMatch(`${error.message} ${JSON.stringify(error)}`, /private-token|personal@example/);
    return true;
  });
  assert.deepEqual(attempts, [`accounts/${ACCOUNT_ID}/access/organizations`, 'zones/zone-id/access/organizations']);
  assert.ok(fake.calls.every(call => call.method === 'GET'));
  assert.ok(!fake.calls.some(call => /\/access\/(?:apps|identity_providers)/.test(call.path)));
  const checks = await probe({token: 'original', accessToken: 'admin', request});
  const organization = checks.find(check => check.check === 'organization');
  assert.equal(organization.classification, 'accessScopeUnavailable'); assert.equal(organization.attempts.length, 2);
  assert.ok(checks.filter(check => ['identityProviders', 'accessApplications'].includes(check.check)).every(check => check.skipped));
});

test('legacy Access scope is never tried for rejected credentials, absent organization, server failure, transport failure or unverified zone', async () => {
  for (const failure of [
    () => Response.json({success: false, errors: [{code: 9109, message: 'Invalid access token'}]}, {status: 403}),
    () => Response.json({success: false, errors: [{code: 12100, message: 'Organization does not exist'}]}, {status: 403}),
    () => Response.json({success: false, errors: []}, {status: 500}),
    () => {throw new Error('network private failure');},
  ]) {
    const fake = fixture(), paths = [];
    const request = async (url, options) => {
      const path = new URL(url).pathname.replace('/client/v4/', ''); paths.push(path);
      if (path === `accounts/${ACCOUNT_ID}/access/organizations`) return failure();
      return fake.request(url, options);
    };
    await assert.rejects(prepareDeployment({token: 'test', accessToken: 'admin', emails: email, request}));
    assert.ok(!paths.some(path => path.startsWith('zones/zone-id/access/')));
    assert.ok(fake.calls.every(call => call.method === 'GET'));
  }
  for (const zones of [[], [{id: 'zone-id', name: 'datapyn.com', status: 'pending', account: {id: ACCOUNT_ID}}],
    [{id: 'zone-id', name: 'datapyn.com', status: 'active', account: {id: 'other'}}]]) {
    const fake = fixture({zones}), paths = [];
    const request = async (url, options) => {
      const path = new URL(url).pathname.replace('/client/v4/', ''); paths.push(path);
      if (path === `accounts/${ACCOUNT_ID}/access/organizations`) return Response.json({success: false, errors: [{code: 10000, message: 'Authentication error'}]}, {status: 403});
      return fake.request(url, options);
    };
    await probe({token: 'test', accessToken: 'admin', request});
    assert.ok(!paths.some(path => path.startsWith('zones/zone-id/access/')));
  }
});

test('only official developer documentation URLs are retained, with credentials, queries, fragments and long paths removed', async () => {
  const links = ['https://developers.cloudflare.com/fundamentals/api/reference/permissions/?token=private-query#private-fragment',
    'https://private-user:private-password@developers.cloudflare.com/api/', 'http://developers.cloudflare.com/api/',
    'https://developers.cloudflare.com.evil.example/api/', 'https://developers.cloudflare.com:444/api/',
    'https://evil.example/api/', 'https://developers.cloudflare.com/'+ 'x'.repeat(513), '/relative'];
  const api = cloudflare('test', async () => Response.json({success: false, errors: links.map(documentation_url => ({code: 10000, message: 'sensitive message', documentation_url}))}, {status: 403}));
  await assert.rejects(api(`accounts/${ACCOUNT_ID}/access/organizations`), error => {
    assert.deepEqual(error.documentationUrls, ['https://developers.cloudflare.com/fundamentals/api/reference/permissions/', 'https://developers.cloudflare.com/api/']);
    assert.doesNotMatch(`${error.message} ${JSON.stringify(error)}`, /private-query|private-fragment|private-user|private-password|evil\.example|sensitive message/);
    return true;
  });
});

const oldDomain = () => ({id: 'old-domain-id', hostname: LEGACY_HOSTNAME, service: WORKER, zone_id: 'old-zone-id'});
const newDomain = () => ({id: 'new-domain-id', hostname: HOSTNAME, service: WORKER, zone_id: 'zone-id'});
const oldRecord = () => ({id: 'old-record-id', name: LEGACY_HOSTNAME, type: 'AAAA', content: '100::', proxied: true, ttl: 1});
function migrationFixture(overrides = {}) {
  return fixture({domains: [oldDomain()], scripts: [{id: WORKER}], providers: [baseProvider()],
    apps: [{...baseApp(), domain: LEGACY_HOSTNAME, destinations: [{type: 'public', uri: LEGACY_HOSTNAME}], self_hosted_domains: [LEGACY_HOSTNAME]}],
    policies: [{...basePolicies()[0], id: 'policy-id', precedence: 1}],
    legacyZones: [{id: 'old-zone-id', name: LEGACY_ZONE, status: 'active', account: {id: ACCOUNT_ID}}],
    legacyRecords: [oldRecord()], ...overrides});
}
async function migrate(fake, extra = {}) {
  return deploy({token: 'worker', accessToken: 'admin', emails: email, request: fake.request, sourceConfig: config,
    save: async () => {}, run: async () => {fake.calls.push({path: 'mock-deploy', method: 'DEPLOY'}); fake.state.domains.push(newDomain());}, ...extra});
}

test('migration moves the same Access application and policy, verifies the new host, then removes only owned legacy routing and unchanged address records', async () => {
  const unrelated = {id: 'collector-domain', hostname: 'telemetry.datapyn.com', service: 'datapyn-telemetry', zone_id: 'zone-id'};
  const txt = {id: 'legacy-txt', name: LEGACY_HOSTNAME, type: 'TXT', content: 'keep unrelated verification'};
  const fake = migrationFixture({domains: [oldDomain(), unrelated], legacyRecords: [oldRecord(), txt]});
  const result = await migrate(fake);
  assert.equal(result.hostname, 'painel.datapyn.com'); assert.equal(result.legacyCleaned, true);
  assert.equal(fake.state.apps.length, 1); assert.equal(fake.state.apps[0].id, 'app-id');
  assert.equal(fake.state.apps[0].domain, HOSTNAME); assert.equal(fake.state.apps[0].aud, audience);
  assert.deepEqual(fake.state.apps[0].destinations, [{type: 'public', uri: HOSTNAME}]);
  const update = fake.calls.find(call => call.path.endsWith('/access/apps/app-id') && call.method === 'PUT');
  assert.deepEqual(JSON.parse(update.body).policies, [{id: 'policy-id', precedence: 1}]);
  assert.deepEqual(fake.state.policies[0].include, [{email: {email}}]);
  assert.ok(!fake.calls.some(call => call.method === 'POST'));
  const deployment = fake.calls.findIndex(call => call.path === 'mock-deploy');
  const verified = fake.calls.map((call,index) => [call,index]).filter(([call]) => call.path === '/' || call.path === '/api/dashboard');
  const removals = fake.calls.map((call,index) => [call,index]).filter(([call]) => call.method === 'DELETE');
  assert.equal(verified.length, 4); assert.ok(verified.every(([,index]) => index > deployment));
  assert.ok(removals.every(([,index]) => index > verified.at(-1)[1]));
  assert.deepEqual(removals.map(([call]) => call.path), [`accounts/${ACCOUNT_ID}/workers/domains/old-domain-id`, 'zones/old-zone-id/dns_records/old-record-id']);
  assert.deepEqual(fake.state.legacyRecords, [txt]);
  assert.ok(fake.state.domains.some(domain => domain.id === 'collector-domain'));
  assert.ok(!fake.calls.some(call => /\/ssl\/|\/certificates\//.test(call.path)));
});

test('migration tolerates Wrangler automatically detaching the old domain and DNS after its preflight ownership snapshot', async () => {
  const fake = migrationFixture();
  const result = await migrate(fake, {run: async () => {
    fake.state.domains = [newDomain()]; fake.state.legacyRecords = [];
  }});
  assert.equal(result.legacyCleaned, true);
  assert.ok(!fake.calls.some(call => call.method === 'DELETE'));
});

test('migration removes unchanged DNS remnants when Wrangler detached only the old custom domain', async () => {
  const fake = migrationFixture();
  await migrate(fake, {run: async () => {fake.state.domains = [newDomain()];}});
  assert.deepEqual(fake.calls.filter(call => call.method === 'DELETE').map(call => call.path), ['zones/old-zone-id/dns_records/old-record-id']);
});

test('rerun after Access hostname migration reuses the new application while completing legacy domain cleanup', async () => {
  const fake = migrationFixture({apps: [baseApp()]});
  await migrate(fake);
  assert.ok(!fake.calls.some(call => ['POST','PUT'].includes(call.method)));
  assert.ok(fake.calls.some(call => call.method === 'DELETE' && call.path.endsWith('/old-domain-id')));
  fake.calls.length = 0;
  const result = await deploy({token: 'worker', accessToken: 'admin', emails: email, request: fake.request, sourceConfig: config,
    save: async () => {}, run: async () => {}});
  assert.equal(result.legacyCleaned, false);
  assert.ok(fake.calls.every(call => ['GET','HEAD'].includes(call.method)));
});

test('destination collisions, ambiguous Worker ownership and wider legacy policies stop before any migration write', async () => {
  const cases = [
    {records: [{id: 'someone-else', name: HOSTNAME, type: 'CNAME', content: 'other.example.com'}]},
    {domains: [oldDomain(), {...newDomain(), service: 'other-worker'}]},
    {domains: [{...oldDomain(), service: 'other-worker'}]},
    {domains: [oldDomain(), {id: 'unrelated', hostname: 'other.example.com', service: WORKER}]},
    {legacyZones: [{id: 'old-zone-id', name: LEGACY_ZONE, status: 'active', account: {id: 'wrong-account'}}]},
    {legacyZones: []},
    {policies: [{id: 'policy-id', decision: 'bypass', include: [{everyone: {}}]}]},
    {policies: [{...basePolicies()[0], id: 'policy-id', include: [{email_domain: {domain: 'example.com'}}]}]},
    {apps: [{...baseApp(), domain: LEGACY_HOSTNAME}, baseApp()]},
  ];
  for (const changes of cases) {
    const fake = migrationFixture(changes);
    await assert.rejects(migrate(fake, {run: async () => assert.fail('must not publish')}));
    assert.ok(fake.calls.every(call => call.method === 'GET'));
  }
});

test('legacy cleanup never runs after a deployment or authentication protection failure', async () => {
  const failingDeploy = migrationFixture();
  await assert.rejects(migrate(failingDeploy, {run: async () => {throw new Error('deploy failed');}}), /deploy failed/);
  assert.ok(!failingDeploy.calls.some(call => call.method === 'DELETE'));
  const publicHost = migrationFixture();
  const request = async (url, options) => new URL(url).hostname === HOSTNAME ? new Response('{}', {status: 200}) : publicHost.request(url, options);
  await assert.rejects(migrate(publicHost, {request}), /did not deny anonymous/);
  assert.ok(!publicHost.calls.some(call => call.method === 'DELETE'));
});

test('migration preserves pre-existing real or DNS-only origins before changing Access or deploying', async () => {
  for (const record of [
    {...oldRecord(), type: 'A', content: '198.51.100.20', proxied: false},
    {...oldRecord(), type: 'CNAME', content: 'unrelated.example.com'},
    {...oldRecord(), content: '2001:db8::1'},
    {...oldRecord(), proxied: false},
  ]) {
    const fake = migrationFixture({legacyRecords: [record]});
    await assert.rejects(migrate(fake), /without a verified Worker-managed origin/);
    assert.ok(fake.calls.every(call => call.method === 'GET'));
    assert.deepEqual(fake.state.legacyRecords, [record]);
  }
});

test('cleanup refuses changed legacy ownership, missing destination proof and DNS changes without deleting the changed records', async () => {
  for (const mutate of [
    fake => {fake.state.domains = [newDomain(), {...oldDomain(), service: 'other-worker'}];},
    fake => {fake.state.domains = [];},
    fake => {fake.state.domains = [newDomain(), oldDomain()]; fake.state.legacyRecords[0].content = '2001:db8::1';},
    fake => {fake.state.domains = [newDomain(), oldDomain()]; fake.state.legacyRecords = [{...oldRecord(), id: 'new-owner-record'}];},
  ]) {
    const fake = migrationFixture();
    await assert.rejects(migrate(fake, {run: async () => mutate(fake)}));
    assert.ok(!fake.calls.some(call => call.method === 'DELETE' && call.path.includes('/dns_records/')));
  }
});

test('a retry after automatic legacy detach does not silently ignore remaining DNS without an ownership snapshot', async () => {
  const fake = migrationFixture({domains: [newDomain()], apps: [baseApp()]});
  await assert.rejects(migrate(fake), /cleanup is pending explicit DNS ownership review/);
  assert.ok(fake.calls.every(call => call.method === 'GET'));
  assert.ok(fake.state.legacyRecords.some(record => record.id === 'old-record-id'));
});

test('normal datapyn deployments preserve a subsequently unrelated service at the former DocFis hostname', async () => {
  const fake = migrationFixture({domains: [newDomain(), {...oldDomain(), service: 'unrelated-worker'}],
    apps: [baseApp(), {...baseApp(), id: 'unrelated-app', name: 'Unrelated service', domain: LEGACY_HOSTNAME}]});
  const result = await deploy({token: 'worker', accessToken: 'admin', emails: email, request: fake.request, sourceConfig: config,
    save: async () => {}, run: async () => {}});
  assert.equal(result.legacyCleanupStatus, 'notApplicable');
  assert.ok(!fake.calls.some(call => ['DELETE','PUT','POST'].includes(call.method)));
  assert.ok(!fake.calls.some(call => call.path.startsWith('zones/old-zone-id/')));
});
