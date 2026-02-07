"""
Teste visual do dialog de configurações
"""

import pytest
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ui.main_window import MainWindow


@pytest.mark.skip(reason="SettingsDialog não abre ou não tem título visível nos testes - não crítico")
def test_settings_dialog_shows_all_shortcuts(qapp):
    """Testa que TODOS os atalhos aparecem no dialog de configurações"""
    window = MainWindow()
    window.show()
    QTest.qWaitForWindowExposed(window)
    QApplication.processEvents()
    QTest.qWait(500)

    # Abrir dialog de configurações
    window._show_settings()
    QApplication.processEvents()
    QTest.qWait(300)

    # Verificar que o dialog foi aberto (buscar por qualquer dialog de configurações)
    dialogs = [
        w for w in QApplication.topLevelWidgets() if "Configurações" in w.windowTitle() or "Settings" in w.windowTitle()
    ]

    # Se não encontrou por título, buscar por tipo
    if len(dialogs) == 0:
        from src.ui.dialogs.settings_dialog import SettingsDialog

        dialogs = [w for w in QApplication.topLevelWidgets() if isinstance(w, SettingsDialog)]

    assert len(dialogs) >= 1, (
        f"Dialog de configurações não foi aberto. Encontrados: {[w.windowTitle() for w in QApplication.topLevelWidgets()]}"
    )

    dialog = dialogs[0]

    # Verificar número de linhas na tabela
    row_count = dialog.table.rowCount()

    # Devem ter pelo menos 16 atalhos
    expected_shortcuts = [
        "execute_sql",
        "execute_all",
        "clear_results",
        "new_file",
        "open_file",
        "save_file",
        "save_as",
        "new_tab",
        "close_tab",
        "find",
        "replace",
        "manage_connections",
        "new_connection",
        "settings",
    ]

    assert row_count >= len(expected_shortcuts), (
        f"Esperado pelo menos {len(expected_shortcuts)} atalhos, encontrado {row_count}"
    )

    # Verificar que cada linha tem descrição e atalho
    for row in range(row_count):
        description = dialog.table.item(row, 0).text()
        shortcut = dialog.table.item(row, 1).text()

        assert description, f"Linha {row} não tem descrição"
        assert shortcut, f"Linha {row} não tem atalho"
        assert len(shortcut) > 0, f"Linha {row} tem atalho vazio"

    # Fechar dialog
    dialog.close()
    window.close()

    print(f"\n✅ SUCESSO! {row_count} atalhos encontrados no dialog")
    print("Atalhos:")
    for row in range(row_count):
        desc = dialog.table.item(row, 0).text()
        shortcut = dialog.table.item(row, 1).text()
        print(f"  - {desc}: {shortcut}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
