import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { createReadStream, createWriteStream, existsSync } from "node:fs";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { promisify } from "node:util";
import { repoRoot, optionValue } from "./common.mjs";

const executeFile = promisify(execFile);
export const windowsPrerequisite = JSON.parse(await readFile(new URL("./windows-prerequisites.json", import.meta.url), "utf8"));

export async function verifyPrerequisiteHash(path, expected = windowsPrerequisite.sha256) {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(path)) digest.update(chunk);
  if (digest.digest("hex").toUpperCase() !== expected.toUpperCase()) {
    throw new Error("O instalador Microsoft ODBC não corresponde ao SHA256 fixado. Build interrompido.");
  }
}

function nsisString(value) {
  if (/[\r\n]/.test(value)) throw new Error("Caminho inválido para incluir o pré-requisito NSIS.");
  return value.replaceAll("$", "$$").replaceAll('"', '$\\"');
}

export async function prepareWindowsPrerequisites(args = [], { platform = process.platform, target = optionValue(args, "--target") } = {}) {
  if (platform !== "win32" || args.includes("--no-bundle")) return undefined;
  if (target && target !== "x86_64-pc-windows-msvc") {
    throw new Error("O instalador de produção Windows usa runtime e ODBC x64; gere essa arquitetura nativamente.");
  }
  const bundles = optionValue(args, "--bundles");
  if (bundles && !bundles.split(",").some(value => value === "nsis" || value === "all")) return undefined;
  const directory = join(repoRoot, "build", "windows-prerequisites");
  await mkdir(directory, { recursive: true });
  const destination = join(directory, windowsPrerequisite.filename);
  if (!existsSync(destination)) {
    const temporary = `${destination}.partial-${process.pid}`;
    try {
      const response = await fetch(windowsPrerequisite.url, { signal: AbortSignal.timeout(120_000) });
      if (!response.ok || !response.body) throw new Error(`Download Microsoft ODBC falhou: HTTP ${response.status}`);
      let received = 0;
      const bounded = new Transform({ transform(chunk, encoding, done) {
        received += chunk.length;
        done(received > 64 * 1024 * 1024 ? new Error("Instalador ODBC excede o tamanho esperado.") : null, chunk);
      } });
      await pipeline(Readable.fromWeb(response.body), bounded, createWriteStream(temporary, { flags: "wx" }));
      await verifyPrerequisiteHash(temporary);
      await rename(temporary, destination);
    } finally {
      await rm(temporary, { force: true });
    }
  }
  await verifyPrerequisiteHash(destination);
  await executeFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
    join(repoRoot, "scripts", "tauri", "windows-verify-prerequisite.ps1"),
    "-Path", destination, "-ExpectedSha256", windowsPrerequisite.sha256], { windowsHide: true });
  const include = join(directory, "odbc-artifact.nsh");
  await writeFile(include, `; Generated after SHA256 and Microsoft Authenticode verification.\n!define DATAPYN_ODBC_MSI "${nsisString(destination)}"\n!define DATAPYN_ODBC_SHA256 "${windowsPrerequisite.sha256}"\n`, "utf8");
  console.log(`Microsoft ODBC ${windowsPrerequisite.version} ${windowsPrerequisite.architecture}: SHA256 e assinatura verificados.`);
  return { path: destination, include, sha256: windowsPrerequisite.sha256 };
}
