"""
Configuracao do pytest e fixtures compartilhadas
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import json

# ==================== FIX: WMI hang on Python 3.12 + Windows ==================
# Python 3.12 changed platform.win32_ver() to use WMI queries instead of registry.
# WMI can hang indefinitely if the service is unresponsive (common after crashes).
# sqlalchemy imports platform.machine() at module level, triggering the WMI query.
# Pre-cache the result or bypass WMI to prevent test hangs.
import platform
try:
    # Try to disable WMI-based queries by pre-caching platform info
    if sys.platform == "win32" and hasattr(platform, "_wmi_query"):
        # Monkey-patch _wmi_query to return empty string (avoids WMI hang)
        platform._wmi_query = lambda *args, **kwargs: ""
        # Force uname cache with fallback values
        if not hasattr(platform, "_uname_cache") or platform._uname_cache is None:
            import struct
            machine = "AMD64" if struct.calcsize("P") * 8 == 64 else "x86"
            platform._uname_cache = platform.uname_result(
                system="Windows",
                node=os.environ.get("COMPUTERNAME", ""),
                release="",
                version="",
                machine=machine,
            )
except Exception:
    pass  # Not critical, just a performance optimization
# ==================== END FIX ==================================================

# Configurar WebEngine para testes (desabilitar GPU para evitar erros)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-software-rasterizer --no-sandbox")
os.environ.setdefault("QT_OPENGL", "software")

# Importar QtWebEngineWidgets ANTES de criar QApplication
# (obrigatorio para evitar ImportError: QtWebEngineWidgets must be imported
# or Qt.AA_ShareOpenGLContexts must be set before QCoreApplication)
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
except ImportError:
    pass

# Adicionar source e source/src ao path
# source/ para imports como src.xxx e source/src/ para imports como database.xxx
source_path = str(Path(__file__).parent.parent / "source")
src_path = str(Path(__file__).parent.parent / "source" / "src")
if source_path not in sys.path:
    sys.path.insert(0, source_path)
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Inicializar sistema de idiomas para testes
from src.language import init_language
init_language("en-US")


# ==================== ISOLAMENTO DO WORKSPACE PARA TESTES ====================


@pytest.fixture(scope="session", autouse=True)
def isolate_workspace_for_tests(tmp_path_factory):
    """
    Isola o workspace para testes - todos os testes usam um diretorio temporario
    ao inves do workspace real do usuario (~/.datapyn)
    
    Isso evita que testes criem sessoes/abas no workspace real.
    """
    # Criar diretorio temporario para testes
    test_workspace = tmp_path_factory.mktemp("datapyn_test_workspace")
    
    # Patch o modulo workspace_service ANTES de qualquer uso
    from src.core import workspace_service
    
    # Salvar valores originais
    original_default_path = workspace_service.DEFAULT_WORKSPACE_PATH
    original_instance = workspace_service._workspace_service_instance
    
    # Configurar para testes
    workspace_service.DEFAULT_WORKSPACE_PATH = test_workspace
    workspace_service._workspace_service_instance = None  # Reset singleton
    
    # Tambem limpar QSettings do Workspaces para testes
    from PyQt6.QtCore import QSettings
    test_settings = QSettings("DataPyn", "Workspaces")
    original_current = test_settings.value("current_workspace", "")
    original_list = test_settings.value("workspace_list", [])
    
    # Limpar para testes
    test_settings.remove("current_workspace")
    test_settings.remove("workspace_list")
    
    yield test_workspace
    
    # Restaurar valores originais apos todos os testes
    workspace_service.DEFAULT_WORKSPACE_PATH = original_default_path
    workspace_service._workspace_service_instance = None  # Reset para proximo uso
    
    # Restaurar QSettings
    if original_current:
        test_settings.setValue("current_workspace", original_current)
    if original_list:
        test_settings.setValue("workspace_list", original_list)


# ==================== CONFIGURAÇÃO MATPLOTLIB PARA TESTES ====================


@pytest.fixture(scope="session", autouse=True)
def configure_matplotlib():
    """
    Configura matplotlib para testes headless evitando problemas com threads de fontes
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.ioff()

    # Previne matplotlib de carregar fontes em threads paralelas
    import matplotlib.font_manager

    matplotlib.font_manager._load_fontmanager = lambda try_read_cache=True: matplotlib.font_manager.FontManager()

    yield

    plt.close("all")


# ==================== AUTO-CLOSE DE DIÁLOGOS PARA CI ====================


@pytest.fixture(autouse=True)
def auto_close_dialogs(qtbot, monkeypatch):
    """
    Auto-fecha TODOS os dialogos (QDialog, QMessageBox, QFileDialog, QInputDialog)
    para evitar travamento no CI
    """
    from PyQt6.QtWidgets import QDialog, QMessageBox, QFileDialog, QInputDialog
    from PyQt6.QtCore import QTimer

    # === PATCH QDIALOG.EXEC() ===
    original_exec = QDialog.exec

    def non_blocking_exec(self):
        """exec() nao-bloqueante - fecha automaticamente"""
        QTimer.singleShot(50, lambda: self.accept() if not self.isHidden() else None)
        qtbot.wait(100)
        return 1  # QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", non_blocking_exec)

    # === PATCH QFILEDIALOG ESTATICOS ===
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("", ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: ("", ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **kw: "")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **kw: ([], ""))

    # === PATCH QINPUTDIALOG ESTATICOS ===
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("", False))
    monkeypatch.setattr(QInputDialog, "getInt", lambda *a, **kw: (0, False))

    # === PATCH QMESSAGEBOX ESTATICOS ===
    original_warning = QMessageBox.warning
    original_information = QMessageBox.information
    original_question = QMessageBox.question
    original_critical = QMessageBox.critical

    def mock_warning(*args, **kwargs):
        """Retorna Ok sem mostrar diálogo"""
        return QMessageBox.StandardButton.Ok

    def mock_information(*args, **kwargs):
        """Retorna Ok sem mostrar diálogo"""
        return QMessageBox.StandardButton.Ok

    def mock_question(*args, **kwargs):
        """Retorna Yes sem mostrar diálogo"""
        return QMessageBox.StandardButton.Yes

    def mock_critical(*args, **kwargs):
        """Retorna Ok sem mostrar diálogo"""
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)
    monkeypatch.setattr(QMessageBox, "information", mock_information)
    monkeypatch.setattr(QMessageBox, "question", mock_question)
    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    yield

    # monkeypatch restaura tudo automaticamente no teardown


# ==================== LIMPEZA DE QSETTINGS PARA TESTES ====================


@pytest.fixture(autouse=True)
def clear_layout_settings():
    """
    Limpa QSettings de layout antes de cada teste para evitar que dados
    salvos pela aplicacao real causem crash em restoreState durante testes.
    """
    from PyQt6.QtCore import QSettings

    for group in ("DataPyn/MainWindow", "DataPyn/DockingLayout"):
        org, app = group.split("/")
        s = QSettings(org, app)
        s.clear()
        s.sync()

    yield

    # Limpar novamente no teardown para nao poluir outros testes
    for group in ("DataPyn/MainWindow", "DataPyn/DockingLayout"):
        org, app = group.split("/")
        s = QSettings(org, app)
        s.clear()
        s.sync()


# ==================== TESTES COM QSCINTILLA ====================
# Removido sistema de parametrizacao - agora usa apenas QScintilla


# ==================== FIXTURES DE CONFIGURAÇÃO ====================


@pytest.fixture
def temp_dir():
    """Diretório temporário para testes"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_home_dir(temp_dir, monkeypatch):
    """Mock do diretório home para não poluir configs reais"""
    monkeypatch.setattr(Path, "home", lambda: temp_dir)
    return temp_dir


# ==================== FIXTURES DE MANAGERS ====================


@pytest.fixture
def shortcut_manager(temp_dir):
    """ShortcutManager com config em temp"""
    from core.shortcut_manager import ShortcutManager

    config_path = temp_dir / "shortcuts.json"
    return ShortcutManager(str(config_path))


@pytest.fixture
def workspace_manager(temp_dir):
    """WorkspaceManager com config em temp"""
    from core.workspace_manager import WorkspaceManager

    config_path = temp_dir / "workspace.json"
    return WorkspaceManager(str(config_path))


@pytest.fixture
def results_manager():
    """ResultsManager limpo"""
    from core.results_manager import ResultsManager

    return ResultsManager()


@pytest.fixture
def connection_manager(temp_dir):
    """ConnectionManager com config em temp"""
    from database.connection_manager import ConnectionManager

    config_path = temp_dir / "connections.json"
    manager = ConnectionManager(str(config_path))
    return manager


# ==================== FIXTURES DE DATABASE MOCK ====================


@pytest.fixture
def mock_db_connector():
    """Conector de banco de dados mockado"""
    connector = MagicMock()
    connector.is_connected.return_value = True
    connector.execute_query.return_value = MagicMock()
    return connector


@pytest.fixture
def sample_dataframe():
    """DataFrame de exemplo para testes"""
    import pandas as pd

    return pd.DataFrame({"id": [1, 2, 3], "nome": ["Alice", "Bob", "Carol"]})


# ==================== HELPER FUNCTIONS ====================


def create_connection_config(
    name="test_conn",
    db_type="mssql",
    host="localhost",
    port=3306,
    database="testdb",
    username="user",
    use_windows_auth=False,
):
    """Cria config de conexão para testes"""
    return {
        "name": name,
        "db_type": db_type,
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "use_windows_auth": use_windows_auth,
        "group": "default",
        "color": "#569cd6",
    }
