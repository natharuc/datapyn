"""Run the legacy CI suite without reading or changing desktop settings or credentials."""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    # Set both the Qt native paths and the two-string constructor explicitly:
    # QSettings(organization, application) does not use setDefaultFormat().
    with tempfile.TemporaryDirectory(prefix="datapyn-legacy-ci-") as directory:
        os.environ.update(
            APPDATA=directory, LOCALAPPDATA=directory, XDG_CONFIG_HOME=directory,
            QT_QPA_PLATFORM="offscreen", QTWEBENGINE_DISABLE_SANDBOX="1",
            QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --no-sandbox",
        )
        from PyQt6 import QtCore
        import keyring
        from keyring.backend import KeyringBackend

        original_settings = QtCore.QSettings
        original_settings.setDefaultFormat(original_settings.Format.IniFormat)
        for scope in (original_settings.Scope.UserScope, original_settings.Scope.SystemScope):
            original_settings.setPath(original_settings.Format.IniFormat, scope, directory)

        class IsolatedSettings(original_settings):
            def __init__(self, *args, **kwargs):
                if len(args) >= 2 and all(isinstance(arg, str) for arg in args[:2]):
                    args = (original_settings.Format.IniFormat, original_settings.Scope.UserScope, *args)
                else:
                    args = tuple(original_settings.Format.IniFormat
                                 if isinstance(arg, original_settings.Format)
                                 and arg == original_settings.Format.NativeFormat else arg for arg in args)
                super().__init__(*args, **kwargs)

        class MemoryKeyring(KeyringBackend):
            priority = 1

            def __init__(self):
                self.passwords = {}

            def get_password(self, service, username):
                return self.passwords.get((service, username))

            def set_password(self, service, username, password):
                self.passwords[(service, username)] = password

            def delete_password(self, service, username):
                self.passwords.pop((service, username), None)

        QtCore.QSettings = IsolatedSettings
        keyring.set_keyring(MemoryKeyring())
        sys.path.insert(0, str(ROOT / "source"))
        import pytest

        ignored = re.findall(r"^    (test_\w+\.py)$", (ROOT / "scripts/ci_pytest.sh").read_text(encoding="utf-8"), re.M)
        args = [str(ROOT / "tests"), "-p", "no:faulthandler", "-q", "--disable-warnings",
                *[f"--ignore={ROOT / 'tests' / name}" for name in ignored]]
        return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
