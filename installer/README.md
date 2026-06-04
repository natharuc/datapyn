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
| `DataPyn-Setup.exe` | Fresh install (default `%LOCALAPPDATA%\DataPyn`) |
| `DataPyn-Setup.exe --update <zip> --version 1.2.3 --dir <path>` | Silent upgrade from downloaded ZIP |
| `DataPyn-Setup.exe --uninstall` | Remove install dir, shortcuts, registry |

## Release artifacts

CI publishes:

- `DataPyn-{version}-windows.zip` — PyInstaller folder
- `DataPyn-Setup.exe` — version-agnostic bootstrap (always fetches latest)
- `DataPyn-Setup-{version}.exe` — pinned to that release

The desktop app auto-update downloads the ZIP and applies it on exit.
