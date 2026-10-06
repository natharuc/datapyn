import { Database } from "lucide-react";
import sqlserver from "./assets/databases/sqlserver.svg";
import sqlserverDark from "./assets/databases/sqlserver-dark.svg";
import postgresql from "./assets/databases/postgresql.svg";
import postgresqlDark from "./assets/databases/postgresql-dark.svg";
import mysql from "./assets/databases/mysql.svg";
import mysqlDark from "./assets/databases/mysql-dark.svg";
import mariadb from "./assets/databases/mariadb.svg";
import mariadbDark from "./assets/databases/mariadb-dark.svg";
import databricks from "./assets/databases/databricks.svg";
import sqlite from "./assets/databases/sqlite.svg";
import sqliteDark from "./assets/databases/sqlite-dark.svg";
import "./databaseIcon.css";

export const databaseIconAssets = {
  sqlserver: { light: sqlserver, dark: sqlserverDark },
  postgresql: { light: postgresql, dark: postgresqlDark },
  mysql: { light: mysql, dark: mysqlDark },
  mariadb: { light: mariadb, dark: mariadbDark },
  databricks: { light: databricks, dark: databricks },
  sqlite: { light: sqlite, dark: sqliteDark },
} as const;
type DatabaseType = keyof typeof databaseIconAssets;
const aliases: Record<string, DatabaseType> = {
  sqlserver: "sqlserver", mssql: "sqlserver", microsoftsqlserver: "sqlserver", azuresql: "sqlserver",
  postgresql: "postgresql", postgres: "postgresql", pgsql: "postgresql",
  mysql: "mysql", mariadb: "mariadb", databricks: "databricks", databrickssql: "databricks",
  sqlite: "sqlite", sqlite3: "sqlite",
};

export function databaseIconType(dbType?: string | null): DatabaseType | undefined {
  if (typeof dbType !== "string") return;
  const key = dbType.trim().toLowerCase().split("+", 1)[0].replace(/[\s_-]+/g, "");
  return Object.hasOwn(aliases, key) ? aliases[key] : undefined;
}

/** Adjacent connection labels make the mark decorative; label standalone use. */
export function DatabaseIcon({ dbType, size = 16, label, fallbackColor }: { dbType?: string | null; size?: number; label?: string; fallbackColor?: string }) {
  const type = databaseIconType(dbType), asset = type ? databaseIconAssets[type] : undefined;
  return <span className="database-icon" data-database={type} style={{ width: size, height: size, color: fallbackColor }} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
    {asset ? asset.dark === asset.light
      ? <img src={asset.light} alt="" aria-hidden="true" />
      : <><img className="database-icon-dark" src={asset.dark} alt="" aria-hidden="true" /><img className="database-icon-light" src={asset.light} alt="" aria-hidden="true" /></>
      : <Database size={size} aria-hidden="true" />}
  </span>;
}
