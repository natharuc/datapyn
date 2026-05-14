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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
