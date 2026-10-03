import {describe,it,expect} from "vitest";
import {documentCopySettings,documentExportSettings,mergeConfigurationDefaults} from "./configurationDefaults";

describe("imported configuration defaults",()=>{
  it("applies legacy defaults to existing and new documents while preserving explicit overrides",()=>{
    const defaults={export_settings:{delimiter:",",decimal:",",encoding:"cp1252",include_header:false,open_folder:false},copy_separator:";",copy_null_display:"NULL"};
    expect(documentExportSettings({},defaults)).toEqual(defaults.export_settings);
    expect(documentCopySettings({},defaults)).toEqual({separator:";",nullDisplay:"NULL"});
    expect(documentExportSettings({export_settings:{delimiter:"|",include_header:true}},defaults)).toMatchObject({delimiter:"|",include_header:true,encoding:"cp1252"});
    expect(documentCopySettings({copy_separator:"\t",copy_null_display:""},defaults)).toEqual({separator:"\t",nullDisplay:""});
  });
  it("merges partial imports without losing unrelated preferences or per-agent choices",()=>{
    expect(mergeConfigurationDefaults({export_settings:{encoding:"cp1252",delimiter:";"},copy_separator:";",pynia:{default_agent_id:"copilot",agent_prefs:{copilot:{model_id:"m1"}}}},{export_settings:{delimiter:","},pynia:{thought_level:"high"}})).toEqual({export_settings:{encoding:"cp1252",delimiter:","},copy_separator:";",pynia:{default_agent_id:"copilot",thought_level:"high",agent_prefs:{copilot:{model_id:"m1"}}}});
    expect(mergeConfigurationDefaults({pynia:{agent_prefs:{copilot:{model_id:"m1"}}}},{pynia:{agent_prefs:{copilot:{thought_level:"high"}}}}).pynia?.agent_prefs?.copilot).toEqual({model_id:"m1",thought_level:"high"});
  });
});
