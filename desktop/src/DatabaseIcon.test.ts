import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DatabaseIcon, databaseIconAssets, databaseIconType } from "./DatabaseIcon";

const databaseTypes = ["sqlserver", "postgresql", "mysql", "mariadb", "databricks", "sqlite"] as const;

describe("database marks", () => {
  it.each(databaseTypes)("renders the bundled %s logo with fixed dimensions", (dbType) => {
    const html = renderToStaticMarkup(createElement(DatabaseIcon, { dbType, size: 16 }));
    expect(html).toContain(`data-database="${dbType}"`);
    expect(html).toContain("width:16px;height:16px");
    expect(html).not.toContain("lucide-database");
    const sources = [...html.matchAll(/src="([^"]+)"/g)].map((match) => match[1].replaceAll("&#x27;", "'").replaceAll("&amp;", "&"));
    expect(sources).toContain(databaseIconAssets[dbType].light);
    expect(sources).toContain(databaseIconAssets[dbType].dark);
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('alt=""');
  });

  it.each([
    [" SQL Server ", "sqlserver"], ["mssql", "sqlserver"], ["Microsoft SQL Server", "sqlserver"],
    ["azure-sql", "sqlserver"], ["mssql+pyodbc", "sqlserver"],
    ["Postgres", "postgresql"], ["pgsql", "postgresql"], ["postgresql+psycopg2", "postgresql"],
    ["MySQL+pymysql", "mysql"], ["MariaDB", "mariadb"],
    ["Databricks SQL", "databricks"], ["databricks_sql", "databricks"], ["SQLite3", "sqlite"],
  ])("recognizes the imported database type %s", (dbType, expected) => {
    expect(databaseIconType(dbType)).toBe(expected);
    expect(renderToStaticMarkup(createElement(DatabaseIcon, { dbType }))).toContain(`data-database="${expected}"`);
  });

  it.each([undefined, null, "", "unknown", "constructor", "__proto__"])("uses a neutral fallback for %s", (dbType) => {
    const html = renderToStaticMarkup(createElement(DatabaseIcon, { dbType, fallbackColor: "#12ab34" }));
    expect(html).toContain("lucide-database");
    expect(html).not.toContain("<img");
    expect(html).toContain("color:#12ab34");
  });

  it("provides one accessible name when used without an adjacent label", () => {
    const html = renderToStaticMarkup(createElement(DatabaseIcon, { dbType: "postgresql", label: "PostgreSQL" }));
    expect(html).toContain('role="img" aria-label="PostgreSQL"');
    expect(html.match(/aria-label=/g)).toHaveLength(1);
    expect(html.match(/alt=""/g)).toHaveLength(2);
  });

  it("reuses the existing PyQt logos and changes only the dark-theme monochrome fill", () => {
    for (const type of databaseTypes) {
      const original = readFileSync(new URL(`../../source/src/assets/icons/db/${type}.svg`, import.meta.url), "utf8").replaceAll("\r\n", "\n");
      const light = readFileSync(new URL(`./assets/databases/${type}.svg`, import.meta.url), "utf8").replaceAll("\r\n", "\n");
      expect(light).toBe(original);
      expect(light).toMatch(/viewBox="0 0 [\d.]+ [\d.]+"/);
      expect(light).not.toMatch(/<script|<foreignObject|<image|\bhref=|\bon\w+=/i);
      if (type === "databricks") continue;
      const dark = readFileSync(new URL(`./assets/databases/${type}-dark.svg`, import.meta.url), "utf8").replaceAll("\r\n", "\n");
      const expected = type === "sqlserver" ? light.replace("<svg ", '<svg fill="#dce7eb" ')
        : light.replaceAll(type === "mariadb" ? "#003545" : "#000000", "#dce7eb");
      expect(dark).toBe(expected);
      expect(dark).not.toMatch(/<script|<foreignObject|<image|\bhref=|\bon\w+=/i);
    }
  });
});
