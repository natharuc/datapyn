import {readBatch} from "./schema.mjs";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"};
    if (url.pathname === "/health" && request.method === "GET") return Response.json({service: "datapyn-telemetry", schema_version: 1}, {headers});
    if (url.pathname !== "/v1/events") return new Response(null, {status: 404, headers});
    if (request.method !== "POST") return new Response(null, {status: 405, headers: {...headers, Allow: "POST"}});
    // The address is only an ephemeral limiter key; it is never written to analytics.
    const allowed = await env.INGEST_LIMIT.limit({key: request.headers.get("CF-Connecting-IP") || "unknown"});
    if (!allowed.success) return new Response(null, {status: 429, headers: {...headers, "Retry-After": "60"}});
    let events;
    try { events = await readBatch(request); }
    catch { return Response.json({error: "invalid_payload"}, {status: 400, headers}); }
    for (const event of events) env.EVENTS.writeDataPoint({
      indexes: [event.db_type],
      blobs: [event.event, event.version, event.platform, event.db_type, event.status, event.error_code, event.rows_bucket],
      doubles: [event.duration_ms, event.attempt],
    });
    return new Response(null, {status: 204, headers});
  },
} satisfies ExportedHandler<Env>;
