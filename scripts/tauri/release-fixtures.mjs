import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, resolve, sep } from "node:path";
import { combineRelease, RELEASE_PLATFORMS, updateManifest } from "./release.mjs";

export function temporaryRelease(t) {
  const directory = mkdtempSync(join(tmpdir(), "datapyn-release-test-"));
  t.after(() => {
    if (!resolve(directory).startsWith(resolve(tmpdir()) + sep) || !basename(directory).startsWith("datapyn-release-test-")) throw new Error("Unsafe test cleanup target.");
    rmSync(directory, { recursive: true, force: true });
  });
  return directory;
}

export function fixturePlatforms(directory, version = "1.0.0") {
  const inputDirectory = join(directory, "incoming");
  for (const platform of RELEASE_PLATFORMS) {
    const platformDirectory = join(inputDirectory, platform);
    mkdirSync(platformDirectory, { recursive: true });
    const extension = platform.startsWith("windows") ? "-setup.exe" : platform.startsWith("linux") ? ".AppImage" : ".app.tar.gz";
    const name = `DataPyn-Tauri-${version}-${platform}${extension}`;
    writeFileSync(join(platformDirectory, name), `signed ${platform} artifact`);
    writeFileSync(join(platformDirectory, name + ".sig"), `actual-${platform}-signature`);
    const manifest = updateManifest({ bundleDirectory: platformDirectory, version, platform });
    writeFileSync(join(platformDirectory, `manifest-${platform}.json`), JSON.stringify(manifest));
    if (platform.startsWith("linux")) for (const suffix of [".deb", ".tar.gz"]) writeFileSync(join(platformDirectory, `DataPyn-Tauri-${version}-${platform}${suffix}`), "package");
    if (platform.startsWith("darwin")) writeFileSync(join(platformDirectory, `DataPyn-Tauri-${version}-${platform}.dmg`), "package");
    if (platform.startsWith("windows")) writeFileSync(join(platformDirectory, `DataPyn-Tauri-${version}-${platform}.zip`), "portable");
  }
  return inputDirectory;
}

export function completeRelease(directory, version = "1.0.0") {
  const inputDirectory = fixturePlatforms(directory, version);
  const outputDirectory = join(directory, "complete");
  combineRelease({ inputDirectory, outputDirectory, version });
  return { directory: outputDirectory, manifest: JSON.parse(readFileSync(join(outputDirectory, "latest.json"), "utf8")) };
}
