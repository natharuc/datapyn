"""
Teste visual do dialog de configuracoes
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock
from PyQt6.QtCore import QEvent

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


def test_settings_dialog_has_sidebar_navigation(qapp, mock_shortcut_manager):
    dialog = SettingsDialog(mock_shortcut_manager)
    try:
        assert hasattr(dialog, "_nav_panel")
        assert hasattr(dialog, "_content_stack")
        assert "general" in dialog._page_order
        assert dialog._nav_panel.node_by_id("shortcuts") is not None
    finally:
        dialog.close()


def test_settings_dialog_initial_tab_pynia(qapp, mock_shortcut_manager):
    dialog = SettingsDialog(mock_shortcut_manager, initial_tab="pynia")
    try:
        assert dialog._page_order[dialog._content_stack.currentIndex()] == "pynia"
        assert dialog._nav_panel._tree.currentItem() is not None
    finally:
        dialog.close()


def test_settings_dialog_search_filters_tree(qapp, mock_shortcut_manager):
    dialog = SettingsDialog(mock_shortcut_manager)
    try:
        dialog._nav_panel.filter_text("telegram")
        assert not dialog._nav_panel._items["notifications.telegram"].isHidden()
        dialog.navigate_to("notifications", "notifications.telegram")
        assert dialog._page_order[dialog._content_stack.currentIndex()] == "notifications"
    finally:
        dialog.close()


def test_settings_search_no_results_hides_content(qapp, mock_shortcut_manager):
    dialog = SettingsDialog(mock_shortcut_manager)
    try:
        dialog._on_settings_search_text_changed("zzzz-not-found")
        qapp.processEvents()
        assert not dialog._search_empty_label.isHidden()
        assert dialog._settings_body.isHidden()
        assert dialog._settings_footer.isHidden()

        dialog._on_settings_search_text_changed("")
        qapp.processEvents()
        assert dialog._search_empty_label.isHidden()
        assert not dialog._settings_body.isHidden()
        assert not dialog._settings_footer.isHidden()
    finally:
        dialog.close()


def test_settings_dialog_search_is_at_dialog_top(qapp, mock_shortcut_manager):
    dialog = SettingsDialog(mock_shortcut_manager)
    try:
        assert hasattr(dialog, "_settings_search")
        assert not hasattr(dialog._nav_panel, "_search")
    finally:
        dialog.close()


def test_search_input_consumes_return_key(qapp):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from src.ui.components.inputs import SearchInput

    widget = SearchInput(consume_return=True)
    widget.show()
    qapp.processEvents()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    assert widget.eventFilter(widget.input, event) is True


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


def test_pynia_settings_page_lists_agents(qapp, mock_shortcut_manager):
    """Pynia settings shows the four ACP agents and autocomplete toggle."""
    dialog = SettingsDialog(mock_shortcut_manager)
    try:
        assert hasattr(dialog, "_pynia_page")
        combo = dialog._pynia_page._default_combo
        agent_ids = [combo.itemData(i) for i in range(combo.count())]
        assert "" in agent_ids
        assert "claude" in agent_ids
        assert "cursor" in agent_ids
        assert "copilot" in agent_ids
        assert "codex" in agent_ids
        assert hasattr(dialog._pynia_page, "_autocomplete")
    finally:
        dialog.close()


def test_pynia_default_agent_emits(qapp, mock_shortcut_manager):
    dialog = SettingsDialog(mock_shortcut_manager)
    emitted = []
    dialog.pynia_connector_changed.connect(lambda pid: emitted.append(pid))
    try:
        combo = dialog._pynia_page._default_combo
        combo.setCurrentIndex(combo.findData("codex"))
        qapp.processEvents()
        assert "codex" in emitted
        assert dialog._current_pynia_connector_id() == "codex"
    finally:
        dialog.close()


def test_save_all_skips_pynia_connector_emit_when_unchanged(qapp, mock_shortcut_manager):
    """Saving unrelated settings must not re-apply the live Pynia connector."""
    dialog = SettingsDialog(mock_shortcut_manager)
    emitted = []
    dialog.pynia_connector_changed.connect(lambda pid: emitted.append(pid))
    try:
        dialog._save_all()
        qapp.processEvents()
        assert emitted == []
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
