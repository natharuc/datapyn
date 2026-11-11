import type { ConnectionConfig } from "./workspace";
import { isCosmosNoSql, isMongoConnection } from "./databaseCapabilities";

const encode = encodeURIComponent;
const quoted = JSON.stringify;
const PUBLIC_MONGO_OPTIONS = new Set("authsource authmechanism replicaset directconnection tls ssl tlscafile tlscertificatekeyfile tlsallowinvalidcertificates tlsallowinvalidhostnames retrywrites retryreads maxpoolsize minpoolsize maxidletimems connecttimeoutms sockettimeoutms serverselectiontimeoutms appname compressors loadbalanced readpreference uuidrepresentation w".split(" "));

/** Split credentials before a Mongo URI can enter the public connection catalog. */
export function parseMongoUri(input: string, type: "mongodb" | "cosmosdb" = "mongodb"): ConnectionConfig {
  const match = /^(mongodb(?:\+srv)?):\/\/([^/?#]+)(\/[^?#]*)?(?:\?([^#]*))?$/i.exec(input.trim());
  if (!match) throw new Error("URI MongoDB inválida.");
  const authority = match[2], separator = authority.lastIndexOf("@");
  const hosts = separator < 0 ? authority : authority.slice(separator + 1);
  if (!hosts || /\s|@/.test(hosts) || match[1].toLowerCase().endsWith("+srv") && (hosts.includes(",") || /:\d+$/.test(hosts))) throw new Error("URI MongoDB inválida.");
  let username = "", password = "", database = "";
  try {
    if (separator >= 0) {
      const account = authority.slice(0, separator), colon = account.indexOf(":");
      username = decodeURIComponent(colon < 0 ? account : account.slice(0, colon));
      password = colon < 0 ? "" : decodeURIComponent(account.slice(colon + 1));
    }
    database = decodeURIComponent((match[3] ?? "/").slice(1));
  } catch { throw new Error("URI MongoDB inválida."); }
  const query = new URLSearchParams(match[4] ?? ""), seen = new Set<string>();
  for (const [name] of query) {
    const key = name.toLowerCase();
    if (!PUBLIC_MONGO_OPTIONS.has(key) || seen.has(key)) throw new Error("A URI possui opções não suportadas ou secretas.");
    seen.add(key);
  }
  return { db_type: type, ...(type === "cosmosdb" ? { cosmos_api: "mongodb" as const } : {}),
    host: "", port: 27017, database, username, password,
    mongodb_uri: `${match[1].toLowerCase()}://${hosts}${match[3] ?? "/"}${query.size ? `?${query}` : ""}` };
}

export function publicMongoUri(uri: string): string { return parseMongoUri(uri).mongodb_uri!; }

function mongoUri(config: ConnectionConfig, include: boolean) {
  const uri = parseMongoUri(config.mongodb_uri || "mongodb://localhost/"), publicUri = uri.mongodb_uri!;
  const [prefix, rest] = publicUri.split("://");
  const authorityEnd = rest.indexOf("/"), hosts = authorityEnd < 0 ? rest : rest.slice(0, authorityEnd);
  const query = rest.includes("?") ? rest.slice(rest.indexOf("?")) : "";
  const account = config.username ? `${encode(config.username)}:${encode(include ? config.password ?? "" : "<password>")}@` : "";
  return `${prefix}://${account}${hosts}/${encode(config.database)}${query}`;
}

export function formatDocumentConnection(config: ConnectionConfig, format: string, include = false): string {
  if (isMongoConnection(config)) {
    const uri = mongoUri(config, include);
    if (format === "uri") return uri;
    if (format === "python") return `from pymongo import MongoClient\n\nclient = MongoClient(${quoted(uri)}, retryReads=False, retryWrites=False)\ndatabase = client[${quoted(config.database)}]`;
    if (format === "csharp") return `using MongoDB.Driver;\n\nvar client = new MongoClient(${quoted(uri)});\nvar database = client.GetDatabase(${quoted(config.database)});`;
  }
  if (isCosmosNoSql(config)) {
    const endpoint = config.endpoint ?? "", key = include ? config.account_key ?? "" : "<account-key>";
    if (format === "native" && config.auth_mode !== "entra") return `AccountEndpoint=${endpoint};AccountKey=${key};`;
    if (format === "python") return `from azure.cosmos import CosmosClient\n${config.auth_mode === "entra" ? "from azure.identity import InteractiveBrowserCredential\n" : ""}\nclient = CosmosClient(${quoted(endpoint)}, credential=${config.auth_mode === "entra" ? `InteractiveBrowserCredential(tenant_id=${quoted(config.tenant_id || "organizations")})` : quoted(key)})\ndatabase = client.get_database_client(${quoted(config.database)})\ncontainer = database.get_container_client(${quoted(config.container ?? "")})`;
    if (format === "csharp") return `using Microsoft.Azure.Cosmos;\n${config.auth_mode === "entra" ? "using Azure.Identity;\n" : ""}\nusing var client = new CosmosClient(${quoted(endpoint)}, ${config.auth_mode === "entra" ? `new InteractiveBrowserCredential(new InteractiveBrowserCredentialOptions { TenantId = ${quoted(config.tenant_id || "organizations")} })` : quoted(key)});\nvar container = client.GetContainer(${quoted(config.database)}, ${quoted(config.container ?? "")});`;
  }
  if (config.db_type === "elasticsearch") {
    const endpoint = config.endpoint ?? "";
    if (format === "uri") return endpoint;
    const apiKey = include ? config.api_key ?? "" : "<api-key>";
    if (format === "python") return `from elasticsearch import Elasticsearch\n\nclient = Elasticsearch(${quoted(endpoint)}, ${config.auth_mode === "api_key" ? `api_key=${quoted(apiKey)}` : `basic_auth=(${quoted(config.username)}, ${quoted(include ? config.password ?? "" : "<password>")})`})\nresponse = client.sql.query(query="SELECT * FROM \\\"my-index\\\" LIMIT 10")`;
    if (format === "csharp") return `using Elastic.Clients.Elasticsearch;\nusing Elastic.Transport;\n\nvar settings = new ElasticsearchClientSettings(new Uri(${quoted(endpoint)}))\n    .Authentication(${config.auth_mode === "api_key" ? `new ApiKey(${quoted(apiKey)})` : `new BasicAuthentication(${quoted(config.username)}, ${quoted(include ? config.password ?? "" : "<password>")})`});\nvar client = new ElasticsearchClient(settings);`;
  }
  throw new Error("Formato indisponível para este banco.");
}
