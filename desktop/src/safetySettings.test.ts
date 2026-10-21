import {afterEach,describe,expect,it,vi} from "vitest";
import {DEFAULT_PREFERENCES,loadPreferences,normalizePreferences,savePreferences} from "./preferences";
import {applySqlSafetyPreferences,readSqlSafetySettings,saveSqlSafetySettings} from "./safetySettings";
import type {RuntimeTransport} from "./runtime";

afterEach(()=>vi.unstubAllGlobals());

describe("SQL destructive confirmation preferences",()=>{
  it("protects old installations and persists only an explicit false as a disable",()=>{
    expect(DEFAULT_PREFERENCES.confirmDestructiveSql).toBe(true);
    expect(normalizePreferences({}).confirmDestructiveSql).toBe(true);
    for(const invalid of ["false",0,null])expect(normalizePreferences({confirmDestructiveSql:invalid as unknown as boolean}).confirmDestructiveSql).toBe(true);
    let value="{}";
    vi.stubGlobal("localStorage",{getItem:()=>value,setItem:(_key:string,next:string)=>{value=next;}});
    expect(loadPreferences().confirmDestructiveSql).toBe(true);
    savePreferences({...DEFAULT_PREFERENCES,confirmDestructiveSql:false});
    expect(loadPreferences().confirmDestructiveSql).toBe(false);
  });
  it("reads and saves the global policy with no database or execution request",async()=>{
    const request=vi.fn().mockResolvedValue({confirm_destructive_sql:false});
    const transport={request,subscribe:vi.fn()} as RuntimeTransport;
    expect(await readSqlSafetySettings(transport)).toEqual({confirm_destructive_sql:false});
    expect(await saveSqlSafetySettings(transport,false)).toEqual({confirm_destructive_sql:false});
    expect(request.mock.calls).toEqual([["sql.safety.settings.get"],["sql.safety.settings.set",{confirm_destructive_sql:false}]]);
  });
  it.each([{},null,{confirm_destructive_sql:"false"},{confirm_destructive_sql:0}])("rejects a malformed runtime policy %s",async value=>{
    const transport={request:vi.fn().mockResolvedValue(value),subscribe:vi.fn()} as RuntimeTransport;
    await expect(readSqlSafetySettings(transport)).rejects.toThrow("Configuração de confirmação SQL inválida");
  });
  it("retains authoritative policy on unrelated edits and saves only a changed checkbox",async()=>{
    const request=vi.fn().mockResolvedValue({confirm_destructive_sql:false});
    const transport={request,subscribe:vi.fn()} as RuntimeTransport;
    expect(await applySqlSafetyPreferences(transport,{...DEFAULT_PREFERENCES,editorFontSize:18},false)).toMatchObject({editorFontSize:18,confirmDestructiveSql:false});
    expect(request).toHaveBeenCalledExactlyOnceWith("sql.safety.settings.get");
    request.mockClear();request.mockResolvedValue({confirm_destructive_sql:true});
    expect((await applySqlSafetyPreferences(transport,DEFAULT_PREFERENCES,true)).confirmDestructiveSql).toBe(true);
    expect(request).toHaveBeenCalledExactlyOnceWith("sql.safety.settings.set",{confirm_destructive_sql:true});
  });
});
