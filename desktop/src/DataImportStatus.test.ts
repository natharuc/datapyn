import { afterEach, describe, expect, it } from "vitest";
import {createElement} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {DataImportStatus} from "./DataImportStatus";
import {setLocale} from "./i18n";
import type {DataImportState} from "./dataImport";
const reading:DataImportState={operationId:"import",path:"C:\\data\\sales.csv",phase:"reading",current:25,total:100};
const render=(state:DataImportState)=>renderToStaticMarkup(createElement(DataImportStatus,{state}));
afterEach(()=>setLocale("pt-BR"));
describe("import progress presentation",()=>{
  it("shows measured CSV bytes as a percentage",()=>{const markup=render(reading);expect(markup).toContain('value="25"');expect(markup).toContain("25%");expect(markup).toContain("sales.csv");expect(markup).toContain('aria-busy="true"');});
  it.each(["sales.xlsx","sales.xls","sales.parquet","sales.json"])("keeps native %s reads indeterminate even when file size is known",path=>{const markup=render({...reading,path,current:0,total:400000});expect(markup).not.toMatch(/<progress[^>]+value=/);expect(markup).not.toContain("0%");});
  it("keeps registration indeterminate after all bytes are read",()=>expect(render({...reading,phase:"registering",current:100})).not.toMatch(/<progress[^>]+value=/));
  it("renders a localized terminal error",()=>{setLocale("en-US");const markup=render({...reading,phase:"error",error:"Invalid workbook"});expect(markup).toContain("Unable to import file");expect(markup).toContain("Invalid workbook");expect(markup).toContain('role="alert"');expect(markup).not.toContain("<progress");});
});
