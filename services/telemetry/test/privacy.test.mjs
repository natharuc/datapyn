import assert from "node:assert/strict";
import {test} from "node:test";
import worker from "../src/index.ts";

const event = {event:"ui_error",version:"1.0.13",platform:"windows",db_type:"none",status:"error",
  error_code:"unknown",duration_ms:0,attempt:0,rows_bucket:"none"};
const make = body => new Request("https://collector.example.com/v1/events",{method:"POST",
  headers:{"Content-Type":"application/json"},body});
function fixture(){
  const points=[];
  return {points,env:{EVENTS:{writeDataPoint:value=>points.push(value)},INGEST_LIMIT:{limit:async()=>({success:true})}}};
}

test("prototype names and personal identifiers reject a whole batch before writing any point",async()=>{
  for(const field of ["__proto__","constructor","email","ip_address","query","connection_id","session_id"]){
    const {points,env}=fixture();
    const source=`{"schema_version":1,"events":[${JSON.stringify(event)},{${JSON.stringify(field)}:"private",${JSON.stringify(event).slice(1)}]}`;
    const response=await worker.fetch(make(source),env);
    assert.equal(response.status,400);assert.deepEqual(points,[]);
    assert.equal((await response.text()).includes("private"),false);
  }
});

test("invalid UTF-8 and non-finite JSON numbers never enter the collector",async()=>{
  for(const body of [new Uint8Array([0xff,0xfe,0x7b]),`{"schema_version":1,"events":[${JSON.stringify(event).replace('"duration_ms":0','"duration_ms":1e999')}]} `]){
    const {points,env}=fixture();
    const response=await worker.fetch(make(body),env);
    assert.equal(response.status,400);assert.deepEqual(points,[]);
  }
});

test("headers, query strings and remote addresses are never copied into analytics",async()=>{
  const {points,env}=fixture();
  const request=new Request("https://collector.example.com/v1/events?email=private@example.com",{method:"POST",
    headers:{"Content-Type":"application/json","Authorization":"Bearer private-secret","User-Agent":"private-device","CF-Connecting-IP":"192.0.2.9"},
    body:JSON.stringify({schema_version:1,events:[event]})});
  const response=await worker.fetch(request,env);
  assert.equal(response.status,204);
  assert.equal(JSON.stringify(points).includes("private"),false);
  assert.equal(JSON.stringify(points).includes("192.0.2.9"),false);
  assert.equal(response.headers.has("Access-Control-Allow-Origin"),false);
});

test("a stream of empty chunks is cancelled before accumulating unbounded metadata",async()=>{
  const {points,env}=fixture();
  let read=0,cancelled=false;
  const body=new ReadableStream({pull(controller){read++;controller.enqueue(new Uint8Array());},cancel(){cancelled=true;}});
  const request=new Request("https://collector.example.com/v1/events",{method:"POST",headers:{"Content-Type":"application/json"},body,duplex:"half"});
  const response=await worker.fetch(request,env);
  assert.equal(response.status,400);assert.deepEqual(points,[]);
  assert.equal(cancelled,true);assert.ok(read<=1026);
});
