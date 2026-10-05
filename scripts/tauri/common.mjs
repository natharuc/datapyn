import { spawn, spawnSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const repoRoot = fileURLToPath(new URL("../../", import.meta.url));
export const desktopRoot = join(repoRoot, "desktop");

function newestDirectory(parent) {
  if (!existsSync(parent)) return undefined;
  const versions = readdirSync(parent, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^\d+(?:\.\d+)+$/.test(entry.name))
    .map((entry) => entry.name)
    .sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  return versions.at(-1);
}

function prependEnvironmentPath(env, name, values) {
  const key = Object.keys(env).find((candidate) => candidate.toUpperCase() === name) || name;
  env[key] = [...values.filter((value) => value && existsSync(value)), env[key] || ""].filter(Boolean).join(delimiter);
}

function addLocalWindowsSdk(env) {
  if (process.platform !== "win32") return;
  const architecture = process.arch === "arm64" ? "arm64" : "x64";
  const cppRoot = join(repoRoot, ".tooling", "windows-sdk", "cpp", "c");
  const sdkVersion = newestDirectory(join(cppRoot, "Include"));
  if (!sdkVersion) return;
  const sdkLibRoot = join(repoRoot, ".tooling", "windows-sdk", architecture, "c");
  const vswhere = join(env["ProgramFiles(x86)"] || "C:\\Program Files (x86)", "Microsoft Visual Studio", "Installer", "vswhere.exe");
  let msvcRoot;
  if (existsSync(vswhere)) {
    const result = spawnSync(vswhere, ["-products", "*", "-property", "installationPath"], { encoding: "utf8", windowsHide: true });
    const installations = result.status === 0 ? result.stdout.trim().split(/\r?\n/) : [];
    for (const installation of installations) {
      const tools = join(installation, "VC", "Tools", "MSVC");
      const version = newestDirectory(tools);
      if (version) { msvcRoot = join(tools, version); break; }
    }
  }
  prependEnvironmentPath(env, "PATH", [join(cppRoot, "bin", sdkVersion, architecture), msvcRoot && join(msvcRoot, "bin", "Hostx64", architecture)]);
  const msvcLib = msvcRoot && (existsSync(join(msvcRoot, "lib", architecture)) ? join(msvcRoot, "lib", architecture) : join(msvcRoot, "lib", "onecore", architecture));
  prependEnvironmentPath(env, "LIB", [join(sdkLibRoot, "um", architecture), join(sdkLibRoot, "ucrt", architecture), msvcLib]);
  prependEnvironmentPath(env, "INCLUDE", [join(repoRoot, ".tooling", "msvc", "include"), ...["um", "shared", "ucrt", "winrt"].map((part) => join(cppRoot, "Include", sdkVersion, part)), ...(msvcRoot ? [join(msvcRoot, "include")] : [])]);
}

export function developmentEnvironment() {
  const env = { ...process.env };
  const cargoRoot = join(repoRoot, ".tooling", "cargo");
  const rustupRoot = join(repoRoot, ".tooling", "rustup");
  const cargoName = process.platform === "win32" ? "cargo.exe" : "cargo";
  const paths = [];
  if (!env.CARGO_HOME && existsSync(join(cargoRoot, "bin", cargoName))) {
    env.CARGO_HOME = cargoRoot;
    if (!env.RUSTUP_HOME && existsSync(rustupRoot)) env.RUSTUP_HOME = rustupRoot;
  }
  if (env.CARGO_HOME) paths.push(join(env.CARGO_HOME, "bin"));
  paths.push(join(homedir(), ".cargo", "bin"));
  // Windows environment keys are case insensitive. Avoid creating both Path and PATH.
  const pathKey = Object.keys(env).find((key) => key.toUpperCase() === "PATH") || "PATH";
  env[pathKey] = [...paths, env[pathKey] || ""].join(delimiter);
  env.DATAPYN_REPO_ROOT = repoRoot;
  env.PYTHONPATH = [join(repoRoot, "source"), env.PYTHONPATH || ""].filter(Boolean).join(delimiter);
  env.PYTHONUNBUFFERED = "1";
  env.MPLBACKEND = "Agg";
  addLocalWindowsSdk(env);
  return env;
}

export function runtimePython(env = process.env) {
  const configured = env.DATAPYN_RUNTIME_PYTHON;
  const candidate = configured ? resolve(configured) : join(repoRoot, ".venv", process.platform === "win32" ? "Scripts" : "bin", process.platform === "win32" ? "python.exe" : "python");
  if (!existsSync(candidate)) {
    throw new Error(`Python não encontrado: ${candidate}. Execute uv sync --dev na raiz ou configure DATAPYN_RUNTIME_PYTHON com um caminho absoluto.`);
  }
  return candidate;
}

export function tauriCli() {
  const cli = join(desktopRoot, "node_modules", "@tauri-apps", "cli", "tauri.js");
  if (!existsSync(cli)) throw new Error("CLI Tauri não instalada. Execute npm ci dentro de desktop.");
  return cli;
}

export function optionValue(args, name) {
  const index = args.indexOf(name);
  if (index !== -1) return args[index + 1];
  const inline = args.find((arg) => arg.startsWith(`${name}=`));
  return inline?.slice(name.length + 1);
}

export function run(command, args, { cwd = desktopRoot, env = developmentEnvironment() } = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: "inherit", windowsHide: true, shell: false });
    const onSignal = (signal) => child.kill(signal);
    const onInterrupt = () => onSignal("SIGINT");
    const onTerminate = () => onSignal("SIGTERM");
    process.once("SIGINT", onInterrupt);
    process.once("SIGTERM", onTerminate);
    const detach = () => {
      process.removeListener("SIGINT", onInterrupt);
      process.removeListener("SIGTERM", onTerminate);
    };
    child.once("error", (error) => { detach(); reject(error); });
    child.once("close", (code, signal) => { detach(); resolvePromise(code ?? (signal ? 130 : 1)); });
  });
}

export function runtimeBuildEnvironment(base = developmentEnvironment()) {
  const env = { ...base };
  env.DATAPYN_RUNTIME_PYTHON = runtimePython(env);
  // Invoking a venv Python directly does not activate its console scripts.
  // PyInstaller and distribution preflight also need the selected interpreter's
  // uv/ruff; local project tools remain available for a custom interpreter.
  prependEnvironmentPath(env, "PATH", [dirname(env.DATAPYN_RUNTIME_PYTHON), join(repoRoot, ".venv", process.platform === "win32" ? "Scripts" : "bin")]);
  return env;
}

export async function bundleRuntime(args = []) {
  const env = runtimeBuildEnvironment();
  return run(env.DATAPYN_RUNTIME_PYTHON, [join(repoRoot, "scripts", "tauri", "build_runtime.py"), ...args], { cwd: repoRoot, env });
}

export async function main(action) {
  try {
    process.exitCode = await action();
  } catch (error) {
    console.error(error.message || error);
    process.exitCode = 1;
  }
}
