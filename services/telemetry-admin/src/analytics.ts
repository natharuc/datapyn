import {queryParameters, whereClause, type Filters} from "./filters.ts";

export class AnalyticsError extends Error {}
const dataset = "events.analyticsEngine.datapyn_telemetry";
const limit = 10_000;
type Row = Record<string, unknown>;
type Query = {query: string; params: Record<string, string>};

export function dashboardQueries(filters: Filters): Query[] {
  const where = whereClause(filters), params = queryParameters(filters);
  // Analytics SQL binding applies adaptive sample weights to COUNT/SUM itself.
  // Multiplying by _sample_interval/sampleInterval again would double-weight data.
  return [
    {query: `SELECT blob1 AS event, blob2 AS version, blob3 AS platform, blob4 AS dbType, blob5 AS status, blob6 AS errorCode, COUNT(*) AS count, SUM(double1) AS durationTotalMs FROM ${dataset} WHERE ${where} GROUP BY blob1, blob2, blob3, blob4, blob5, blob6 LIMIT ${limit}`, params},
    {query: `SELECT ${filters.interval === "HOUR" ? "toStartOfHour" : "toStartOfDay"}(timestamp) AS bucket, blob1 AS event, blob5 AS status, COUNT(*) AS count, SUM(double1) AS durationTotalMs FROM ${dataset} WHERE ${where} AND blob1 = 'execution_finished' GROUP BY bucket, event, status ORDER BY bucket ASC LIMIT ${limit}`, params},
    {query: `SELECT timestamp, blob1 AS event, blob2 AS version, blob3 AS platform, blob4 AS dbType, blob5 AS status, blob6 AS errorCode, blob7 AS rowsBucket, double1 AS durationMs, double2 AS attempt, sampleInterval AS sampleWeight FROM ${dataset} WHERE ${where} ORDER BY timestamp DESC LIMIT 100`, params},
    {query: `SELECT blob2 AS version, blob3 AS platform, blob4 AS dbType, COUNT(*) AS count FROM ${dataset} WHERE ${whereClause(filters, false)} GROUP BY blob2, blob3, blob4 LIMIT ${limit}`, params: queryParameters(filters, false)},
  ];
}

function number(value: unknown): number {
  if ((typeof value !== "string" && typeof value !== "number") || value === "") throw new AnalyticsError();
  const result = Number(value);
  if (!Number.isFinite(result) || result < 0) throw new AnalyticsError();
  return result;
}
function string(value: unknown): string {
  if (typeof value !== "string" || value.length > 128) throw new AnalyticsError();
  return value;
}
function sampleWeight(value: unknown): number {
  const weight = number(value);
  if (weight < 1) throw new AnalyticsError();
  return weight;
}
function timestamp(value: unknown): string {
  const source = string(value);
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,3})?$/.test(source) ? source.replace(" ", "T") + "Z" : source;
  const result = Date.parse(normalized);
  if (!Number.isFinite(result)) throw new AnalyticsError();
  return new Date(result).toISOString();
}
const failures = new Set(["failed", "error", "blocked"]);
const recoverySuccess = new Set(["succeeded", "ready"]);
const terminalRecovery = new Set([...failures, ...recoverySuccess]);
function entries(map: Map<string, number>) {
  return [...map.entries()].map(([name,count]) => ({name,count})).sort((a,b) => b.count-a.count || a.name.localeCompare(b.name));
}
function add(map: Map<string, number>, key: string, value: number) { map.set(key, (map.get(key) || 0) + value); }
const ratio = (a: number,b: number) => b ? a / b : null;

export function assembleDashboard(filters: Filters, groups: Row[], points: Row[], events: Row[], facets: Row[], now = Date.now()) {
  if ([groups, points, facets].some(rows => rows.length >= limit) || events.length > 100) throw new AnalyticsError();
  const summary = {events: 0, executions: 0, failures: 0, failureRate: null as number|null,
    averageDurationMs: null as number|null, recoveries: 0, recoverySuccessRate: null as number|null,
    runtimeErrors: 0, uiErrors: 0, appStarts: 0};
  let totalDuration = 0, recovered = 0;
  const databases = new Map<string, number>(), errors = new Map<string, number>(), versions = new Map<string, number>();
  for (const row of groups) {
    const event = string(row.event), status = string(row.status), version = string(row.version), database = string(row.dbType), code = string(row.errorCode);
    const count = number(row.count), duration = number(row.durationTotalMs);
    if (version === "dev") throw new AnalyticsError();
    summary.events += count;
    add(versions,version,count);
    if (event === "execution_finished") {
      summary.executions += count; totalDuration += duration;
      if (failures.has(status)) summary.failures += count;
      add(databases,database,count);
    }
    if (code !== "none" && code !== "cancelled") add(errors,code,count);
    if (event === "connection_recovery" && terminalRecovery.has(status)) {
      summary.recoveries += count;
      if (recoverySuccess.has(status)) recovered += count;
    }
    if (event === "runtime_error") summary.runtimeErrors += count;
    if (event === "ui_error") summary.uiErrors += count;
    if (event === "app_start") summary.appStarts += count;
  }
  summary.failureRate = ratio(summary.failures, summary.executions);
  summary.averageDurationMs = ratio(totalDuration,summary.executions);
  summary.recoverySuccessRate = ratio(recovered,summary.recoveries);
  const step = filters.interval === "HOUR" ? 3_600_000 : 86_400_000;
  const buckets = new Map<string, {timestamp: string; executions: number; failures: number; duration: number}>();
  for (let t = Math.floor(Date.parse(filters.start)/step)*step; t < Date.parse(filters.end); t+=step) {
    const key = new Date(t).toISOString(); buckets.set(key,{timestamp:key,executions:0,failures:0,duration:0});
  }
  for (const row of points) {
    const key = timestamp(row.bucket), bucket = buckets.get(key);
    if (!bucket || row.event !== "execution_finished") throw new AnalyticsError();
    const count = number(row.count); bucket.executions += count; bucket.duration += number(row.durationTotalMs);
    if (failures.has(string(row.status))) bucket.failures += count;
  }
  const series = [...buckets.values()].map(({duration,...point}) => ({...point,averageDurationMs:ratio(duration,point.executions)}));
  const versionsAvailable = new Set<string>(), platforms = new Set<string>(), databasesAvailable = new Set<string>();
  for (const row of facets) {
    const version = string(row.version);
    if (version === "dev") throw new AnalyticsError();
    versionsAvailable.add(version); platforms.add(string(row.platform)); databasesAvailable.add(string(row.dbType));
  }
  return {summary, series, breakdowns: {databases: entries(databases),errors: entries(errors),versions: entries(versions)},
    events: events.map(row => ({timestamp:timestamp(row.timestamp),event:string(row.event),version:string(row.version),platform:string(row.platform),
      dbType:string(row.dbType),status:string(row.status),errorCode:string(row.errorCode),rowsBucket:string(row.rowsBucket),
      durationMs:number(row.durationMs),attempt:number(row.attempt),sampleWeight:sampleWeight(row.sampleWeight)})),
    filters: {versions:[...versionsAvailable].sort().reverse(),platforms:[...platforms].sort(),databases:[...databasesAvailable].sort()},
    meta: {generatedAt:new Date(now).toISOString(),start:filters.start,end:filters.end,sampled:true,cacheSeconds:60,eventLimit:100}};
}

export async function loadDashboard(binding: AnalyticsSQLBinding, filters: Filters, now = Date.now()) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const work = Promise.all(dashboardQueries(filters).map(async query => {
      const result = await binding.query(query);
      if (!result || !Array.isArray(result.data)) throw new AnalyticsError();
      return result.data;
    }));
    const [groups, points, events, facets] = await Promise.race([work,new Promise<never>((_,reject) => {
      timer = setTimeout(() => reject(new AnalyticsError()), 12_000);
    })]);
    return assembleDashboard(filters, groups, points, events, facets, now);
  } catch { throw new AnalyticsError(); }
  finally { if (timer) clearTimeout(timer); }
}
