import type {RuntimeTransport} from "./runtime";
import type {Preferences} from "./preferences";

export interface SqlSafetySettings {confirm_destructive_sql: boolean}

function settings(value: unknown): SqlSafetySettings {
  if (!value || typeof value !== "object" || typeof (value as SqlSafetySettings).confirm_destructive_sql !== "boolean") {
    throw new Error("Configuração de confirmação SQL inválida.");
  }
  return {confirm_destructive_sql: (value as SqlSafetySettings).confirm_destructive_sql};
}

export async function readSqlSafetySettings(transport: RuntimeTransport) {
  return settings(await transport.request("sql.safety.settings.get"));
}

export async function saveSqlSafetySettings(transport: RuntimeTransport, confirmDestructiveSql: boolean) {
  return settings(await transport.request("sql.safety.settings.set", {confirm_destructive_sql: confirmDestructiveSql}));
}

/** Unrelated settings edits must not overwrite an authoritative policy still loading. */
export async function applySqlSafetyPreferences(transport: RuntimeTransport, preferences: Preferences, edited: boolean) {
  const value = edited ? await saveSqlSafetySettings(transport, preferences.confirmDestructiveSql) : await readSqlSafetySettings(transport);
  return {...preferences, confirmDestructiveSql: value.confirm_destructive_sql};
}
