import { describe,expect,it } from "vitest";
import { boundedClipboard, cellSelected, htmlClipboard, jsonClipboard, plainClipboard, selectedLayout, sqlClipboard } from "./gridClipboard";

describe("Result clipboard",()=>{
  it("keeps disjoint ranges separate and never copies unselected intersections",()=>{
    const ranges=[{x:0,y:0,width:1,height:2},{x:1,y:4,width:1,height:2}];
    expect(selectedLayout(ranges)).toEqual({columns:[0,1],rows:[0,1,4,5]});
    expect(cellSelected(1,0,ranges)).toBe(false);
    expect(plainClipboard({columns:["a","b"],rows:[[1,undefined],[undefined,2]]},{headers:true})).toBe("a\tb\r\n1\t\r\n\t2");
  });
  it("quotes separators/newlines and escapes rich Excel markup without changing big integers",()=>{
    const table={columns:["<name>","id"],rows:[["a;b\nc","9007199254740993"]]};
    expect(plainClipboard(table,{separator:";"})).toBe('"a;b\nc";9007199254740993');
    expect(htmlClipboard(table,{headers:true})).toContain("&lt;name&gt;");
    expect(htmlClipboard(table)).toContain('mso-number-format:"\\@"');
    expect(JSON.parse(jsonClipboard(table))[0].id).toBe("9007199254740993");
  });
  it("preserves duplicate JSON columns rather than silently overwriting values",()=>{
    expect(JSON.parse(jsonClipboard({columns:["id","id"],rows:[[1,2]]}))).toEqual({columns:["id","id"],rows:[[1,2]]});
  });
  it("escapes SQL names and values with the active database dialect",()=>{
    expect(sqlClipboard({columns:["weird.col","quote]"],rows:[["O'Brien",null],[true,12]]},"dbo.sample","sqlserver")).toBe("INSERT INTO [dbo].[sample] ([weird.col], [quote]]]) VALUES ('O''Brien', NULL);\nINSERT INTO [dbo].[sample] ([weird.col], [quote]]]) VALUES (1, 12);");
  });
  it("rejects oversized copies before unbounded clipboard allocation",()=>{
    expect(()=>selectedLayout([{x:0,y:0,width:20,height:20_000}])).toThrow(/exportação/);
    expect(()=>boundedClipboard("x".repeat(16*1024*1024+1))).toThrow(/16 MB/);
  });
});
