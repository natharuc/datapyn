"""Transfer legacy global QSettings through real Qt INI files.

Run with the legacy Python environment. This optional migration helper is never
imported by the Qt-free Tauri runtime and never runs on application startup.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

GLOBAL_CATEGORIES = ("DataPyn", "MainWindow", "DockingLayout", "CSVExport", "ExportSettings", "PackageManager")
SECRET_NAMES = {"password", "token", "access_token", "client_secret", "telegram_bot_token", "email_password", "bot_token"}
MAX_INI_BYTES = 16 * 1024 * 1024


def _secret(key):
    return str(key).replace("\\", "/").rsplit("/", 1)[-1].casefold() in SECRET_NAMES


def _sanitize(value, key=""):
    if isinstance(value, dict):
        return {name: _sanitize(item, name) for name, item in value.items() if not _secret(name)}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, str) and key in {"url", "extra_index_urls", "extra_index_url"}:
        parts = urlsplit(value)
        if "@" in parts.netloc:
            return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, parts.query, parts.fragment))
    return value


def _values(settings):
    from PyQt6.QtCore import QSettings
    settings.setFallbacksEnabled(False)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("Unable to read legacy settings")
    values = {key: _sanitize(settings.value(key), key) for key in settings.allKeys() if not _secret(key)}
    sources = values.get("sources_v2")
    if isinstance(sources, list):
        # The headless importer cannot decode an opaque QVariant safely. Also
        # supply the legacy password-free QStringList representation.
        values["extra_index_urls"] = [source["url"] for source in sources if isinstance(source, dict) and isinstance(source.get("url"), str)]
    return values


def export_globals(folder, factory=None):
    """Add INI files to an explicit folder, refusing any existing destination file."""
    from PyQt6.QtCore import QSettings
    destination = Path(folder).expanduser().resolve()
    if destination.exists() and not destination.is_dir():
        raise ValueError("Select a configuration folder")
    files = [destination / f"{category}.ini" for category in GLOBAL_CATEGORIES]
    if any(path.exists() or path.is_symlink() for path in files):
        raise FileExistsError("A global settings file already exists; choose another folder")
    # All reads finish before creating or changing any export file.
    values = [(category, _values(factory(category) if factory else QSettings("DataPyn", category))) for category in GLOBAL_CATEGORIES]
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for category, data in values:
            if not data:
                continue
            path = destination / f"{category}.ini"
            target = QSettings(str(path), QSettings.Format.IniFormat)
            target.setFallbacksEnabled(False)
            written.append(path)
            for key, value in data.items():
                target.setValue(key, value)
            target.sync()
            if target.status() != QSettings.Status.NoError or path.stat().st_size > MAX_INI_BYTES:
                raise OSError("Unable to export legacy global settings")
        return written
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise


def import_globals(folder, factory=None):
    """Apply explicitly selected INI files to legacy settings, retaining Qt types."""
    from PyQt6.QtCore import QSettings
    source = Path(folder).expanduser().resolve()
    if not source.is_dir():
        raise ValueError("Select a configuration folder")
    incoming = []
    for category in GLOBAL_CATEGORIES:
        path = source / f"{category}.ini"
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INI_BYTES:
            raise ValueError("Invalid global settings file")
        values = _values(QSettings(str(path), QSettings.Format.IniFormat))
        target = factory(category) if factory else QSettings("DataPyn", category)
        target.setFallbacksEnabled(False)
        target.sync()
        if target.status() != QSettings.Status.NoError:
            raise OSError("Unable to read the target legacy settings")
        original = {key: (target.contains(key), target.value(key)) for key in values}
        incoming.append((category, values, target, original))
    if not incoming:
        raise ValueError("This folder contains no legacy global settings INI files")
    applied = []
    try:
        for category, values, target, original in incoming:
            applied.append((target, original))
            for key, value in values.items():
                target.setValue(key, value)
            target.sync()
            if target.status() != QSettings.Status.NoError:
                raise OSError(f"Unable to apply {category} settings")
        return [category for category, _, _, _ in incoming]
    except Exception:
        for target, original in reversed(applied):
            for key, (existed, value) in original.items():
                if existed:
                    target.setValue(key, value)
                else:
                    target.remove(key)
            target.sync()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("export", "import"))
    parser.add_argument("--folder", required=True, help="Explicit configuration folder; import changes the legacy PyQt settings")
    args = parser.parse_args()
    try:
        items = export_globals(args.folder) if args.operation == "export" else import_globals(args.folder)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Global settings {args.operation}: {len(items)} categories. Credentials and workspace registrations are excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
