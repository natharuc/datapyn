import {type JWTVerifyGetKey} from "jose";
import {AccessError, ConfigurationError, verifyAccess} from "./auth.ts";
import {AnalyticsError, loadDashboard} from "./analytics.ts";
import {FilterError, parseFilters} from "./filters.ts";

const securityHeaders = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "same-origin",
  "X-Frame-Options": "DENY",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
};
function secure(response: Response, method: string) {
  const headers = new Headers(response.headers);
  for (const [key,value] of Object.entries(securityHeaders)) headers.set(key,value);
  return new Response(method === "HEAD" ? null : response.body,{status:response.status,statusText:response.statusText,headers});
}
function error(code: string,message: string,status: number) {
  return Response.json({error:code,message},{status});
}
type Dependencies = {resolver?: JWTVerifyGetKey; now?: () => number; cache?: Cache};

export function createHandler(dependencies: Dependencies = {}) {
  return {
    async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
      let response: Response;
      try {
        const url = new URL(request.url);
        // Deny alternate origins even if workers.dev or preview URLs are re-enabled.
        if (url.protocol !== "https:" || url.host !== "painel.docfis.com") return secure(error("access_denied","Acesso negado.",403),request.method);
        await verifyAccess(request,env,dependencies.resolver);
        if (!["GET","HEAD"].includes(request.method)) {
          response = error("method_not_allowed","Método não permitido.",405);
          response.headers.set("Allow","GET, HEAD");
        } else if (url.pathname === "/api/dashboard") {
          const now = dependencies.now?.() ?? Date.now();
          const filters = parseFilters(url.searchParams,now);
          const cache = dependencies.cache ?? (typeof caches === "undefined" ? undefined : await caches.open("telemetry-admin-v1"));
          // This key contains only approved filters. Lookup always follows JWT verification.
          const cacheKey = new Request(`https://painel.docfis.com/__internal/dashboard?v=1&${new URLSearchParams({...filters})}`);
          const cached = await cache?.match(cacheKey);
          if (cached) response = cached;
          else {
            if (!env.ANALYTICS_SQL) throw new ConfigurationError();
            response = Response.json(await loadDashboard(env.ANALYTICS_SQL,filters,now));
            if (cache) {
              const stored = response.clone(); stored.headers.set("Cache-Control","public, max-age=60");
              ctx.waitUntil(cache.put(cacheKey,stored).catch(() => {}));
            }
          }
        } else if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/__internal/")) response = error("not_found","Recurso não encontrado.",404);
        else if (url.pathname === "/health") response = Response.json({service:"datapyn-telemetry-admin",schema_version:1});
        else response = await env.ASSETS.fetch(request);
      } catch (cause) {
        if (cause instanceof ConfigurationError) response = error("configuration_required","A configuração segura do painel ainda não foi concluída.",503);
        else if (cause instanceof AccessError) response = error("access_denied","Sua sessão expirou ou o acesso não foi autorizado.",403);
        else if (cause instanceof FilterError) response = error("invalid_filters","Revise os filtros e o período selecionado.",400);
        else if (cause instanceof AnalyticsError) response = error("analytics_unavailable","Não foi possível consultar a telemetria. Tente novamente em instantes.",503);
        else response = error("service_unavailable","O painel está temporariamente indisponível.",503);
      }
      return secure(response,request.method);
    },
  } satisfies ExportedHandler<Env>;
}

export default createHandler();
