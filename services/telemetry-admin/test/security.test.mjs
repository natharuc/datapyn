import assert from "node:assert/strict";
import {test} from "node:test";
import {generateKeyPair, exportJWK, createLocalJWKSet, SignJWT} from "jose";
import {createHandler} from "../src/index.ts";
import {verifyAccess, accessConfiguration} from "../src/auth.ts";
import {parseFilters} from "../src/filters.ts";

const {privateKey,publicKey} = await generateKeyPair("RS256");
const jwk = await exportJWK(publicKey); jwk.kid = "test-key";
const resolver = createLocalJWKSet({keys:[jwk]});
const settings = {ACCESS_TEAM_DOMAIN:"https://datapyn-test.cloudflareaccess.com",ACCESS_AUD:"a".repeat(64)};
const now = Date.now();
async function token(overrides={}) {
  return new SignJWT({...overrides}).setProtectedHeader({alg:"RS256",kid:"test-key"})
    .setIssuer(settings.ACCESS_TEAM_DOMAIN).setAudience(settings.ACCESS_AUD).setSubject("test-user")
    .setIssuedAt(Math.floor(now/1000)).setExpirationTime(Math.floor(now/1000)+300).sign(privateKey);
}
async function signed(payload={},options={}) {
  return new SignJWT({iss:settings.ACCESS_TEAM_DOMAIN,aud:settings.ACCESS_AUD,sub:"test-user",iat:Math.floor(now/1000),exp:Math.floor(now/1000)+300,...payload})
    .setProtectedHeader({alg:"RS256",kid:"test-key",...options}).sign(privateKey);
}
const req = (path,assertion,origin="https://painel.docfis.com") => new Request(origin+path,{headers:assertion?{"Cf-Access-Jwt-Assertion":assertion}:{}});
const ctx = {waitUntil(){throw new Error("must not write cache");}};

test("requires strict configured Access issuer/audience, never accepts a placeholder",()=>{
  assert.throws(()=>accessConfiguration({ACCESS_TEAM_DOMAIN:"",ACCESS_AUD:""}));
  assert.throws(()=>accessConfiguration({...settings,ACCESS_TEAM_DOMAIN:"https://attacker.example"}));
  assert.throws(()=>accessConfiguration({...settings,ACCESS_AUD:"other"}));
});
test("verifies authentic RS256 assertion, issuer, audience, signature, expiry and not-before",async()=>{
  await verifyAccess(req("/",await token()),settings,resolver);
  for (const payload of [
    {iss:"https://attacker.cloudflareaccess.com"},{aud:"b".repeat(64)},
    {exp:Math.floor(now/1000)-1},{nbf:Math.floor(now/1000)+3600},{exp:undefined},{sub:undefined},{iat:undefined},
  ]) await assert.rejects(verifyAccess(req("/",await signed(payload)),settings,resolver));
  const valid = await token();
  const parts=valid.split("."); parts[2]=parts[2].slice(0,-8)+"AAAAAAAA";
  await assert.rejects(verifyAccess(req("/",parts.join(".")),settings,resolver));
  await assert.rejects(verifyAccess(req("/","eyJhbGciOiJub25lIn0.e30."),settings,resolver));
  await assert.rejects(verifyAccess(req("/"),settings,resolver));
});
test("denies unauthenticated UI, static assets, health and API before touching assets, queries or cached data",async()=>{
  let touches=0;
  const app=createHandler({resolver,cache:{match(){touches++;throw Error();}}});
  const env={...settings,ASSETS:{fetch(){touches++;throw Error();}},ANALYTICS_SQL:{query(){touches++;throw Error();}}};
  for(const path of ["/","/app.js","/styles.css","/health","/api/dashboard"]){
    const response=await app.fetch(req(path),env,ctx);
    assert.equal(response.status,403);
    assert.equal(response.headers.get("Cache-Control"),"no-store");
    assert.equal(response.headers.get("X-Frame-Options"),"DENY");
  }
  assert.equal(touches,0);
});
test("workers.dev, version URLs, alternate hosts, plaintext and non-default ports cannot bypass Access",async()=>{
  const app=createHandler({resolver}),assertion=await token();
  for(const host of ["https://datapyn-telemetry-admin.account.workers.dev","https://abc-datapyn-telemetry-admin.account.workers.dev","https://other.docfis.com","http://painel.docfis.com","https://painel.docfis.com:8443"]){
    assert.equal((await app.fetch(req("/api/dashboard",assertion,host),settings,ctx)).status,403);
  }
});
test("missing Access config fails closed and exposes no UI",async()=>{
  const response=await createHandler().fetch(req("/"),{ACCESS_TEAM_DOMAIN:"",ACCESS_AUD:""},ctx);
  assert.equal(response.status,503); assert.equal((await response.json()).error,"configuration_required");
});
test("authenticated static assets are served with restrictive headers",async()=>{
  const app=createHandler({resolver});
  const response=await app.fetch(req("/app.js",await token()),{...settings,ASSETS:{fetch:async()=>new Response("script",{headers:{"content-type":"text/javascript"}})}},ctx);
  assert.equal(response.status,200); assert.equal(await response.text(),"script");
  assert.match(response.headers.get("Content-Security-Policy"),/script-src 'self'/);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"),null);
});
test("authenticated cached API data still requires a valid assertion; cache responses never become public",async()=>{
  let lookups=0;
  const app=createHandler({resolver,cache:{async match(){lookups++;return Response.json({cached:true},{headers:{"Cache-Control":"public,max-age=60"}});}}});
  const response=await app.fetch(req("/api/dashboard",await token()),settings,ctx);
  assert.equal(response.status,200);assert.equal(lookups,1);
  assert.equal(response.headers.get("Cache-Control"),"no-store");
  assert.equal((await app.fetch(req("/api/dashboard"),settings,ctx)).status,403);assert.equal(lookups,1);
});
test("rejects arbitrary SQL, duplicate/unknown parameters, dev and invalid dates",()=>{
  for(const query of ["sql=DROP+TABLE+datapyn_telemetry","version=1.0.13%27+OR+1%3D1--","platform=windows%27","database=other","version=dev","period=all","period=7d&period=30d","start=2026-10-10T00:00:00Z","start=2026-10-30T00:00:00Z&end=2026-10-31T00:00:00Z","start=2026-02-30T00:00:00Z&end=2026-03-01T00:00:00Z"]){
    assert.throws(()=>parseFilters(new URLSearchParams(query),Date.parse("2026-10-28T12:00:00Z")),query);
  }
});
test("methods and unregistered API paths do not execute queries",async()=>{
  const app=createHandler({resolver}),assertion=await token();
  assert.equal((await app.fetch(new Request("https://painel.docfis.com/api/dashboard",{method:"POST",headers:{"Cf-Access-Jwt-Assertion":assertion}}),settings,ctx)).status,405);
  assert.equal((await app.fetch(req("/api/sql",assertion),settings,ctx)).status,404);
  assert.equal((await app.fetch(req("/__internal/dashboard",assertion),settings,ctx)).status,404);
});
test("authorized API runs the bounded binding queries, stores internal cache and returns only the dashboard contract",async()=>{
  const queries=[],stored=[],pending=[];
  const app=createHandler({resolver,now:()=>Date.parse("2026-10-28T12:00:00Z"),cache:{async match(){return undefined;},async put(key,value){stored.push([key,await value.json(),value.headers.get("Cache-Control")]);}}});
  const env={...settings,ANALYTICS_SQL:{async query(request){queries.push(request);return {data:[],rows:0};}}};
  const response=await app.fetch(req("/api/dashboard?period=24h",await token()),env,{waitUntil(promise){pending.push(promise);}});
  await Promise.all(pending);
  assert.equal(response.status,200);assert.equal(queries.length,4);assert.equal(stored.length,1);
  const data=await response.json();assert.equal(data.summary.executions,0);assert.equal(data.meta.sampled,true);
  assert.equal(data.series.length,24);assert.equal(response.headers.get("Cache-Control"),"no-store");
  assert.match(stored[0][0].url,/\/__internal\/dashboard\?/);assert.equal(stored[0][2],"public, max-age=60");
  assert.equal(JSON.stringify(data).includes("test-user"),false);assert.equal(JSON.stringify(data).includes("ANALYTICS_SQL"),false);
});
