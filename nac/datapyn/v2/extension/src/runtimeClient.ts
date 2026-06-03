import { spawn, type ChildProcessWithoutNullStreams } from "child_process";
import * as path from "path";
import * as readline from "readline";
import * as vscode from "vscode";

export interface JsonRpcResponse<T = unknown> {
  jsonrpc?: string;
  id?: number;
  result?: T;
  error?: { code: number; message: string; data?: unknown };
}

export interface ExecuteSqlResult {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
}

export class RuntimeClient {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private rl: readline.Interface | null = null;
  private nextId = 1;

  constructor(private readonly runtimeDirectory: string, private readonly useUv: boolean) {}

  async start(): Promise<void> {
    if (this.proc) {
      return;
    }

    const cwd = this.runtimeDirectory;
    const args = this.useUv
      ? ["run", "python", "-m", "datapyn_runtime"]
      : ["-m", "datapyn_runtime"];
    const command = this.useUv ? "uv" : "python3";

    this.proc = spawn(command, args, {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
      env: process.env,
    });

    this.proc.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      if (text.trim()) {
        console.error("[datapyn-runtime]", text);
      }
    });

    this.rl = readline.createInterface({ input: this.proc.stdout });

    const ping = await this.call<{ ok: boolean; version?: string }>("ping", {});
    if (!ping.ok) {
      throw new Error("Runtime ping failed");
    }
  }

  async executeSql(sql: string): Promise<ExecuteSqlResult> {
    await this.start();
    return this.call<ExecuteSqlResult>("execute_sql", { sql });
  }

  dispose(): void {
    if (this.proc?.stdin.writable) {
      try {
        this.proc.stdin.write(
          JSON.stringify({ jsonrpc: "2.0", method: "shutdown", id: this.nextId++ }) + "\n"
        );
      } catch {
        // ignore
      }
    }
    this.rl?.close();
    this.proc?.kill();
    this.proc = null;
    this.rl = null;
  }

  private call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    return new Promise((resolve, reject) => {
      if (!this.proc?.stdin.writable || !this.rl) {
        reject(new Error("Runtime process is not running"));
        return;
      }

      const id = this.nextId++;
      const payload = JSON.stringify({ jsonrpc: "2.0", method, params, id }) + "\n";

      const onLine = (line: string) => {
        if (!line.trim()) {
          return;
        }
        let message: JsonRpcResponse<T>;
        try {
          message = JSON.parse(line) as JsonRpcResponse<T>;
        } catch (e) {
          this.rl?.off("line", onLine);
          reject(e);
          return;
        }
        if (message.id !== id) {
          return;
        }
        this.rl?.off("line", onLine);
        if (message.error) {
          reject(new Error(message.error.message));
          return;
        }
        resolve(message.result as T);
      };

      this.rl.on("line", onLine);
      this.proc.stdin.write(payload, (err) => {
        if (err) {
          this.rl?.off("line", onLine);
          reject(err);
        }
      });
    });
  }
}

export function resolveRuntimeDirectory(
  context: vscode.ExtensionContext
): string {
  const configured = vscode.workspace
    .getConfiguration("datapyn")
    .get<string>("runtime.directory")
    ?.trim();
  if (configured) {
    return path.resolve(configured);
  }
  return path.resolve(context.extensionPath, "..", "runtime");
}
