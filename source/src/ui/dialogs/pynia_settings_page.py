"""Pynia settings page — ACP agent install, login, test, autocomplete."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.design_system.tokens import get_colors
from src.language import S
from src.services.pynia.acp.catalog import get_agent, list_agents, load_agent_icon, resolve_global_launch
from src.services.pynia.acp.installer import handshake_test, install_command, probe_agent, run_install, run_login
from src.services.pynia.settings import get_pynia_settings
from src.ui.components.toggle_switch import LabeledToggleSwitch
from src.utils.qt_threading import stop_qthread

logger = logging.getLogger(__name__)


class _Worker(QObject):
    done = pyqtSignal(str, bool, str)  # agent_id, ok, detail
    output = pyqtSignal(str)

    def __init__(self, agent_id: str, action: str):
        super().__init__()
        self._agent_id = agent_id
        self._action = action

    @pyqtSlot()
    def run(self):
        spec = get_agent(self._agent_id)
        if spec is None:
            self.done.emit(self._agent_id, False, "Unknown agent")
            return
        try:
            if self._action == "install":
                code, out = run_install(spec, on_output=self.output.emit)
                self.done.emit(self._agent_id, code == 0, out[-2000:] if out else "")
            elif self._action == "login":
                code, out = run_login(spec)
                self.done.emit(self._agent_id, code == 0, out)
            else:
                ok, detail = handshake_test(spec)
                self.done.emit(self._agent_id, ok, detail)
        except Exception as exc:
            self.done.emit(self._agent_id, False, str(exc))


class PyniaSettingsPage(QWidget):
    """Settings body for the Pynia ACP agents."""

    default_agent_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._threads: list[QThread] = []
        self._status_labels: dict[str, QLabel] = {}
        self._action_buttons: list[QPushButton] = []
        self._busy = False
        self._setup_ui()
        self.refresh()

    def cleanup(self) -> None:
        for thread in list(self._threads):
            stop_qthread(thread, wait_ms=1500)
        self._threads.clear()

    def _setup_ui(self) -> None:
        colors = get_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 12)
        layout.setSpacing(14)

        from src.assets.pynia_branding import load_pynia_logo

        header = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(40, 40)
        icon = load_pynia_logo(40)
        if icon:
            logo.setPixmap(icon.pixmap(40, 40))
        header.addWidget(logo)
        title = QLabel(getattr(S.pynia, "title", "Pynia"))
        title.setStyleSheet(f"color: {colors.text_primary}; font-size: 18px; font-weight: 600;")
        header.addWidget(title, 1)
        layout.addLayout(header)

        intro = QLabel(
            getattr(
                S.pynia,
                "settings_intro",
                "Install an ACP agent, sign in, and run a connection test. Each DataPyn tab is its own chat.",
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {colors.text_secondary};")
        layout.addWidget(intro)

        default_row = QHBoxLayout()
        default_row.addWidget(QLabel(getattr(S.pynia, "default_agent", "Default agent")))
        self._default_combo = QComboBox()
        self._default_combo.addItem(getattr(S.pynia, "default_agent_none", "Ask each time"), "")
        for spec in list_agents():
            self._default_combo.addItem(spec.label, spec.id)
        settings = get_pynia_settings()
        idx = self._default_combo.findData(settings.default_agent_id)
        if idx >= 0:
            self._default_combo.setCurrentIndex(idx)
        self._default_combo.currentIndexChanged.connect(self._on_default_changed)
        default_row.addWidget(self._default_combo, 1)
        layout.addLayout(default_row)

        for spec in list_agents():
            layout.addWidget(self._make_card(spec, colors))

        auto = LabeledToggleSwitch(
            getattr(S.pynia, "autocomplete_enable", "Enable AI inline autocomplete in code blocks"),
            checked=settings.autocomplete_enabled,
        )
        auto.toggled.connect(lambda checked: get_pynia_settings().set_autocomplete_enabled(checked))
        self._autocomplete = auto
        layout.addWidget(auto)
        hint = QLabel(
            getattr(
                S.pynia,
                "autocomplete_hint",
                "When enabled, Pynia asks the tab's agent for ghost-text after you pause typing. It never blocks the editor.",
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
        layout.addWidget(hint)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(140)
        self._log.setPlaceholderText(getattr(S.pynia, "install_log", "Install and test output appears here."))
        layout.addWidget(self._log)
        layout.addStretch()

    def _make_card(self, spec, colors) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"QWidget {{ background: {colors.bg_secondary}; border: 1px solid {colors.border_default}; border-radius: 8px; }}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        icon_label = QLabel()
        icon_label.setFixedSize(28, 28)
        icon = load_agent_icon(spec, 28)
        if icon:
            icon_label.setPixmap(icon.pixmap(28, 28))
        row.addWidget(icon_label)
        col = QVBoxLayout()
        name = QLabel(spec.label)
        name.setStyleSheet(f"color: {colors.text_primary}; font-weight: 600;")
        status = QLabel()
        status.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
        status.setWordWrap(True)
        self._status_labels[spec.id] = status
        col.addWidget(name)
        col.addWidget(status)
        row.addLayout(col, 1)
        for action, label in (
            ("install", getattr(S.pynia, "btn_install", "Install")),
            ("login", getattr(S.pynia, "btn_login", "Login")),
            ("test", getattr(S.pynia, "btn_test", "Test")),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, aid=spec.id, act=action: self._run_action(aid, act))
            self._action_buttons.append(btn)
            row.addWidget(btn)
        return card

    def refresh(self) -> None:
        for spec in list_agents():
            probe = probe_agent(spec.id)
            label = self._status_labels.get(spec.id)
            if label:
                extra = f" · {probe.command}" if probe.command else ""
                label.setText(f"{probe.status.replace('_', ' ')}{extra}")

    def _on_default_changed(self) -> None:
        agent_id = self._default_combo.currentData() or ""
        get_pynia_settings().set_default_agent_id(agent_id)
        self.default_agent_changed.emit(agent_id)

    def snapshot(self) -> dict:
        return {
            "default_agent": self._default_combo.currentData() or "",
            "autocomplete": self._autocomplete.isChecked(),
        }

    def persist(self) -> None:
        get_pynia_settings().set_default_agent_id(self._default_combo.currentData() or "")
        get_pynia_settings().set_autocomplete_enabled(self._autocomplete.isChecked())

    def _append_log(self, text: str) -> None:
        self._log.append(text)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for btn in self._action_buttons:
            btn.setEnabled(not busy)

    def _run_action(self, agent_id: str, action: str) -> None:
        if self._busy:
            return
        spec = get_agent(agent_id)
        if spec and action == "install":
            existing = resolve_global_launch(spec)
            if existing:
                self._append_log(f"[{agent_id}] already installed — skipping")
                self._append_log(existing[0])
                self.refresh()
                return
            self._append_log(f"$ {install_command(spec)}")
        self._set_busy(True)
        worker = _Worker(agent_id, action)
        thread = QThread()
        thread.setObjectName(f"pynia-{action}-{agent_id}")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.output.connect(self._append_log)
        worker.done.connect(self._on_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._forget_thread(t))
        self._threads.append(thread)
        thread.start()

    def _forget_thread(self, thread: QThread) -> None:
        try:
            self._threads.remove(thread)
        except ValueError:
            pass

    def _on_done(self, agent_id: str, ok: bool, detail: str) -> None:
        self._set_busy(False)
        mark = "ok" if ok else "error"
        self._append_log(f"[{agent_id}] {mark}: {detail}")
        self.refresh()
