import {normalizeExportSettings,type ExportSettings} from "./exportSettings";
import type {PyniaDefaults} from "./pynia";

export interface ConfigurationDefaults {
  export_settings?:Partial<ExportSettings>;
  copy_separator?:string;
  copy_null_display?:string;
  export_open_folder?:boolean;
  pynia?:PyniaDefaults;
}

export function mergeConfigurationDefaults(base:ConfigurationDefaults={},override:ConfigurationDefaults={}):ConfigurationDefaults {
  const agent_prefs={...base.pynia?.agent_prefs};
  for(const [agent,preferences] of Object.entries(override.pynia?.agent_prefs ?? {}))agent_prefs[agent]={...agent_prefs[agent],...preferences};
  return {...base,...override,
    ...(base.export_settings || override.export_settings ? {export_settings:{...base.export_settings,...override.export_settings}} : {}),
    ...(base.pynia || override.pynia ? {pynia:{...base.pynia,...override.pynia,agent_prefs}} : {})};
}

export function documentExportSettings(extras:Record<string,unknown>,defaults:ConfigurationDefaults):ExportSettings {
  return normalizeExportSettings({...defaults.export_settings,...extras.export_settings as Partial<ExportSettings>});
}

export function documentCopySettings(extras:Record<string,unknown>,defaults:ConfigurationDefaults) {
  return {separator:String(extras.copy_separator ?? defaults.copy_separator ?? "\t"),nullDisplay:String(extras.copy_null_display ?? defaults.copy_null_display ?? "")};
}
