export const EVENTS = new Set(["app_start", "execution_finished", "connection_recovery", "runtime_error", "ui_error"]);
export const PLATFORMS = new Set(["windows", "macos", "linux", "other"]);
export const DATABASES = new Set(["sqlserver", "postgresql", "mysql", "mariadb", "databricks", "sqlite", "none"]);
export const STATUSES = new Set(["started", "succeeded", "failed", "cancelled", "recovering", "ready", "error", "blocked"]);
export const ERRORS = new Set(["none", "transport", "timeout", "authentication", "syntax", "cancelled", "unknown"]);
export const ROW_BUCKETS = new Set(["none", "0", "1-100", "101-10000", "10001-1000000", "1000000+"]);
const fields = new Set(["event", "version", "platform", "db_type", "status", "error_code", "duration_ms", "attempt", "rows_bucket"]);

/** Reject, rather than log or retain, any unrecognized source field.
 * @param {unknown} input
 */
export function validateEvent(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Invalid event");
  const value = /** @type {Record<string, unknown>} */ (input);
  if (Object.keys(value).some(key => !fields.has(key))) throw new Error("Unknown event field");
  if (typeof value.event !== "string" || !EVENTS.has(value.event)
    || typeof value.version !== "string" || !/^(?:\d{1,3}\.\d{1,3}\.\d{1,3}|dev)$/.test(value.version)
    || typeof value.platform !== "string" || !PLATFORMS.has(value.platform)
    || typeof value.db_type !== "string" || !DATABASES.has(value.db_type)
    || typeof value.status !== "string" || !STATUSES.has(value.status)
    || typeof value.error_code !== "string" || !ERRORS.has(value.error_code)
    || typeof value.rows_bucket !== "string" || !ROW_BUCKETS.has(value.rows_bucket)
    || typeof value.duration_ms !== "number" || !Number.isFinite(value.duration_ms) || value.duration_ms < 0 || value.duration_ms > 86_400_000
    || typeof value.attempt !== "number" || !Number.isInteger(value.attempt) || value.attempt < 0 || value.attempt > 10) throw new Error("Invalid event fields");
  return {event: value.event, version: value.version, platform: value.platform, db_type: value.db_type,
    status: value.status, error_code: value.error_code, rows_bucket: value.rows_bucket,
    duration_ms: value.duration_ms, attempt: value.attempt};
}

/** @param {unknown} input */
export function validateBatch(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Invalid batch");
  const value = /** @type {Record<string, unknown>} */ (input);
  if (Object.keys(value).some(key => !["schema_version", "events"].includes(key)) || value.schema_version !== 1
    || !Array.isArray(value.events) || value.events.length < 1 || value.events.length > 50) throw new Error("Invalid batch");
  return value.events.map(validateEvent);
}

/** Read a capped body even when Content-Length is missing or dishonest.
 * @param {Request} request
 */
export async function readBatch(request) {
  if ((request.headers.get("content-type") || "").toLowerCase().split(";")[0].trim() !== "application/json") throw new Error("JSON required");
  if (request.headers.has("content-encoding") && request.headers.get("content-encoding") !== "identity") throw new Error("Unsupported encoding");
  if (Number(request.headers.get("content-length") || 0) > 32_768 || !request.body) throw new Error("Body too large");
  const reader = request.body.getReader(), chunks = [];
  let length = 0, parts = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      if (++parts > 1024) { await reader.cancel(); throw new Error("Too many body chunks"); }
      if (!part.value.byteLength) continue;
      length += part.value.byteLength;
      if (length > 32_768) { await reader.cancel(); throw new Error("Body too large"); }
      chunks.push(part.value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return validateBatch(JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes)));
}
