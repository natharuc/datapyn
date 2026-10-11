import { describe, expect, it } from "vitest";
import { connectionStringFormats, formatConnectionString, parseConnectionPairs, parseConnectionString, PASSWORD_PLACEHOLDER } from "./connectionStrings";
import type { ConnectionConfig } from "./workspace";

const profile = (db_type: ConnectionConfig["db_type"]): ConnectionConfig => ({ db_type, host: "analytics.example", port: db_type === "sqlserver" ? 1433 : db_type === "postgresql" ? 5432 : db_type === "databricks" ? 443 : 3306,
  database: db_type === "sqlite" ? "C:/data/analysis.db" : "analytics", schema: db_type === "postgresql" ? "reporting" : db_type === "databricks" ? "finance" : "", username: "reader@company", password: 'p@ss:;}/" 😀', http_path: "/sql/1.0/warehouses/abc", databricks_auth_mode: "token", sqlserver_auth_mode: "sql_password" });
const kinds: ConnectionConfig["db_type"][] = ["sqlserver", "postgresql", "mysql", "mariadb", "sqlite", "databricks"];

describe("connection string export", () => {
  it.each(kinds)("formats %s in its real provider formats without exposing secrets by default", kind => {
    const config = profile(kind);
    for (const format of connectionStringFormats(config)) {
      const result = formatConnectionString(config, format.id);
      expect(result).not.toContain(config.password);
      if (kind !== "sqlite") expect(decodeURIComponent(result)).toContain(PASSWORD_PLACEHOLDER);
    }
  });
  it.each(kinds)("preserves the %s driver configuration in a native round trip", kind => {
    const config = profile(kind), parsed = parseConnectionString(formatConnectionString(config, "native", true), kind);
    expect(parsed.db_type).toBe(kind); expect(parsed.database).toBe(config.database);
    if (kind !== "sqlite") { expect(parsed.host).toBe(config.host); expect(parsed.port).toBe(config.port); expect(parsed.password).toBe(config.password); }
    if (["postgresql", "databricks"].includes(kind)) expect(parsed.schema).toBe(config.schema);
    if (kind === "databricks") expect(parsed.http_path).toBe(config.http_path);
  });
  it.each(kinds.filter(kind => kind !== "databricks"))("preserves %s URI credentials and scope in a round trip", kind => {
    const config = profile(kind), parsed = parseConnectionString(formatConnectionString(config, "uri", true));
    expect(parsed.db_type).toBe(kind); expect(parsed.database).toBe(config.database);
    if (kind !== "sqlite") expect(parsed.password).toBe(config.password);
    if (kind === "postgresql") expect(parsed.schema).toBe(config.schema);
  });
  it.each(["windows", "entra_mfa"])("preserves SQL Server %s authentication without invented passwords", mode => {
    const config = { ...profile("sqlserver"), sqlserver_auth_mode: mode, password: "unused-password" };
    for (const format of ["native", "uri"] as const) {
      const result = formatConnectionString(config, format, true), parsed = parseConnectionString(result);
      expect(parsed.sqlserver_auth_mode).toBe(mode); expect(result).not.toContain("unused-password");
    }
  });
  it("supports Databricks browser OAuth for .NET ODBC and Python without a PAT", () => {
    const config = { ...profile("databricks"), databricks_auth_mode: "oauth" as const, password: "unused-token" };
    expect(parseConnectionString(formatConnectionString(config, "native", true)).databricks_auth_mode).toBe("oauth");
    expect(formatConnectionString(config, "python", true)).toContain('auth_type="databricks-oauth"');
    expect(formatConnectionString(config, "python", true)).not.toContain("unused-token");
    expect(formatConnectionString(config, "csharp", true)).toContain("OdbcConnection");
  });
  it("supports SQLite memory, relative and Unix absolute paths", () => {
    for (const path of [":memory:", "data/analysis.db", "/var/data/analysis.db", "C:\\analysis folder\\sample.db"]) {
      const config = { ...profile("sqlite"), database: path };
      expect(parseConnectionString(formatConnectionString(config, "uri")).database).toBe(path);
    }
  });
  it("handles IPv6 URI authority and whitespace/quote passwords", () => {
    const config = { ...profile("postgresql"), host: "2001:db8::123", password: '  a;"b";c  ' };
    expect(parseConnectionString(formatConnectionString(config, "uri", true))).toMatchObject({ host: config.host, password: config.password });
    expect(parseConnectionString(formatConnectionString(config, "native", true), "postgresql").password).toBe(config.password);
  });
  it("preserves database names literally for SQLAlchemy and quotes mixed-case PostgreSQL schemas", () => {
    const config = { ...profile("postgresql"), database: "finance %20/#records", schema: 'Sales "2026" data' };
    expect(parseConnectionString(formatConnectionString(config, "uri", true))).toMatchObject({ database: config.database, schema: config.schema });
    expect(parseConnectionString(formatConnectionString(config, "native", true))).toMatchObject({ database: config.database, schema: config.schema });
    expect(formatConnectionString({ ...config, database: "db?2026" }, "python", true)).toContain('database="db?2026"');
    expect(connectionStringFormats({ ...config, database: "db?2026" }).map(format => format.id)).not.toContain("uri");
  });
  it("omits stored secrets from a copied preview round trip", () => {
    for (const kind of kinds) expect(parseConnectionString(formatConnectionString(profile(kind), "native"), kind).password).toBe("");
  });
});

describe("connection string import", () => {
  it("parses standard SQL Server aliases, instance, port and braced credentials", () => {
    expect(parseConnectionString("Driver={ODBC Driver 18 for SQL Server};SERVER={tcp:sql\\reporting,1435};Initial Catalog=prod;UID=reader;PWD={pass;with}}brace};Encrypt=yes;TrustServerCertificate=no;"))
      .toMatchObject({ db_type: "sqlserver", host: "sql\\reporting", port: 1435, database: "prod", username: "reader", password: "pass;with}brace", trust_server_certificate: false });
  });
  it("detects common providers even when the empty dialog defaults to SQLite", () => {
    expect(parseConnectionString("Server=sql;Database=prod;User ID=reader;Password=secret;", "sqlite").db_type).toBe("sqlserver");
    expect(parseConnectionString("Host=pg;Port=5432;Database=prod;Username=reader;Password=secret;", "sqlite").db_type).toBe("postgresql");
    expect(parseConnectionString("Server=my;Port=3306;Database=prod;User ID=reader;Password=secret;", "sqlite").db_type).toBe("mysql");
    expect(parseConnectionString("Host=pg;Port=5432;Database=prod;Username=reader;Password=secret;", "sqlserver").db_type).toBe("postgresql");
    expect(parseConnectionString("Data Source=C:/data/work.db;", "sqlserver").db_type).toBe("sqlite");
    expect(parseConnectionString("Data Source=sql;Initial Catalog=prod;User ID=reader;Password=secret;", "sqlite").db_type).toBe("sqlserver");
  });
  it("does not silently ignore unsupported TLS or OAuth options", () => {
    expect(() => parseConnectionString("postgresql://user:password@pg/prod?sslmode=verify-full")).toThrow("opções");
    expect(() => parseConnectionString("Host=pg;Database=prod;SSLMode=Require;", "postgresql")).toThrow("opções");
    expect(() => parseConnectionString("Server=sql;Database=prod;Encrypt=false;")).toThrow("criptografia");
    expect(() => parseConnectionString("Server=sql;Database=prod;Authentication=Active Directory Managed Identity;")).toThrow("autenticação");
    expect(() => parseConnectionString("Driver=Databricks;Host=db;HTTPPath=/sql/test;AuthMech=11;Auth_Flow=1;")).toThrow("OAuth");
    expect(() => parseConnectionString("Driver=Oracle;Server=sql;Database=prod;")).toThrow("Driver");
    expect(() => parseConnectionString("postgresql://user:password@pg/prod?options=-csearch_path%3Dpublic%20-cstatement_timeout%3D1")).toThrow("opções");
  });
  it.each(["", "jdbc:sqlserver://server;database=prod", "http://example.org/db", "postgresql://user:pwd@pg:99999/prod", "postgresql://user:bad%xx@pg/prod", "Server=sql;PWD={not-closed", "Server=sql;Password=\"not-closed", "Server;Database=prod", "sqlite:///test.db?mode=ro"])("rejects malformed or unsupported text without quoting credentials: %s", value => {
    expect(() => parseConnectionString(value)).toThrow();
    try { parseConnectionString(value); } catch (failure) { expect(String(failure)).not.toContain(value || "__empty__"); }
  });
  it("rejects duplicate keys and ambiguous aliases", () => {
    expect(() => parseConnectionString("Server=sql;SERVER=other;Database=prod")).toThrow("duplicados");
    expect(() => parseConnectionString("Server=sql;Database=prod;Password=one;PWD=two")).toThrow("duplicados");
  });
  it("preserves doubled ADO.NET quotes and exact ODBC brace values", () => {
    const values = parseConnectionPairs('User ID=" reader ";Password="a;""b""";Database={a;b}}c};');
    expect(values.get("userid")).toBe(" reader "); expect(values.get("password")).toBe('a;"b"'); expect(values.get("database")).toBe("a;b}c");
  });
});
