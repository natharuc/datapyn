import test from 'node:test';
import assert from 'node:assert/strict';
import {probe, cloudflare, ACCOUNT_ID} from './telemetry-admin.mjs';

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
