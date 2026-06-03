import * as vscode from "vscode";
import { resolveRuntimeDirectory, RuntimeClient } from "./runtimeClient";

let client: RuntimeClient | undefined;
let outputChannel: vscode.OutputChannel | undefined;

export function activate(context: vscode.ExtensionContext): void {
  outputChannel = vscode.window.createOutputChannel("DataPyn");
  context.subscriptions.push(outputChannel);

  const getClient = () => {
    const cfg = vscode.workspace.getConfiguration("datapyn");
    const runtimeDir = resolveRuntimeDirectory(context);
    const useUv = cfg.get<boolean>("runtime.useUv", true);
    if (!client) {
      client = new RuntimeClient(runtimeDir, useUv);
      context.subscriptions.push({ dispose: () => client?.dispose() });
    }
    return client;
  };

  context.subscriptions.push(
    vscode.commands.registerCommand("datapyn.pocPing", async () => {
      try {
        const c = getClient();
        await c.start();
        log("Runtime ping OK");
        vscode.window.showInformationMessage("DataPyn runtime: ping OK");
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        log(`Ping failed: ${msg}`);
        vscode.window.showErrorMessage(`DataPyn runtime ping failed: ${msg}`);
      }
    }),

    vscode.commands.registerCommand("datapyn.pocRunSql", async () => {
      const editor = vscode.window.activeTextEditor;
      const sql =
        editor?.document.getText(editor.selection)?.trim() ||
        editor?.document.getText()?.trim() ||
        "SELECT 1 AS n";

      try {
        const c = getClient();
        const result = await c.executeSql(sql);
        const preview = formatResult(result);
        log(`SQL OK (${result.row_count} row(s)):\n${preview}`);
        vscode.window.showInformationMessage(
          `DataPyn: ${result.row_count} row(s) — see Output channel`
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        log(`SQL failed: ${msg}`);
        vscode.window.showErrorMessage(`DataPyn SQL failed: ${msg}`);
      }
    })
  );

  log("DataPyn v2 extension activated (PoC)");
}

export function deactivate(): void {
  client?.dispose();
  client = undefined;
}

function log(message: string): void {
  outputChannel?.appendLine(`[${new Date().toISOString()}] ${message}`);
}

function formatResult(result: {
  columns: string[];
  rows: unknown[][];
}): string {
  const header = result.columns.join(" | ");
  const lines = result.rows.map((row) =>
    row.map((c) => String(c ?? "")).join(" | ")
  );
  return [header, "-".repeat(Math.max(header.length, 3)), ...lines].join("\n");
}
