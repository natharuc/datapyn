import type { ConnectionConfig } from "./workspace";

export interface DatabaseCapabilities {
  query_language: "sql"; sql_dialect: string;
  context_levels: Array<"database" | "schema" | "container">;
  metadata: boolean; streaming: boolean; sqlalchemy: boolean;
  table_export: boolean; temporary_tables: boolean; manual_transactions: boolean;
  ssh: boolean; read_only: boolean;
}
export const RELATIONAL_TYPES = ["sqlserver", "postgresql", "mysql", "mariadb", "sqlite", "databricks"] as const;
export const isDocumentDatabase = (type?: string) => ["elasticsearch", "cosmosdb", "mongodb"].includes(type ?? "");
export const isCosmosNoSql = (config?: Partial<ConnectionConfig>) => config?.db_type === "cosmosdb" && config.cosmos_api !== "mongodb";
export const isMongoConnection = (config?: Partial<ConnectionConfig>) => config?.db_type === "mongodb" || config?.db_type === "cosmosdb" && config.cosmos_api === "mongodb";

/** UI defaults mirror the runtime contract; backend validation remains authoritative. */
export function databaseCapabilities(input?: string | Partial<ConnectionConfig>): DatabaseCapabilities {
  const config = typeof input === "string" ? { db_type: input, cosmos_api:undefined } : input;
  const type = config?.db_type ?? "";
  const relational = (RELATIONAL_TYPES as readonly string[]).includes(type);
  const cosmos = type === "cosmosdb" && config?.cosmos_api !== "mongodb";
  return { query_language: "sql", sql_dialect: type === "cosmosdb" && !cosmos ? "mongodb" : type,
    context_levels: type === "elasticsearch" ? [] : cosmos ? ["database", "container"] : ["postgresql", "sqlserver", "databricks"].includes(type) ? ["database", "schema"] : ["database"],
    metadata: relational || isDocumentDatabase(type), streaming: true, sqlalchemy: relational,
    table_export: relational, temporary_tables: relational, manual_transactions: relational,
    ssh: ["sqlserver", "postgresql", "mysql", "mariadb"].includes(type), read_only: !relational };
}
