import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, realpathSync, rmSync } from "node:fs";
import { basename, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { fileSha256, stableVersion } from "./release.mjs";
import { repoRoot, runtimePython } from "./common.mjs";

export function requireHostedRunner(env = process.env, platform = process.platform) {
  const runnerOs = platform === "linux" ? "Linux" : platform === "darwin" ? "macOS" : undefined;
  const runnerArchitecture = platform === "linux" ? "X64" : "ARM64";
  if (!runnerOs || env.GITHUB_ACTIONS !== "true" || env.RUNNER_ENVIRONMENT !== "github-hosted" || env.RUNNER_OS !== runnerOs || env.RUNNER_ARCH !== runnerArchitecture || !env.RUNNER_TEMP) throw new Error("Installed-package acceptance runs only on the matching GitHub Linux/macOS runner, never on the user's computer.");
  return realpathSync(env.RUNNER_TEMP);
}

function invoke(command, args, { cwd = repoRoot, env = process.env } = {}) {
  const result = spawnSync(command, args, { cwd, env, stdio: "inherit", shell: false, windowsHide: true });
  if (result.error || result.status !== 0) throw new Error(`Installed-package acceptance failed: ${command} (${result.error?.message ?? result.status}).`);
}

function frozenSmokes(runtime, invokeCommand, env) {
  if (!existsSync(runtime)) throw new Error(`The installed package does not contain its runtime: ${runtime}`);
  const python = runtimePython(env);
  for (const script of ["smoke_runtime.py", "smoke_parity.py", "smoke_persistence.py", "smoke_distribution.py"]) invokeCommand(python, [join(repoRoot, "scripts/tauri", script), "--executable", runtime], { env });
}

export function smokeInstalled({ directory, version, env = process.env, platform = process.platform, execute = invoke }) {
  const runnerRoot = requireHostedRunner(env, platform);
  stableVersion(version);
  const workspace = mkdtempSync(join(runnerRoot, "datapyn-installed-"));
  let mounted = false;
  const mount = join(workspace, "dmg-mount");
  try {
    if (platform === "linux") {
      const prefix = `DataPyn-Tauri-${version}-linux-x86_64`;
      const packageDirectory = join(workspace, "deb");
      mkdirSync(packageDirectory);
      execute("dpkg-deb", ["--extract", resolve(directory, prefix + ".deb"), packageDirectory], { env });
      const installedSeed = join(packageDirectory, "usr/lib/datapyn-tauri/DataPyn-Tauri.AppImage");
      if (fileSha256(installedSeed) !== fileSha256(join(directory, prefix + ".AppImage"))) throw new Error("The Debian seed differs from the signed updater AppImage.");
      const extraction = join(workspace, "appimage");
      mkdirSync(extraction);
      const extractionEnv = { ...env };
      // Request extraction only: do not allow the runtime's extract-and-run
      // environment switch to launch AppRun or the graphical application.
      delete extractionEnv.APPIMAGE_EXTRACT_AND_RUN;
      execute(installedSeed, ["--appimage-extract"], { cwd: extraction, env: extractionEnv });
      frozenSmokes(join(extraction, "squashfs-root/usr/bin/datapyn-runtime"), execute, env);
    } else {
      mkdirSync(mount);
      execute("hdiutil", ["attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", mount, resolve(directory, `DataPyn-Tauri-${version}-darwin-aarch64.dmg`)], { env });
      mounted = true;
      const application = join(workspace, "DataPyn Tauri.app");
      execute("ditto", [join(mount, "DataPyn Tauri.app"), application], { env });
      execute("codesign", ["--verify", "--deep", "--strict", application], { env });
      frozenSmokes(join(application, "Contents/MacOS/datapyn-runtime"), execute, env);
    }
    console.log(`Installed-package acceptance passed for ${platform}; no graphical window was opened.`);
  } finally {
    try {
      if (mounted) {
        execute("hdiutil", ["detach", mount], { env });
        mounted = false;
      }
    }
    finally {
      const resolved = resolve(workspace);
      if (!resolved.startsWith(resolve(runnerRoot) + sep) || !basename(resolved).startsWith("datapyn-installed-")) throw new Error("Refusing to clean a directory outside the runner's installation workspace.");
      // A failed detach must not turn recursive cleanup into traversal of a
      // mounted volume. The disposable runner can clean that workspace later.
      if (!mounted) rmSync(resolved, { recursive: true, force: true });
    }
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [directory, version] = process.argv.slice(2);
    smokeInstalled({ directory, version });
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
