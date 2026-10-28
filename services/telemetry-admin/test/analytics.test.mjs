import assert from "node:assert/strict";
import {test} from "node:test";
import {parseFilters} from "../src/filters.ts";
import {dashboardQueries,assembleDashboard,loadDashboard} from "../src/analytics.ts";
const now=Date.parse("2026-10-28T12:00:15Z");
const filters=parseFilters(new URLSearchParams("period=24h&version=1.0.13&platform=windows&database=sqlserver"),now);
const group=(event,status,count,durationTotalMs=0,errorCode="none")=>({event,status,count,durationTotalMs,errorCode,version:"1.0.13",platform:"windows",dbType:"sqlserver"});

test("uses four bounded queries, fixed dataset, bound filter values and automatic sampling once",()=>{
  const queries=dashboardQueries(filters);
  assert.equal(queries.length,4);
  for(const {query,params} of queries){
    assert.match(query,/FROM events\.analyticsEngine\.datapyn_telemetry/);
    assert.match(query,/timestamp >= \$start/); assert.match(query,/timestamp < \$end/);
    assert.match(query,/blob2 != 'dev'/);
    assert.doesNotMatch(query,/FORMAT|accountTag|_sample_interval|sampleInterval|1\.0\.13|windows|sqlserver/);
    assert.ok(query.length<10*1024); assert.ok(params.start && params.end);
  }
  assert.match(queries[0].query,/COUNT\(\*\) AS count, SUM\(double1\) AS durationTotalMs/);
  assert.equal(queries[0].params.blob2,"1.0.13");
  assert.deepEqual(queries[3].params,{start:filters.start,end:filters.end});
  assert.match(queries[2].query,/LIMIT 100$/);
});
test("combines sampling-adjusted counts/totals correctly and excludes cancellations from failures",()=>{
  // Source sample weights 10 and 2 have ALREADY been applied by SQL binding:
  // 1 success of 100ms *10, 1 failure of 400ms *2 => 12 executions, 150ms mean.
  const groups=[group("execution_finished","succeeded",10,1000),group("execution_finished","failed",2,800,"transport"),
    group("execution_finished","cancelled",3,600,"cancelled"),group("connection_recovery","recovering",20),
    group("connection_recovery","ready",8),group("connection_recovery","error",2,0,"transport"),
    group("app_start","started",5),group("runtime_error","error",4,0,"unknown"),group("ui_error","error",1,0,"unknown")];
  const points=[{bucket:"2026-10-28 10:00:00",...group("execution_finished","succeeded",10,1000)},
    {bucket:"2026-10-28 10:00:00",...group("execution_finished","failed",2,800)}];
  const events=[{timestamp:"2026-10-28 10:30:00",event:"execution_finished",version:"1.0.13",platform:"windows",dbType:"sqlserver",status:"failed",errorCode:"transport",rowsBucket:"none",durationMs:400,attempt:0}];
  const result=assembleDashboard(filters,groups,points,events,[{version:"1.0.13",platform:"windows",dbType:"sqlserver"}],now);
  assert.equal(result.summary.executions,15); assert.equal(result.summary.failures,2);
  assert.equal(result.summary.failureRate,2/15); assert.equal(result.summary.averageDurationMs,160);
  assert.equal(result.summary.recoveries,10);assert.equal(result.summary.recoverySuccessRate,0.8);
  assert.equal(result.summary.runtimeErrors,4);assert.equal(result.summary.uiErrors,1);assert.equal(result.summary.appStarts,5);
  const bucket=result.series.find(row=>row.timestamp==="2026-10-28T10:00:00.000Z");
  assert.equal(bucket.executions,12);assert.equal(bucket.averageDurationMs,150);
  assert.equal(result.series.length,24);assert.equal(result.series[0].executions,0);
  assert.deepEqual(result.breakdowns.databases,[{name:"sqlserver",count:15}]);
  assert.deepEqual(result.breakdowns.errors,[{name:"unknown",count:5},{name:"transport",count:4}]);
  assert.equal(result.events[0].sampleWeight,null);assert.equal(result.meta.sampled,true);
});
test("empty telemetry yields zeros, null averages/rates and all expected buckets",()=>{
  const result=assembleDashboard(filters,[],[],[],[],now);
  assert.equal(result.summary.executions,0);assert.equal(result.summary.failureRate,null);
  assert.equal(result.summary.averageDurationMs,null);assert.equal(result.summary.recoverySuccessRate,null);
  assert.equal(result.series.length,24);assert.equal(result.events.length,0);
});
test("rejects malformed numeric results, truncated aggregates and dev rows instead of showing incomplete metrics",()=>{
  assert.throws(()=>assembleDashboard(filters,[group("execution_finished","succeeded","NaN")],[],[],[],now));
  assert.throws(()=>assembleDashboard(filters,[{...group("app_start","started",1),version:"dev"}],[],[],[],now));
  assert.throws(()=>assembleDashboard(filters,Array(10000).fill(group("app_start","started",1)),[],[],[],now));
});
test("binding failure is normalized and never exposes raw error text",async()=>{
  await assert.rejects(loadDashboard({query:async()=>{throw Error("private upstream credential");}},filters,now),error=>error.constructor.name==="AnalyticsError" && !error.message.includes("private"));
});
