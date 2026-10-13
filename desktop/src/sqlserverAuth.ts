import type { RuntimeInfo } from "./runtime";

export interface SqlServerAuthenticationCapabilities {
  platform: "windows" | "linux" | "macos";
  modes: string[];
  kerberos_available: boolean;
}
export const SQLSERVER_AUTH_LABELS: Record<string, string> = {
  sql_password: "Usuário e senha SQL", windows: "Windows integrada", ntlm: "NTLM", kerberos: "Kerberos", entra_mfa: "Microsoft Entra MFA",
};
export function sqlserverAuthenticationCapabilities(info: RuntimeInfo): SqlServerAuthenticationCapabilities | undefined {
  const capabilities = info.capabilities;
  if (!capabilities || Array.isArray(capabilities)) return;
  const value = capabilities.sqlserver_authentication;
  if (!value || typeof value !== "object") return;
  const record = value as Record<string, unknown>;
  if (!["windows", "linux", "macos"].includes(String(record.platform)) || !Array.isArray(record.modes)) return;
  return { platform: record.platform as SqlServerAuthenticationCapabilities["platform"], kerberos_available: record.kerberos_available === true,
    modes: record.modes.filter((mode): mode is string => typeof mode === "string" && Object.hasOwn(SQLSERVER_AUTH_LABELS, mode) && (mode !== "windows" || record.platform === "windows")) };
}
export function sqlserverAuthenticationModes(capabilities?: SqlServerAuthenticationCapabilities): string[] {
  return capabilities?.modes ?? ["sql_password", "entra_mfa"];
}
