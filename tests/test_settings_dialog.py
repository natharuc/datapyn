"""
Teste visual do dialog de configuracoes
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ui.dialogs.settings_dialog import SettingsDialog
from src.core.shortcut_manager import ShortcutManager


@pytest.fixture
def mock_shortcut_manager():
    """Cria um mock do ShortcutManager"""
    manager = MagicMock(spec=ShortcutManager)
    manager.get_all_shortcuts.return_value = {
        "execute_sql": "F5",
        "execute_all": "Shift+F5",
        "new_tab": "Ctrl+T",
        "show_entity_info": "Alt+F1",
    }
    return manager


def test_settings_dialog_can_be_instantiated(qapp, mock_shortcut_manager):
    """Testa que SettingsDialog pode ser criado"""
    dialog = SettingsDialog(mock_shortcut_manager)
    assert dialog is not None
    assert hasattr(dialog, "table")
    dialog.close()


def test_settings_dialog_has_shortcuts_table(qapp, mock_shortcut_manager):
    """Testa que o dialog tem uma tabela de atalhos"""
    dialog = SettingsDialog(mock_shortcut_manager)
    assert dialog.table.columnCount() >= 2
    dialog.close()


def test_settings_dialog_lists_entity_info_shortcut(qapp, mock_shortcut_manager):
    """O atalho de informacoes da entidade aparece na tabela."""
    dialog = SettingsDialog(mock_shortcut_manager)
    shortcut_values = [dialog.table.item(row, 1).text() for row in range(dialog.table.rowCount())]
    assert "Alt+F1" in shortcut_values
    dialog.close()


def test_shortcut_conflicts_are_flagged(qapp):
    """Two actions bound to the same shortcut are detected and tooltip-flagged."""
    manager = MagicMock(spec=ShortcutManager)
    manager.get_all_shortcuts.return_value = {
        "clear_results": "Ctrl+Shift+C",
        "copy_with_headers": "Ctrl+Shift+C",  # conflict
        "new_tab": "Ctrl+T",
    }
    dialog = SettingsDialog(manager)
    try:
        conflicts = dialog._highlight_shortcut_conflicts()
        assert any(
            key == "Ctrl+Shift+C" and len(actions) == 2 for key, actions in conflicts
        )
        tips = {
            dialog.table.item(r, 1).text(): dialog.table.item(r, 1).toolTip()
            for r in range(dialog.table.rowCount())
        }
        assert tips.get("Ctrl+Shift+C")  # conflicting row has a tooltip
        assert not tips.get("Ctrl+T")    # unique row does not
    finally:
        dialog.close()


def test_pynia_completion_model_picker_round_trips(qapp, mock_shortcut_manager):
    """The autocomplete model picker persists an explicit pick and 'auto' (blank)."""
    from src.services.pynia.settings import get_pynia_settings

    dialog = SettingsDialog(mock_shortcut_manager)
    try:
        assert hasattr(dialog, "_pynia_completion_model_combo")
        pid = dialog._current_pynia_connector_id()

        dialog._pynia_completion_model_combo.setEditText("gpt-4.1-mini")
        dialog._save_pynia_completion_model()
        assert get_pynia_settings().completion_model_override(pid) == "gpt-4.1-mini"

        # Blank == auto (use chat model): the override is cleared.
        dialog._pynia_completion_model_combo.setEditText("")
        dialog._save_pynia_completion_model()
        assert get_pynia_settings().completion_model_override(pid) == ""
    finally:
        dialog.close()


def test_pynia_save_token_activates_and_emits(qapp, mock_shortcut_manager, monkeypatch):
    """Saving a connector token makes it active and signals the live agent."""
    from unittest.mock import MagicMock
    from src.services.pynia.settings import (
        get_pynia_settings,
        get_provider_secret,
        set_provider_secret,
    )

    monkeypatch.setattr(
        "src.services.pynia.settings.threading.Thread",
        lambda *args, **kwargs: MagicMock(start=lambda: None),
    )

    dialog = SettingsDialog(mock_shortcut_manager)
    dialog._fetch_pynia_models = lambda _pid: None
    emitted = []
    dialog.pynia_connector_changed.connect(lambda pid: emitted.append(pid))
    try:
        combo = dialog._pynia_provider_combo
        combo.setCurrentIndex(combo.findData("openrouter"))
        dialog._pynia_token_edit.setText("sk-or-test")
        dialog._on_pynia_save_token()

        assert get_pynia_settings().active_provider == "openrouter"
        assert get_provider_secret("openrouter") == "sk-or-test"
        qapp.processEvents()
        assert emitted == ["openrouter"]
    finally:
        set_provider_secret("openrouter", "")
        dialog.close()


def test_copilot_signin_switches_agent_and_logs_in(qapp, mock_shortcut_manager, monkeypatch):
    """Clicking Copilot sign-in activates the connector and triggers GitHub login
    (not the API-token verify path)."""
    from unittest.mock import MagicMock
    from src.services.pynia.settings import get_pynia_settings

    fake_auth = MagicMock()
    fake_auth.login_chat.return_value = True
    monkeypatch.setattr("src.services.pynia.get_pynia_auth_service", lambda: fake_auth)

    dialog = SettingsDialog(mock_shortcut_manager)
    emitted = []
    dialog.pynia_connector_changed.connect(lambda pid: emitted.append(pid))
    try:
        dialog._on_chat_auth_clicked()
        assert emitted == ["copilot"]
        fake_auth.login_chat.assert_called_once()
        assert get_pynia_settings().active_provider == "copilot"
    finally:
        get_pynia_settings().set_active_provider("openai")
        dialog.close()


def test_pynia_connectors_include_copilot(qapp, mock_shortcut_manager):
    """GitHub Copilot is listed as a connector and swaps to its sign-in UI."""
    dialog = SettingsDialog(mock_shortcut_manager)
    try:
        combo = dialog._pynia_provider_combo
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert "copilot" in ids

        # Copilot selected → GitHub sign-in section shown, API-token hidden.
        combo.setCurrentIndex(combo.findData("copilot"))
        assert not dialog._pynia_copilot_section.isHidden()
        assert dialog._pynia_token_section.isHidden()

        # API connector selected → token fields shown, Copilot hidden.
        combo.setCurrentIndex(combo.findData("openai"))
        assert not dialog._pynia_token_section.isHidden()
        assert dialog._pynia_copilot_section.isHidden()
    finally:
        dialog.close()


def test_pynia_model_picker_lists_fetched_models(qapp, mock_shortcut_manager):
    """Fetched connector models populate the picker as a selectable list."""
    from src.services.pynia.completion import COMPLETION_MODEL_SUGGESTIONS

    dialog = SettingsDialog(mock_shortcut_manager)
    try:
        pid = dialog._current_pynia_connector_id()
        dialog._on_pynia_models_fetched(pid, ["gpt-4.1", "gpt-4.1-mini", "o3-mini"])

        combo = dialog._pynia_completion_model_combo
        items = [combo.itemText(i) for i in range(combo.count())]
        # Real fetched models are now in the dropdown.
        assert "o3-mini" in items
        assert "gpt-4.1" in items
        # Curated fast suggestions are still surfaced (for easy picking).
        for suggestion in COMPLETION_MODEL_SUGGESTIONS.get(pid, [])[:1]:
            assert suggestion in items
        # No duplicates in the list.
        assert len(items) == len(set(items))
    finally:
        dialog.close()


def test_settings_dialog_exec_twice_with_parent_window(qapp):
    """Opening Settings twice on the main window must not crash (backdrop/shadow)."""
    from PyQt6.QtWidgets import QMainWindow, QWidget

    manager = ShortcutManager()
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    window.resize(900, 700)
    window.show()
    qapp.processEvents()

    for _ in range(2):
        dialog = SettingsDialog(manager, parent=window)
        dialog.exec()
        qapp.processEvents()
        assert window.findChild(QWidget, "modalBackdrop") is None

    window.close()


def test_settings_with_nested_confirm_then_reopen(qapp):
    """Child confirm over Settings must not break a second Settings open."""
    from PyQt6.QtWidgets import QMainWindow, QWidget
    from src.design_system.app_dialogs import confirm_yes_no

    manager = ShortcutManager()
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    window.resize(900, 700)
    window.show()
    qapp.processEvents()

    first = SettingsDialog(manager, parent=window)
    first.show()
    qapp.processEvents()
    confirm_yes_no(first, "Confirm", "Nested test?", default_yes=False)
    qapp.processEvents()
    first.reject()
    qapp.processEvents()

    second = SettingsDialog(manager, parent=window)
    second.exec()
    qapp.processEvents()
    assert window.findChild(QWidget, "modalBackdrop") is None

    window.close()


def test_no_false_shortcut_conflict(qapp):
    """Distinct shortcuts produce no conflict."""
    manager = MagicMock(spec=ShortcutManager)
    manager.get_all_shortcuts.return_value = {
        "execute_sql": "F5",
        "new_tab": "Ctrl+T",
    }
    dialog = SettingsDialog(manager)
    try:
        assert dialog._highlight_shortcut_conflicts() == []
    finally:
        dialog.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
