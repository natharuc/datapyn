"""
Tests for the internationalization (i18n) language system.

Validates JSON loading, key access, fallback behavior,
format strings, and parity between en-US and pt-BR.
"""

import json
import os
import pytest
from unittest.mock import patch


# Path to language files
LANG_DIR = os.path.join(os.path.dirname(__file__), "..", "source", "src", "language")
EN_US_PATH = os.path.join(LANG_DIR, "en-US.json")
PT_BR_PATH = os.path.join(LANG_DIR, "pt-BR.json")


@pytest.fixture
def en_us_data():
    """Load en-US.json"""
    with open(EN_US_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def pt_br_data():
    """Load pt-BR.json"""
    with open(PT_BR_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _collect_keys(data: dict, prefix: str = "") -> set:
    """Recursively collect all keys (dot paths) from nested dict."""
    keys = set()
    for k, v in data.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(_collect_keys(v, full_key))
        else:
            keys.add(full_key)
    return keys


class TestLanguageFiles:
    """Tests for JSON language files"""

    def test_en_us_file_exists(self):
        assert os.path.exists(EN_US_PATH), "en-US.json must exist"

    def test_pt_br_file_exists(self):
        assert os.path.exists(PT_BR_PATH), "pt-BR.json must exist"

    def test_en_us_valid_json(self, en_us_data):
        assert isinstance(en_us_data, dict)
        assert "meta" in en_us_data
        assert en_us_data["meta"]["code"] == "en-US"

    def test_pt_br_valid_json(self, pt_br_data):
        assert isinstance(pt_br_data, dict)
        assert "meta" in pt_br_data
        assert pt_br_data["meta"]["code"] == "pt-BR"

    def test_en_us_has_required_sections(self, en_us_data):
        """en-US.json must have all required top-level sections"""
        required = [
            "meta", "menu", "toolbar", "dock", "status", "main_window",
            "empty_state", "about", "dialogs", "connection_panel",
            "session_widget", "results", "object_explorer", "variables_panel",
            "output_panel", "session_tabs", "bottom_tabs", "block",
            "find_replace", "block_editor", "settings", "connections_manager",
            "connection_edit", "connection_picker", "export_to_table",
            "file_import", "package_manager", "update_dialog",
            "mixed_executor", "workers", "session", "schema_service",
        ]
        for section in required:
            assert section in en_us_data, f"Missing section: {section}"

    def test_all_keys_match_between_languages(self, en_us_data, pt_br_data):
        """en-US and pt-BR must have exactly the same keys"""
        en_keys = _collect_keys(en_us_data)
        pt_keys = _collect_keys(pt_br_data)

        missing_in_pt = en_keys - pt_keys
        extra_in_pt = pt_keys - en_keys

        errors = []
        if missing_in_pt:
            errors.append(f"Keys in en-US but missing in pt-BR: {sorted(missing_in_pt)}")
        if extra_in_pt:
            errors.append(f"Keys in pt-BR but not in en-US: {sorted(extra_in_pt)}")

        assert not errors, "\n".join(errors)

    def test_no_empty_values_en_us(self, en_us_data):
        """No empty string values in en-US.json"""
        empty_keys = []
        for key_path in sorted(_collect_keys(en_us_data)):
            parts = key_path.split(".")
            value = en_us_data
            for p in parts:
                value = value[p]
            if isinstance(value, str) and value.strip() == "":
                empty_keys.append(key_path)

        assert not empty_keys, f"Empty values in en-US: {empty_keys}"

    def test_no_empty_values_pt_br(self, pt_br_data):
        """No empty string values in pt-BR.json"""
        empty_keys = []
        for key_path in sorted(_collect_keys(pt_br_data)):
            parts = key_path.split(".")
            value = pt_br_data
            for p in parts:
                value = value[p]
            if isinstance(value, str) and value.strip() == "":
                empty_keys.append(key_path)

        assert not empty_keys, f"Empty values in pt-BR: {empty_keys}"

    def test_format_placeholders_match(self, en_us_data, pt_br_data):
        """Format placeholders ({name}, {count}, etc.) must match between languages"""
        import re
        placeholder_pattern = re.compile(r"\{(\w+)\}")

        en_keys = _collect_keys(en_us_data)
        mismatches = []

        for key_path in sorted(en_keys):
            parts = key_path.split(".")
            en_value = en_us_data
            pt_value = pt_br_data
            try:
                for p in parts:
                    en_value = en_value[p]
                    pt_value = pt_value[p]
            except (KeyError, TypeError):
                continue  # Skip if key missing in one language (caught by other test)

            if not isinstance(en_value, str) or not isinstance(pt_value, str):
                continue

            en_placeholders = set(placeholder_pattern.findall(en_value))
            pt_placeholders = set(placeholder_pattern.findall(pt_value))

            if en_placeholders != pt_placeholders:
                mismatches.append(
                    f"{key_path}: en={en_placeholders}, pt={pt_placeholders}"
                )

        assert not mismatches, f"Placeholder mismatches:\n" + "\n".join(mismatches)


class TestLanguageModule:
    """Tests for the _Strings singleton and language loading"""

    def test_load_en_us(self):
        """Load en-US and verify basic keys exist"""
        from src.language import _Strings

        s = _Strings()
        s.init("en-US")

        assert s.language_code == "en-US"
        assert s.menu.file == "&File"
        assert s.menu.new_tab == "&New Tab"
        assert s.status.ready == "Ready"

    def test_load_pt_br(self):
        """Load pt-BR and verify basic keys exist"""
        from src.language import _Strings

        s = _Strings()
        s.init("pt-BR")

        assert s.language_code == "pt-BR"
        assert s.menu.file == "&Arquivo"
        assert s.menu.new_tab == "&Nova Aba"

    def test_fallback_to_en_us(self):
        """When a key is missing in target language, fallback to en-US"""
        from src.language import _Strings, _merge_with_fallback

        # Simulate a pt-BR missing a key
        fallback = {"menu": {"file": "&File", "special_key": "Special"}}
        target = {"menu": {"file": "&Arquivo"}}

        merged = _merge_with_fallback(target, fallback)
        assert merged["menu"]["file"] == "&Arquivo"  # Target has it
        assert merged["menu"]["special_key"] == "Special"  # Fallback kicks in

    def test_missing_key_returns_bracket_key(self):
        """Completely missing keys return [key_name] for debugging"""
        from src.language import _Strings

        s = _Strings()
        s.init("en-US")

        # Single-level missing key returns [key_name]
        result = s.nonexistent_section
        assert "[" in str(result)

    def test_format_strings_work(self):
        """Format strings with {param} work correctly"""
        from src.language import _Strings

        s = _Strings()
        s.init("en-US")

        # Test status.connected_to which has {name} and {db}
        result = s.status.connected_to.format(name="MyDB", db="testdb")
        assert "MyDB" in result
        assert "testdb" in result

    def test_get_available_languages(self):
        """get_available_languages returns at least en-US and pt-BR"""
        from src.language import get_available_languages

        languages = get_available_languages()
        codes = [lang["code"] for lang in languages]

        assert "en-US" in codes
        assert "pt-BR" in codes

    def test_language_names(self):
        """Available languages have proper display names"""
        from src.language import get_available_languages

        languages = get_available_languages()
        lang_map = {lang["code"]: lang["name"] for lang in languages}

        assert "English" in lang_map.get("en-US", "")
        assert "Portugu" in lang_map.get("pt-BR", "")  # Portugues

    def test_init_language_function(self):
        """init_language() initializes the global S singleton"""
        from src.language import init_language, S

        init_language("en-US")
        assert S.language_code == "en-US"
        assert S.menu.file == "&File"

    def test_singleton_pattern(self):
        """_Strings is a singleton - multiple instances are the same object"""
        from src.language import _Strings

        s1 = _Strings()
        s2 = _Strings()
        assert s1 is s2

    def test_reinit_language(self):
        """Re-initializing with different language updates all strings"""
        from src.language import _Strings

        s = _Strings()
        s.init("en-US")
        assert s.menu.file == "&File"

        s.init("pt-BR")
        assert s.menu.file == "&Arquivo"

        # Restore to en-US for other tests
        s.init("en-US")


class TestLanguageKeyUsage:
    """Tests that verify key categories used in the application"""

    def test_menu_keys(self):
        """Menu keys exist and have reasonable values"""
        from src.language import _Strings

        s = _Strings()
        s.init("en-US")

        assert "&" in s.menu.file  # Has mnemonic
        assert "&" in s.menu.new_tab
        assert "&" in s.menu.open
        assert "&" in s.menu.save
        assert "&" in s.menu.exit

    def test_block_keys(self):
        """Code block keys exist"""
        from src.language import _Strings

        s = _Strings()
        s.init("en-US")

        assert s.block.status_waiting == "Waiting"
        assert s.block.status_running == "Running"
        assert s.block.status_cancelled == "Cancelled"
        assert s.block.status_error == "Error"

    def test_find_replace_keys(self):
        """Find/Replace bar keys exist"""
        from src.language import _Strings

        s = _Strings()
        s.init("en-US")

        assert "Find" in s.find_replace.placeholder_find
        assert "Replace" in s.find_replace.placeholder_replace
        assert s.find_replace.btn_replace_all == "All"

    def test_settings_keys(self):
        """Settings dialog keys exist"""
        from src.language import _Strings

        s = _Strings()
        s.init("en-US")

        assert "Settings" in s.settings.title
        assert "Language" in s.settings.section_language or "LANGUAGE" in s.settings.section_language
        assert "restart" in s.settings.language_restart_hint.lower()

    def test_connection_panel_keys(self):
        """Connection panel keys exist"""
        from src.language import _Strings

        s = _Strings()
        s.init("en-US")

        assert s.connection_panel.section_active == "ACTIVE CONNECTION"
        assert s.connection_panel.btn_disconnect == "Disconnect"
        assert s.connection_panel.section_saved == "SAVED CONNECTIONS"
