"""
Internationalization (i18n) module for DataPyn.

Provides a simple JSON-based translation system with hierarchical keys.
Language files are stored as JSON in src/language/ (e.g., en-US.json, pt-BR.json).

Usage:
    from src.language import S
    label.setText(S.menu.file)              # returns "&File" or "&Arquivo"
    status.setText(S.status.ready)          # returns "Ready" or "Pronto"
    msg = S.status.connected_to.format(name="MyDB")  # format strings
"""

import json
import os
from types import SimpleNamespace
from typing import Optional


class _LanguageNamespace(SimpleNamespace):
    """Namespace that supports nested attribute access with fallback."""

    def __getattr__(self, name: str) -> str:
        # Return the key name itself as fallback (for debugging)
        return f"[{name}]"


def _dict_to_namespace(data: dict, path: str = "") -> _LanguageNamespace:
    """Convert a nested dict to a namespace with dot-access."""
    ns = _LanguageNamespace()
    for key, value in data.items():
        if isinstance(value, dict):
            setattr(ns, key, _dict_to_namespace(value, f"{path}.{key}" if path else key))
        else:
            setattr(ns, key, value)
    return ns


def _merge_with_fallback(target: dict, fallback: dict) -> dict:
    """Merge target dict with fallback, filling missing keys from fallback."""
    merged = {}
    for key in set(list(target.keys()) + list(fallback.keys())):
        if key in target and key in fallback:
            if isinstance(target[key], dict) and isinstance(fallback[key], dict):
                merged[key] = _merge_with_fallback(target[key], fallback[key])
            else:
                merged[key] = target[key]
        elif key in target:
            merged[key] = target[key]
        else:
            merged[key] = fallback[key]
    return merged


class _Strings:
    """
    Singleton class that holds all translated strings.

    Access strings via dot notation: S.menu.file, S.connection_panel.disconnect
    Strings are loaded from JSON files in the language directory.
    """

    _instance: Optional["_Strings"] = None
    _initialized: bool = False
    _language_code: str = "en-US"
    _data: dict = {}
    _ns: _LanguageNamespace = _LanguageNamespace()

    def __new__(cls) -> "_Strings":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __getattr__(self, name: str):
        return getattr(self._ns, name)

    def init(self, language_code: str = "en-US") -> None:
        """Initialize or re-initialize the language system."""
        self._language_code = language_code
        lang_dir = os.path.dirname(os.path.abspath(__file__))

        # Always load en-US as fallback base
        fallback_path = os.path.join(lang_dir, "en-US.json")
        fallback_data = {}
        if os.path.exists(fallback_path):
            with open(fallback_path, "r", encoding="utf-8") as f:
                fallback_data = json.load(f)

        if language_code == "en-US":
            self._data = fallback_data
        else:
            # Load target language and merge with fallback
            target_path = os.path.join(lang_dir, f"{language_code}.json")
            if os.path.exists(target_path):
                with open(target_path, "r", encoding="utf-8") as f:
                    target_data = json.load(f)
                self._data = _merge_with_fallback(target_data, fallback_data)
            else:
                self._data = fallback_data

        self._ns = _dict_to_namespace(self._data)
        self._initialized = True

    @property
    def language_code(self) -> str:
        return self._language_code

    @property
    def language_name(self) -> str:
        meta = self._data.get("meta", {})
        return meta.get("name", self._language_code)


def get_available_languages() -> list[dict]:
    """
    Scan the language directory for available language JSON files.
    Returns a list of dicts with 'code' and 'name' keys.
    """
    lang_dir = os.path.dirname(os.path.abspath(__file__))
    languages = []
    for filename in sorted(os.listdir(lang_dir)):
        if filename.endswith(".json"):
            filepath = os.path.join(lang_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = data.get("meta", {})
                languages.append({
                    "code": meta.get("code", filename.replace(".json", "")),
                    "name": meta.get("name", filename.replace(".json", "")),
                })
            except (json.JSONDecodeError, OSError):
                continue
    return languages


def init_language(language_code: str = "en-US") -> None:
    """Initialize the global language system. Call before creating any UI."""
    S.init(language_code)


# Global singleton instance - import this everywhere
S = _Strings()
