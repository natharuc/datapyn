import type { ConnectionConfig } from "./workspace";

export type ConnectionStringFormat = "uri" | "native" | "python" | "csharp";
export const PASSWORD_PLACEHOLDER = "<password>";
const defaults: Record<ConnectionConfig["db_type"], number> = { sqlserver: 1433, postgresql: 5432, mysql: 3306, mariadb: 3306, sqlite: 0, databricks: 443 };
const enc = (value: string) => encodeURIComponent(value).replace(/[!'()*]/g, character => `%${character.charCodeAt(0).toString(16).toUpperCase()}`);
const literal = (value: string) => JSON.stringify(value);
const adoValue = (value: string) => /[;"'\s]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
const odbcValue = (value: string) => `{${value.replace(/}/g, "}}")}}`;
const pairs = (values: Array<[string, string]>, quote = adoValue) => values.map(([key, value]) => `${key}=${quote(value)}`).join(";") + ";";
function password(config: ConnectionConfig, include: boolean) { return include ? config.password ?? "" : PASSWORD_PLACEHOLDER; }
function auth(config: ConnectionConfig) { return config.use_windows_auth ? "windows" : config.sqlserver_auth_mode ?? "sql_password"; }
const pgSchema = (value: string) => /^[a-z_][a-z0-9_$]*$/.test(value) ? value : `"${value.replace(/"/g, '""')}"`;
const pgOptions = (value: string) => `-csearch_path=${pgSchema(value).replace(/[\\\s]/g, character => `\\${character}`)}`;
function parsePgSchema(value: string) { return /^"(?:[^"]|"")*"$/.test(value) ? value.slice(1, -1).replace(/""/g, '"') : value; }
const pgTlsFields = ["sslmode", "sslrootcert", "sslcert", "sslkey"] as const;
const pgTlsMode = (value: string): NonNullable<ConnectionConfig["sslmode"]> => {
  const normalized = value.toLowerCase().replace(/[\s_-]/g, "");
  const modes = { disable: "disable", allow: "allow", prefer: "prefer", require: "require", verifyca: "verify-ca", verifyfull: "verify-full" } as const;
  const mode = modes[normalized as keyof typeof modes]; if (!mode) throw new Error("Modo TLS PostgreSQL inválido."); return mode;
};
function pgQuery(config: ConnectionConfig): Array<[string, string]> {
  return [...(config.schema ? [["options", pgOptions(config.schema)] as [string, string]] : []),
    ...pgTlsFields.filter(field => Boolean(config[field])).map(field => [field, config[field]!] as [string, string])];
}

export function connectionStringFormats(config: ConnectionConfig): Array<{ id: ConnectionStringFormat; label: string }> {
  return [...(config.db_type === "databricks" || config.database.includes("?") ? [] : [{ id: "uri" as const, label: "URI · SQLAlchemy" }]),
    { id: "native" as const, label: config.db_type === "databricks" ? "ODBC" : ".NET" },
    { id: "python" as const, label: "Python" }, { id: "csharp" as const, label: "C#" }];
}

function nativeString(config: ConnectionConfig, include: boolean, odbc = false): string {
  const kind = config.db_type, secret = password(config, include);
  if (kind === "sqlite") return pairs([["Data Source", config.database]]);
  if (kind === "databricks") return pairs([
    ["Driver", "Databricks ODBC Driver"], ["Host", config.host], ["Port", String(config.port || 443)],
    ["HTTPPath", config.http_path ?? ""], ["SSL", "1"], ["ThriftTransport", "2"],
    ...(config.database ? [["Catalog", config.database] as [string, string]] : []),
    ...(config.schema ? [["Schema", config.schema] as [string, string]] : []),
    ...(config.databricks_auth_mode === "oauth" ? [["AuthMech", "11"], ["Auth_Flow", "2"], ["PWD", "<refresh-token-encryption-password>"]] : [["AuthMech", "3"], ["UID", "token"], ["PWD", secret]]) as Array<[string, string]>,
  ], odbcValue);
  if (kind === "sqlserver") {
    const values: Array<[string, string]> = [
      ...(odbc ? [["Driver", "ODBC Driver 18 for SQL Server"] as [string, string]] : []),
      ["Server", `${config.host}${config.port ? `,${config.port}` : ""}`], ["Database", config.database], ["Encrypt", "yes"],
      ["TrustServerCertificate", config.trust_server_certificate ? "yes" : "no"],
    ];
    if (auth(config) === "windows") values.push([odbc ? "Trusted_Connection" : "Integrated Security", "true"]);
    else if (auth(config) === "entra_mfa") { values.push(["Authentication", "Active Directory Interactive"]); if (config.username) values.push([odbc ? "UID" : "User ID", config.username]); }
    else values.push([odbc ? "UID" : "User ID", config.username], [odbc ? "PWD" : "Password", secret]);
    return pairs(values, odbc ? odbcValue : adoValue);
  }
  return pairs([[kind === "postgresql" ? "Host" : "Server", config.host], ["Port", String(config.port || defaults[kind])],
    ["Database", config.database], [kind === "postgresql" ? "Username" : "User ID", config.username], ["Password", secret],
    ...(kind === "postgresql" && config.schema ? [["Search Path", pgSchema(config.schema)] as [string, string]] : []),
    ...(kind === "postgresql" ? pgTlsFields.filter(field => Boolean(config[field])).map(field => {
      const names = { sslmode: "SSL Mode", sslrootcert: "Root Certificate", sslcert: "SSL Certificate", sslkey: "SSL Key" };
      // libpq require + an explicit CA verifies the chain; Npgsql Require does not.
      const mode = config.sslmode === "require" && config.sslrootcert ? "verify-ca" : config.sslmode;
      return [names[field], field === "sslmode" ? ({ disable: "Disable", allow: "Allow", prefer: "Prefer", require: "Require", "verify-ca": "VerifyCA", "verify-full": "VerifyFull" }[mode!]) : config[field]!] as [string, string];
    }) : [])]);
}

/** Credentials are only formatted from caller-provided transient data; no storage, logging or requests. */
export function formatConnectionString(config: ConnectionConfig, format: ConnectionStringFormat, includePassword = false): string {
  const kind = config.db_type;
  if (format === "native") return nativeString(config, includePassword);
  if (format === "uri") {
    if (kind === "databricks") throw new Error("Use ODBC ou Python para Databricks.");
    if (config.database.includes("?")) throw new Error("Use Python ou .NET para bancos cujo nome contém ?.");
    if (kind === "sqlite") return config.database === ":memory:" ? "sqlite://" : `sqlite:///${config.database}`;
    if (kind === "sqlserver") return `mssql+pyodbc:///?odbc_connect=${enc(nativeString(config, includePassword, true))}`;
    const scheme = kind === "postgresql" ? "postgresql+psycopg2" : kind === "mariadb" ? "mariadb+pymysql" : "mysql+pymysql";
    const host = config.host.includes(":") && !config.host.startsWith("[") ? `[${config.host}]` : config.host;
    const query = kind === "postgresql" ? pgQuery(config) : [];
    const scope = query.length ? `?${query.map(([key, value]) => `${key}=${enc(value)}`).join("&")}` : "";
    // SQLAlchemy decodes user/password, but keeps the database portion literal.
    return `${scheme}://${enc(config.username)}:${enc(password(config, includePassword))}@${host}:${config.port || defaults[kind]}/${config.database}${scope}`;
  }
  if (format === "python") {
    if (kind === "sqlite") return `import sqlite3\n\nconnection = sqlite3.connect(${literal(config.database)})`;
    if (kind === "sqlserver") return `import pyodbc\n\nconnection = pyodbc.connect(${literal(nativeString(config, includePassword, true))})`;
    if (kind === "databricks") return `from databricks import sql\n\nconnection = sql.connect(\n    server_hostname=${literal(config.host)},\n    http_path=${literal(config.http_path ?? "")},\n    ${config.databricks_auth_mode === "oauth" ? 'auth_type="databricks-oauth"' : `access_token=${literal(password(config, includePassword))}`},\n    catalog=${literal(config.database)},\n    schema=${literal(config.schema ?? "default")},\n)`;
    const dialect = kind === "postgresql" ? "postgresql+psycopg2" : kind === "mariadb" ? "mariadb+pymysql" : "mysql+pymysql";
    const query = kind === "postgresql" ? pgQuery(config) : [];
    return `from sqlalchemy import URL, create_engine\n\nurl = URL.create(\n    ${literal(dialect)},\n    username=${literal(config.username)},\n    password=${literal(password(config, includePassword))},\n    host=${literal(config.host)},\n    port=${config.port || defaults[kind]},\n    database=${literal(config.database)},\n${query.length ? `    query={${query.map(([key, value]) => `${literal(key)}: ${literal(value)}`).join(", ")}},\n` : ""})\nengine = create_engine(url)`;
  }
  const names = kind === "sqlserver" ? ["Microsoft.Data.SqlClient", "SqlConnection"] : kind === "postgresql" ? ["Npgsql", "NpgsqlConnection"] : kind === "sqlite" ? ["Microsoft.Data.Sqlite", "SqliteConnection"] : kind === "databricks" ? ["System.Data.Odbc", "OdbcConnection"] : ["MySqlConnector", "MySqlConnection"];
  return `using ${names[0]};\n\nusing var connection = new ${names[1]}(${literal(nativeString(config, includePassword))});\nconnection.Open();`;
}

function fail(): never { throw new Error("Connection string inválida ou formato não suportado. Cole uma URI ou uma string .NET/ODBC."); }
function decode(value: string): string { try { return decodeURIComponent(value); } catch { return fail(); } }
function flag(value: string | undefined, fallback = false) { if (value === undefined) return fallback; if (/^(true|yes|1|sspi)$/i.test(value)) return true; if (/^(false|no|0)$/i.test(value)) return false; return fail(); }
function port(value: string | undefined, kind: ConnectionConfig["db_type"]): number { if (!value) return defaults[kind]; if (!/^\d+$/.test(value) || +value < 1 || +value > 65535) return fail(); return +value; }
function base(kind: ConnectionConfig["db_type"]): ConnectionConfig { return { db_type: kind, host: "", port: defaults[kind], database: "", username: "", password: "", schema: kind === "postgresql" ? "public" : "", sqlserver_auth_mode: "sql_password", trust_server_certificate: false }; }

/** Semicolons inside ODBC braces / doubled ADO.NET quotes remain part of the value. */
export function parseConnectionPairs(text: string): Map<string, string> {
  const output = new Map<string, string>(); let index = 0;
  while (index < text.length) {
    while (/[;\s]/.test(text[index] ?? "") && index < text.length) index++;
    if (index === text.length) break;
    const start = index; while (index < text.length && text[index] !== "=") { if (text[index] === ";") fail(); index++; }
    if (index >= text.length) fail(); const key = text.slice(start, index++).trim().toLowerCase().replace(/[\s_]/g, ""); if (!key) fail();
    while (index < text.length && /\s/.test(text[index])) index++;
    let value = "", closed = false; const opener = text[index];
    if (["{", '"', "'"].includes(opener)) {
      index++; const ending = opener === "{" ? "}" : opener;
      while (index < text.length) { const character = text[index++]; if (character === ending) { if (text[index] === ending) { value += ending; index++; } else { closed = true; break; } } else value += character; }
      if (!closed) fail(); while (index < text.length && /\s/.test(text[index])) index++; if (index < text.length && text[index] !== ";") fail();
    } else { const valueStart = index; while (index < text.length && text[index] !== ";") index++; value = text.slice(valueStart, index).trim(); }
    if (output.has(key)) throw new Error("Connection string contém parâmetros duplicados."); output.set(key, value);
  }
  if (!output.size) fail(); return output;
}

export function parseConnectionString(input: string, selectedKind: ConnectionConfig["db_type"] = "sqlserver"): ConnectionConfig {
  const text = input.trim(); if (!text || text.length > 32768 || /\0/.test(text)) fail();
  const scheme = /^([a-z][a-z0-9+]*):\/\//i.exec(text)?.[1].toLowerCase();
  if (scheme) {
    if (scheme === "sqlite" || scheme === "sqlite+pysqlite") {
      if (text === `${scheme}://`) return { ...base("sqlite"), database: ":memory:" };
      if (!text.startsWith(`${scheme}:///`) || text.includes("?")) fail();
      return { ...base("sqlite"), database: text.slice(scheme.length + 4) };
    }
    if (scheme === "mssql+pyodbc" && text.startsWith(`${scheme}:///?`)) {
      const query = new URLSearchParams(text.slice(text.indexOf("?") + 1)); if (query.size !== 1 || !query.has("odbc_connect")) fail(); return parseConnectionString(query.get("odbc_connect")!, "sqlserver");
    }
    const kind = scheme.startsWith("postgres") ? "postgresql" : scheme.startsWith("mysql") ? "mysql" : scheme.startsWith("mariadb") ? "mariadb" : scheme.startsWith("mssql") ? "sqlserver" : undefined;
    if (!kind || !/^(postgres|postgresql|mysql|mariadb|mssql)(\+(psycopg2|psycopg|pymysql|pyodbc|pymssql|mysqldb))?$/.test(scheme)) fail();
    let url: URL; try { url = new URL(text); } catch { return fail(); }
    const pathStart = text.indexOf("/", text.indexOf("://") + 3), queryStart = text.indexOf("?", pathStart);
    const database = pathStart >= 0 ? text.slice(pathStart + 1, queryStart >= 0 ? queryStart : undefined) : "";
    if (!url.hostname || !database) fail();
    const config: ConnectionConfig = { ...base(kind), host: url.hostname.replace(/^\[|\]$/g, ""), port: port(url.port, kind), database: scheme.includes("+") ? database : decode(database), username: decode(url.username), password: decode(url.password) };
    const query = new URLSearchParams(queryStart >= 0 ? text.slice(queryStart + 1) : ""), seen = new Set<string>();
    for (const [key, value] of query) {
      if (seen.has(key.toLowerCase())) throw new Error("Connection string contém parâmetros duplicados."); seen.add(key.toLowerCase());
      if (kind === "postgresql" && key === "options" && /^-csearch_path=(?:\\[\s\S]|[^\s\\])+$/.test(value)) config.schema = parsePgSchema(value.slice(14).replace(/\\([\\\s])/g, "$1"));
      else if (kind === "postgresql" && pgTlsFields.includes(key.toLowerCase() as typeof pgTlsFields[number])) {
        const field = key.toLowerCase() as typeof pgTlsFields[number];
        if (field === "sslmode") config.sslmode = pgTlsMode(value); else config[field] = value;
      }
      else if (kind === "sqlserver" && key.toLowerCase() === "trustservercertificate") config.trust_server_certificate = flag(value);
      else if (kind === "sqlserver" && key.toLowerCase() === "driver" && /^ODBC Driver (17|18) for SQL Server$/i.test(value)) { /* Equivalent bundled driver. */ }
      else throw new Error("A conexão possui opções que o cadastro do DataPyn não suporta.");
    }
    if (config.password === PASSWORD_PLACEHOLDER) config.password = ""; return config;
  }
  const values = parseConnectionPairs(text), get = (...keys: string[]) => {
    const matches = keys.map(key => values.get(key.toLowerCase().replace(/[\s_]/g, ""))).filter(value => value !== undefined);
    if (matches.length > 1) throw new Error("Connection string contém parâmetros duplicados.");
    return matches[0];
  };
  const driver = get("driver") ?? "";
  const kind = /databricks|simba|spark/i.test(driver) || get("httppath") !== undefined ? "databricks" : /postgres/i.test(driver) || get("searchpath") !== undefined ? "postgresql" : /mysql/i.test(driver) ? "mysql" : /mariadb/i.test(driver) ? "mariadb" : ["integratedsecurity", "trustedconnection", "authentication", "trustservercertificate", "initialcatalog"].some(key => values.has(key)) || /sql server/i.test(driver) ? "sqlserver" : get("host") !== undefined ? "postgresql" : get("data source") !== undefined && get("database") === undefined ? "sqlite" : get("server") !== undefined && get("port") !== undefined && (selectedKind === "sqlite" || selectedKind === "sqlserver") ? "mysql" : selectedKind !== "sqlite" ? selectedKind : get("server") !== undefined ? "sqlserver" : "sqlite";
  const config = base(kind);
  if (driver && !/sql server|postgres|mysql|mariadb|databricks|simba|spark/i.test(driver)) throw new Error("Driver ODBC não suportado no cadastro do DataPyn.");
  const allowed = new Set(kind === "sqlite" ? ["datasource", "database"] : ["driver", "server", "datasource", "host", "port", "database", "username", "userid", "uid", "user", "password", "pwd",
    ...(kind === "sqlserver" ? ["initialcatalog", "integratedsecurity", "trustedconnection", "authentication", "encrypt", "trustservercertificate", "persistsecurityinfo"] : []),
    ...(kind === "postgresql" ? ["searchpath", "sslmode", "sslrootcert", "rootcertificate", "sslcert", "sslcertificate", "sslkey"] : []),
    ...(kind === "databricks" ? ["httppath", "catalog", "schema", "ssl", "thrifttransport", "authmech", "authflow"] : [])]);
  if ([...values.keys()].some(key => !allowed.has(key))) throw new Error("A conexão possui opções que o cadastro do DataPyn não suporta.");
  config.database = get("database", "initialcatalog") ?? "";
  config.username = get("username", "user id", "uid", "user") ?? "";
  config.password = get("password", "pwd") ?? "";
  if (kind === "sqlite") { config.database = get("data source") ?? config.database; if (!config.database) fail(); return config; }
  let host = get("host", "server", "data source") ?? "";
  if (kind === "sqlserver") { host = host.replace(/^tcp:/i, ""); const match = /^(.*),(\d+)$/.exec(host); if (match) { host = match[1]; config.port = port(match[2], kind); } }
  config.host = host; config.port = port(get("port") ?? String(config.port), kind); if (!host) fail();
  if (kind === "sqlserver") {
    config.use_windows_auth = flag(get("integrated security", "trusted_connection"));
    const authentication = get("authentication"); if (authentication && !/^Active Directory Interactive$/i.test(authentication)) throw new Error("Esse modo de autenticação não é suportado no cadastro.");
    config.sqlserver_auth_mode = config.use_windows_auth ? "windows" : authentication ? "entra_mfa" : "sql_password";
    config.trust_server_certificate = flag(get("trust server certificate"));
    if (get("encrypt") && !flag(get("encrypt"))) throw new Error("O DataPyn usa criptografia no SQL Server; Encrypt=false não é suportado.");
  }
  if (kind === "postgresql") {
    config.schema = parsePgSchema(get("search path") ?? "public");
    const mode = get("ssl mode"); if (mode !== undefined) config.sslmode = pgTlsMode(mode);
    const root = get("root certificate", "sslrootcert"), cert = get("ssl certificate", "sslcert"), key = get("ssl key");
    if (root !== undefined) config.sslrootcert = root;
    if (cert !== undefined) config.sslcert = cert;
    if (key !== undefined) config.sslkey = key;
  }
  if (kind === "databricks") {
    config.http_path = get("http path") ?? ""; config.database = get("catalog") ?? ""; config.schema = get("schema") ?? "default";
    const mechanism = get("authmech") ?? "3";
    if (mechanism === "11" && get("authflow") === "2") { config.databricks_auth_mode = "oauth"; config.password = ""; }
    else if (mechanism === "3" && (!config.username || config.username === "token")) config.databricks_auth_mode = "token";
    else throw new Error("Use OAuth no navegador ou token PAT para Databricks.");
    if (!config.http_path || get("ssl") && !flag(get("ssl")) || get("thrifttransport") && get("thrifttransport") !== "2") fail();
    config.username = "";
  } else if (!config.database) fail();
  if (config.password === PASSWORD_PLACEHOLDER) config.password = "";
  return config;
}
