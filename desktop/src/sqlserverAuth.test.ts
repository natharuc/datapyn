import { describe, expect, it } from "vitest";
import { sqlserverAuthenticationCapabilities, sqlserverAuthenticationModes } from "./sqlserverAuth";
import type { RuntimeInfo } from "./runtime";

function info(platform: string, modes = ["sql_password", "windows", "ntlm", "kerberos", "entra_mfa"]): RuntimeInfo {
  return { protocol_version: 1, python_version: "test", capabilities: { sqlserver_authentication: { platform, modes, kerberos_available: true } } };
}
describe("SQL Server authentication capabilities", () => {
  it.each(["linux", "macos"])("hides Windows integrated on %s even if advertised", platform => {
    expect(sqlserverAuthenticationModes(sqlserverAuthenticationCapabilities(info(platform)))).toEqual(["sql_password", "ntlm", "kerberos", "entra_mfa"]);
  });
  it("exposes the current Windows identity separately from explicit network credentials", () => {
    expect(sqlserverAuthenticationCapabilities(info("windows"))?.modes).toEqual(["sql_password", "windows", "ntlm", "kerberos", "entra_mfa"]);
  });
  it("does not infer network authentication from browser OS guesses or malformed metadata", () => {
    expect(sqlserverAuthenticationCapabilities(info("unknown"))).toBeUndefined();
    expect(sqlserverAuthenticationModes()).toEqual(["sql_password", "entra_mfa"]);
    expect(sqlserverAuthenticationCapabilities(info("linux", ["sql_password", "toString", "exec", "ntlm"]))?.modes).toEqual(["sql_password", "ntlm"]);
  });
});
