import { describe,expect,it } from "vitest";
import { ClipboardFormatter, formatClipboardPayload } from "./clipboardFormatter";
import { htmlClipboard,jsonClipboard,plainClipboard,type CopyTable } from "./gridClipboard";
import { MAX_CLIPBOARD_BYTES,utf8Bytes } from "./clipboardLimits";

describe("Worker clipboard formatting",()=>{
  const table:CopyTable={columns:["<name>","exact","decimal","date","null"],rows:[["ação 🧬;\n'\"<&>","9007199254740993","-9007199254740993.145","2026-10-03T15:30:00-03:00",null],[undefined,"000123","0.123456",null,true]]};
  it.each(["plain","excel","json"] as const)("preserves existing %s output and original exact values",format=>{
    const options={format,headers:true,separator:";",nullDisplay:"NULL",formats:{decimal:{type:"number" as const,decimals:2},date:{type:"datetime" as const}}};
    const actual=formatClipboardPayload(table,options);
    expect(actual.plain).toBe(format==="json"?jsonClipboard(table):plainClipboard(table,options));
    expect(actual.html).toBe(format==="excel"?htmlClipboard(table,options):undefined);
    expect(actual.rowCount).toBe(2);expect(actual.plain).toContain("9007199254740993");
    if(format==="json")expect(JSON.parse(actual.plain)[0].decimal).toBe("-9007199254740993.145");
    else expect(actual.plain).toContain("-9,007,199,254,740,993.15");
  });
  it.each([
    {columns:["id","id"],rows:[[1,undefined],["12345678901234567890",null]]},
    {columns:["2","01","0","a","1","__proto__"],rows:[[2,"01",0,"a",1,"safe"]]},
    {columns:[],rows:[[],[]]},
    {columns:["x"],rows:[]},
    {columns:["x","x"],rows:[]},
    {columns:["x","x"],rows:[[],[NaN,Infinity]]},
  ] satisfies CopyTable[])("keeps JSON shape, duplicate columns, numeric key order and empty rows: %j",source=>{
    expect(formatClipboardPayload(source,{format:"json"}).plain).toBe(jsonClipboard(source));
  });
  it("keeps UTF-8 accounting exact for emoji, lone surrogates and chunk boundaries",()=>{
    const value="aç中😀\ud800\udc00\ud800\udc00x\ud800";
    expect(utf8Bytes(value)).toBe(new TextEncoder().encode(value).byteLength);
    expect(utf8Bytes("😀",4)).toBe(4);expect(()=>utf8Bytes("😀",3)).toThrow(/16 MB/);
    const long="a".repeat(4095)+"😀\ud800\"\n";
    const source={columns:[long],rows:[[long]]};
    expect(formatClipboardPayload(source,{format:"json"}).plain).toBe(jsonClipboard(source));
    expect(formatClipboardPayload(source,{format:"excel",headers:true}).html).toBe(htmlClipboard(source,{headers:true}));
    expect(formatClipboardPayload({columns:["a","b"],rows:[["\ud800","\udc00"]]},{format:"plain",separator:""}).plain).toBe(plainClipboard({columns:["a","b"],rows:[["\ud800","\udc00"]]},{separator:""}));
  });
  it("honors raw values and overrides visual formats only when requested",()=>{
    const source={columns:["amount"],rows:[["9007199254740993.1234"]]};
    expect(formatClipboardPayload(source,{format:"plain",raw:true}, {amount:{type:"currency",decimals:2}}).plain).toBe("9007199254740993.1234");
    expect(formatClipboardPayload(source,{format:"plain"}, {amount:{type:"currency",decimals:2}}).plain).toBe("$ 9,007,199,254,740,993.12");
  });
  it.each(["plain","excel","json"] as const)("formats acknowledged row batches incrementally without changing %s boundaries",format=>{
    for(const source of [table,{columns:["id","id"],rows:[[1,undefined],[null,"🧬"]]}]){
      const options={format,headers:true},formatter=new ClipboardFormatter(source.columns,options);
      formatter.addRows([]);for(const row of source.rows)formatter.addRows([row]);
      expect(formatter.finish()).toEqual(formatClipboardPayload(source,options));
      expect(()=>formatter.addRows([])).toThrow();expect(()=>formatter.finish()).toThrow();
    }
  });
  it("supports the bounded 200k-cell case and rejects larger tables before formatting",()=>{
    const rows=Array.from({length:100_000},()=>[1,2]);
    const value=formatClipboardPayload({columns:["a","b"],rows},{format:"plain"});
    expect(value.rowCount).toBe(100_000);expect(value.plain.length).toBe(499_998);
    expect(()=>formatClipboardPayload({columns:["a","b"],rows:[...rows,[3,4]]},{format:"plain"})).toThrow(/200 mil/);
  });
  it("checks encoded output limits incrementally before building a huge escaped value",()=>{
    const untouched=[""];Object.defineProperty(untouched,0,{get(){throw new Error("Later values must not be formatted");}});
    expect(()=>formatClipboardPayload({columns:["x"],rows:[["\"".repeat(MAX_CLIPBOARD_BYTES/2)],untouched]},{format:"json"})).toThrow(/16 MB/);
    expect(()=>formatClipboardPayload({columns:["x"],rows:[["&".repeat(MAX_CLIPBOARD_BYTES/5+1)]]},{format:"excel"})).toThrow(/16 MB/);
    expect(()=>formatClipboardPayload({columns:["x"],rows:[["😀".repeat(MAX_CLIPBOARD_BYTES/4+1)]]},{format:"plain"})).toThrow(/16 MB/);
    expect(formatClipboardPayload({columns:["x"],rows:[["x".repeat(MAX_CLIPBOARD_BYTES)]]},{format:"plain"}).plain.length).toBe(MAX_CLIPBOARD_BYTES);
  });
});
