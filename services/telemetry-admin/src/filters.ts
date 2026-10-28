export class FilterError extends Error {}
export const PLATFORMS = ["windows", "macos", "linux", "other"];
export const DATABASES = ["sqlserver", "postgresql", "mysql", "mariadb", "databricks", "sqlite", "none"];
const periods = new Map([["24h", 1], ["7d", 7], ["30d", 30], ["90d", 90]]);
export type Filters = {start: string; end: string; version: string; platform: string; database: string; interval: "HOUR" | "DAY"};

export function parseFilters(params: URLSearchParams, now = Date.now()): Filters {
  const allowed = new Set(["period", "version", "platform", "database", "start", "end"]);
  if ([...params.keys()].some(key => !allowed.has(key) || params.getAll(key).length !== 1)) throw new FilterError();
  const version = params.get("version") || "", platform = params.get("platform") || "", database = params.get("database") || "";
  if ((version && !/^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(version))
    || (platform && !PLATFORMS.includes(platform)) || (database && !DATABASES.includes(database))) throw new FilterError();
  // Rounding keeps the internal cache key stable across requests in the same minute.
  let end = Math.floor(now / 60_000) * 60_000, start: number;
  if (params.has("start") || params.has("end")) {
    if (params.has("period") || !params.has("start") || !params.has("end")) throw new FilterError();
    const first = params.get("start")!, last = params.get("end")!;
    const iso = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/;
    if (!iso.test(first) || !iso.test(last)) throw new FilterError();
    start = Date.parse(first); end = Date.parse(last);
    if (!Number.isFinite(start) || !Number.isFinite(end) || new Date(start).toISOString().slice(0,19) !== first.slice(0,19)
      || new Date(end).toISOString().slice(0,19) !== last.slice(0,19)) throw new FilterError();
    if (end > now || start < now - 90 * 86_400_000 || start >= end || end - start > 90 * 86_400_000) throw new FilterError();
  } else {
    const days = periods.get(params.get("period") || "7d");
    if (!days) throw new FilterError();
    start = end - days * 86_400_000;
  }
  return {start: new Date(start).toISOString(), end: new Date(end).toISOString(), version, platform, database,
    interval: end - start <= 7 * 86_400_000 ? "HOUR" : "DAY"};
}

export function whereClause(filters: Filters, dimensions = true) {
  const terms = ["timestamp >= $start", "timestamp < $end", "blob2 != 'dev'"];
  if (dimensions) for (const [column, value] of [["blob2",filters.version], ["blob3",filters.platform], ["blob4",filters.database]]) {
    if (value) terms.push(`${column} = $${column}`);
  }
  return terms.join(" AND ");
}

export function queryParameters(filters: Filters, dimensions = true) {
  const params: Record<string, string> = {start: filters.start, end: filters.end};
  if (dimensions) for (const [column, value] of [["blob2",filters.version], ["blob3",filters.platform], ["blob4",filters.database]]) {
    if (value) params[column] = value;
  }
  return params;
}
