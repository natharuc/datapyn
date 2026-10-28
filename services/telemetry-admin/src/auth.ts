import {createRemoteJWKSet, jwtVerify, type JWTVerifyGetKey} from "jose";

export class ConfigurationError extends Error {}
export class AccessError extends Error {}

export type AccessConfig = {ACCESS_TEAM_DOMAIN: string; ACCESS_AUD: string};
// Cache public signing keys only; never retain assertions or identity claims.
const keySets = new Map<string, ReturnType<typeof createRemoteJWKSet>>();

export function accessConfiguration(env: AccessConfig) {
  const issuer = env.ACCESS_TEAM_DOMAIN;
  if (!/^https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com$/.test(issuer)
    || !/^[a-f0-9]{64}$/.test(env.ACCESS_AUD)) throw new ConfigurationError();
  return {issuer, audience: env.ACCESS_AUD};
}

export async function verifyAccess(request: Request, env: AccessConfig, resolver?: JWTVerifyGetKey) {
  const config = accessConfiguration(env);
  const token = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!token || token.length > 16_384) throw new AccessError();
  if (!resolver) {
    resolver = keySets.get(config.issuer);
    if (!resolver) {
      resolver = createRemoteJWKSet(new URL(`${config.issuer}/cdn-cgi/access/certs`), {timeoutDuration: 5_000});
      if (keySets.size >= 4) keySets.clear();
      keySets.set(config.issuer, resolver as ReturnType<typeof createRemoteJWKSet>);
    }
  }
  try {
    await jwtVerify(token, resolver, {
      issuer: config.issuer, audience: config.audience, algorithms: ["RS256"],
      requiredClaims: ["exp", "iat", "sub"], clockTolerance: 0,
    });
  } catch { throw new AccessError(); }
}
