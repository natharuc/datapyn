import { spawnSync } from "node:child_process";
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));

// Both Debian and portable entry points execute the same writable AppImage.
// Package upgrades update only the seed; the user's signed update takes precedence.
export function linuxLauncher({ portable = false } = {}) {
  const seed = portable ? '$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)' : "/usr/lib/datapyn-tauri";
  return `#!/bin/sh
set -eu
seed_directory="\${DATAPYN_TAURI_SEED_ROOT:-${seed}}"
data_directory="\${XDG_DATA_HOME:-$HOME/.local/share}/datapyn-tauri/installation"
umask 077
mkdir -p "$data_directory"
application="$data_directory/DataPyn-Tauri.AppImage"
if [ ! -f "$application" ]; then
  if [ ! -r "$seed_directory/DataPyn-Tauri.AppImage" ]; then
    printf '%s\\n' "DataPyn Tauri: arquivo inicial ausente: $seed_directory/DataPyn-Tauri.AppImage" >&2
    exit 1
  fi
  temporary=$(mktemp "$data_directory/.initial-XXXXXX")
  trap 'rm -f -- "$temporary"' EXIT HUP INT TERM
  cp -- "$seed_directory/DataPyn-Tauri.AppImage" "$temporary"
  chmod 700 "$temporary"
  # Link atomically without replacing a concurrent launch or an installed update.
  if ! ln -- "$temporary" "$application" 2>/dev/null && [ ! -f "$application" ]; then
    printf '%s\\n' "DataPyn Tauri: não foi possível preparar $application" >&2
    exit 1
  fi
  rm -f -- "$temporary"
  trap - EXIT HUP INT TERM
fi
export APPIMAGE_EXTRACT_AND_RUN=1
exec "$application" "$@"
`;
}

export function debianLayout({ directory, appImage, version, icon = join(root, "desktop/src-tauri/icons/256x256.png") }) {
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version)) throw new Error("Debian requires the independent stable Tauri version.");
  const write = (relative, content, mode = 0o644) => {
    const output = join(directory, relative);
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, content, { mode });
  };
  write("DEBIAN/control", `Package: datapyn-tauri\nVersion: ${version}\nArchitecture: amd64\nMaintainer: DataPyn Team (github.com/natharuc/datapyn)\nSection: devel\nPriority: optional\nInstalled-Size: ${Math.ceil(statSync(appImage).size / 1024) + 10}\nDepends: libc6 (>= 2.35), libstdc++6, libgtk-3-0, libnss3, libx11-6, unixodbc, libodbc2, libsecret-1-0, dbus-user-session, shared-mime-info\nRecommends: gnome-keyring, msodbcsql18\nHomepage: https://github.com/natharuc/datapyn\nDescription: DataPyn Tauri SQL and Python desktop\n Isolated desktop application with a per-user signed AppImage updater.\n`);
  write("usr/bin/datapyn-tauri", linuxLauncher(), 0o755);
  const image = join(directory, "usr/lib/datapyn-tauri/DataPyn-Tauri.AppImage");
  mkdirSync(dirname(image), { recursive: true });
  copyFileSync(appImage, image);
  chmodSync(image, 0o755);
  const imageIcon = join(directory, "usr/share/icons/hicolor/256x256/apps/datapyn-tauri.png");
  mkdirSync(dirname(imageIcon), { recursive: true });
  copyFileSync(icon, imageIcon);
  write("usr/share/applications/datapyn-tauri.desktop", "[Desktop Entry]\nType=Application\nName=DataPyn Tauri\nComment=SQL and Python data analysis\nExec=datapyn-tauri %F\nIcon=datapyn-tauri\nTerminal=false\nCategories=Development;Database;\nMimeType=application/x-datapyn-tauri-workspace;\nStartupWMClass=DataPyn Tauri\n");
  write("usr/share/mime/packages/datapyn-tauri.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info"><mime-type type="application/x-datapyn-tauri-workspace"><comment>DataPyn workspace</comment><glob pattern="*.dpw"/></mime-type></mime-info>\n');
  const refreshDesktop = '#!/bin/sh\nset -e\nif command -v update-mime-database >/dev/null 2>&1; then update-mime-database /usr/share/mime; fi\nif command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database /usr/share/applications; fi\nexit 0\n';
  write("DEBIAN/postinst", refreshDesktop, 0o755);
  write("DEBIAN/postrm", refreshDesktop, 0o755);
  write("usr/share/doc/datapyn-tauri/copyright", "DataPyn Tauri\nCopyright (c) 2024-2026 DataPyn Team\nLicense: MIT\nThe accompanying license.rtf contains the complete upstream license.\nhttps://github.com/natharuc/datapyn\n");
  write("usr/share/doc/datapyn-tauri/license.rtf", readFileSync(join(root, "scripts/license.rtf"), "utf8"));
}

export function buildDebianPackage({ appImage, version, output }) {
  if (process.platform !== "linux") throw new Error("Build the Debian installer on the native Linux release runner.");
  const temporary = mkdtempSync(join(tmpdir(), "datapyn-tauri-deb-"));
  try {
    const directory = join(temporary, "package");
    debianLayout({ directory, appImage, version });
    mkdirSync(dirname(output), { recursive: true });
    const result = spawnSync("dpkg-deb", ["--build", "--root-owner-group", directory, resolve(output)], { stdio: "inherit", shell: false });
    if (result.error || result.status !== 0) throw new Error("Failed to build the isolated Debian installer.");
    const verification = spawnSync("dpkg-deb", ["--field", resolve(output), "Package", "Version", "Architecture"], { encoding: "utf8", shell: false });
    if (verification.status !== 0 || !verification.stdout.includes("datapyn-tauri") || !verification.stdout.includes(version) || !verification.stdout.includes("amd64")) throw new Error("Debian installer metadata verification failed.");
  } finally {
    if (!resolve(temporary).startsWith(resolve(tmpdir()) + sep) || !basename(temporary).startsWith("datapyn-tauri-deb-")) throw new Error("Refusing to remove a non-temporary Debian workspace.");
    rmSync(temporary, { recursive: true, force: true });
  }
}
