"""
Pynia Chat Panel - multi-provider AI chat for DataPyn.

Dockable chat UI for the Pynia agent. Connectors (OpenAI, Claude, Open Router,
GitHub Copilot) are selected per workspace; all MCP IDE tools run through Pynia.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLabel,
    QPushButton,
    QComboBox,
    QFrame,
    QSizePolicy,
    QApplication,
    QMenu,
    QWidgetAction,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QUrl, QTimer, QSettings, QByteArray, QObject, QRect, QSize, QThread, QEvent
from PyQt6.QtGui import QFont, QDesktopServices, QKeyEvent, QIcon, QPixmap, QPainter, QPen, QColor, QFontMetrics, QKeySequence, QShortcut, QImage
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6 import sip
import sys
from PyQt6.QtWebChannel import QWebChannel
from pathlib import Path
import json
import logging
import os
import re
from datetime import datetime

from src.language import S
from src.design_system.tokens import get_colors, RADIUS
from src.services.copilot.copilot_settings import get_copilot_settings
from src.services.copilot.copilot_chat_runtime import CopilotChatRuntime
from src.services.copilot.copilot_models import (
    REASONING_EFFORTS,
    fallback_models,
    find_model,
    model_supported_reasoning_efforts,
    model_supports_reasoning_effort,
    normalize_models,
    usage_snapshot_for_model,
)
from src.services.copilot.reference_resolver import ReferenceResolver

try:
    import qtawesome as qta

    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False

logger = logging.getLogger(__name__)


def _load_pynia_icon(color: str, size: int = 20) -> QIcon:
    """Load Pynia mark icon (SVG) with custom color."""
    try:
        # Get path relative to this file (ui/components -> ui -> src -> assets/icons)
        components_dir = os.path.dirname(os.path.abspath(__file__))
        ui_dir = os.path.dirname(components_dir)
        src_dir = os.path.dirname(ui_dir)
        svg_path = os.path.join(src_dir, "assets", "icons", "copilot_icon.svg")

        with open(svg_path, "r", encoding="utf-8") as f:
            svg_content = f.read()

        # Replace all fill colors
        svg_content = re.sub(r"fill\s*:\s*#[0-9a-fA-F]{3,6}", f"fill:{color}", svg_content)
        svg_content = re.sub(r'fill="[^"]*"', f'fill="{color}"', svg_content)

        svg_bytes = QByteArray(svg_content.encode("utf-8"))
        renderer = QSvgRenderer(svg_bytes)

        if not renderer.isValid():
            return None

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()

        return QIcon(pixmap)
    except Exception as e:
        logger.error(f"Failed to load Copilot icon: {e}")
        return None


class ModelItemDelegate(QStyledItemDelegate):
    """Custom delegate for model combobox with right-aligned multiplier."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors = get_colors()
    
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """Paint item with model name left-aligned and multiplier right-aligned."""
        painter.save()
        
        # Get colors
        colors = self._colors
        
        # Draw background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(colors.interactive_primary))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor(colors.bg_elevated))
        else:
            painter.fillRect(option.rect, QColor(colors.bg_tertiary))
        
        # Get data
        display_text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        multiplier = index.data(Qt.ItemDataRole.UserRole + 1)  # Store multiplier separately
        
        # Parse multiplier from display text if not stored separately
        if multiplier is None and "  (" in display_text:
            # Extract from "Model Name  (0.33x)" format
            parts = display_text.rsplit("  (", 1)
            if len(parts) == 2:
                display_text = parts[0]
                multiplier = parts[1].rstrip(")")
        
        # Text rect with padding
        rect = option.rect.adjusted(12, 0, -12, 0)
        
        # Draw model name (left aligned)
        painter.setPen(QColor(colors.text_primary))
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        
        fm = QFontMetrics(font)
        name_rect = QRect(rect.left(), rect.top(), rect.width() - 50, rect.height())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, display_text)
        
        # Draw multiplier (right aligned, smaller, dimmer)
        if multiplier:
            painter.setPen(QColor(colors.text_tertiary))
            mult_font = painter.font()
            mult_font.setPointSize(10)
            painter.setFont(mult_font)
            
            mult_rect = QRect(rect.right() - 45, rect.top(), 45, rect.height())
            painter.drawText(mult_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(multiplier))
        
        painter.restore()
    
    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        """Return size hint for item."""
        return QSize(200, 32)


class ChatBridge(QObject):
    """
    Bridge class for QWebChannel communication between Python and chat HTML.
    
    JavaScript calls Python slots via bridge.methodName()
    Python calls JavaScript via web_view.page().runJavaScript()
    """
    
    # Signals emitted when JS calls our slots
    web_view_ready = pyqtSignal()
    insert_code_requested = pyqtSignal(str)
    message_submitted = pyqtSignal(str)
    cancel_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    refresh_models_requested = pyqtSignal()
    auth_requested = pyqtSignal(str)
    new_chat_requested = pyqtSignal()
    restore_chat_requested = pyqtSignal(str)
    delete_chat_requested = pyqtSignal(str)
    model_selected = pyqtSignal(str)
    reasoning_effort_selected = pyqtSignal(str)
    references_requested = pyqtSignal(str)
    reference_open_requested = pyqtSignal(str)
    history_collapsed_changed = pyqtSignal(bool)
    clipboard_paste_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    @pyqtSlot()
    def onWebViewReady(self):
        """Called when the WebView chat is fully loaded."""
        self.web_view_ready.emit()

    @pyqtSlot(str)
    def insertCode(self, code: str):
        """Called from JS when user clicks Insert button on a code block."""
        self.insert_code_requested.emit(code)

    @pyqtSlot(str)
    def sendMessage(self, payload_json: str):
        self.message_submitted.emit(payload_json)

    @pyqtSlot(str)
    def cancelTurn(self, turn_id: str):
        self.cancel_requested.emit(turn_id)

    @pyqtSlot(str)
    def retryTurn(self, turn_id: str):
        self.retry_requested.emit(turn_id)

    @pyqtSlot(str)
    def refreshModels(self, _payload_json: str = ""):
        self.refresh_models_requested.emit()

    @pyqtSlot(str)
    def authAction(self, payload_json: str = ""):
        self.auth_requested.emit(payload_json or "{}")

    @pyqtSlot(str)
    def createNewChat(self, _payload_json: str = ""):
        self.new_chat_requested.emit()

    @pyqtSlot(str)
    def restoreChat(self, session_id: str):
        self.restore_chat_requested.emit(session_id)

    @pyqtSlot(str)
    def deleteChat(self, session_id: str):
        self.delete_chat_requested.emit(session_id)

    @pyqtSlot(str)
    def selectModel(self, model_id: str):
        self.model_selected.emit(model_id)

    @pyqtSlot(str)
    def selectReasoningEffort(self, effort: str):
        self.reasoning_effort_selected.emit(effort)

    @pyqtSlot(str)
    def listReferences(self, query: str):
        self.references_requested.emit(query)

    @pyqtSlot(str)
    def openReference(self, reference: str):
        self.reference_open_requested.emit(reference)

    @pyqtSlot(str)
    def setHistoryCollapsed(self, payload_json: str):
        try:
            payload = json.loads(payload_json) if payload_json else {}
            collapsed = bool(payload.get("collapsed", False))
        except Exception:
            collapsed = str(payload_json).lower() in ("1", "true", "yes")
        self.history_collapsed_changed.emit(collapsed)

    @pyqtSlot(str)
    def requestClipboardPaste(self, _payload_json: str = ""):
        """Legacy paste hook — prefer readClipboardImageJson from JS."""
        self.clipboard_paste_requested.emit()

    @pyqtSlot(result=str)
    def readClipboardImageJson(self) -> str:
        """Return a clipboard image payload for the WebView composer."""
        panel = self.parent()
        if panel is None or not hasattr(panel, "_build_clipboard_image_payload"):
            return ""
        payload = panel._build_clipboard_image_payload()
        return json.dumps(payload) if payload else ""

    @pyqtSlot(result=str)
    def readClipboardText(self) -> str:
        """Return plain text from the OS clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return ""
        return clipboard.text() or ""

    @pyqtSlot(str)
    def requestComposerRepaint(self, _payload_json: str = ""):
        """Lightweight WebView refresh after composer DOM updates."""
        panel = self.parent()
        webview = getattr(panel, "_chat_webview", None) if panel is not None else None
        if webview is None or sip.isdeleted(webview):
            return
        webview.update()

    @pyqtSlot(str)
    def refreshUsagePanel(self, payload_json: str = ""):
        panel = self.parent()
        if panel is None or not hasattr(panel, "_refresh_usage_panel"):
            return
        check_latest = True
        try:
            payload = json.loads(payload_json) if payload_json else {}
            check_latest = bool(payload.get("check_latest", True))
        except Exception:
            pass
        panel._refresh_usage_panel(check_latest=check_latest)

    @pyqtSlot(str)
    def updateCopilotCli(self, _payload_json: str = ""):
        panel = self.parent()
        if panel is not None and hasattr(panel, "_begin_runtime_update_flow"):
            panel._begin_runtime_update_flow()

    @pyqtSlot(str)
    def openCopilotSubscription(self, _payload_json: str = ""):
        QDesktopServices.openUrl(QUrl("https://github.com/settings/copilot"))

    @pyqtSlot(str)
    def openExternalUrl(self, url: str = ""):
        if url:
            QDesktopServices.openUrl(QUrl(url))

    @pyqtSlot(str)
    def switchAccount(self, _payload_json: str = ""):
        panel = self.parent()
        if panel is not None and hasattr(panel, "_open_account_picker"):
            panel._open_account_picker()

    @pyqtSlot(str)
    def selectAccount(self, payload_json: str = ""):
        panel = self.parent()
        if panel is None or not hasattr(panel, "_activate_copilot_account"):
            return
        username = ""
        try:
            payload = json.loads(payload_json) if payload_json else {}
            username = str(payload.get("username") or "").strip()
        except Exception:
            pass
        if username:
            panel._activate_copilot_account(username)

    @pyqtSlot(str)
    def addAccount(self, _payload_json: str = ""):
        panel = self.parent()
        if panel is not None and hasattr(panel, "_add_copilot_account"):
            panel._add_copilot_account()

    @pyqtSlot(result=str)
    def listAccountsJson(self) -> str:
        from src.services.copilot import get_copilot_auth_service

        payload = get_copilot_auth_service().build_account_picker_payload()
        return json.dumps(payload, default=str)


class _StateItem:
    def __init__(self):
        self._enabled = True

    def setEnabled(self, enabled: bool):
        self._enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self._enabled


class _StateItemModel:
    def __init__(self, items):
        self._items = items

    def item(self, index: int):
        return self._items[index]


class _WebComboState:
    """Tiny non-visual combo model used by the WebView chat host."""

    def __init__(self):
        self._items = []
        self._current_index = -1
        self._enabled = True
        self._blocked = False
        self._on_changed = None

    def set_on_change(self, callback):
        self._on_changed = callback

    def blockSignals(self, blocked: bool):
        self._blocked = bool(blocked)

    def clear(self):
        self._items.clear()
        self._current_index = -1

    def count(self) -> int:
        return len(self._items)

    def addItem(self, text: str, data=None):
        self._items.append({"text": text, "data": data, "roles": {}, "item": _StateItem()})
        if self._current_index < 0:
            self._current_index = 0

    def setItemData(self, index: int, value, role=None):
        self._items[index]["roles"][role] = value

    def itemData(self, index: int, role=None):
        if role is None:
            return self._items[index]["data"]
        return self._items[index]["roles"].get(role)

    def findData(self, value) -> int:
        for index, item in enumerate(self._items):
            if item["data"] == value:
                return index
        return -1

    def setCurrentIndex(self, index: int):
        if 0 <= index < len(self._items):
            changed = self._current_index != index
            self._current_index = index
            if changed and not self._blocked and self._on_changed:
                self._on_changed(index)

    def currentIndex(self) -> int:
        return self._current_index

    def currentData(self):
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]["data"]
        return None

    def setEnabled(self, enabled: bool):
        self._enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self._enabled

    def model(self):
        return _StateItemModel([item["item"] for item in self._items])


class _WebLabelState:
    def __init__(self, text: str = ""):
        self._text = text
        self._tooltip = ""
        self._visible = False

    def setText(self, text: str):
        self._text = str(text or "")

    def text(self) -> str:
        return self._text

    def setToolTip(self, text: str):
        self._tooltip = str(text or "")

    def toolTip(self) -> str:
        return self._tooltip

    def setVisible(self, visible: bool):
        self._visible = bool(visible)

    def show(self):
        self.setVisible(True)

    def hide(self):
        self.setVisible(False)

    def isHidden(self) -> bool:
        return not self._visible

    def setStyleSheet(self, _style: str):
        return None


class _WebButtonState(_WebLabelState):
    def __init__(self, text: str = ""):
        super().__init__(text)
        self._enabled = True

    def setEnabled(self, enabled: bool):
        self._enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self._enabled


class _WebInputState:
    def __init__(self, focus_callback=None):
        self._text = ""
        self._focus_callback = focus_callback

    def clear(self):
        self._text = ""

    def setPlainText(self, text: str):
        self._text = str(text or "")

    def toPlainText(self) -> str:
        return self._text

    def setFocus(self):
        if self._focus_callback:
            self._focus_callback()



# Legacy widget classes removed (ChatMessageWidget, ThinkingIndicatorWidget,
# ThinkingContentWidget, ToolCallWidget). Chat rendering uses WebView now.

class ChatInputWidget(QTextEdit):
    """Custom text input that sends on Enter (Shift+Enter for newline)."""

    submit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(S.pynia.input_placeholder)
        self.setMaximumHeight(120)
        self.setMinimumHeight(36)
        self.setAcceptRichText(False)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.submit_requested.emit()
                return
        super().keyPressEvent(event)


class ExternalLinkPage(QWebEnginePage):
    """WebEnginePage that opens external links in the system browser."""

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:
        """Intercept navigation requests and open external URLs in system browser."""
        # Allow local file URLs (our template)
        if url.isLocalFile():
            return True

        # Allow qrc: URLs
        if url.scheme() == "qrc":
            return True

        # Allow about:blank and similar
        if url.scheme() in ("about", "data", "javascript"):
            return True

        # For http/https URLs, open in external browser
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
            return False  # Don't navigate in webview

        # Default: allow navigation
        return True


class GhCliInstallWorker(QObject):
    """Worker that installs GitHub CLI using QProcess (non-blocking)."""

    progress = pyqtSignal(str)  # Status message
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._arch = "amd64"

    def run(self):
        """Install GitHub CLI and Copilot extension."""
        import shutil
        import platform
        from src.services.copilot.copilot_process import run_hidden, configure_hidden_qprocess

        try:
            # Check if gh is already installed
            if shutil.which("gh"):
                # gh exists - check/install extension
                self.progress.emit("Checking Copilot extension...")
                self._install_copilot_extension()
                return

            system = platform.system()
            if system != "Linux":
                self.finished.emit(
                    False,
                    f"Automatic installation is only supported on Linux. "
                    f"Please install manually from https://cli.github.com/"
                )
                return

            # Use pkexec for graphical sudo prompt
            pkexec = shutil.which("pkexec")
            if not pkexec:
                self.finished.emit(
                    False,
                    "pkexec not found. Please install GitHub CLI manually:\n"
                    "https://cli.github.com/"
                )
                return

            self.progress.emit("Downloading GitHub CLI package...")

            # Pre-compute architecture
            try:
                arch_result = run_hidden(
                    ["dpkg", "--print-architecture"],
                    text=True,
                    timeout=10,
                )
                self._arch = arch_result.stdout.strip() or "amd64"
            except Exception:
                self._arch = "amd64"

            # Build install script
            setup_script = (
                "set -e && "
                "mkdir -p -m 755 /etc/apt/keyrings && "
                "wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg "
                "| tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null && "
                "chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg && "
                f"echo 'deb [arch={self._arch} "
                "signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] "
                "https://cli.github.com/packages stable main' "
                "| tee /etc/apt/sources.list.d/github-cli.list > /dev/null && "
                "apt-get update -qq && "
                "apt-get install -y gh"
            )

            # Use QProcess for non-blocking execution
            from PyQt6.QtCore import QProcess
            from src.services.copilot.copilot_process import configure_hidden_qprocess

            self._process = QProcess(self)
            configure_hidden_qprocess(self._process)
            self._process.finished.connect(self._on_process_finished)
            self._process.errorOccurred.connect(self._on_process_error)

            self._process.start(pkexec, ["bash", "-c", setup_script])

        except Exception as e:
            self.finished.emit(False, str(e))

    def _on_process_finished(self, exit_code, exit_status):
        """Handle QProcess completion for gh CLI install."""
        import shutil

        if exit_code == 0:
            # Verify gh installation
            if shutil.which("gh"):
                # gh installed - now install the Copilot extension
                self.progress.emit("Installing GitHub Copilot extension...")
                self._install_copilot_extension()
            else:
                self.finished.emit(
                    False,
                    "Installation completed but 'gh' command not found in PATH."
                )
        elif exit_code == 126:
            self.finished.emit(False, "Installation cancelled by user.")
        else:
            stderr = ""
            if self._process:
                stderr = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
            error_msg = stderr.strip() or f"Installation failed (exit code {exit_code})"
            self.finished.emit(False, error_msg[:200])

        self._process = None

    def _install_copilot_extension(self):
        """Install the gh-copilot extension (no sudo needed).
        
        Note: In gh CLI 2.87+, copilot is a built-in command and no extension is needed.
        """
        import shutil
        from src.services.copilot.copilot_process import run_hidden, configure_hidden_qprocess

        gh_path = shutil.which("gh")
        if not gh_path:
            self.finished.emit(False, "gh CLI not found")
            return

        # First check if gh copilot command works (built-in in gh 2.87+)
        try:
            result = run_hidden(
                [gh_path, "copilot", "--help"],
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Copilot command works (built-in or extension already installed)
                self.finished.emit(True, "")
                return
        except Exception:
            pass  # Continue with install attempt

        # Check if extension already installed (for older gh versions)
        try:
            result = run_hidden(
                [gh_path, "extension", "list"],
                text=True,
                timeout=10,
            )
            if "copilot" in result.stdout.lower():
                # Already installed
                self.finished.emit(True, "")
                return
        except Exception:
            pass  # Continue with install attempt

        # Install extension using QProcess (for older gh versions)
        from PyQt6.QtCore import QProcess
        self._ext_process = QProcess(self)
        configure_hidden_qprocess(self._ext_process)
        self._ext_process.finished.connect(self._on_extension_finished)
        self._ext_process.errorOccurred.connect(self._on_extension_error)

        self._ext_process.start(gh_path, ["extension", "install", "github/gh-copilot"])

    def _on_extension_finished(self, exit_code, exit_status):
        """Handle Copilot extension install completion."""
        if exit_code == 0:
            self.finished.emit(True, "")
        else:
            stderr = ""
            if self._ext_process:
                stderr = self._ext_process.readAllStandardError().data().decode("utf-8", errors="replace")
            
            # Check if error is because copilot is already a built-in command
            if "built-in" in stderr.lower() or "matches the name" in stderr.lower():
                # This means gh copilot is available as built-in, success!
                self.finished.emit(True, "")
            else:
                # Real extension install failure
                error_msg = stderr.strip() or f"Extension install failed (code {exit_code})"
                self.finished.emit(False, f"gh CLI installed but Copilot extension failed: {error_msg[:150]}")

        self._ext_process = None

    def _on_extension_error(self, error):
        """Handle QProcess error for extension install."""
        from PyQt6.QtCore import QProcess

        error_messages = {
            QProcess.ProcessError.FailedToStart: "Failed to start gh",
            QProcess.ProcessError.Crashed: "gh process crashed",
            QProcess.ProcessError.Timedout: "Extension install timed out",
            QProcess.ProcessError.WriteError: "Write error",
            QProcess.ProcessError.ReadError: "Read error",
            QProcess.ProcessError.UnknownError: "Unknown error",
        }
        msg = error_messages.get(error, "Unknown error")
        self.finished.emit(False, f"gh CLI installed but extension failed: {msg}")
        self._ext_process = None

    def _on_process_error(self, error):
        """Handle QProcess error."""
        from PyQt6.QtCore import QProcess

        error_messages = {
            QProcess.ProcessError.FailedToStart: "Failed to start pkexec",
            QProcess.ProcessError.Crashed: "Installation process crashed",
            QProcess.ProcessError.Timedout: "Installation timed out",
            QProcess.ProcessError.WriteError: "Write error",
            QProcess.ProcessError.ReadError: "Read error",
            QProcess.ProcessError.UnknownError: "Unknown error",
        }
        msg = error_messages.get(error, "Unknown error")
        self.finished.emit(False, msg)
        self._process = None


class CopilotCliCheckWorker(QObject):
    """Fetch Copilot CLI + SDK runtime status in a background thread."""

    finished = pyqtSignal(dict)

    def __init__(self, *, check_latest: bool = False, parent=None):
        super().__init__(parent)
        self._check_latest = check_latest

    @pyqtSlot()
    def run(self):
        from src.services.copilot.copilot_cli_manager import build_cli_status

        try:
            self.finished.emit(build_cli_status(check_latest=self._check_latest))
        except Exception as exc:
            logger.info("Copilot CLI status check failed: %s", exc)
            self.finished.emit({})


class CopilotAccountSwitchWorker(QObject):
    """Switch gh accounts without blocking the UI thread."""

    finished = pyqtSignal(bool, str, str)

    def __init__(self, username: str = "", parent=None):
        super().__init__(parent)
        self._username = username

    @pyqtSlot()
    def run(self):
        from src.services.copilot import get_copilot_auth_service

        auth = get_copilot_auth_service()
        ok, message, mode = auth.prepare_chat_account_switch(self._username)
        self.finished.emit(ok, message, mode)


class CopilotCliUpdateWorker(QObject):
    """Update Copilot CLI + SDK in a background thread."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, bool)

    @pyqtSlot()
    def run(self):
        from src.services.copilot.copilot_cli_manager import update_copilot_runtime

        try:
            success, message, requires_restart = update_copilot_runtime(progress=self.progress.emit)
            self.finished.emit(success, message, requires_restart)
        except Exception as exc:
            self.finished.emit(False, str(exc), False)


class PyniaChatPanel(QWidget):
    """
    Copilot Chat panel - integrates as a dockable panel in DataPyn.

    Provides chat interface with GitHub Copilot, model selection,
    mode selection, and authentication.

    Signals:
        message_sent(str): User sent a message.
        tool_call_requested(str, dict): Tool call requested by Copilot.
        thinking_started(): Copilot started processing.
    """

    message_sent = pyqtSignal(str)
    tool_call_requested = pyqtSignal(str, dict)
    thinking_started = pyqtSignal()
    insert_code_requested = pyqtSignal(str)

    def __init__(self, copilot_client=None, mcp_server=None, theme_manager=None, parent=None):
        super().__init__(parent)
        self._agent_client = copilot_client
        self._mcp_server = mcp_server
        self.theme_manager = theme_manager
        self._messages: list = []  # Chat history [{role, content}]
        self._current_stream_id = None  # Tracks current streaming message
        self._current_thinking_widget = None  # Legacy - not used with WebView
        self._current_actions_widget = None  # Legacy - not used with WebView
        self._active_tool_calls: dict = {}  # tool_name -> reference
        self._turn_tools_used = 0
        self._turn_had_notify_user = False
        self._auth_success_shown = False
        self._auth_signing_in = False
        self._auth_device_code = None
        self._auth_error_message = None
        self._auth_gh_required = False
        self._auth_installing_gh = False
        self._auth_gate_progress_message = None
        self._auth_post_install_message = None
        self._auth_runtime_update_action = False
        self._account_switch_thread = None
        self._account_switch_worker = None
        self._is_thinking = False  # Tracks collapsible thinking block state
        self._settings = QSettings("DataPyn", "PyniaChat")
        legacy = QSettings("DataPyn", "CopilotChat")
        if legacy.contains("last_session_id") and not self._settings.contains("last_session_id"):
            self._settings.setValue("last_session_id", legacy.value("last_session_id", ""))
        self._available_models = fallback_models()
        self._usage_snapshot = usage_snapshot_for_model(self._available_models, "gpt-4o")
        self._current_session_id = None
        self._current_tab_id = None
        self._current_tab_name = ""
        self._active_tool_target_id = None
        self._gh_install_worker = None
        self._cli_status = {}
        self._cli_check_worker = None
        self._cli_check_thread = None
        self._cli_update_worker = None
        self._cli_update_thread = None
        self._pending_runtime_update = False
        self._cleaned_up = False
        self._chat_runtime = CopilotChatRuntime(timeout_message=S.pynia.timeout_message, parent=self)
        self._chat_runtime.state_changed.connect(self._on_runtime_state_changed)
        self._chat_runtime.timeout.connect(self._on_runtime_timeout)
        self._setup_ui()
        self._connect_signals()
        # Restore last session on startup
        QTimer.singleShot(100, self._restore_last_session)

    def set_copilot_client(self, client):
        """Backward-compatible alias for set_agent_client."""
        self.set_agent_client(client)

    def set_agent_client(self, client):
        """Set or update the Pynia agent client."""
        if self._agent_client:
            try:
                self._agent_client.chat_response_chunk.disconnect(self._on_response_chunk)
                self._agent_client.chat_response_complete.disconnect(self._on_response_complete)
                self._agent_client.chat_error.disconnect(self._on_chat_error)
                # NOTE: auth_required handled by main_window to avoid duplication
                self._agent_client.authenticated.disconnect(self._on_authenticated)
                self._agent_client.auth_failed.disconnect(self._on_auth_failed)
                if hasattr(self._agent_client, 'tool_called'):
                    self._agent_client.tool_called.disconnect(self._on_tool_called)
                if hasattr(self._agent_client, 'tool_result'):
                    self._agent_client.tool_result.disconnect(self._on_tool_result)
                if hasattr(self._agent_client, 'thinking'):
                    self._agent_client.thinking.disconnect(self._on_thinking)
                if hasattr(self._agent_client, 'models_changed'):
                    self._agent_client.models_changed.disconnect(self._on_models_changed)
                if hasattr(self._agent_client, 'models_updated'):
                    self._agent_client.models_updated.disconnect(self._on_models_changed)
                if hasattr(self._agent_client, 'usage_changed'):
                    self._agent_client.usage_changed.disconnect(self._on_usage_changed)
                if hasattr(self._agent_client, 'auth_started'):
                    self._agent_client.auth_started.disconnect(self._on_auth_started)
                if hasattr(self._agent_client, 'gh_not_found'):
                    self._agent_client.gh_not_found.disconnect(self._on_gh_not_found)
            except (TypeError, RuntimeError):
                pass

        self._agent_client = client
        if client:
            client.chat_response_chunk.connect(self._on_response_chunk)
            client.chat_response_complete.connect(self._on_response_complete)
            client.chat_error.connect(self._on_chat_error)
            # NOTE: auth_required handled by main_window to avoid duplication
            client.authenticated.connect(self._on_authenticated)
            client.auth_failed.connect(self._on_auth_failed)
            if hasattr(client, 'tool_called'):
                client.tool_called.connect(self._on_tool_called)
            if hasattr(client, 'tool_result'):
                client.tool_result.connect(self._on_tool_result)
            if hasattr(client, 'thinking'):
                client.thinking.connect(self._on_thinking)
            if hasattr(client, 'models_changed'):
                client.models_changed.connect(self._on_models_changed)
            if hasattr(client, 'models_updated'):
                client.models_updated.connect(self._on_models_changed)
            if hasattr(client, 'usage_changed'):
                client.usage_changed.connect(self._on_usage_changed)
            if hasattr(client, 'auth_started'):
                client.auth_started.connect(self._on_auth_started)
            if hasattr(client, 'gh_not_found'):
                client.gh_not_found.connect(self._on_gh_not_found)
            if hasattr(client, 'license_warning'):
                client.license_warning.connect(self._on_license_warning)
            if hasattr(client, 'provider_changed'):
                client.provider_changed.connect(self._on_provider_changed)
            # Pass tool registry from MCP server to client
            if self._mcp_server and hasattr(client, 'set_tool_registry'):
                client.set_tool_registry(self._mcp_server.tool_registry, parent=self.window())
            self._update_auth_state()
            # Update model list from client if available
            self._update_models_from_client()
            if hasattr(client, 'usage_snapshot'):
                self._on_usage_changed(client.usage_snapshot())

    def set_mcp_server(self, server):
        """Set or update the MCP server reference."""
        self._mcp_server = server
        # Update tool registry in client if available
        if server and self._agent_client and hasattr(self._agent_client, 'set_tool_registry'):
            self._agent_client.set_tool_registry(server.tool_registry, parent=self.window())

    def _setup_ui(self):
        """Build the chat panel UI."""
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # === Header bar ===
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)

        # Pynia icon + title
        copilot_icon = _load_pynia_icon(colors.text_primary, size=20)
        if copilot_icon:
            icon_label = QLabel()
            icon_label.setPixmap(copilot_icon.pixmap(20, 20))
            header_layout.addWidget(icon_label)

        title_label = QLabel(S.pynia.title)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(10)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {colors.text_primary};")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # New chat button
        self._new_chat_btn = QPushButton()
        self._new_chat_btn.setFixedSize(28, 28)
        self._new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_chat_btn.setToolTip(S.pynia.new_chat)
        if HAS_QTAWESOME:
            self._new_chat_btn.setIcon(qta.icon("mdi.plus", color=colors.text_primary))
        else:
            self._new_chat_btn.setText("+")
        self._new_chat_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {colors.border_muted};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        header_layout.addWidget(self._new_chat_btn)

        # Sessions button (history)
        self._sessions_btn = QPushButton()
        self._sessions_btn.setFixedSize(28, 28)
        self._sessions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sessions_btn.setToolTip(S.pynia.chat_history)
        if HAS_QTAWESOME:
            self._sessions_btn.setIcon(qta.icon("mdi.history", color=colors.text_primary))
        else:
            self._sessions_btn.setText(S.pynia.chat_history_short)
        self._sessions_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {colors.border_muted};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        header_layout.addWidget(self._sessions_btn)

        # Auth button (no icon, just text showing username or sign-in)
        self._auth_btn = QPushButton(S.pynia.sign_in)
        self._auth_btn.setFixedWidth(90)
        self._auth_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout.addWidget(self._auth_btn)

        header.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-bottom: 1px solid {colors.border_default};
            }}
        """)
        layout.addWidget(header)

        # === Tab context badge (shows which tab the chat is scoped to) ===
        self._tab_badge = QLabel()
        self._tab_badge.setVisible(False)
        self._tab_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_secondary};
                font-size: 11px;
                padding: 3px 12px;
                border-bottom: 1px solid {colors.border_default};
            }}
        """)
        layout.addWidget(self._tab_badge)

        # === Messages area with persistent history sidebar ===
        self._chat_body = QWidget()
        chat_body_layout = QHBoxLayout(self._chat_body)
        chat_body_layout.setContentsMargins(0, 0, 0, 0)
        chat_body_layout.setSpacing(0)

        self._history_sidebar = self._create_history_sidebar()
        self._history_sidebar.setVisible(False)
        chat_body_layout.addWidget(self._history_sidebar)

        self._setup_chat_webview()
        chat_body_layout.addWidget(self._chat_webview, 1)
        layout.addWidget(self._chat_body, 1)

        # === GitHub CLI install bar (hidden by default) ===
        self._gh_install_widget = QWidget()
        gh_layout = QHBoxLayout(self._gh_install_widget)
        gh_layout.setContentsMargins(10, 8, 10, 8)
        gh_layout.setSpacing(8)

        gh_icon_label = QLabel()
        if HAS_QTAWESOME:
            gh_icon_label.setPixmap(
                qta.icon("mdi.alert-circle-outline", color="#e5c07b").pixmap(20, 20)
            )
        else:
            gh_icon_label.setText("!")
        gh_layout.addWidget(gh_icon_label)

        gh_text = QLabel(S.pynia.gh_cli_not_found.split("\n")[0])
        gh_text.setWordWrap(True)
        gh_text.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px;")
        gh_layout.addWidget(gh_text, 1)

        self._gh_install_btn = QPushButton(S.pynia.install_gh_cli)
        self._gh_install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gh_install_btn.setFixedHeight(30)
        self._gh_install_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 14px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
            QPushButton:disabled {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_tertiary};
            }}
        """)
        self._gh_install_btn.clicked.connect(self._install_gh_cli)
        gh_layout.addWidget(self._gh_install_btn)

        self._gh_install_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-top: 1px solid {colors.border_muted};
            }}
        """)
        self._gh_install_widget.setVisible(False)
        layout.addWidget(self._gh_install_widget)

        # === Config bar (Model selector only - always uses Agent mode) ===
        config_bar = QWidget()
        config_layout = QHBoxLayout(config_bar)
        config_layout.setContentsMargins(8, 4, 8, 4)
        config_layout.setSpacing(8)

        # Mode is always Agent (hidden) - tools only work in agent mode
        self._mode_combo = None  # Removed - always agent mode

        from src.services.pynia import PROVIDERS, get_pynia_settings

        self._provider_combo = QComboBox()
        self._provider_combo.setFixedWidth(168)
        self._provider_combo.setToolTip(
            getattr(S.pynia, "provider_tooltip", "AI connector for Pynia chat")
            if hasattr(S, "pynia")
            else "AI connector"
        )
        provider_labels = {
            "openai": getattr(S.pynia, "provider_openai", "OpenAI"),
            "openrouter": getattr(S.pynia, "provider_openrouter", "Open Router"),
            "anthropic": getattr(S.pynia, "provider_anthropic", "Claude"),
            "copilot": getattr(S.pynia, "provider_copilot", "GitHub Copilot"),
        }
        for pid in PROVIDERS:
            self._provider_combo.addItem(provider_labels.get(pid, pid), pid)
        active = get_pynia_settings().active_provider
        idx = self._provider_combo.findData(active)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_combo_changed)
        config_layout.addWidget(self._provider_combo)

        # Model selector with custom delegate
        self._model_combo = QComboBox()
        self._model_delegate = ModelItemDelegate(self._model_combo)
        self._model_combo.setItemDelegate(self._model_delegate)
        self._model_combo.setFixedWidth(220)  # Accommodate model names + multiplier
        self._model_combo.setToolTip(S.pynia.model_tooltip)
        config_layout.addWidget(self._model_combo)

        self._refresh_models_btn = QPushButton()
        self._refresh_models_btn.setFixedSize(26, 26)
        self._refresh_models_btn.setToolTip(S.pynia.refresh_models)
        self._refresh_models_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if HAS_QTAWESOME:
            self._refresh_models_btn.setIcon(qta.icon("mdi.refresh", color=colors.text_secondary))
        else:
            self._refresh_models_btn.setText(S.pynia.refresh_models_short)
        self._refresh_models_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_muted};
                border-radius: {RADIUS.radius_sm}px;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_secondary_hover};
                border-color: {colors.border_default};
            }}
        """)
        config_layout.addWidget(self._refresh_models_btn)

        self._effort_combo = QComboBox()
        self._effort_combo.setFixedWidth(118)
        self._effort_combo.setToolTip(S.pynia.reasoning_effort_tooltip)
        effort_labels = {
            "auto": S.pynia.effort_auto,
            "low": S.pynia.effort_low,
            "medium": S.pynia.effort_medium,
            "high": S.pynia.effort_high,
            "xhigh": S.pynia.effort_xhigh,
        }
        for effort in REASONING_EFFORTS:
            self._effort_combo.addItem(effort_labels.get(effort, effort), effort)
        config_layout.addWidget(self._effort_combo)

        # Usage label (shows premium requests percentage)
        # Hidden by default - shown when usage data becomes available
        self._usage_label = QLabel("")
        self._usage_label.setStyleSheet(f"""
            QLabel {{
                color: {colors.text_tertiary};
                font-size: 11px;
                padding: 0 8px;
            }}
        """)
        self._usage_label.setVisible(False)  # Hidden until we have data or model metadata
        config_layout.addWidget(self._usage_label)

        config_layout.addStretch()

        config_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-top: 1px solid {colors.border_muted};
            }}
        """)
        layout.addWidget(config_bar)

        # === Input area ===
        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(8, 6, 8, 8)
        input_layout.setSpacing(6)

        self._input = ChatInputWidget()
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_md}px;
                padding: 8px 12px;
                font-size: 13px;
            }}
            QTextEdit:focus {{
                border-color: {colors.interactive_primary};
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(128, 128, 128, 0.3);
                border-radius: 4px;
                min-height: 40px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(128, 128, 128, 0.5);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        input_layout.addWidget(self._input, 1)

        self._send_btn = QPushButton()
        self._send_btn.setFixedSize(36, 36)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setToolTip(S.pynia.send_tooltip)
        if HAS_QTAWESOME:
            self._send_btn.setIcon(qta.icon("mdi.send", color=colors.text_primary))
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.interactive_primary};
                border: none;
                border-radius: {RADIUS.radius_md}px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.interactive_primary_active};
            }}
        """)
        input_layout.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignBottom)

        # Stop button (hidden by default, shown when loading)
        self._stop_btn = QPushButton()
        self._stop_btn.setFixedSize(36, 36)
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setToolTip(S.pynia.stop_tooltip)
        if HAS_QTAWESOME:
            self._stop_btn.setIcon(qta.icon("mdi.stop", color=colors.text_primary))
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.danger};
                border: none;
                border-radius: {RADIUS.radius_md}px;
            }}
            QPushButton:hover {{
                background-color: {colors.danger_hover};
            }}
            QPushButton:pressed {{
                background-color: {colors.danger_active};
            }}
        """)
        self._stop_btn.hide()  # Hidden by default
        input_layout.addWidget(self._stop_btn, 0, Qt.AlignmentFlag.AlignBottom)

        input_container.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.bg_secondary};
                border-top: 1px solid {colors.border_default};
            }}
        """)
        layout.addWidget(input_container)

        # Style combo boxes
        combo_style = f"""
            QComboBox {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
                padding: 3px 8px;
                font-size: 12px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {colors.bg_elevated};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                selection-background-color: {colors.interactive_primary};
            }}
        """
        # Mode combo was removed - always agent mode
        self._model_combo.setStyleSheet(combo_style)
        self._effort_combo.setStyleSheet(combo_style)

        self._auth_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: {RADIUS.radius_sm}px;
                padding: 4px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {colors.interactive_secondary_hover};
            }}
        """)

        self._populate_model_combo(self._available_models)
        preferred_effort = get_copilot_settings().chat_reasoning_effort
        effort_index = self._effort_combo.findData(preferred_effort)
        if effort_index >= 0:
            self._effort_combo.setCurrentIndex(effort_index)
        self._update_reasoning_effort_state()
        self._set_usage_snapshot(self._usage_snapshot)
        self._refresh_history_sidebar()
        self._apply_theme()

    def _create_history_sidebar(self):
        """Create the persistent chat history sidebar."""
        colors = get_colors()
        sidebar = QFrame()
        sidebar.setObjectName("copilotHistorySidebar")
        sidebar.setMinimumWidth(190)
        sidebar.setMaximumWidth(260)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel(S.pynia.chat_history)
        title.setObjectName("copilotHistoryTitle")
        layout.addWidget(title)

        self._history_search = QLineEdit()
        self._history_search.setObjectName("copilotHistorySearch")
        self._history_search.setPlaceholderText(S.pynia.history_search_placeholder)
        layout.addWidget(self._history_search)

        self._history_list = QListWidget()
        self._history_list.setObjectName("copilotHistoryList")
        self._history_list.setFrameShape(QFrame.Shape.NoFrame)
        self._history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._history_list, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self._history_delete_btn = QPushButton(S.pynia.delete_chat)
        self._history_delete_btn.setEnabled(False)
        self._history_delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        actions.addWidget(self._history_delete_btn)
        self._history_clear_btn = QPushButton(S.pynia.clear_all)
        self._history_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        actions.addWidget(self._history_clear_btn)
        layout.addLayout(actions)

        self._history_search.textChanged.connect(self._refresh_history_sidebar)
        self._history_list.itemClicked.connect(self._restore_session_from_item)
        self._history_list.currentItemChanged.connect(
            lambda item, _prev: self._history_delete_btn.setEnabled(item is not None)
        )
        self._history_delete_btn.clicked.connect(self._delete_selected_history_session)
        self._history_clear_btn.clicked.connect(self._clear_all_sessions)

        sidebar.setStyleSheet(f"""
            QFrame#copilotHistorySidebar {{
                background-color: {colors.bg_secondary};
                border-right: 1px solid {colors.border_default};
            }}
            QLabel#copilotHistoryTitle {{
                color: {colors.text_primary};
                font-size: 12px;
                font-weight: 600;
            }}
            QLineEdit#copilotHistorySearch {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 5px;
                padding: 5px 8px;
                font-size: 12px;
            }}
            QListWidget#copilotHistoryList {{
                background-color: transparent;
                color: {colors.text_primary};
                outline: none;
            }}
            QListWidget#copilotHistoryList::item {{
                border-radius: 5px;
                padding: 7px 6px;
                margin: 1px 0;
            }}
            QListWidget#copilotHistoryList::item:selected {{
                background-color: {colors.bg_tertiary};
            }}
            QPushButton {{
                background-color: transparent;
                color: {colors.text_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 5px;
                padding: 5px 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
            }}
            QPushButton:disabled {{
                color: {colors.text_tertiary};
                border-color: {colors.border_muted};
            }}
        """)
        return sidebar

    def _get_template_path(self) -> Path:
        """Get path to chat template, handling PyInstaller bundle."""
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Running as PyInstaller bundle
            return Path(sys._MEIPASS) / 'src' / 'ui' / 'components' / 'chat_template.html'
        else:
            # Development mode
            return Path(__file__).parent / 'chat_template.html'

    def _setup_chat_webview(self):
        """Setup the WebView-based chat messages area."""
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        from PyQt6.QtGui import QColor
        colors = get_colors()
        
        # Create WebView with custom page for external links
        self._chat_webview = QWebEngineView()
        self._external_link_page = ExternalLinkPage(self._chat_webview)
        self._chat_webview.setPage(self._external_link_page)
        self._chat_webview.setMinimumSize(200, 100)
        self._chat_webview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Set dark background BEFORE loading to avoid white flash
        self._chat_webview.setStyleSheet(f"background-color: {colors.bg_primary};")
        self._chat_webview.page().setBackgroundColor(QColor(colors.bg_primary))
        
        # Enable JavaScript
        settings = self._chat_webview.page().settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        if hasattr(QWebEngineSettings.WebAttribute, "JavascriptCanAccessClipboard"):
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        if hasattr(QWebEngineSettings.WebAttribute, "JavascriptCanPaste"):
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)

        self._chat_webview.installEventFilter(self)

        self._paste_image_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        self._paste_image_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._paste_image_shortcut.activated.connect(self._on_clipboard_paste)
        self._chat_channel = QWebChannel(self._chat_webview.page())
        self._chat_bridge = ChatBridge(self)
        self._chat_channel.registerObject("bridge", self._chat_bridge)
        self._chat_webview.page().setWebChannel(self._chat_channel)
        
        # Connect bridge signals
        self._chat_bridge.web_view_ready.connect(self._on_webview_ready)
        self._chat_bridge.insert_code_requested.connect(self.insert_code_requested)
        
        # Track WebView ready state
        self._webview_ready = False
        self._pending_webview_ops = []
        
        # Load the HTML template
        template_path = self._get_template_path()
        if template_path.exists():
            self._chat_webview.setUrl(QUrl.fromLocalFile(str(template_path)))
        else:
            logger.error(f"Chat template not found: {template_path}")
            # Fallback minimal HTML
            fallback_text = S.pynia.template_not_found
            self._chat_webview.setHtml("""
                <!DOCTYPE html>
                <html>
                <body style="background:%s;color:%s;font-family:sans-serif;padding:20px;">
                    <p>%s</p>
                </body>
                </html>
            """ % (colors.bg_primary, colors.text_secondary, fallback_text))

    def _apply_theme(self):
        """Apply current design-system colors to the native shell and WebView."""
        colors = get_colors()
        if hasattr(self, '_chat_webview'):
            from PyQt6.QtGui import QColor
            self._chat_webview.setStyleSheet(f"background-color: {colors.bg_primary};")
            self._chat_webview.page().setBackgroundColor(QColor(colors.bg_primary))
        theme_payload = {
            "bg_primary": colors.bg_primary,
            "bg_secondary": colors.bg_secondary,
            "bg_tertiary": colors.bg_tertiary,
            "text_primary": colors.text_primary,
            "text_secondary": colors.text_secondary,
            "text_tertiary": colors.text_tertiary,
            "border_default": colors.border_default,
            "interactive_primary": colors.interactive_primary,
            "interactive_primary_hover": colors.interactive_primary_hover,
            "interactive_secondary": colors.interactive_secondary,
            "interactive_secondary_hover": colors.interactive_secondary_hover,
        }
        self._run_chat_js(f"setTheme({json.dumps(theme_payload)})")
    
    def _on_webview_ready(self):
        """Called when chat WebView is ready."""
        self._webview_ready = True
        
        # Set welcome text from translation
        welcome_title = getattr(S.pynia, "welcome_title", S.pynia.title)
        welcome_msg = S.pynia.welcome_message
        self._run_chat_js(f"setWelcomeText({json.dumps(welcome_title)}, {json.dumps(welcome_msg)})")
        
        # Send i18n labels to WebView
        chat_labels = {
            "thinking": S.pynia.thinking,
            "thinking_complete": S.pynia.thinking_complete,
            "tool_processing": S.pynia.tool_processing,
            "tool_using_one": S.pynia.tool_using_one,
            "tool_using_many": S.pynia.tool_using_many,
            "tool_used_one": S.pynia.tool_used_one,
            "tool_used_many": S.pynia.tool_used_many,
            "tool_running": S.pynia.tool_running,
            "tool_ok": S.pynia.tool_ok,
            "tool_error": S.pynia.tool_error,
            "copy": S.pynia.copy_code,
            "copied": S.pynia.copied_code,
            "insert": S.pynia.insert_code,
            "inserted": S.pynia.inserted_code,
            "waiting_response": S.pynia.waiting_response,
        }
        self._run_chat_js(f"setLabels({json.dumps(chat_labels)})")
        self._apply_theme()
        
        # Execute pending operations
        for op in self._pending_webview_ops:
            self._run_chat_js(op)
        self._pending_webview_ops.clear()
        
        logger.debug("Chat WebView ready")
    
    def _run_chat_js(self, code: str):
        """Run JavaScript in the chat WebView."""
        if self._webview_ready:
            self._chat_webview.page().runJavaScript(code)
        else:
            self._pending_webview_ops.append(code)

    def _connect_signals(self):
        """Connect internal signals."""
        self._send_btn.clicked.connect(self._on_send)
        self._stop_btn.clicked.connect(self._on_stop)
        self._input.submit_requested.connect(self._on_send)
        self._auth_btn.clicked.connect(self._on_auth_clicked)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._effort_combo.currentIndexChanged.connect(self._on_reasoning_effort_changed)
        self._refresh_models_btn.clicked.connect(self._on_refresh_models_clicked)
        self._new_chat_btn.clicked.connect(self._on_new_chat)
        self._sessions_btn.clicked.connect(self._on_sessions_clicked)
        
        # Connect to Pynia auth service for cross-component updates
        auth_service = self._get_chat_auth_service()
        auth_service.chat_authenticated.connect(self._on_auth_service_chat_updated)
        auth_service.chat_logged_out.connect(self._on_auth_service_chat_logged_out)
        if hasattr(auth_service, 'chat_gh_not_found'):
            auth_service.chat_gh_not_found.connect(self._on_gh_not_found)

    def _on_new_chat(self):
        """Start a new chat session."""
        self._save_current_session()
        self.clear_chat()
        self._current_session_id = None
        self._settings.setValue("last_session_id", "")
        self._turn_tools_used = 0
        self._turn_had_notify_user = False
        if self._agent_client and hasattr(self._agent_client, "reset_chat_session"):
            self._agent_client.reset_chat_session()

    def _on_sessions_clicked(self):
        """Toggle the persistent chat history sidebar."""
        self._refresh_history_sidebar()
        self._history_sidebar.setVisible(not self._history_sidebar.isVisible())

    def _session_display_name(self, session: dict) -> str:
        name = session.get("name") or session.get("title") or S.pynia.untitled_chat
        return str(name).strip() or S.pynia.untitled_chat

    def _refresh_history_sidebar(self):
        """Refresh the visible history list from persisted sessions."""
        if not hasattr(self, '_history_list'):
            return
        query = ""
        if hasattr(self, '_history_search'):
            query = self._history_search.text().strip().lower()

        self._history_list.clear()
        sessions = self._get_sessions_list()
        for session in sessions:
            name = self._session_display_name(session)
            if query and query not in name.lower():
                continue
            timestamp = str(session.get("timestamp", ""))[:16].replace("T", " ")
            model = session.get("model", "")
            label = name
            details = "  ".join(part for part in (timestamp, model) if part)
            if details:
                label = f"{name}\n{details}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, session.get("id", ""))
            if session.get("id") == self._current_session_id:
                item.setSelected(True)
            self._history_list.addItem(item)

        if self._history_list.count() == 0:
            item = QListWidgetItem(S.pynia.no_sessions)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._history_list.addItem(item)
        self._history_delete_btn.setEnabled(self._history_list.currentItem() is not None)

    def _restore_session_from_item(self, item: QListWidgetItem):
        session_id = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if session_id:
            self._restore_session(session_id)

    def _delete_selected_history_session(self):
        item = self._history_list.currentItem() if hasattr(self, '_history_list') else None
        session_id = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if session_id:
            self._delete_session(session_id)

    def _delete_session(self, session_id: str, menu: QMenu = None):
        """Delete a specific session."""
        from src.services.copilot.copilot_session_storage import delete_session_storage

        delete_session_storage(session_id)
        sessions = self._get_sessions_list()
        sessions = [s for s in sessions if s.get("id") != session_id]
        self._save_sessions_list(sessions)

        # If deleting current session, clear it
        if self._current_session_id == session_id:
            self._current_session_id = ""
            self._settings.setValue("last_session_id", "")

        if menu is not None:
            menu.close()
        self._refresh_history_sidebar()

    def _clear_all_sessions(self):
        """Clear all saved sessions."""
        from src.services.copilot.copilot_session_storage import delete_session_storage

        for session in self._get_sessions_list():
            delete_session_storage(session.get("id", ""))
        self._settings.setValue("sessions", "[]")
        self._settings.setValue("last_session_id", "")
        self._refresh_history_sidebar()

    def _set_loading(self, loading: bool):
        """Set loading state - disable input while waiting for response."""
        self._send_btn.setEnabled(not loading)
        self._input.setEnabled(not loading)
        if loading:
            self._send_btn.setToolTip(getattr(S.pynia, 'waiting_response', S.pynia.send_tooltip))
            self._send_btn.hide()
            self._stop_btn.show()
        else:
            self._send_btn.setToolTip(S.pynia.send_tooltip)
            self._stop_btn.hide()
            self._send_btn.show()

    def _on_stop(self):
        """Handle stop button - cancel current operation."""
        if self._agent_client and hasattr(self._agent_client, "cancel"):
            self._agent_client.cancel()
        self._cancel_active_tool_target()
        if self._mcp_server and hasattr(self._mcp_server, "tool_registry"):
            self._mcp_server.tool_registry.unpin_session()
        self._active_tool_target_id = None
        self._set_loading(False)
        self._hide_thinking_indicator()
        # Mark any widgets as complete
        if hasattr(self, '_current_thinking_widget') and self._current_thinking_widget:
            self._current_thinking_widget.set_complete()
            self._current_thinking_widget = None
        if hasattr(self, '_current_actions_widget') and self._current_actions_widget:
            self._current_actions_widget.set_complete()
            self._current_actions_widget = None

    def _on_send(self):
        """Handle send button or Enter key."""
        text = self._input.toPlainText().strip()
        if not text:
            return

        self._input.clear()

        # Hide welcome message (done automatically in _add_message via WebView)

        # Add user message
        self._add_message("user", text)

        # Show loading state
        self._set_loading(True)

        # Build static system prompt and lightweight per-turn context.
        system_prompt = self._build_system_prompt()
        context_section, start_here = self._build_request_context_section()

        from src.services.pynia.system_prompt import build_request_prompt
        request_prompt = build_request_prompt(text, context_section, start_here)

        # Prepare messages for API
        api_messages = [{"role": "system", "content": system_prompt}]
        for msg in self._messages[:-1]:
            api_messages.append({"role": msg["role"], "content": msg["content"]})
        api_messages.append({"role": "user", "content": request_prompt})

        # Send to Copilot
        if self._agent_client:
            if hasattr(self._agent_client, "system_message"):
                self._agent_client.system_message = system_prompt

            # Pin MCP tools to the current tab so tools target it even if user switches tabs
            if self._mcp_server and hasattr(self._mcp_server, "tool_registry"):
                tab_id = self._resolve_current_tab_id()
                if tab_id:
                    self._active_tool_target_id = tab_id
                    self._mcp_server.tool_registry.pin_session(tab_id)

            # Clear any previous assistant widget to ensure fresh response
            self._current_assistant_widget = None
            # Add animated thinking indicator
            self._show_thinking_indicator()
            self.thinking_started.emit()
            self._agent_client.send_chat(api_messages)
        else:
            self._set_loading(False)
            self._add_message("assistant", S.pynia.not_authenticated)

        self.message_sent.emit(text)

    def _build_system_prompt(self) -> str:
        """Build Pynia system prompt (tools via API — not duplicated in text)."""
        from src.services.pynia.system_prompt import build_system_prompt

        return build_system_prompt(include_tool_catalog=False)

    def _build_request_context_section(self) -> str:
        """Build a lightweight context snapshot for a single chat turn."""
        from src.services.pynia.system_prompt import build_context_section

        try:
            context_json = json.dumps(self._build_context_snapshot(), indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"Error building editor context snapshot: {e}")
            context_json = "{}"
        return build_context_section(context_json, "")

    def _build_context_snapshot(self) -> dict:
        """Return bounded editor state without triggering live database work."""
        context = {
            "chat_scope": "workspace_global",
            "target_session_id": self._resolve_current_tab_id() or "",
            "target_tab_name": self._current_tab_name or "",
            "visible_artifact_policy": (
                "Use silent tools for exploration. Edit existing blocks when possible. "
                "Create at most one final visible tab/block for a user-facing deliverable."
            ),
        }

        mw = self._get_registry_main_window()
        session_widget = self._get_context_session_widget(mw, context["target_session_id"])
        session = getattr(session_widget, "session", None) if session_widget else None
        if session:
            context["session"] = {
                "id": getattr(session, "session_id", ""),
                "title": getattr(session, "title", ""),
                "connection_name": getattr(session, "connection_name", "") or "",
                "is_connected": bool(getattr(session, "is_connected", False)),
            }

        block_editor = getattr(session_widget, "editor", None) if session_widget else None
        if block_editor:
            from src.services.pynia.focus_context import focused_block_payload

            focus_detail = focused_block_payload(block_editor)
            if focus_detail:
                context["focused_block_detail"] = focus_detail
                context["focused_block"] = focus_detail["name"]

            blocks = list(getattr(block_editor, "blocks", []) or [])
            last_focused = None
            if hasattr(block_editor, "get_last_focused_block"):
                last_focused = block_editor.get_last_focused_block()
            elif hasattr(block_editor, "focused_block"):
                last_focused = block_editor.focused_block
            block_infos = []
            for index, block in enumerate(blocks[:18]):
                try:
                    code = block.get_code() if hasattr(block, "get_code") else ""
                    name = block.get_block_name() if hasattr(block, "get_block_name") else f"block{index + 1}"
                    language = block.get_language() if hasattr(block, "get_language") else "unknown"
                    preview = code[:160] + "..." if len(code) > 160 else code
                    from src.services.copilot.mcp_tools import _infer_block_hints
                    hints = _infer_block_hints(code, language)
                    block_infos.append({
                        "index": index,
                        "name": name,
                        "language": language,
                        "focused": block is last_focused,
                        "lines": len(code.splitlines()) if code else 0,
                        "hints": hints,
                        "code_preview": preview,
                    })
                except Exception as e:
                    logger.debug(f"Error reading block context: {e}")
            context["blocks"] = block_infos
            context["total_blocks"] = len(blocks)
            if len(blocks) > len(block_infos):
                context["blocks_truncated"] = len(blocks) - len(block_infos)
            if block_infos:
                context["block_map"] = {b["name"]: b["index"] for b in block_infos}
                html_blocks = [b["name"] for b in block_infos if "generates_html" in b.get("hints", [])]
                if html_blocks:
                    context["html_blocks"] = html_blocks
                focused = next((b["name"] for b in block_infos if b.get("focused")), None)
                if focused:
                    context["focused_block"] = focused

        connection_name = context.get("session", {}).get("connection_name", "")
        schema_summary = self._build_cached_schema_summary(mw, connection_name, context["target_session_id"])
        if schema_summary:
            context["cached_schema"] = schema_summary

        variables = self._build_namespace_summary(session_widget, session)
        if variables:
            context["variables"] = variables

        return context

    def _get_registry_main_window(self):
        if not self._mcp_server or not hasattr(self._mcp_server, "tool_registry"):
            return None
        return getattr(self._mcp_server.tool_registry, "_main_window", None)

    def _resolve_current_tab_id(self):
        if self._current_tab_id:
            return self._current_tab_id
        mw = self._get_registry_main_window()
        widget = self._get_context_session_widget(mw, "")
        session = getattr(widget, "session", None) if widget else None
        return getattr(session, "session_id", None)

    def _get_context_session_widget(self, mw, session_id: str):
        if not mw:
            return None
        if session_id and hasattr(mw, "_session_widgets"):
            widget = mw._session_widgets.get(session_id)
            if widget:
                return widget
        if hasattr(mw, "session_tabs") and mw.session_tabs:
            idx = mw.session_tabs.currentIndex()
            return mw.session_tabs.widget(idx) if idx >= 0 else None
        return None

    def _build_cached_schema_summary(self, mw, connection_name: str, session_id: str) -> dict:
        if not mw or not connection_name:
            return {}
        schema_service = getattr(mw, "_schema_service", None)
        if not schema_service or not hasattr(schema_service, "get_cached_schema"):
            return {}
        try:
            cached = schema_service.get_cached_schema(connection_name, session_id=session_id or "")
        except TypeError:
            cached = schema_service.get_cached_schema(connection_name)
        except Exception as e:
            logger.debug(f"Error reading cached schema: {e}")
            return {}
        if not cached:
            return {}

        tables = cached.get("tables", []) or []
        columns = cached.get("columns", {}) or {}
        table_summaries = []
        for table in tables[:50]:
            table_name = table.get("name", "") if isinstance(table, dict) else str(table)
            table_columns = columns.get(table_name, []) if isinstance(columns, dict) else []
            column_names = []
            for column in table_columns[:20]:
                if isinstance(column, dict):
                    column_names.append(column.get("name", ""))
                else:
                    column_names.append(str(column))
            table_summaries.append({"name": table_name, "columns": column_names})

        return {
            "connection_name": connection_name,
            "database": cached.get("database", ""),
            "total_tables": len(tables),
            "tables": table_summaries,
            "tables_truncated": max(0, len(tables) - len(table_summaries)),
        }

    def _build_namespace_summary(self, session_widget, session) -> dict:
        namespace = getattr(session_widget, "namespace", None) if session_widget else None
        if namespace is None:
            namespace = getattr(session_widget, "_namespace", None) if session_widget else None
        if namespace is None:
            namespace = getattr(session, "namespace", None) if session else None
        if not namespace:
            return {}

        variables = {}
        for name, value in list(namespace.items())[:80]:
            if name.startswith("_") or name in ("pd", "np", "plt") or callable(value) or isinstance(value, type):
                continue
            try:
                type_name = type(value).__name__
                if hasattr(value, "shape"):
                    variables[name] = f"{type_name}{value.shape}"
                elif hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
                    variables[name] = f"{type_name}(len={len(value)})"
                else:
                    variables[name] = type_name
            except Exception:
                variables[name] = "unknown"
            if len(variables) >= 30:
                break
        return variables

    def _cancel_active_tool_target(self):
        """Cancel visible execution for the chat target if one is active."""
        if not self._mcp_server or not hasattr(self._mcp_server, "tool_registry"):
            return
        registry = self._mcp_server.tool_registry
        session_widget = registry._get_active_session_widget() if hasattr(registry, "_get_active_session_widget") else None
        editor = getattr(session_widget, "editor", None) if session_widget else None
        if editor and hasattr(editor, "cancel_all_executions"):
            try:
                editor.cancel_all_executions()
            except Exception as e:
                logger.debug(f"Error cancelling active Copilot execution: {e}")
        session = getattr(session_widget, "session", None) if session_widget else None
        connector = getattr(session, "connector", None) if session else None
        if connector and hasattr(connector, "cancel_query"):
            try:
                connector.cancel_query()
            except Exception as e:
                logger.debug(f"Error cancelling active Copilot query: {e}")

    def _add_message(
        self,
        role: str,
        content: str,
        references: list = None,
        attachments: list = None,
    ):
        """Add a message to the chat."""
        message = {"role": role, "content": content}
        if attachments:
            message["attachments"] = list(attachments)
        self._messages.append(message)

        msg_id = f"msg_{len(self._messages)}_{id(content) % 10000}"
        role_js = "error" if role == "assistant" and content.startswith("Error:") else role
        content_escaped = json.dumps(content)
        refs_payload = []
        for ref in references or []:
            if not isinstance(ref, dict):
                continue
            if ref.get("ok") is False:
                continue
            token = ref.get("reference") or ref.get("insert_text") or ""
            if not token and ref.get("type") == "block":
                name = ref.get("name") or ref.get("label") or ""
                if name:
                    token = f"#block:{name}"
            refs_payload.append({
                "reference": token,
                "type": ref.get("type", "block"),
                "label": ref.get("label") or ref.get("name", ""),
                "detail": ref.get("detail", ""),
            })
        attachments_payload = []
        for item in attachments or []:
            if not isinstance(item, dict):
                continue
            attachments_payload.append({
                "name": item.get("name", "image.png"),
                "mimeType": item.get("mimeType") or item.get("mime_type") or "image/png",
                "data": item.get("data", ""),
                "size": item.get("size", 0),
                "source": item.get("source", "user"),
            })
        self._run_chat_js(
            "addMessage("
            f"{json.dumps(role_js)}, {content_escaped}, {json.dumps(msg_id)}, "
            f"{json.dumps(refs_payload)}, {json.dumps(attachments_payload)})"
        )
        self._run_chat_js("hideWelcome()")

    def _scroll_to_bottom(self):
        """Scroll the messages area to the bottom via WebView."""
        self._run_chat_js("scrollToBottom()")

    def _on_response_chunk(self, chunk: str):
        """Handle streaming response chunk."""
        # Hide thinking indicator on first chunk
        self._hide_thinking_indicator()
        # End collapsible thinking block when response starts
        if self._is_thinking:
            self._is_thinking = False
            self._run_chat_js("endThinkingBlock()")
        
        if self._current_stream_id:
            # Stream to existing message
            chunk_escaped = json.dumps(chunk)
            self._run_chat_js(f"streamChunk({chunk_escaped})")
        else:
            # Start a new streaming message
            self._messages.append({"role": "assistant", "content": chunk})
            self._current_stream_id = f"stream_{len(self._messages)}"
            self._run_chat_js("startStreaming()")
            chunk_escaped = json.dumps(chunk)
            self._run_chat_js(f"streamChunk({chunk_escaped})")

    def _on_response_complete(self, full_text: str):
        """Handle complete response."""
        self._set_loading(False)
        self._hide_thinking_indicator()

        # Unpin MCP tools session (response is complete)
        if self._mcp_server and hasattr(self._mcp_server, "tool_registry"):
            self._mcp_server.tool_registry.unpin_session()
        self._active_tool_target_id = None
        
        # End collapsible thinking block
        if self._is_thinking:
            self._is_thinking = False
            self._run_chat_js("endThinkingBlock()")
        
        # End streaming in WebView
        self._run_chat_js("endStreaming()")
        
        # End tool group (mark as complete)
        self._run_chat_js("endToolGroup()")
        
        # Mark thinking widget as complete (legacy - not used with WebView)
        if self._current_thinking_widget:
            self._current_thinking_widget = None
        
        # Mark actions widget as complete (legacy - not used with WebView)
        if self._current_actions_widget:
            self._current_actions_widget = None
        
        # Clear active tool calls tracking
        self._active_tool_calls.clear()
        
        if not self._current_stream_id:
            self._add_message("assistant", full_text)
        else:
            # Update the last message content in history
            if self._messages and self._messages[-1]["role"] == "assistant":
                self._messages[-1]["content"] = full_text
        self._current_stream_id = None
        
        # Auto-save session after each exchange
        self._save_current_session()

    def _on_chat_error(self, error: str):
        """Handle chat error."""
        self._set_loading(False)
        self._hide_thinking_indicator()

        # Unpin MCP tools session (stream ended with error)
        if self._mcp_server and hasattr(self._mcp_server, "tool_registry"):
            self._mcp_server.tool_registry.unpin_session()
        self._active_tool_target_id = None
        
        # End collapsible thinking block
        if self._is_thinking:
            self._is_thinking = False
            self._run_chat_js("endThinkingBlock()")
        
        # End any streaming
        self._run_chat_js("endStreaming()")
        self._current_stream_id = None
        
        # End tool group (mark as complete)
        self._run_chat_js("endToolGroup()")
        
        # Mark widgets as complete (legacy)
        self._current_thinking_widget = None
        self._current_actions_widget = None
        
        # Clear active tool calls tracking
        self._active_tool_calls.clear()
        
        # Check if error is about missing Copilot extension
        if "Cannot find GitHub Copilot CLI" in error or "Copilot CLI" in error:
            self._on_gh_not_found()
            self._add_message(
                "assistant",
                "GitHub Copilot extension not found. Click the button above to install it."
            )
        else:
            self._add_message("assistant", f"Error: {error}")

    def _show_thinking_indicator(self):
        """Show the animated thinking indicator via WebView."""
        self._run_chat_js("showThinking()")

    def _hide_thinking_indicator(self):
        """Hide the thinking indicator via WebView."""
        self._run_chat_js("hideThinking()")

    def _on_tool_called(self, tool_name: str, arguments: dict, tool_call_id: str = ""):
        """Handle tool call from Copilot - show in WebView."""
        logger.info(f"Tool called: {tool_name}({arguments})")
        
        # Build a short summary of the arguments for display
        arg_summary = ""
        if arguments:
            parts = []
            for key, val in arguments.items():
                if key in ("thought",):
                    continue  # Skip verbose params
                val_str = str(val)
                if len(val_str) > 40:
                    val_str = val_str[:37] + "..."
                parts.append(f'{key}={val_str}')
            if parts:
                arg_summary = ", ".join(parts[:3])

        # Show tool use in WebView with argument summary
        tool_name_escaped = json.dumps(tool_name)
        arg_summary_escaped = json.dumps(arg_summary)
        self._run_chat_js(f"addToolUse({tool_name_escaped}, {arg_summary_escaped})")
        
        # Track by name for later result update
        self._active_tool_calls[tool_name] = True
        
        # Emit signal for external listeners (output panel)
        self.tool_call_requested.emit(tool_name, arguments)

    def _on_tool_result(self, tool_name: str, result: str):
        """Handle tool execution result."""
        logger.info(f"Tool result: {tool_name} -> {result[:100]}...")
        
        # Build short result preview (first meaningful line, max 80 chars)
        result_preview = ""
        is_error = "error" in result.lower()[:100]
        if result:
            # Get first non-empty, non-decoration line
            for line in result.split("\n"):
                line = line.strip()
                if line and not line.startswith("```") and not line.startswith("##"):
                    result_preview = line[:80]
                    if len(line) > 80:
                        result_preview += "..."
                    break

        # Update tool status in WebView
        tool_name_escaped = json.dumps(tool_name)
        result_preview_escaped = json.dumps(result_preview)
        self._run_chat_js(
            f"updateToolStatus({tool_name_escaped}, 'done', {str(is_error).lower()}, {result_preview_escaped})"
        )

    def _on_thinking(self, text: str):
        """Handle reasoning/thinking text from Copilot."""
        if not text.strip():
            return
        
        logger.debug(f"Thinking: {text[:50]}...")
        
        # Start a collapsible thinking block if not already open
        if not self._is_thinking:
            self._is_thinking = True
            self._run_chat_js("startThinkingBlock()")
        
        # Append thinking text to the block
        text_escaped = json.dumps(text)
        self._run_chat_js(f"appendThinking({text_escaped})")

    def _on_models_changed(self, models: list):
        """Handle dynamic model list update from SDK."""
        self._populate_model_combo(models)

    def _on_refresh_models_clicked(self):
        """Refresh model and usage metadata from the Copilot client."""
        self._usage_label.setText(S.pynia.usage_loading)
        self._usage_label.setVisible(True)
        if self._agent_client and hasattr(self._agent_client, 'refresh_metadata'):
            self._agent_client.refresh_metadata()
        elif self._agent_client and hasattr(self._agent_client, 'start_auth'):
            self._agent_client.start_auth()

    def _format_multiplier(self, multiplier) -> str:
        try:
            value = float(multiplier)
        except (TypeError, ValueError):
            value = 1.0
        if value == int(value):
            return f"{int(value)}x"
        return f"{value:.2g}x"

    def _populate_model_combo(self, models: list):
        """Populate the model combo with normalized model metadata."""
        normalized = normalize_models(models) or fallback_models()
        current_model = self._model_combo.currentData()
        if not current_model and self._agent_client and hasattr(self._agent_client, 'model'):
            current_model = self._agent_client.model
        self._available_models = normalized

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model in normalized:
            model_id = model.get("id", "")
            model_name = model.get("name", model_id)
            idx = self._model_combo.count()
            self._model_combo.addItem(model_name, model_id)
            self._model_combo.setItemData(idx, self._format_multiplier(model.get("multiplier", 1.0)), Qt.ItemDataRole.UserRole + 1)
            self._model_combo.setItemData(idx, dict(model), Qt.ItemDataRole.UserRole + 2)

        restore_idx = self._model_combo.findData(current_model) if current_model else -1
        if restore_idx < 0 and self._model_combo.count() > 0:
            restore_idx = 0
        if restore_idx >= 0:
            self._model_combo.setCurrentIndex(restore_idx)
        self._model_combo.blockSignals(False)

        selected_model = self._model_combo.currentData()
        if selected_model and self._agent_client and hasattr(self._agent_client, 'model'):
            self._agent_client.model = selected_model
        self._update_reasoning_effort_state()
        self._set_usage_snapshot(usage_snapshot_for_model(self._available_models, selected_model))

    def _on_usage_changed(self, snapshot: dict):
        """Update usage display from client/service metadata."""
        self._set_usage_snapshot(snapshot)

    def _set_usage_snapshot(self, snapshot: dict):
        """Render the compact usage pill. Never invent quota numbers."""
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        self._usage_snapshot = snapshot
        if snapshot.get("available"):
            used = snapshot.get("used")
            total = snapshot.get("total")
            remaining = snapshot.get("remaining_percentage")
            if used is not None and total is not None:
                text = S.pynia.usage_format.format(used=used, total=total)
            elif used is not None:
                text = S.pynia.usage_used_format.format(used=used)
            elif remaining is not None:
                text = S.pynia.usage_remaining_format.format(remaining=remaining)
            else:
                text = S.pynia.usage_unavailable
            reset_date = snapshot.get("reset_date")
            tooltip = S.pynia.usage_tooltip_with_reset.format(reset_date=reset_date) if reset_date else S.pynia.usage_tooltip
        else:
            multiplier = self._format_multiplier(snapshot.get("multiplier", 1.0))
            text = S.pynia.usage_unavailable
            tooltip = S.pynia.usage_unavailable_tooltip.format(multiplier=multiplier)
        self._usage_label.setText(text)
        self._usage_label.setToolTip(tooltip)
        self._usage_label.setVisible(True)

    def _update_reasoning_effort_state(self):
        """Enable reasoning effort choices only for supporting models."""
        model_id = self._model_combo.currentData() or ""
        supported = model_supports_reasoning_effort(self._available_models, model_id)
        supported_efforts = model_supported_reasoning_efforts(self._available_models, model_id)
        self._effort_combo.setEnabled(True)
        for index in range(self._effort_combo.count()):
            effort = self._effort_combo.itemData(index)
            enabled = effort == "auto" or effort in supported_efforts
            self._effort_combo.model().item(index).setEnabled(enabled)
        current_effort = self._effort_combo.currentData()
        if current_effort != "auto" and current_effort not in supported_efforts:
            model = find_model(self._available_models, model_id) or {}
            preferred_effort = model.get("default_reasoning_effort") if supported else "auto"
            if preferred_effort not in supported_efforts:
                preferred_effort = "auto"
            effort_idx = self._effort_combo.findData(preferred_effort)
            if effort_idx >= 0:
                self._effort_combo.setCurrentIndex(effort_idx)
        tooltip = S.pynia.reasoning_effort_tooltip
        if not supported:
            tooltip = S.pynia.reasoning_effort_unavailable
        self._effort_combo.setToolTip(tooltip)

    def _on_reasoning_effort_changed(self, index: int):
        """Persist and apply the selected reasoning effort."""
        effort = self._effort_combo.currentData() or "auto"
        model_id = self._model_combo.currentData() or ""
        supported_efforts = model_supported_reasoning_efforts(self._available_models, model_id)
        if effort != "auto" and effort not in supported_efforts:
            auto_idx = self._effort_combo.findData("auto")
            if auto_idx >= 0:
                self._effort_combo.setCurrentIndex(auto_idx)
            return
        get_copilot_settings().set_chat_reasoning_effort(effort)
        if self._agent_client and hasattr(self._agent_client, 'reasoning_effort'):
            self._agent_client.reasoning_effort = effort

    def _on_auth_clicked(self):
        """Handle auth button click."""
        # Use centralized auth service
        from src.services.copilot import get_copilot_auth_service
        auth_service = get_copilot_auth_service()
        
        if auth_service.is_chat_authenticated:
            # Show menu with options
            colors = get_colors()
            menu = QMenu(self)
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {colors.bg_secondary};
                    border: 1px solid {colors.border_default};
                    border-radius: 4px;
                    padding: 4px;
                }}
                QMenu::item {{
                    padding: 6px 12px;
                    color: {colors.text_primary};
                }}
                QMenu::item:selected {{
                    background-color: {colors.bg_tertiary};
                }}
            """)

            # Show subscription
            subscription_action = menu.addAction(S.pynia.show_subscription)
            subscription_action.triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl("https://github.com/settings/copilot"))
            )

            menu.addSeparator()

            # Logout
            logout_action = menu.addAction(S.pynia.logout)
            logout_action.triggered.connect(self._do_logout)

            menu.exec(self._auth_btn.mapToGlobal(self._auth_btn.rect().bottomLeft()))
            return

        # Start login via centralized auth service
        if auth_service.login_chat():
            self._auth_btn.setText(S.pynia.signing_in)
            self._auth_btn.setEnabled(False)
        else:
            logger.info("Chat login blocked - auth already in progress")

    def _do_logout(self):
        """Perform logout via centralized auth service."""
        from src.services.copilot import get_copilot_auth_service
        auth_service = get_copilot_auth_service()
        
        auth_service.logout_chat()
        self._update_auth_state()
        self._usage_label.setVisible(False)
        # Also update legacy setting
        self._settings.setValue("was_authenticated", "false")
        # Reset model combo to defaults
        self._populate_model_combo(fallback_models())

    def _on_auth_required(self, user_code: str, verification_uri: str):
        """Show device-code auth in the gate overlay (not in chat)."""
        self._auth_device_code = (user_code, verification_uri)
        self._auth_signing_in = False
        self._auth_error_message = None
        self._hide_account_switch_busy()
        QApplication.clipboard().setText(user_code)
        self._refresh_auth_gate()

    def _on_auth_started(self, message: str):
        """Authentication process started — update gate status."""
        _ = message
        self._auth_signing_in = True
        self._auth_error_message = None
        self._auth_btn.setText(S.pynia.signing_in)
        self._auth_btn.setEnabled(False)
        self._refresh_auth_gate()

    def _on_authenticated(self, info: str):
        """Authentication succeeded — unlock chat."""
        _ = info
        self._auth_signing_in = False
        self._auth_device_code = None
        self._auth_error_message = None
        self._auth_gh_required = False
        self._auth_installing_gh = False
        self._hide_account_switch_busy()
        self._update_auth_state()
        username = getattr(self._agent_client, "_username", "") if self._agent_client else ""
        get_copilot_settings().on_chat_authenticated(username)
        self._settings.setValue("was_authenticated", True)

    def _on_auth_failed(self, error: str):
        """Authentication failed — show status in gate."""
        from src.services.copilot.copilot_sdk_compat import is_runtime_update_error

        self._auth_signing_in = False
        self._auth_device_code = None
        self._auth_runtime_update_action = False
        self._auth_btn.setText(S.pynia.sign_in)
        self._auth_btn.setEnabled(True)

        if "Cannot find GitHub Copilot CLI" in error or "Copilot CLI" in error:
            self._hide_account_switch_busy()
            self._on_gh_not_found()
            return

        if is_runtime_update_error(error):
            self._auth_runtime_update_action = True
            self._auth_error_message = S.pynia.runtime_update_required.format(error=error)
            self._hide_account_switch_busy()
            self._refresh_auth_gate()
            return

        if "cancel" in str(error or "").lower():
            self._auth_error_message = S.pynia.auth_cancelled
        else:
            self._auth_error_message = S.pynia.auth_failed.format(error=error)
        self._hide_account_switch_busy()
        self._refresh_auth_gate()

    def _cancel_auth_flow(self):
        """Cancel an in-progress GitHub login and return to retryable gate state."""
        from src.services.copilot import get_copilot_auth_service

        self._auth_signing_in = False
        self._auth_device_code = None
        get_copilot_auth_service().cancel_chat_auth()
        self._auth_error_message = S.pynia.auth_cancelled
        self._hide_account_switch_busy()
        self._auth_btn.setText(S.pynia.sign_in)
        self._auth_btn.setEnabled(True)
        self._refresh_auth_gate()
        self._sync_app_state()

    def _on_gh_not_found(self):
        """GitHub CLI not found — prompt install via auth gate."""
        self._auth_gh_required = True
        self._auth_signing_in = False
        self._auth_device_code = None
        self._auth_error_message = None
        self._auth_btn.setText(S.pynia.sign_in)
        self._auth_btn.setEnabled(True)
        if hasattr(self, "_gh_install_widget"):
            self._gh_install_widget.setVisible(True)
        self._refresh_auth_gate()

    def _on_license_warning(self, message: str):
        """License may not support chat — surface in auth gate."""
        self._auth_error_message = (
            f"Warning: {message}\n\n"
            "Your organization's Copilot license may not include Chat API access. "
            "Please contact your IT admin to verify your Copilot subscription includes Chat features."
        )
        self._refresh_auth_gate()

    def _install_gh_cli(self):
        """Start GitHub CLI installation (non-blocking via QProcess)."""
        self._auth_installing_gh = True
        self._auth_gh_required = False
        if hasattr(self, "_gh_install_btn"):
            self._gh_install_btn.setEnabled(False)
            self._gh_install_btn.setText(S.pynia.installing_gh_cli)
        self._refresh_auth_gate()

        self._gh_install_worker = GhCliInstallWorker(self)
        self._gh_install_worker.progress.connect(self._on_gh_install_progress)
        self._gh_install_worker.finished.connect(self._on_gh_install_finished)
        self._gh_install_worker.run()

    def _on_gh_install_progress(self, message: str):
        self._auth_installing_gh = True
        self._auth_gate_progress_message = message
        self._refresh_auth_gate()

    def _on_gh_install_finished(self, success: bool, message: str):
        """Handle GitHub CLI installation result."""
        self._auth_installing_gh = False
        self._auth_gate_progress_message = None
        if success:
            self._auth_gh_required = False
            self._auth_post_install_message = S.pynia.gh_cli_installed
            if hasattr(self, "_gh_install_widget"):
                self._gh_install_widget.setVisible(False)
        else:
            self._auth_error_message = S.pynia.gh_cli_install_failed.format(error=message)
            if hasattr(self, "_gh_install_btn"):
                self._gh_install_btn.setEnabled(True)
                self._gh_install_btn.setText(S.pynia.install_gh_cli)

        self._gh_install_worker = None
        self._refresh_auth_gate()

    def _update_auth_state(self):
        """Update UI based on authentication state."""
        if self._agent_client and self._agent_client.is_authenticated:
            # Get username from client
            username = getattr(self._agent_client, "_username", None)
            if username:
                self._auth_btn.setText(f"@{username}")
                self._auth_btn.setToolTip(S.pynia.click_to_sign_out)
            else:
                self._auth_btn.setText(S.pynia.connected)
                self._auth_btn.setToolTip(S.pynia.click_to_sign_out)
            self._auth_btn.setEnabled(True)
        else:
            self._auth_btn.setText(S.pynia.sign_in)
            self._auth_btn.setToolTip(S.pynia.sign_in_tooltip)
            self._auth_btn.setEnabled(True)

    def _on_auth_service_chat_updated(self, username: str):
        """Handle chat auth state change from auth service (e.g., login via Settings)."""
        self._on_authenticated(username or "")
        self._update_models_from_client()

    def _on_clipboard_paste(self):
        """Route paste to the WebView composer (native OS clipboard access)."""
        if getattr(self, "_webview_ready", False):
            self._run_chat_js("handleHostClipboardPaste()");
            return
        self._on_composer_clipboard_paste(fallback_web_paste=True)

    def _on_composer_clipboard_paste(self, *, fallback_web_paste: bool = False):
        """Handle paste in the composer: image attachment first, then plain text."""
        if self._try_paste_image_from_clipboard():
            return
        if not fallback_web_paste:
            clipboard = QApplication.clipboard()
            text = clipboard.text() if clipboard is not None else ""
            if text:
                self._run_chat_js(f"insertComposerText({json.dumps(text)})")
                self._run_chat_js("focusComposer()")
            return
        webview = getattr(self, "_chat_webview", None)
        if webview is not None and not sip.isdeleted(webview):
            webview.page().triggerAction(QWebEnginePage.WebAction.Paste)

    def _build_clipboard_image_payload(self) -> dict | None:
        """Build an attachment payload from the OS clipboard, if present."""
        if not getattr(self, "_webview_ready", False):
            return None

        image = self._clipboard_image()
        if image is None:
            return None

        from PyQt6.QtCore import QBuffer, QIODevice
        import base64

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            return None

        raw = bytes(buffer.data())
        return {
            "name": "pasted.png",
            "mimeType": "image/png",
            "data": base64.b64encode(raw).decode("ascii"),
            "size": len(raw),
            "source": "clipboard",
        }

    def _try_paste_image_from_clipboard(self) -> bool:
        """Read a clipboard image and inject it into the WebView composer."""
        payload = self._build_clipboard_image_payload()
        if not payload:
            return False
        self._run_chat_js(f"addComposerAttachment({json.dumps(payload)})")
        self._run_chat_js("focusComposer()")
        return True

    def _clipboard_image(self):
        """Return a clipboard image when present (Windows screenshots, copy image, etc.)."""
        from PyQt6.QtGui import QImage, QPixmap

        clipboard = QApplication.clipboard()
        if clipboard is None:
            return None

        image = clipboard.image()
        if isinstance(image, QImage) and not image.isNull():
            return image

        mime = clipboard.mimeData()
        if mime is None:
            return None

        if mime.hasImage():
            image_data = mime.imageData()
            if isinstance(image_data, QPixmap):
                image_data = image_data.toImage()
            if isinstance(image_data, QImage) and not image_data.isNull():
                return image_data

        for fmt in ("image/png", "image/jpeg", "image/bmp", "image/webp", "image/gif"):
            if mime.hasFormat(fmt):
                image_data = QImage.fromData(bytes(mime.data(fmt)))
                if not image_data.isNull():
                    return image_data

        return None

    def eventFilter(self, watched, event):
        """Forward copy/cut/select-all to the chat WebView."""
        if watched is getattr(self, "_chat_webview", None) and event.type() == QEvent.Type.KeyPress:
            if event.matches(QKeySequence.StandardKey.Copy):
                self._chat_webview.page().triggerAction(QWebEnginePage.WebAction.Copy)
                return True
            if event.matches(QKeySequence.StandardKey.Cut):
                self._chat_webview.page().triggerAction(QWebEnginePage.WebAction.Cut)
                return True
            if event.matches(QKeySequence.StandardKey.SelectAll):
                self._chat_webview.page().triggerAction(QWebEnginePage.WebAction.SelectAll)
                return True
            if event.matches(QKeySequence.StandardKey.Paste):
                if getattr(self, "_webview_ready", False):
                    self._run_chat_js("handleHostClipboardPaste()");
                    return True
                if self._try_paste_image_from_clipboard():
                    return True
        return super().eventFilter(watched, event)

    def cleanup(self):
        """Release background work and WebEngine resources."""
        if self._cleaned_up:
            return

        self._cleaned_up = True

        try:
            self._on_stop()
        except RuntimeError:
            pass

        try:
            self.set_agent_client(None)
        except RuntimeError:
            pass

        webview = getattr(self, "_chat_webview", None)
        if webview is not None and not sip.isdeleted(webview):
            try:
                webview.stop()
                page = webview.page()
                if page is not None and not sip.isdeleted(page):
                    try:
                        page.setWebChannel(None)
                    except (RuntimeError, TypeError):
                        pass
                    replacement_page = QWebEnginePage(webview)
                    webview.setPage(replacement_page)
                    sip.delete(page)
                webview.close()
            except RuntimeError:
                pass
            try:
                sip.delete(webview)
            except RuntimeError:
                pass

        self._chat_webview = None
        self._external_link_page = None
        self._chat_channel = None
        self._chat_bridge = None

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def deleteLater(self):
        self.cleanup()
        super().deleteLater()

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self.cleanup()
        return super().event(event)

    def _on_auth_service_chat_logged_out(self):
        """Handle chat logout from auth service (e.g., logout via Settings)."""
        self._auth_success_shown = False
        self._update_auth_state()
        self._usage_label.setVisible(False)

    def _update_models_from_client(self):
        """Update model combo box from client's available models."""
        if not self._agent_client:
            return

        try:
            models = self._agent_client.available_models()
            if models and len(models) > 0:
                self._populate_model_combo(models)
        except Exception as e:
            logger.debug(f"Could not update models from client: {e}")

    def _on_model_changed(self, index: int):
        """Handle model selection change."""
        model_id = self._model_combo.currentData()
        if model_id and self._agent_client:
            self._agent_client.model = model_id
        self._update_reasoning_effort_state()
        self._set_usage_snapshot(usage_snapshot_for_model(self._available_models, model_id))

    def set_theme_manager(self, theme_manager):
        """Set theme manager for dynamic theming."""
        self.theme_manager = theme_manager
        self._apply_theme()

    # === Per-Tab Chat Context ===

    def switch_tab_context(self, tab_id: str, tab_name: str = ""):
        """Update the active DataPyn target while keeping chat history global."""
        self._current_tab_id = tab_id
        self._current_tab_name = tab_name or ""
        if tab_name:
            self._update_tab_badge(tab_name)
    
    def _update_tab_badge(self, tab_name: str):
        """Update the tab context badge in the chat header."""
        label_text = S.pynia.chat_context_tab.replace('{name}', tab_name)
        if hasattr(self, '_tab_badge'):
            self._tab_badge.setText(label_text)
            self._tab_badge.setVisible(True)
        # If no badge widget exists yet, we will create it in _setup_ui update

    def clear_chat(self):
        """Clear all messages."""
        self._messages.clear()
        # Clear messages in WebView
        self._run_chat_js("clearMessages()")
        self._current_stream_id = None
        self._current_session_id = None
        self._refresh_history_sidebar()

    # === Session Persistence ===

    def _get_sessions_list(self) -> list:
        """Get list of saved chat sessions."""
        sessions_json = self._settings.value("sessions", "[]")
        try:
            return json.loads(sessions_json)
        except Exception:
            return []

    def _save_sessions_list(self, sessions: list):
        """Save list of chat sessions."""
        self._settings.setValue("sessions", json.dumps(sessions))

    def _save_current_session(self):
        """Save the current chat session."""
        if not self._messages:
            return

        import uuid
        from datetime import datetime

        session_id = self._current_session_id or str(uuid.uuid4())[:8]
        self._current_session_id = session_id

        # Generate session name from first user message or timestamp
        session_name = datetime.now().strftime("%d/%m %H:%M")
        for msg in self._messages:
            if msg["role"] != "user":
                continue
            content = str(msg.get("content") or "").strip()
            if content:
                session_name = content[:40] + ("..." if len(content) > 40 else "")
                break
            attachments = msg.get("attachments") or []
            if attachments:
                session_name = str(attachments[0].get("name") or "Image")
                break

        sessions = self._get_sessions_list()

        # Update existing or add new
        existing_idx = None
        for i, s in enumerate(sessions):
            if s.get("id") == session_id:
                existing_idx = i
                break

        from src.services.copilot.copilot_session_storage import save_session_messages

        save_session_messages(session_id, self._messages.copy())

        session_data = {
            "id": session_id,
            "name": session_name,
            "timestamp": datetime.now().isoformat(),
            "model": self._model_combo.currentData() if hasattr(self, '_model_combo') else "",
            "reasoning_effort": self._effort_combo.currentData() if hasattr(self, '_effort_combo') else "auto",
            "target_tab_id": self._current_tab_id,
            "target_tab_name": self._current_tab_name,
            "preview": next((msg.get("content", "")[:120] for msg in self._messages if msg.get("role") == "assistant"), ""),
        }

        if existing_idx is not None:
            sessions[existing_idx] = session_data
        else:
            # Insert at beginning (most recent)
            sessions.insert(0, session_data)

        # Keep only last 20 sessions
        sessions = sessions[:20]
        self._save_sessions_list(sessions)
        self._refresh_history_sidebar()

        # Save as last session
        self._settings.setValue("last_session_id", session_id)

    def _restore_last_session(self):
        """Restore the last chat session on startup."""
        if self._cleaned_up:
            return

        last_id = self._settings.value("last_session_id", "")
        if last_id:
            self._restore_session(last_id)
        # Note: Auto-auth is now handled by CopilotAuthService.trigger_auto_auth()

    def _restore_session(self, session_id: str):
        """Restore a specific chat session."""
        sessions = self._get_sessions_list()
        for session in sessions:
            if session.get("id") == session_id:
                self.clear_chat()
                self._current_session_id = session_id
                model_id = session.get("model", "")
                if model_id:
                    index = self._model_combo.findData(model_id)
                    if index >= 0:
                        self._model_combo.setCurrentIndex(index)
                effort = session.get("reasoning_effort", "auto")
                effort_index = self._effort_combo.findData(effort)
                if effort_index >= 0:
                    self._effort_combo.setCurrentIndex(effort_index)
                from src.services.copilot.copilot_session_storage import resolve_session_messages

                messages = resolve_session_messages(session)
                for msg in messages:
                    self._add_message(
                        msg["role"],
                        msg["content"],
                        attachments=msg.get("attachments", []),
                    )
                if messages:
                    self._run_chat_js("hideWelcome()")
                self._refresh_history_sidebar()
                return True
        return False

    # Note: _try_auto_auth removed - CopilotAuthService handles auto-auth centrally

    def _on_authenticated_save(self):
        """Save authentication state when authenticated."""
        self._settings.setValue("was_authenticated", "true")

    def new_chat_session(self):
        """Start a new chat session."""
        # Save current session first
        self._save_current_session()
        self.clear_chat()
        self._current_session_id = None

    def get_saved_sessions(self) -> list:
        """Get list of saved sessions for UI display."""
        return self._get_sessions_list()

    # === New full-WebView chat surface ===

    def _setup_ui(self):
        """Build a minimal PyQt host; all visible chat UI lives in WebView."""
        self._model_combo = _WebComboState()
        self._effort_combo = _WebComboState()
        self._model_combo.set_on_change(self._on_model_changed)
        self._effort_combo.set_on_change(self._on_reasoning_effort_changed)
        self._usage_label = _WebLabelState()
        self._tab_badge = _WebLabelState()
        self._auth_btn = _WebButtonState(S.pynia.sign_in)
        self._send_btn = _WebButtonState(S.pynia.send_tooltip)
        self._stop_btn = _WebButtonState(S.pynia.stop_tooltip)
        self._input = _WebInputState(self.focus_input)
        self._mode_combo = None
        self._gh_install_widget = _WebLabelState()
        self._gh_install_btn = _WebButtonState(S.pynia.install_gh_cli)
        self._active_references = []

        for effort in REASONING_EFFORTS:
            self._effort_combo.addItem(effort, effort)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._setup_chat_webview()
        layout.addWidget(self._chat_webview, 1)

        self._populate_model_combo(self._available_models)
        preferred_effort = get_copilot_settings().chat_reasoning_effort
        effort_index = self._effort_combo.findData(preferred_effort)
        if effort_index >= 0:
            self._effort_combo.setCurrentIndex(effort_index)
        self._update_reasoning_effort_state()
        self._set_usage_snapshot(self._usage_snapshot)
        self._apply_theme()

    def _get_template_path(self) -> Path:
        """Get path to the new Copilot chat WebView app."""
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            return Path(sys._MEIPASS) / 'src' / 'ui' / 'components' / 'copilot_chat_app.html'
        return Path(__file__).parent / 'copilot_chat_app.html'

    def focus_input(self):
        """Focus the WebView composer when the Copilot dock is shown."""
        if hasattr(self, "_chat_webview") and self._chat_webview:
            self._chat_webview.setFocus()
        self._run_chat_js("focusComposer()")

    def _connect_signals(self):
        """Connect bridge and service signals for the full-WebView app."""
        bridge = getattr(self, '_chat_bridge', None)
        if bridge:
            bridge.message_submitted.connect(self._on_bridge_message_submitted)
            bridge.cancel_requested.connect(self._on_stop)
            bridge.retry_requested.connect(self._on_retry_turn)
            bridge.refresh_models_requested.connect(self._on_refresh_models_clicked)
            bridge.auth_requested.connect(self._on_auth_clicked)
            bridge.new_chat_requested.connect(self._on_new_chat)
            bridge.restore_chat_requested.connect(self._restore_session)
            bridge.delete_chat_requested.connect(self._delete_session)
            bridge.model_selected.connect(self._on_model_changed)
            bridge.reasoning_effort_selected.connect(self._on_reasoning_effort_changed)
            bridge.references_requested.connect(self._on_reference_suggestions_requested)
            bridge.reference_open_requested.connect(self._on_reference_open_requested)
            bridge.history_collapsed_changed.connect(self._on_history_collapsed_changed)
            bridge.clipboard_paste_requested.connect(
                lambda: self._on_composer_clipboard_paste(fallback_web_paste=False)
            )

        from src.services.copilot import get_copilot_auth_service
        auth_service = get_copilot_auth_service()
        auth_service.chat_authenticated.connect(self._on_auth_service_chat_updated)
        auth_service.chat_logged_out.connect(self._on_auth_service_chat_logged_out)
        auth_service.chat_auth_failed.connect(self._on_auth_failed)
        auth_service.chat_auth_required.connect(self._on_auth_required)
        auth_service.chat_auth_started.connect(self._on_auth_started)
        if hasattr(auth_service, 'chat_gh_not_found'):
            auth_service.chat_gh_not_found.connect(self._on_gh_not_found)

    def _labels_payload(self) -> dict:
        keys = [
            "title", "input_placeholder", "send_tooltip", "stop_tooltip", "sign_in",
            "signing_in", "model_tooltip", "reasoning_effort_tooltip", "refresh_models",
            "model_search_placeholder", "no_models_found",
            "new_chat", "chat_history", "history_search_placeholder", "delete_chat",
            "untitled_chat", "no_sessions", "usage_unavailable", "usage_format",
            "usage_used_format", "usage_remaining_format", "usage_panel_open",
            "usage_panel_close", "usage_panel_title", "usage_panel_title_user",
            "usage_panel_credits", "usage_panel_plan_included", "usage_panel_plan_unknown",
            "usage_panel_runtime", "usage_panel_cli", "usage_panel_sdk",
            "usage_panel_not_installed",             "usage_panel_reset", "usage_panel_update", "usage_panel_update_runtime",
            "usage_panel_updating", "usage_panel_update_available", "usage_panel_restart_required",
            "show_subscription", "runtime_update_required", "switch_account",
            "account_picker_title", "account_picker_close", "add_account",
            "account_current", "account_ready", "account_ready_short",
            "account_needs_login", "account_picker_empty",
            "account_switch_title", "account_switch_message",
            "account_switch_add_title", "account_switch_add_message",
            "runtime_update_checking", "runtime_update_downloading_cli", "runtime_update_installing_cli",
            "runtime_update_downloading_sdk", "runtime_update_installing_sdk", "runtime_update_complete",
            "waiting_response", "thinking",
            "thinking_complete", "tool_running", "tool_ok", "tool_error", "copy_code",
            "copied_code", "insert_code", "inserted_code", "effort_auto", "effort_low",
            "effort_medium", "effort_high", "effort_xhigh", "work_title",
            "work_running", "work_complete", "toggle_history", "logout",
            "retry_turn", "task_complete_title", "task_complete_default",
            "activity_sending", "activity_running_tool",
            "chat_locked_placeholder", "thinking_live",
            "attach_image_tooltip", "remove_attachment",
            "attachment_only_prompt", "attachment_limit_reached", "attachment_too_large",
            "attachment_invalid_type", "attachment_read_failed", "attachment_loading", "attachment_no_result",
            "view_attachment", "close_image_preview",
            "vision_not_supported",
            "usage_panel_title", "usage_panel_title_user", "usage_panel_limits_link",
            "usage_panel_credits", "usage_panel_plan_included", "usage_panel_plan_unknown",
            "connector_label", "title", "welcome_title",
        ]
        labels = {key: getattr(S.pynia, key, key) for key in keys}
        labels["copy"] = getattr(S.pynia, "copy_code", "Copy")
        labels["insert"] = getattr(S.pynia, "insert_code", "Insert")
        return labels

    def _on_webview_ready(self):
        """Called when the new chat WebView app is ready."""
        self._webview_ready = True
        self._run_chat_js(f"setLabels({json.dumps(self._labels_payload())})")
        welcome_title = getattr(S.pynia, "welcome_title", S.pynia.title)
        self._run_chat_js(
            f"setWelcomeText({json.dumps(welcome_title)}, {json.dumps(S.pynia.welcome_message)})"
        )
        self._apply_theme()
        self._sync_all_web_state()
        for op in self._pending_webview_ops:
            self._chat_webview.page().runJavaScript(op)
        self._pending_webview_ops.clear()

    def _usage_payload(self, *, updating: bool = False) -> dict:
        from src.services.pynia.usage import build_pynia_usage_payload

        provider_id = getattr(self._agent_client, "provider_id", "copilot") if self._agent_client else "copilot"
        username = ""
        if self._agent_client and getattr(self._agent_client, "is_authenticated", False):
            username = getattr(self._agent_client, "_username", "") or ""
        model = self._model_combo.currentData() if hasattr(self, "_model_combo") else ""
        return build_pynia_usage_payload(
            provider_id,
            model=model or "",
            usage_snapshot=self._usage_snapshot,
            models=self._available_models,
            username=username,
            cli_status=self._cli_status or None,
            updating=updating,
        )

    def _refresh_usage_panel(self, *, check_latest: bool = False):
        provider_id = getattr(self._agent_client, "provider_id", "copilot") if self._agent_client else "copilot"
        if provider_id != "copilot":
            self._sync_usage_to_webview()
            return

        if self._cli_check_thread and self._cli_check_thread.isRunning():
            return

        self._cli_check_worker = CopilotCliCheckWorker(check_latest=check_latest)
        self._cli_check_thread = QThread(self)
        self._cli_check_worker.moveToThread(self._cli_check_thread)
        self._cli_check_thread.started.connect(self._cli_check_worker.run)
        self._cli_check_worker.finished.connect(self._on_cli_status_ready)
        self._cli_check_worker.finished.connect(self._cli_check_thread.quit)
        self._cli_check_worker.finished.connect(self._cli_check_worker.deleteLater)
        self._cli_check_thread.finished.connect(self._cli_check_thread.deleteLater)
        self._cli_check_thread.start()

    def _on_cli_status_ready(self, status: dict):
        self._cli_status = status if isinstance(status, dict) else {}
        self._cli_check_thread = None
        self._cli_check_worker = None
        self._sync_usage_to_webview()
        if self._pending_runtime_update:
            self._pending_runtime_update = False
            if self._cli_status.get("update_available"):
                self._start_copilot_cli_update()

    def _begin_runtime_update_flow(self):
        if self._cli_update_thread and self._cli_update_thread.isRunning():
            return
        if (self._cli_status or {}).get("update_available"):
            self._start_copilot_cli_update()
            return
        self._pending_runtime_update = True
        self._refresh_usage_panel(check_latest=True)

    def _start_copilot_cli_update(self):
        if self._cli_update_thread and self._cli_update_thread.isRunning():
            return
        if not (self._cli_status or {}).get("update_available"):
            return
        cli = dict(self._cli_status or {})
        cli["update_phase"] = "checking"
        cli.pop("update_error", None)
        cli.pop("restart_required", None)
        self._cli_status = cli
        self._sync_usage_to_webview(updating=True)

        self._cli_update_worker = CopilotCliUpdateWorker()
        self._cli_update_thread = QThread(self)
        self._cli_update_worker.moveToThread(self._cli_update_thread)
        self._cli_update_thread.started.connect(self._cli_update_worker.run)
        self._cli_update_worker.progress.connect(self._on_cli_update_progress)
        self._cli_update_worker.finished.connect(self._on_cli_update_finished)
        self._cli_update_worker.finished.connect(self._cli_update_thread.quit)
        self._cli_update_worker.finished.connect(self._cli_update_worker.deleteLater)
        self._cli_update_thread.finished.connect(self._cli_update_thread.deleteLater)
        self._cli_update_thread.start()

    def _on_cli_update_progress(self, message: str):
        cli = dict(self._cli_status or {})
        cli["update_phase"] = message
        self._cli_status = cli
        self._sync_usage_to_webview(updating=True)

    def _open_account_picker(self):
        from src.services.copilot import get_copilot_auth_service

        payload = get_copilot_auth_service().build_account_picker_payload()
        self._run_chat_js(f"openAccountPicker({json.dumps(payload, default=str)})")

    def _activate_copilot_account(self, username: str):
        from src.services.copilot import get_copilot_auth_service

        login = str(username or "").strip()
        if not login:
            return

        auth = get_copilot_auth_service()
        current = ""
        if self._agent_client and getattr(self._agent_client, "is_authenticated", False):
            current = getattr(self._agent_client, "_username", "") or ""
        if login == current and auth.is_chat_authenticated:
            return

        if self._account_switch_thread and self._account_switch_thread.isRunning():
            return

        self._show_account_switch_busy(login, kind="switch")
        self._messages.clear()
        self._run_chat_js("clearMessages()")
        self._run_chat_js("showWelcome()")
        self._current_session_id = None
        self._settings.setValue("last_session_id", "")

        self._account_switch_worker = CopilotAccountSwitchWorker(login, self)
        self._account_switch_thread = QThread(self)
        self._account_switch_worker.moveToThread(self._account_switch_thread)
        self._account_switch_thread.started.connect(self._account_switch_worker.run)
        self._account_switch_worker.finished.connect(self._on_account_switch_prepared)
        self._account_switch_worker.finished.connect(self._account_switch_thread.quit)
        self._account_switch_worker.finished.connect(self._account_switch_worker.deleteLater)
        self._account_switch_thread.finished.connect(self._account_switch_thread.deleteLater)
        self._account_switch_thread.start()

    def _add_copilot_account(self):
        from src.services.copilot import get_copilot_auth_service

        if self._account_switch_thread and self._account_switch_thread.isRunning():
            return

        auth = get_copilot_auth_service()
        self._show_account_switch_busy("", kind="add")
        self._messages.clear()
        self._run_chat_js("clearMessages()")
        self._run_chat_js("showWelcome()")
        self._current_session_id = None
        self._settings.setValue("last_session_id", "")
        if auth.add_chat_account():
            self._auth_signing_in = True
            self._auth_error_message = None
            self._auth_runtime_update_action = False
            self._refresh_auth_gate()
            self._sync_app_state()
        else:
            self._hide_account_switch_busy()

    def _show_account_switch_busy(self, username: str = "", *, kind: str = "switch"):
        if kind == "add":
            title = S.pynia.account_switch_add_title
            message = S.pynia.account_switch_add_message
        else:
            title = S.pynia.account_switch_title
            message = S.pynia.account_switch_message.format(username=username or "")
        payload = {
            "visible": True,
            "username": username,
            "kind": kind,
            "title": title,
            "message": message,
        }
        self._run_chat_js(f"setAccountSwitchBusy({json.dumps(payload, ensure_ascii=False)})")

    def _hide_account_switch_busy(self):
        self._run_chat_js('setAccountSwitchBusy({"visible":false})')

    def _on_account_switch_prepared(self, ok: bool, message: str, mode: str):
        self._account_switch_thread = None
        self._account_switch_worker = None
        if not ok:
            self._hide_account_switch_busy()
            self._auth_error_message = message or S.pynia.auth_failed.format(error="")
            self._refresh_auth_gate()
            self._sync_app_state()
            return

        from src.services.copilot import get_copilot_auth_service

        auth = get_copilot_auth_service()
        if not auth.complete_chat_account_activation(mode):
            self._hide_account_switch_busy()
            return

        self._auth_signing_in = True
        self._auth_error_message = None
        self._auth_runtime_update_action = False
        self._refresh_auth_gate()
        self._sync_app_state()

    def _on_cli_update_finished(self, success: bool, message: str, requires_restart: bool = False):
        self._cli_update_thread = None
        self._cli_update_worker = None
        if success:
            cli = dict(self._cli_status or {})
            if requires_restart:
                cli["update_progress"] = message
                cli["restart_required"] = True
                self._cli_status = cli
                self._sync_usage_to_webview(updating=False)
            if self._agent_client and getattr(self._agent_client, "is_authenticated", False) and not requires_restart:
                self._agent_client.start_auth()
            elif self._auth_runtime_update_action and not requires_restart:
                from src.services.copilot import get_copilot_auth_service
                get_copilot_auth_service().login_chat()
            self._auth_runtime_update_action = False
            self._auth_error_message = None if not requires_restart else S.pynia.usage_panel_restart_required
            self._refresh_auth_gate()
            self._refresh_usage_panel(check_latest=True)
            return

        cli = dict(self._cli_status or {})
        cli["update_error"] = message
        self._cli_status = cli
        self._sync_usage_to_webview(updating=False)

    def _sync_all_web_state(self):
        self._sync_models_to_webview()
        self._sync_usage_to_webview()
        self._sync_attachment_limits_to_webview()
        self._refresh_history_sidebar()
        self._sync_app_state()

    def _sync_attachment_limits_to_webview(self):
        from src.services.copilot.copilot_attachments import attachment_limits_for_model

        model_id = self._model_combo.currentData() if hasattr(self, "_model_combo") else ""
        limits = attachment_limits_for_model(self._available_models, model_id or "")
        self._run_chat_js(f"setAttachmentLimits({json.dumps(limits)})")

    def _is_token_provider(self) -> bool:
        from src.services.pynia.types import PROVIDERS

        pid = getattr(self._agent_client, "provider_id", "copilot") if self._agent_client else "copilot"
        info = PROVIDERS.get(pid)
        return bool(info and info.auth_kind == "api_token")

    def _get_chat_auth_service(self):
        from src.services.pynia import get_pynia_auth_service

        return get_pynia_auth_service()

    def _on_provider_combo_changed(self, _index: int = 0) -> None:
        if not self._agent_client or not hasattr(self, "_provider_combo"):
            return
        provider_id = self._provider_combo.currentData()
        if provider_id and hasattr(self._agent_client, "set_provider"):
            self._agent_client.set_provider(provider_id)
        self._auth_error_message = None
        self._auth_gh_required = False
        if provider_id != "copilot" and hasattr(self, "_gh_install_widget"):
            self._gh_install_widget.setVisible(False)
        self._update_auth_state()
        if hasattr(self._agent_client, "available_models"):
            self._populate_model_combo(self._agent_client.available_models())
        self._refresh_usage_panel()
        self._sync_app_state()

    def _on_provider_changed(self, provider_id: str) -> None:
        if not hasattr(self, "_provider_combo"):
            return
        idx = self._provider_combo.findData(provider_id)
        if idx >= 0:
            self._provider_combo.blockSignals(True)
            self._provider_combo.setCurrentIndex(idx)
            self._provider_combo.blockSignals(False)

    def _open_pynia_settings(self) -> None:
        main = self.window()
        if main and hasattr(main, "show_settings_dialog"):
            main.show_settings_dialog(initial_tab="pynia")

    def _auth_gate_payload(self) -> dict:
        if self._is_token_provider():
            if self._agent_client and self._agent_client.is_authenticated:
                label = getattr(S.pynia, "connected", S.pynia.connected) if hasattr(S, "pynia") else S.pynia.connected
                return {"status": "ready", "pill_label": label}
            title = getattr(S.pynia, "token_required_title", S.pynia.chat_locked_title)
            message = getattr(S.pynia, "token_required_message", S.pynia.chat_locked_message)
            action = getattr(S.pynia, "open_settings", S.pynia.sign_in)
            return {
                "status": "locked",
                "pill_label": S.pynia.auth_status_locked,
                "title": title,
                "message": message,
                "action_label": action,
                "action": "open_pynia_settings",
            }

        if self._agent_client and self._agent_client.is_authenticated:
            username = getattr(self._agent_client, "_username", "") or ""
            return {
                "status": "ready",
                "pill_label": f"@{username}" if username else S.pynia.connected,
            }

        if self._auth_installing_gh:
            message = self._auth_gate_progress_message or S.pynia.installing_gh_cli
            return {
                "status": "signing_in",
                "pill_label": S.pynia.auth_status_signing_in,
                "title": S.pynia.install_gh_cli,
                "message": message,
            }

        if self._auth_error_message:
            payload = {
                "status": "error",
                "pill_label": S.pynia.auth_status_error,
                "title": S.pynia.chat_auth_error_title,
                "message": self._auth_error_message,
            }
            if self._auth_runtime_update_action:
                payload["action_label"] = S.pynia.usage_panel_update_runtime
                payload["action"] = "update_runtime"
            else:
                payload["action_label"] = S.pynia.auth_gate_retry_action
                payload["action"] = "sign_in"
            return payload

        if self._auth_gh_required:
            return {
                "status": "locked",
                "pill_label": S.pynia.auth_status_locked,
                "title": S.pynia.chat_locked_title,
                "message": S.pynia.gh_cli_not_found,
                "action_label": S.pynia.install_gh_cli,
                "action": "install_gh",
            }

        if self._auth_post_install_message:
            message = self._auth_post_install_message
            return {
                "status": "locked",
                "pill_label": S.pynia.auth_status_locked,
                "title": S.pynia.chat_locked_title,
                "message": message,
                "action_label": S.pynia.sign_in,
                "action": "sign_in",
            }

        if self._auth_device_code:
            user_code, verification_uri = self._auth_device_code
            return {
                "status": "device_code",
                "pill_label": S.pynia.auth_status_device_code,
                "title": S.pynia.chat_device_code_title,
                "message": S.pynia.chat_device_code_message.format(url=verification_uri),
                "code": user_code,
                "action_label": S.pynia.auth_gate_cancel_action,
                "action": "cancel_auth",
            }

        if self._auth_signing_in:
            return {
                "status": "signing_in",
                "pill_label": S.pynia.auth_status_signing_in,
                "title": S.pynia.chat_locked_title,
                "message": S.pynia.chat_signing_in_message,
                "action_label": S.pynia.auth_gate_cancel_action,
                "action": "cancel_auth",
            }

        return {
            "status": "locked",
            "pill_label": S.pynia.auth_status_locked,
            "title": S.pynia.chat_locked_title,
            "message": S.pynia.chat_locked_message,
            "action_label": S.pynia.sign_in,
            "action": "sign_in",
        }

    def _refresh_auth_gate(self):
        self._run_chat_js(f"setAuthGate({json.dumps(self._auth_gate_payload(), ensure_ascii=False)})")

    def _provider_display_name(self) -> str:
        if not self._agent_client:
            return getattr(S.pynia, "title", "Pynia")
        pid = getattr(self._agent_client, "provider_id", "copilot")
        key = {
            "openai": "provider_openai",
            "openrouter": "provider_openrouter",
            "anthropic": "provider_anthropic",
            "copilot": "provider_copilot",
        }.get(pid, "title")
        return getattr(S.pynia, key, pid)

    def _sync_app_state(self):
        provider_label = S.pynia.connector_label.format(provider=self._provider_display_name())
        payload = {
            "tab_name": S.pynia.chat_context_tab.replace('{name}', self._current_tab_name) if self._current_tab_name else "",
            "provider_label": provider_label,
            "auth_label": self._auth_btn.text(),
            "auth_ready": bool(self._agent_client and self._agent_client.is_authenticated),
            "selected_model": self._model_combo.currentData() or "",
            "selected_effort": self._effort_combo.currentData() or "auto",
            "supported_efforts": self._supported_efforts_for_current_model(),
            "loading": self._chat_runtime.is_active,
            "history_collapsed": get_copilot_settings().chat_history_collapsed,
        }
        self._run_chat_js(f"setAppState({json.dumps(payload, default=str)})")
        self._refresh_auth_gate()

    def _sync_models_to_webview(self):
        payload = {
            "models": self._available_models,
            "selected_model": self._model_combo.currentData() or "",
            "supported_efforts": self._supported_efforts_for_current_model(),
        }
        self._run_chat_js(f"setModels({json.dumps(payload, default=str)})")

    def _sync_usage_to_webview(self, *, updating: bool = False):
        self._run_chat_js(f"setUsage({json.dumps(self._usage_payload(updating=updating), default=str)})")

    def _supported_efforts_for_current_model(self) -> list:
        return model_supported_reasoning_efforts(self._available_models, self._model_combo.currentData() or "")

    def _on_bridge_message_submitted(self, payload_json: str):
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {"text": payload_json}
        self._on_send(
            str(payload.get("text", "")),
            payload.get("references", []),
            attachments=payload.get("attachments", []),
        )

    def _on_send(
        self,
        text: str = "",
        references: list = None,
        retry: bool = False,
        attachments: list = None,
    ):
        """Send a user prompt from the WebView composer."""
        if not text and hasattr(self, '_input') and self._input:
            text = self._input.toPlainText().strip()
            self._input.clear()
        text = (text or "").strip()
        attachments = list(attachments or [])
        if (not text and not attachments) or self._chat_runtime.is_active:
            return

        if not self._agent_client or not self._agent_client.is_authenticated:
            self._refresh_auth_gate()
            return

        from src.services.copilot.copilot_attachments import (
            AttachmentValidationError,
            attachments_for_message_storage,
            parse_attachments_payload,
            validate_attachments_for_model,
        )

        model_id = self._model_combo.currentData() if hasattr(self, "_model_combo") else ""
        normalized_attachments = []
        try:
            if attachments:
                normalized_attachments = parse_attachments_payload(attachments)
                validate_attachments_for_model(
                    normalized_attachments,
                    self._available_models,
                    model_id or getattr(self._agent_client, "_model", ""),
                )
        except AttachmentValidationError as exc:
            self._chat_runtime.fail(str(exc))
            self._set_loading(False)
            self._add_message("error", str(exc))
            return

        stored_attachments = attachments_for_message_storage(normalized_attachments)

        resolved_refs = self._resolve_prompt_references(text, references or [])
        self._active_references = resolved_refs
        self._turn_tools_used = 0
        self._turn_had_notify_user = False
        self._chat_runtime.start_turn(text, resolved_refs, stored_attachments)
        if not retry:
            self._add_message("user", text, references=resolved_refs, attachments=stored_attachments)
        self._set_loading(True)
        self._run_chat_js(f"setActivity({json.dumps({'phase': S.pynia.activity_sending})})")

        system_prompt = self._build_system_prompt()
        context_section, start_here = self._build_request_context_section()
        from src.services.pynia.system_prompt import build_request_prompt
        request_prompt = build_request_prompt(text, context_section, start_here)
        if stored_attachments and not text:
            request_prompt = build_request_prompt(
                S.pynia.attachment_only_prompt,
                context_section,
                start_here,
            )
        focus_name = ""
        if "`" in start_here:
            import re

            m = re.search(r"block `([^`]+)`", start_here)
            if m:
                focus_name = m.group(1)
        if focus_name:
            phase = S.pynia.activity_focused_block.format(block=focus_name) if hasattr(
                S.pynia, "activity_focused_block"
            ) else f"Focused block: {focus_name}"
            self._run_chat_js(f"setActivity({json.dumps({'phase': phase, 'detail': ''})})")

        # SDK session keeps conversation history; send only system rules + current turn.
        api_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request_prompt},
        ]

        if self._agent_client:
            if hasattr(self._agent_client, "system_message"):
                self._agent_client.system_message = system_prompt
            if self._mcp_server and hasattr(self._mcp_server, "tool_registry"):
                tab_id = self._resolve_current_tab_id()
                if tab_id:
                    self._active_tool_target_id = tab_id
                    self._mcp_server.tool_registry.pin_session(tab_id)
            self._current_assistant_widget = None
            self._show_thinking_indicator()
            self.thinking_started.emit()
            self._agent_client.send_chat(api_messages, attachments=stored_attachments)
        else:
            self._chat_runtime.fail(S.pynia.not_authenticated)
            self._set_loading(False)
            self._refresh_auth_gate()
        self.message_sent.emit(text)

    def _resolve_prompt_references(self, text: str, explicit_refs: list) -> list:
        resolver = ReferenceResolver(self._get_registry_main_window())
        refs = []
        seen = set()
        for item in explicit_refs or []:
            ref = item.get("reference") or item.get("insert_text") if isinstance(item, dict) else str(item)
            if ref and ref not in seen:
                refs.append(resolver.resolve(ref))
                seen.add(ref)
        for item in resolver.parse(text):
            ref = item.get("reference")
            if ref and ref not in seen:
                refs.append(resolver.resolve(ref))
                seen.add(ref)
        return refs

    def _build_request_context_section(self) -> tuple[str, str]:
        """Return (context_section, start_here_directive) for the user message."""
        from src.services.pynia.focus_context import start_here_directive
        from src.services.pynia.system_prompt import build_context_section

        try:
            snapshot = self._build_context_snapshot()
            if self._active_references:
                snapshot["active_references"] = self._active_references
            focus_detail = snapshot.get("focused_block_detail")
            start_here = start_here_directive(focus_detail)
            context_json = json.dumps(snapshot, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"Error building editor context snapshot: {e}")
            context_json = "{}"
            start_here = start_here_directive(None)
        return build_context_section(context_json, ""), start_here

    def _set_loading(self, loading: bool):
        self._run_chat_js(f"setAppState({json.dumps({'loading': bool(loading)})})")

    def _on_runtime_state_changed(self, state: dict):
        self._run_chat_js(f"setTurnState({json.dumps(state)})")

    def _on_runtime_timeout(self, _turn_id: str):
        if self._agent_client and hasattr(self._agent_client, "cancel"):
            self._agent_client.cancel()
        if self._mcp_server and hasattr(self._mcp_server, "tool_registry"):
            self._mcp_server.tool_registry.unpin_session()
        self._active_tool_target_id = None
        self._set_loading(False)
        self._hide_thinking_indicator()
        self._run_chat_js("endThinkingBlock(); endStreaming(); endToolGroup(); stopActivityTimer();")

    def _on_stop(self, *_args):
        if self._agent_client and hasattr(self._agent_client, "cancel"):
            self._agent_client.cancel()
        self._cancel_active_tool_target()
        if self._mcp_server and hasattr(self._mcp_server, "tool_registry"):
            self._mcp_server.tool_registry.unpin_session()
        self._active_tool_target_id = None
        self._chat_runtime.cancel()
        self._set_loading(False)
        self._hide_thinking_indicator()
        self._run_chat_js("endThinkingBlock(); endStreaming(); endToolGroup(); stopActivityTimer();")

    def _on_retry_turn(self, *_args):
        payload = self._chat_runtime.retry_payload()
        if payload.get("prompt") or payload.get("attachments"):
            self._run_chat_js(
                "document.querySelectorAll('.message-row.error').forEach(n => n.remove())"
            )
            self._on_send(
                payload.get("prompt", ""),
                payload.get("references", []),
                retry=True,
                attachments=payload.get("attachments", []),
            )

    def _on_response_chunk(self, chunk: str):
        self._chat_runtime.touch_activity()
        self._chat_runtime.mark_streaming()
        self._hide_thinking_indicator()
        if self._is_thinking:
            self._is_thinking = False
            self._run_chat_js("endThinkingBlock()")
        if self._current_stream_id:
            self._run_chat_js(f"streamChunk({json.dumps(chunk)})")
        else:
            self._messages.append({"role": "assistant", "content": chunk})
            self._current_stream_id = f"stream_{len(self._messages)}"
            self._run_chat_js("startStreaming()")
            self._run_chat_js(f"streamChunk({json.dumps(chunk)})")

    def _on_response_complete(self, full_text: str):
        if self._chat_runtime.last_turn.get("state") == "timed_out":
            logger.info("Ignoring response completion after turn timeout")
            return
        self._chat_runtime.complete(full_text)
        self._set_loading(False)
        self._hide_thinking_indicator()
        if self._mcp_server and hasattr(self._mcp_server, "tool_registry"):
            self._mcp_server.tool_registry.unpin_session()
        self._active_tool_target_id = None
        if self._is_thinking:
            self._is_thinking = False
            self._run_chat_js("endThinkingBlock()")
        self._run_chat_js("endStreaming(); endToolGroup(); stopActivityTimer();")
        self._active_tool_calls.clear()
        if not self._current_stream_id:
            self._add_message("assistant", full_text)
        elif self._messages and self._messages[-1]["role"] == "assistant":
            self._messages[-1]["content"] = full_text
        self._current_stream_id = None
        self._active_references = []
        self._notify_copilot_task_complete(full_text)
        self._save_current_session()

    def _notify_copilot_task_complete(self, response_text: str):
        """Show a toast when Copilot finished a tool-backed task."""
        if self._turn_tools_used <= 0 or self._turn_had_notify_user:
            self._turn_tools_used = 0
            self._turn_had_notify_user = False
            return
        try:
            from src.ui.components.toast_notification import ToastManager
            preview = (response_text or "").strip().replace("\n", " ")
            if len(preview) > 120:
                preview = preview[:117] + "..."
            if not preview:
                preview = S.pynia.task_complete_default
            tab_index = None
            mw = self._get_registry_main_window()
            if mw and hasattr(mw, "session_tabs") and self._current_tab_id:
                for idx in range(mw.session_tabs.count()):
                    widget = mw.session_tabs.widget(idx)
                    session = getattr(widget, "session", None)
                    if session and getattr(session, "session_id", None) == self._current_tab_id:
                        tab_index = idx
                        break
            ToastManager.notify(
                S.pynia.task_complete_title,
                preview,
                success=True,
                on_click=(lambda idx=tab_index: mw._focus_window_and_tab(idx)) if tab_index is not None and mw else None,
            )
        except Exception as e:
            logger.debug(f"Could not show Copilot completion toast: {e}")
        finally:
            self._turn_tools_used = 0
            self._turn_had_notify_user = False

    def _on_chat_error(self, error: str):
        self._chat_runtime.fail(error)
        self._set_loading(False)
        self._hide_thinking_indicator()
        if self._mcp_server and hasattr(self._mcp_server, "tool_registry"):
            self._mcp_server.tool_registry.unpin_session()
        self._active_tool_target_id = None
        if self._is_thinking:
            self._is_thinking = False
            self._run_chat_js("endThinkingBlock()")
        self._run_chat_js("endStreaming(); endToolGroup(); stopActivityTimer();")
        self._current_stream_id = None
        self._active_tool_calls.clear()
        if "Cannot find GitHub Copilot CLI" in error or "Copilot CLI" in error:
            self._on_gh_not_found()

    def _on_tool_called(self, tool_name: str, arguments: dict, tool_call_id: str = ""):
        self._chat_runtime.mark_tool(tool_name, "running")
        if tool_name != "think":
            self._turn_tools_used += 1
        if tool_name == "notify_user":
            self._turn_had_notify_user = True
        arg_summary = ""
        if arguments:
            parts = []
            for key, val in arguments.items():
                if key == "thought":
                    continue
                val_str = str(val)
                parts.append(f"{key}={val_str[:37] + '...' if len(val_str) > 40 else val_str}")
            arg_summary = ", ".join(parts[:3])
        tool_id = tool_call_id or f"{tool_name}-{len(self._active_tool_calls) + 1}"
        self._run_chat_js(
            f"addToolUse({json.dumps(tool_name)}, {json.dumps(arg_summary)}, {json.dumps(tool_id)})"
        )
        self._active_tool_calls[tool_id] = tool_name
        self.tool_call_requested.emit(tool_name, arguments)

    def _on_tool_result(self, tool_name: str, result: str, tool_call_id: str = ""):
        self._chat_runtime.touch_activity()
        self._chat_runtime.mark_tool(tool_name, "done")
        result_preview = ""
        is_error = "error" in result.lower()[:100]
        for line in (result or "").split("\n"):
            line = line.strip()
            if line and not line.startswith("```") and not line.startswith("##"):
                result_preview = line[:80] + ("..." if len(line) > 80 else "")
                break
        tool_id = tool_call_id or next(
            (tid for tid, name in reversed(list(self._active_tool_calls.items())) if name == tool_name),
            "",
        )
        self._run_chat_js(
            f"updateToolStatus({json.dumps(tool_name)}, 'done', {str(is_error).lower()}, "
            f"{json.dumps(result_preview)}, {json.dumps(tool_id)})"
        )
        if tool_id in self._active_tool_calls:
            del self._active_tool_calls[tool_id]

    def _on_thinking(self, text: str):
        if not text.strip():
            return
        self._chat_runtime.mark_thinking(text)
        if not self._is_thinking:
            self._is_thinking = True
            self._run_chat_js("startThinkingBlock()")
        self._run_chat_js(f"appendThinking({json.dumps(text)})")

    def _populate_model_combo(self, models: list):
        normalized = normalize_models(models) or fallback_models()
        current_model = self._model_combo.currentData()
        if not current_model and self._agent_client and hasattr(self._agent_client, 'model'):
            current_model = self._agent_client.model
        self._available_models = normalized
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model in normalized:
            model_id = model.get("id", "")
            model_name = model.get("name", model_id)
            idx = self._model_combo.count()
            self._model_combo.addItem(model_name, model_id)
            self._model_combo.setItemData(idx, self._format_multiplier(model.get("multiplier", 1.0)), Qt.ItemDataRole.UserRole + 1)
            self._model_combo.setItemData(idx, dict(model), Qt.ItemDataRole.UserRole + 2)
        restore_idx = self._model_combo.findData(current_model) if current_model else -1
        if restore_idx < 0 and self._model_combo.count() > 0:
            restore_idx = 0
        if restore_idx >= 0:
            self._model_combo.setCurrentIndex(restore_idx)
        self._model_combo.blockSignals(False)
        selected_model = self._model_combo.currentData()
        if selected_model and self._agent_client and hasattr(self._agent_client, 'model'):
            self._agent_client.model = selected_model
        self._update_reasoning_effort_state()
        self._set_usage_snapshot(usage_snapshot_for_model(self._available_models, selected_model))
        self._sync_models_to_webview()
        self._sync_attachment_limits_to_webview()

    def _on_model_changed(self, value):
        model_id = value if isinstance(value, str) else self._model_combo.currentData()
        if model_id:
            idx = self._model_combo.findData(model_id)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
            get_copilot_settings().set_chat_selected_model(model_id)
            if self._agent_client:
                self._agent_client.model = model_id
        self._update_reasoning_effort_state()
        self._set_usage_snapshot(usage_snapshot_for_model(self._available_models, model_id))
        self._sync_app_state()
        self._sync_attachment_limits_to_webview()

    def _update_reasoning_effort_state(self):
        model_id = self._model_combo.currentData() or ""
        supported = model_supports_reasoning_effort(self._available_models, model_id)
        supported_efforts = model_supported_reasoning_efforts(self._available_models, model_id)
        self._effort_combo.setEnabled(True)
        for index in range(self._effort_combo.count()):
            effort = self._effort_combo.itemData(index)
            self._effort_combo.model().item(index).setEnabled(effort == "auto" or effort in supported_efforts)
        current_effort = self._effort_combo.currentData()
        if current_effort != "auto" and current_effort not in supported_efforts:
            model = find_model(self._available_models, model_id) or {}
            preferred_effort = model.get("default_reasoning_effort") if supported else "auto"
            if preferred_effort not in supported_efforts:
                preferred_effort = "auto"
            effort_idx = self._effort_combo.findData(preferred_effort)
            if effort_idx >= 0:
                self._effort_combo.setCurrentIndex(effort_idx)
        self._sync_models_to_webview()

    def _on_reasoning_effort_changed(self, value):
        effort = value if isinstance(value, str) else self._effort_combo.currentData() or "auto"
        effort_index = self._effort_combo.findData(effort)
        if effort_index >= 0:
            self._effort_combo.setCurrentIndex(effort_index)
        model_id = self._model_combo.currentData() or ""
        supported_efforts = model_supported_reasoning_efforts(self._available_models, model_id)
        if effort != "auto" and effort not in supported_efforts:
            auto_idx = self._effort_combo.findData("auto")
            if auto_idx >= 0:
                self._effort_combo.setCurrentIndex(auto_idx)
            effort = "auto"
        get_copilot_settings().set_chat_reasoning_effort(effort)
        if self._agent_client and hasattr(self._agent_client, 'reasoning_effort'):
            self._agent_client.reasoning_effort = effort
        self._sync_app_state()

    def _on_refresh_models_clicked(self):
        self._usage_label.setText(S.pynia.usage_loading)
        self._usage_label.setVisible(True)
        self._sync_usage_to_webview()
        if self._agent_client and hasattr(self._agent_client, 'refresh_metadata'):
            self._agent_client.refresh_metadata()
        elif self._agent_client and hasattr(self._agent_client, 'start_auth'):
            self._agent_client.start_auth()

    def _set_usage_snapshot(self, snapshot: dict):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        self._usage_snapshot = snapshot
        if snapshot.get("available"):
            used = snapshot.get("used")
            total = snapshot.get("total")
            remaining = snapshot.get("remaining_percentage")
            if used is not None and total is not None:
                text = S.pynia.usage_format.format(used=used, total=total)
            elif used is not None:
                text = S.pynia.usage_used_format.format(used=used)
            elif remaining is not None:
                text = S.pynia.usage_remaining_format.format(remaining=remaining)
            else:
                text = S.pynia.usage_unavailable
            reset_date = snapshot.get("reset_date")
            tooltip = S.pynia.usage_tooltip_with_reset.format(reset_date=reset_date) if reset_date else S.pynia.usage_tooltip
        else:
            multiplier = self._format_multiplier(snapshot.get("multiplier", 1.0))
            text = S.pynia.usage_unavailable
            tooltip = S.pynia.usage_unavailable_tooltip.format(multiplier=multiplier)
        self._usage_label.setText(text)
        self._usage_label.setToolTip(tooltip)
        self._usage_label.setVisible(True)
        self._sync_usage_to_webview()

    def _on_auth_clicked(self, payload_json: str = ""):
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {}
        action = payload.get("action", "sign_in")

        if action == "install_gh":
            self._install_gh_cli()
            return
        if action == "update_runtime":
            self._begin_runtime_update_flow()
            return
        if action == "switch_account":
            self._open_account_picker()
            return
        if action == "cancel_auth":
            self._cancel_auth_flow()
            return
        if action == "logout":
            self._do_logout()
            return
        if action == "open_pynia_settings":
            self._open_pynia_settings()
            return

        auth_service = self._get_chat_auth_service()
        if auth_service.is_chat_authenticated:
            return
        self._auth_error_message = None
        self._auth_post_install_message = None
        if auth_service.login_chat():
            self._auth_signing_in = True
            self._auth_btn.setText(S.pynia.signing_in)
            self._auth_btn.setEnabled(False)
            self._refresh_auth_gate()
            self._sync_app_state()

    def _update_auth_state(self):
        if self._agent_client and self._agent_client.is_authenticated:
            username = getattr(self._agent_client, "_username", None)
            self._auth_btn.setText(f"@{username}" if username else S.pynia.connected)
        else:
            self._auth_btn.setText(S.pynia.sign_in)
        self._auth_btn.setEnabled(True)
        self._refresh_auth_gate()
        self._sync_app_state()

    def _on_auth_service_chat_logged_out(self):
        self._auth_success_shown = False
        self._auth_signing_in = False
        self._auth_device_code = None
        self._auth_error_message = None
        self._auth_gh_required = False
        self._auth_installing_gh = False
        self._auth_gate_progress_message = None
        self._auth_post_install_message = None
        self._update_auth_state()
        self._usage_label.setVisible(False)
        self._sync_usage_to_webview()

    def _on_reference_suggestions_requested(self, query: str):
        resolver = ReferenceResolver(self._get_registry_main_window())
        suggestions = resolver.suggestions(query)
        self._run_chat_js(f"showReferenceSuggestions({json.dumps(suggestions)})")

    def _on_reference_open_requested(self, reference: str):
        resolver = ReferenceResolver(self._get_registry_main_window())
        resolved = resolver.resolve(reference)
        if not resolved.get("ok") or resolved.get("type") != "tab":
            return
        mw = self._get_registry_main_window()
        if mw and hasattr(mw, "session_tabs"):
            mw.session_tabs.setCurrentIndex(int(resolved.get("tab_index", 0)))

    def _on_history_collapsed_changed(self, collapsed: bool):
        get_copilot_settings().set_chat_history_collapsed(collapsed)
        self._sync_app_state()

    def _refresh_history_sidebar(self):
        sessions = self._get_sessions_list()
        self._run_chat_js(f"setSessions({json.dumps({'sessions': sessions, 'current_session_id': self._current_session_id})})")

    def _update_tab_badge(self, tab_name: str):
        label_text = S.pynia.chat_context_tab.replace("{name}", tab_name)
        self._tab_badge.setText(label_text)
        self._tab_badge.setVisible(bool(tab_name))
        self._sync_app_state()


# Backward-compatible alias (imports/tests)
CopilotChatPanel = PyniaChatPanel
