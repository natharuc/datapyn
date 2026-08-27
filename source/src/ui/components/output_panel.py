"""
Output/Logs Panel - Structured, interactive log system.

Each log entry is a rich item with metadata (block info, line number,
timestamp, duration). Errors are navigable (double-click goes to error
line) and inspectable (eye icon opens detail dialog).
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QSizePolicy, QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QKeySequence, QShortcut

from .buttons import GhostButton
from src.language import S

try:
    import qtawesome as qta
    HAS_QTAWESOME = True
except ImportError:
    HAS_QTAWESOME = False


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class LogEntry:
    """Structured log entry with full execution context."""
    timestamp: datetime = field(default_factory=datetime.now)
    level: str = "info"           # info, success, warning, error, debug
    log_type: str = ""            # SQL, PYTHON, SYSTEM, etc.
    message: str = ""             # Short display message
    detail: str = ""              # Full error / traceback
    block_index: Optional[int] = None
    block_name: str = ""
    line_number: Optional[int] = None   # Parsed error line within the block
    column_number: Optional[int] = None  # Parsed error column within the line
    duration_ms: Optional[float] = None
    code_snippet: str = ""        # The code that was executed
    connection_name: str = ""
    database_name: str = ""


def _find_token_in_sql(token: str, sql: str) -> Optional[tuple]:
    """Find a token in the SQL code and return (line, column) 1-based.

    Used as fallback when the DB error message doesn't include line info
    but mentions a specific identifier (column name, table name, etc.).
    """
    if not token or not sql:
        return None
    # Search case-insensitive
    sql_lower = sql.lower()
    token_lower = token.lower()
    pos = sql_lower.find(token_lower)
    if pos < 0:
        return None
    # Convert char offset to line/column
    before = sql[:pos]
    line = before.count('\n') + 1
    last_nl = before.rfind('\n')
    col = pos - last_nl if last_nl >= 0 else pos + 1
    return (line, col)


def _extract_error_token(error_text: str) -> Optional[str]:
    """Extract the problematic identifier from a DB error message.

    Patterns recognized:
      - Unknown column 'xxx'
      - Invalid column name 'xxx'
      - column "xxx" does not exist
      - Invalid object name 'xxx'
      - Table 'xxx' doesn't exist
      - near 'xxx'
      - near "xxx"
    """
    patterns = [
        r"Unknown column\s+'([^']+)'",
        r"Invalid column name\s+'([^']+)'",
        r'column\s+"([^"]+)"\s+does not exist',
        r"Invalid object name\s+'([^']+)'",
        r"Table\s+'([^']+)'\s+doesn't exist",
        r"relation\s+\"([^\"]+)\"\s+does not exist",
        r"near\s+'([^']+)'",
        r'near\s+"([^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, error_text, re.IGNORECASE)
        if m:
            token = m.group(1)
            # For qualified names like 'pa.adicionalid', also try the last part
            return token
    return None


def parse_error_line(error_text: str, log_type: str = "SQL") -> Optional[int]:
    """Extract line number from an error message.

    Supports:
      SQL Server : 'Line 5' / 'line 5'
      MySQL      : 'at line 5'
      PostgreSQL : 'LINE 5:'
      Python     : 'File "<string>", line 5'
      Generic    : 'line N' anywhere
    """
    if not error_text:
        return None

    patterns = [
        # SQL Server: Msg N, Level N, State N, Line N
        r'Line\s+(\d+)',
        # MySQL: ... at line N
        r'at\s+line\s+(\d+)',
        # PostgreSQL: LINE N:
        r'LINE\s+(\d+)\s*:',
        # Python traceback: File "...", line N
        r'line\s+(\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, error_text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def parse_error_position(error_text: str, sql_code: str = "",
                         log_type: str = "SQL") -> tuple:
    """Extract (line, column) from an error, with token-based fallback.

    Returns (line_or_None, column_or_None).
    """
    line = parse_error_line(error_text, log_type)
    col = None

    # If we already have a line from the message, try to also find column
    # via token search within that line
    if line and sql_code:
        token = _extract_error_token(error_text)
        if token:
            pos = _find_token_in_sql(token, sql_code)
            if pos and pos[0] == line:
                col = pos[1]

    # Fallback: no line in message but we have the SQL and a token
    if line is None and sql_code:
        token = _extract_error_token(error_text)
        if token:
            pos = _find_token_in_sql(token, sql_code)
            if pos:
                line, col = pos

    return (line, col)


# ---------------------------------------------------------------------------
# OutputPanel Widget
# ---------------------------------------------------------------------------

MAX_OUTPUT_ENTRIES = 200


class OutputPanel(QWidget):
    """Interactive output/logs panel with structured log entries."""

    # Signals
    cleared = pyqtSignal()
    navigate_to_block = pyqtSignal(int, int, int)  # (block_index, line_number, column_number)
    resolve_with_copilot = pyqtSignal(dict)    # context dict for Copilot

    def __init__(self, theme_manager=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._entries: List[LogEntry] = []
        self._filter_errors_only = False
        self._setup_ui()
        self._apply_theme()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        from src.design_system.tokens import get_colors
        colors = get_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Toolbar ---
        toolbar = QWidget()
        toolbar.setObjectName("outputToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 4, 8, 4)
        toolbar_layout.setSpacing(6)

        # Filter: Errors only toggle
        self._filter_btn = GhostButton(S.output_panel.filter_errors)
        if HAS_QTAWESOME:
            self._filter_btn.setIcon(qta.icon("mdi.filter-outline", color=colors.text_tertiary))
        self._filter_btn.setCheckable(True)
        self._filter_btn.setChecked(False)
        self._filter_btn.toggled.connect(self._on_filter_toggled)
        toolbar_layout.addWidget(self._filter_btn)

        toolbar_layout.addStretch()

        # Clear button
        self.btn_clear = GhostButton(S.output_panel.btn_clear)
        if HAS_QTAWESOME:
            self.btn_clear.setIcon(qta.icon("mdi.trash-can-outline", color=colors.text_tertiary))
        self.btn_clear.clicked.connect(self.clear)
        toolbar_layout.addWidget(self.btn_clear)

        # Copy button
        self.btn_copy = GhostButton(S.output_panel.btn_copy)
        if HAS_QTAWESOME:
            self.btn_copy.setIcon(qta.icon("mdi.content-copy", color=colors.text_tertiary))
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        toolbar_layout.addWidget(self.btn_copy)

        toolbar.setStyleSheet(f"""
            #outputToolbar {{
                background-color: {colors.bg_secondary};
                border: none;
                border-bottom: 1px solid {colors.border_default};
            }}
        """)
        layout.addWidget(toolbar)

        # --- Log list ---
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setFont(QFont("Consolas", 10))
        self._list.setSpacing(0)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list)

        # Ctrl+C copies the selected log entry (with its traceback). Scoped to
        # the list so it doesn't collide with copy in other panels.
        copy_sc = QShortcut(QKeySequence.StandardKey.Copy, self._list)
        copy_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy_sc.activated.connect(self._copy_selected_entry)

    def _apply_theme(self):
        from src.design_system.tokens import get_colors, SCROLLBAR_STYLE
        colors = get_colors()

        bg = colors.bg_primary
        fg = colors.text_primary
        border = colors.border_default
        hover = colors.bg_elevated

        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {bg};
                color: {fg};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                border-bottom: 1px solid {border};
                padding: 0px;
            }}
            QListWidget::item:selected {{
                background-color: {hover};
            }}
            QListWidget::item:hover:!selected {{
                background-color: {hover};
            }}
            {SCROLLBAR_STYLE}
        """)

    def set_theme_manager(self, theme_manager):
        self.theme_manager = theme_manager
        self._apply_theme()

    # ------------------------------------------------------------------
    # Public API  (new structured)
    # ------------------------------------------------------------------

    def add_entry(self, entry: LogEntry):
        """Add a structured LogEntry to the panel."""
        self._entries.append(entry)
        overflow = len(self._entries) - MAX_OUTPUT_ENTRIES
        if overflow > 0:
            del self._entries[:overflow]
            self._rebuild_list()
            return
        if self._filter_errors_only and entry.level not in ("error", "warning"):
            return  # filtered out
        self._add_item_for_entry(entry, index=len(self._entries) - 1)

    # ------------------------------------------------------------------
    # Public API  (backward-compatible)
    # ------------------------------------------------------------------

    def append(self, text: str, level: str = "info"):
        entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            message=text,
        )
        self.add_entry(entry)

    def append_output(self, text: str, error: bool = False):
        self.append(text, "error" if error else "info")

    def log(self, text: str):
        self.append(text, "info")

    def success(self, text: str):
        self.append(text, "success")

    def warning(self, text: str):
        self.append(text, "warning")

    def error(self, text: str):
        self.append(text, "error")

    def debug(self, text: str):
        self.append(text, "debug")

    def clear(self):
        self._entries.clear()
        self._list.clear()
        self.cleared.emit()

    def get_text(self) -> str:
        lines = []
        for e in self._entries:
            ts = e.timestamp.strftime("%H:%M:%S")
            prefix = f"[{ts}]"
            if e.log_type:
                prefix += f"[{e.log_type}]"
            lines.append(f"{prefix} {e.message}")
        return "\n".join(lines)

    def toPlainText(self) -> str:
        return self.get_text()

    def get_last_error(self) -> Optional[dict]:
        """Return the most recent error entry as a plain dict, or None.

        Used by Pynia to answer "why did my query fail?" without an extra
        tool round. ``is_latest`` is True when no info/success entry was
        logged after the error (i.e. the failure is still the current state).
        """
        error_entry: Optional[LogEntry] = None
        error_pos = -1
        for pos, entry in enumerate(self._entries):
            if entry.level == "error":
                error_entry = entry
                error_pos = pos
        if error_entry is None:
            return None

        detail = (error_entry.detail or "").strip()
        if len(detail) > 2000:
            detail = detail[:2000] + "\n... (truncated)"
        is_latest = not any(
            e.level in ("info", "success") for e in self._entries[error_pos + 1 :]
        )
        return {
            "message": (error_entry.message or "").strip(),
            "detail": detail,
            "log_type": error_entry.log_type or "",
            "block_name": error_entry.block_name or "",
            "block_index": error_entry.block_index,
            "line_number": error_entry.line_number,
            "connection_name": error_entry.connection_name or "",
            "timestamp": error_entry.timestamp.strftime("%H:%M:%S"),
            "is_latest": is_latest,
        }

    def get_html(self) -> str:
        return self.get_text()

    def _copy_to_clipboard(self):
        QApplication.clipboard().setText(self.get_text())

    def _copy_selected_entry(self):
        """Copy the selected log entry (message + detail). Falls back to all."""
        item = self._list.currentItem()
        idx = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if idx is None or idx >= len(self._entries):
            QApplication.clipboard().setText(self.get_text())
            return
        entry = self._entries[idx]
        ts = entry.timestamp.strftime("%H:%M:%S")
        header = f"[{ts}]"
        if entry.log_type:
            header += f"[{entry.log_type}]"
        parts = [f"{header} {entry.message}".strip()]
        detail = (entry.detail or "").strip()
        if detail and detail != (entry.message or "").strip():
            parts.append(detail)
        QApplication.clipboard().setText("\n".join(parts))

    # Compat: some code accesses .text_edit or .verticalScrollBar()
    @property
    def text_edit(self):
        return self._list

    def verticalScrollBar(self):
        return self._list.verticalScrollBar()

    # ------------------------------------------------------------------
    # Item rendering
    # ------------------------------------------------------------------

    def _add_item_for_entry(self, entry: LogEntry, index: Optional[int] = None, *, scroll: bool = True):
        from src.design_system.tokens import get_colors
        colors = get_colors()

        widget = QWidget()
        widget.setObjectName("logRow")
        row = QHBoxLayout(widget)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)

        level_colors = {
            "info": colors.info,
            "success": colors.success,
            "warning": colors.warning,
            "error": colors.danger,
            "debug": colors.text_tertiary,
        }
        level_icons = {
            "info": "mdi.information-outline",
            "success": "mdi.check-circle-outline",
            "warning": "mdi.alert-outline",
            "error": "mdi.close-circle-outline",
            "debug": "mdi.bug-outline",
        }
        lcolor = level_colors.get(entry.level, colors.info)

        # 1. Level icon
        if HAS_QTAWESOME:
            icon_name = level_icons.get(entry.level, "mdi.information-outline")
            icon_label = QLabel()
            icon_label.setPixmap(qta.icon(icon_name, color=lcolor).pixmap(QSize(16, 16)))
            icon_label.setFixedWidth(18)
            row.addWidget(icon_label)

        # 2. Timestamp
        ts_label = QLabel(entry.timestamp.strftime("%H:%M:%S"))
        ts_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px; font-family: Consolas;")
        ts_label.setFixedWidth(58)
        row.addWidget(ts_label)

        # 3. Block badge (if applicable)
        if entry.block_index is not None:
            badge_text = entry.block_name or f"Block {entry.block_index + 1}"
            badge = QLabel(badge_text)
            badge.setStyleSheet(f"""
                QLabel {{
                    background-color: {lcolor}30;
                    color: {lcolor};
                    font-size: 10px;
                    font-weight: bold;
                    padding: 1px 6px;
                    border-radius: 3px;
                    font-family: Consolas;
                }}
            """)
            badge.setFixedHeight(18)
            row.addWidget(badge)

            # Line:Column badge
            if entry.line_number is not None:
                pos_text = f"L{entry.line_number}"
                if entry.column_number is not None:
                    pos_text += f":{entry.column_number}"
                line_badge = QLabel(pos_text)
                line_badge.setStyleSheet(f"""
                    QLabel {{
                        color: {colors.text_tertiary};
                        font-size: 10px;
                        padding: 1px 4px;
                        font-family: Consolas;
                    }}
                """)
                line_badge.setFixedHeight(18)
                row.addWidget(line_badge)

        # 4. Message text
        msg_label = QLabel(self._truncate(entry.message, 200))
        msg_label.setStyleSheet(f"color: {lcolor}; font-size: 12px; font-family: Consolas;")
        msg_label.setWordWrap(False)
        msg_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(msg_label, 1)

        # 5. Duration badge
        if entry.duration_ms is not None:
            dur_text = self._format_duration(entry.duration_ms)
            dur_label = QLabel(dur_text)
            dur_label.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; font-family: Consolas;")
            dur_label.setFixedWidth(52)
            dur_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(dur_label)

        # 6. Eye button (for errors/warnings with detail)
        if entry.level in ("error", "warning") or entry.detail:
            eye_btn = QPushButton()
            if HAS_QTAWESOME:
                eye_btn.setIcon(qta.icon("mdi.eye-outline", color=colors.text_tertiary))
            eye_btn.setFixedSize(24, 24)
            eye_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            eye_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    background-color: {colors.bg_elevated};
                }}
            """)
            eye_btn.clicked.connect(lambda checked, e=entry: self._open_detail_dialog(e))
            row.addWidget(eye_btn)

        # Create list item
        item = QListWidgetItem()
        item.setData(
            Qt.ItemDataRole.UserRole,
            len(self._entries) - 1 if index is None else index,
        )
        item.setSizeHint(QSize(0, max(32, widget.sizeHint().height())))
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

        # Scroll to bottom
        if scroll:
            self._list.scrollToBottom()

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def _on_item_double_clicked(self, item: QListWidgetItem):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is None or idx >= len(self._entries):
            return
        entry = self._entries[idx]
        if entry.block_index is not None:
            line = entry.line_number or 1
            col = entry.column_number or 0
            self.navigate_to_block.emit(entry.block_index, line, col)
        else:
            self._open_detail_dialog(entry)

    def _open_detail_dialog(self, entry: LogEntry):
        from src.ui.dialogs.log_detail_dialog import LogDetailDialog
        dlg = LogDetailDialog(entry, parent=self)
        dlg.resolve_requested.connect(lambda ctx: self.resolve_with_copilot.emit(ctx))
        dlg.exec()

    def _on_filter_toggled(self, checked: bool):
        self._filter_errors_only = checked
        self._rebuild_list()

    def _rebuild_list(self):
        self._list.clear()
        for i, entry in enumerate(self._entries):
            if self._filter_errors_only and entry.level not in ("error", "warning"):
                continue
            self._add_item_for_entry(entry, index=i, scroll=False)
        self._list.scrollToBottom()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        first_line = text.split("\n")[0]
        if len(first_line) > max_len:
            return first_line[:max_len] + "..."
        return first_line

    @staticmethod
    def _format_duration(ms: float) -> str:
        if ms < 1000:
            return f"{ms:.0f}ms"
        s = ms / 1000
        if s < 60:
            return f"{s:.1f}s"
        m = int(s // 60)
        sec = s % 60
        return f"{m}m{sec:.0f}s"
