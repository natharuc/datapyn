import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve, dirname} from 'node:path';
import {probe, cloudflare, ACCOUNT_ID, HOSTNAME, WORKER, APP_NAME, OTP_NAME, parseEmails,
  prepareDeployment, validateApplication, productionConfig, verifyProtection, deploy} from './telemetry-admin.mjs';

test('probe uses exact requested zone and emits no identity-provider secrets', async () => {
  const paths = [];
  const request = async (url, options) => {
    paths.push(url);
    assert.equal(options.headers.Authorization, 'Bearer test-token');
    let result = [];
    if (url.includes('/zones?')) result = [{name: 'docfis.com', status: 'active', account: {id: ACCOUNT_ID}}];
    if (url.endsWith('/organizations')) result = {auth_domain: 'example.cloudflareaccess.com'};
    if (url.endsWith('/identity_providers')) result = [{type: 'onetimepin', config: {client_secret: 'do-not-print'}}];
    return Response.json({success: true, result});
  };
  const results = await probe('test-token', request);
  assert.equal(results[0].expectedAccount, true);
  assert.equal(results[0].active, true);
  assert.match(paths[0], /zones\?name=docfis.com$/);
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
    zones: [{id: 'zone-id', name: 'docfis.com', status: 'active', account: {id: ACCOUNT_ID}}],
    domains: [], records: [], scripts: [], organization: {auth_domain: 'test.cloudflareaccess.com'},
    providers: [], apps: [], policies: basePolicies(), subdomain: {enabled: false, previews_enabled: false}, ...overrides,
  };
  const calls = [];
  const request = async (url, options = {}) => {
    const parsed = new URL(url);
    const path = parsed.pathname.replace('/client/v4/', '');
    const method = options.method ?? 'GET';
    calls.push({path, method, body: options.body});
    if (parsed.hostname === HOSTNAME) return new Response(null, {status: 302, headers: {Location: `${issuer}/cdn-cgi/access/login/${HOSTNAME}`}});
    const wrap = result => Response.json({success: true, result});
    if (path === 'analytics/sql/introspection') return Response.json({datasets: [{name: 'events.analyticsEngine.datapyn_telemetry', columns: [{name: 'timestamp'}, {name: 'sampleInterval'}]}]});
    if (path === 'zones') return wrap(state.zones);
    if (path.endsWith('/workers/domains')) return wrap(state.domains);
    if (path.endsWith('/dns_records')) return wrap(state.records);
    if (path.endsWith('/workers/scripts')) return wrap(state.scripts);
    if (path.endsWith('/access/organizations')) return wrap(state.organization);
    if (path.endsWith('/identity_providers/otp-id')) return wrap(state.providers[0]);
    if (path.endsWith('/access/identity_providers')) {
      if (method === 'POST') state.providers.push({...JSON.parse(options.body), id: 'otp-id'});
      return wrap(method === 'POST' ? state.providers.at(-1) : state.providers);
    }
    if (path.endsWith('/access/apps/app-id/policies')) return wrap(state.policies);
    if (path.endsWith('/access/apps/app-id')) return wrap(state.apps[0]);
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

test('preflight refuses missing, inactive, duplicate or foreign-account docfis.com zones', async () => {
  for (const zones of [[], [{name: 'datapyn.com', status: 'active', account: {id: ACCOUNT_ID}}],
    [{name: 'docfis.com', status: 'pending', account: {id: ACCOUNT_ID}}],
    [{name: 'docfis.com', status: 'active', account: {id: 'another-account'}}],
    [1, 2].map(() => ({name: 'docfis.com', status: 'active', account: {id: ACCOUNT_ID}}))]) {
    const fake = fixture({zones});
    await assert.rejects(prepareDeployment({token: 'test', emails: email, request: fake.request}), /active docfis.com/);
    assert.ok(fake.calls.every(call => call.method === 'GET'));
  }
});

test('preflight preserves unrelated DNS, domains, Workers, wildcard and path Access apps', async () => {
  for (const overrides of [
    {records: [{name: HOSTNAME, type: 'CNAME', content: 'another-service.example.com'}]},
    {domains: [{hostname: HOSTNAME, service: 'another-worker'}]},
    {scripts: [{id: WORKER}]},
    {domains: [{hostname: 'other.docfis.com', service: WORKER}]},
    {apps: [{...baseApp(), name: 'Another app'}]},
    {apps: [{...baseApp(), domain: `${HOSTNAME}/api`}]},
    {apps: [{...baseApp(), domain: '*.docfis.com'}]},
    {apps: [{...baseApp(), domain: 'other.docfis.com'}]},
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
    {options_preflight_bypass: true}, {domain: 'other.docfis.com'}, {self_hosted_domains: ['another.example.com']}]) {
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
