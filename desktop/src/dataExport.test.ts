import { describe, expect, it, vi } from "vitest";
import { clipboardFormat, DEFAULT_FORMAT_EXPORT_SETTINGS, EXPORT_FORMATS, exportOptions, exportPath, exportProgressPercent, exportSource, readExportProgress, requestSqlText, temporaryTableName } from "./dataExport";
import { DEFAULT_EXPORT_SETTINGS, normalizeExportSettings } from "./exportSettings";

describe("Export parity and original-value SQL generation", () => {
  it("retains all legacy CSV settings and forces a real tab only for TSV", () => {
    const csv = normalizeExportSettings({delimiter:"|",decimal:",",encoding:"cp1252",include_header:false,open_folder:false});
    expect(csv).toEqual({delimiter:"|",decimal:",",encoding:"cp1252",include_header:false,open_folder:false});
    expect(exportOptions("csv",csv,DEFAULT_FORMAT_EXPORT_SETTINGS,"data","")).toMatchObject({delimiter:"|",decimal:",",encoding:"cp1252",include_header:false,index:false});
    expect(exportOptions("tsv",csv,DEFAULT_FORMAT_EXPORT_SETTINGS,"data","").delimiter).toBe("\t");
    expect(exportOptions("txt",csv,DEFAULT_FORMAT_EXPORT_SETTINGS,"data","").delimiter).toBe("|");
  });
  it("maps Excel to tabular clipboard output and prevents a Parquet text export", () => {
    expect(EXPORT_FORMATS).toEqual(expect.arrayContaining(["csv","tsv","txt","xlsx","json","parquet","sql"]));
    expect(clipboardFormat("xlsx")).toBe("excel");
    for (const format of ["csv","tsv","txt","json","sql"] as const) expect(clipboardFormat(format)).toBe(format);
    expect(()=>clipboardFormat("parquet")).toThrow("Parquet");
  });
  it("keeps a data filename extension compatible with the selected format", () => {
    expect(exportPath("C:\\out\\result.CSV","csv")).toBe("C:\\out\\result.CSV");
    expect(exportPath("C:\\out\\result","xlsx")).toBe("C:\\out\\result.xlsx");
    expect(exportPath("result.json","sql")).toBe("result.json.sql");
  });
  it("exports the filtered/sorted view and applies exact disjoint scope only when selected", () => {
    const view={filter:{text:"O'Brien"},sort:{column:"amount",direction:"desc" as const},scope:{rectangles:[{x:0,y:3,width:2,height:1},{x:1,y:7,width:1,height:2}]}};
    expect(exportSource("analysis-1","frame-1",view)).toEqual({session_id:"analysis-1",result_id:"frame-1",filter:view.filter,sort:view.sort});
    expect(exportSource("analysis-1","frame-1",view,true)).toEqual({...exportSource("analysis-1","frame-1",view),scope:view.scope});
    expect(exportSource("analysis-1","frame-1",undefined,true)).not.toHaveProperty("scope");
  });
  it("sends SQL table/schema as literal parts and limits GO to SQL Server", () => {
    const settings={...DEFAULT_FORMAT_EXPORT_SETTINGS,sqlMode:"create_insert" as const,sqlBatchSize:50,sqlTransaction:true,sqlGo:true};
    expect(exportOptions("sql",DEFAULT_EXPORT_SETTINGS,settings,"a.b","my.schema")).toEqual({table_name:"a.b",table_name_literal:true,schema_name:"my.schema",db_type:"sqlserver",sql_mode:"create_insert",batch_size:50,include_transaction:true,include_go:true});
    expect(exportOptions("sql",DEFAULT_EXPORT_SETTINGS,{...settings,sqlDialect:"postgresql"},"data","").include_go).toBe(false);
    expect(exportOptions("sql",DEFAULT_EXPORT_SETTINGS,{...settings,sqlDialect:"databricks"},"data","").include_transaction).toBe(false);
    expect(exportOptions("sql",DEFAULT_EXPORT_SETTINGS,{...settings,sqlDialect:"databricks",sqlMode:"insert"},"data","").include_transaction).toBe(true);
  });
  it("preserves Excel/JSON/Parquet options while preventing invalid non-record JSON lines", () => {
    expect(exportOptions("xlsx",DEFAULT_EXPORT_SETTINGS,{...DEFAULT_FORMAT_EXPORT_SETTINGS,sheetName:" Detail "},"","")).toMatchObject({sheet_name:"Detail",include_header:true,index:false});
    expect(exportOptions("parquet",DEFAULT_EXPORT_SETTINGS,{...DEFAULT_FORMAT_EXPORT_SETTINGS,compression:"none"},"","")).toEqual({index:false,compression:null});
    expect(exportOptions("json",DEFAULT_EXPORT_SETTINGS,{...DEFAULT_FORMAT_EXPORT_SETTINGS,jsonLines:true},"","")).toMatchObject({orient:"records",indent:2,lines:true});
    expect(exportOptions("json",DEFAULT_EXPORT_SETTINGS,{...DEFAULT_FORMAT_EXPORT_SETTINGS,jsonOrient:"split",jsonLines:true},"","").lines).toBe(false);
  });
  it("preserves SQL Server local/global temp names and uses literal names on other dialects", () => {
    expect(temporaryTableName(" frame ",true,"sqlserver")).toBe("#frame");
    expect(temporaryTableName("##shared",true,"sqlserver")).toBe("##shared");
    expect(temporaryTableName("frame",false,"sqlserver")).toBe("frame");
    expect(temporaryTableName("frame",true,"postgresql")).toBe("frame");
  });
  it("keeps arbitrary-precision and binary literals from the kernel instead of regenerating SQL from JSON pages", async () => {
    const original="INSERT INTO `a.b` (`bigint`, `decimal`, `binary`, `path`) VALUES (1152921504606846979, 1.000000000000000001, X'FF00', 'a\\\\b');";
    const request=vi.fn().mockResolvedValue({text:original,row_count:1,column_count:4,format:"sql"});
    const source=exportSource("source","result",{scope:{rectangles:[{x:0,y:2,width:4,height:1}]}},true);
    expect((await requestSqlText({request},source,'`a.b`',"mysql",()=>true)).text).toBe(original);
    expect(request).toHaveBeenCalledExactlyOnceWith("result.export_text",{...source,format:"sql",options:{table_name:'`a.b`',db_type:"mysql",sql_mode:"insert",batch_size:1}});
  });
  it("does not copy or insert a late SQL response from a changed result view", async () => {
    let finish!:(value:unknown)=>void;
    const request=vi.fn(()=>new Promise<unknown>(resolve=>{finish=resolve;}));
    let current=true;
    const pending=requestSqlText({request:request as never},exportSource("source","old"),"dbo.data","sqlserver",()=>current);
    current=false; finish({text:"stale script",row_count:1,column_count:1,format:"sql"});
    await expect(pending).rejects.toThrow("Os resultados mudaram");
  });
  it("validates progress payloads and bounds the visible percentage", () => {
    const payload={session_id:"source",operation_id:"uuid",phase:"writing" as const,current:250,total:1000};
    expect(readExportProgress({event:"result.export_progress",payload})).toEqual(payload);
    expect(exportProgressPercent(payload)).toBe(25);
    expect(exportProgressPercent({...payload,current:2000})).toBe(100);
    expect(exportProgressPercent({...payload,total:0})).toBeUndefined();
    for(const invalid of [{...payload,operation_id:null},{...payload,current:NaN},{...payload,total:-1},{...payload,phase:"unrelated"}]) expect(readExportProgress({event:"result.export_progress",payload:invalid})).toBeUndefined();
    expect(readExportProgress({event:"execution.export_progress",payload})).toBeUndefined();
  });
});
