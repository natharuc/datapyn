# DataPyn Setup (Windows)

Lightweight GUI installer that downloads the latest **ZIP** artifact from GitHub Releases.

## Build

```powershell
uv sync --dev
uv run pyinstaller installer/datapyn_setup.spec --clean
# Output: dist/DataPyn-Setup.exe
```

## Usage

| Command | Description |
|---------|-------------|
| `DataPyn-Setup.exe` | Fresh install, or **Reparar** if an install is already detected |
| `DataPyn-Setup.exe --repair` | Re-download latest ZIP and replace files (waits for DataPyn to close) |
| `DataPyn-Setup.exe --repair --dir <path>` | Repair a custom install folder |
| `DataPyn-Setup.exe --update <zip> --version 1.2.3 --dir <path>` | Silent upgrade from downloaded ZIP |
| `DataPyn-Setup.exe --uninstall` | Remove install dir, shortcuts, registry |

## Release artifacts

CI publishes:

CI publishes (same GitHub Release):

Windows:
- `DataPyn-{version}-windows.zip` — PyInstaller folder
- `DataPyn-Setup.exe` — version-agnostic bootstrap (always fetches latest)

Linux (amd64, built on Ubuntu 22.04):
- `datapyn_{version}_amd64.deb`
- `datapyn-{version}-1.x86_64.rpm`
- `datapyn-{version}-1-x86_64.pkg.tar.zst`
- `DataPyn-{version}-x86_64.AppImage`
- `DataPyn-{version}-linux-x86_64.tar.gz`
- `DataPyn-linux-artifacts.json`
- `SHA256SUMS`

macOS (Apple Silicon, unsigned):
- `DataPyn-{version}-macos-arm64.dmg`

The desktop app auto-update downloads the Windows ZIP and applies it on exit.
