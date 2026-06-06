"""
Tests for per-tab notification feature:
- TabNotificationDialog UI
- result[row][col] template rendering
- Per-tab config in SessionWidget
- DPW persistence of notification config
"""

import pytest
import json
import pandas as pd
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt


# ==================== RESULT REFERENCE RENDERING ====================


class TestResultRefRendering:
    """Test the result[N][M] reference resolution in templates."""

    def _resolve(self, template, last_result):
        from src.ui.components.session_widget import SessionWidget
        return SessionWidget._resolve_result_refs(template, last_result)

    def test_basic_result_ref(self):
        """{{result[0][0]}} resolves to first cell of DataFrame."""
        df = pd.DataFrame({"a": [42], "b": [99]})
        result = self._resolve("Value: {{result[0][0]}}", df)
        assert result == "Value: 42"

    def test_result_ref_second_column(self):
        """{{result[0][1]}} resolves to second column."""
        df = pd.DataFrame({"a": [42], "b": [99]})
        result = self._resolve("{{result[0][1]}}", df)
        assert result == "99"

    def test_result_ref_second_row(self):
        """{{result[1][0]}} resolves to second row."""
        df = pd.DataFrame({"x": [10, 20, 30]})
        result = self._resolve("{{result[1][0]}}", df)
        assert result == "20"

    def test_multiple_result_refs(self):
        """Multiple result refs in one template."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = self._resolve("{{result[0][0]}} / {{result[1][1]}}", df)
        assert result == "1 / 4"

    def test_result_ref_out_of_bounds(self):
        """Out-of-bounds ref is left as-is."""
        df = pd.DataFrame({"a": [42]})
        result = self._resolve("{{result[5][0]}}", df)
        assert result == "{{result[5][0]}}"

    def test_result_ref_none_dataframe(self):
        """None last_result leaves refs as-is."""
        result = self._resolve("{{result[0][0]}}", None)
        assert result == "{{result[0][0]}}"

    def test_result_ref_mixed_with_vars(self):
        """result refs mixed with {{var}} placeholders (vars not resolved here)."""
        df = pd.DataFrame({"val": [123]})
        result = self._resolve("{{tab_name}}: {{result[0][0]}}", df)
        assert result == "{{tab_name}}: 123"

    def test_result_ref_string_value(self):
        """String values are resolved correctly."""
        df = pd.DataFrame({"name": ["Alice"]})
        result = self._resolve("{{result[0][0]}}", df)
        assert result == "Alice"

    def test_result_ref_no_refs_in_template(self):
        """Template without result refs is returned unchanged."""
        df = pd.DataFrame({"a": [1]})
        result = self._resolve("No refs here", df)
        assert result == "No refs here"

    def test_result_ref_empty_dataframe(self):
        """Empty DataFrame leaves refs as-is."""
        df = pd.DataFrame()
        result = self._resolve("{{result[0][0]}}", df)
        assert result == "{{result[0][0]}}"


# ==================== TAB NOTIFICATION DIALOG ====================


class TestTabNotificationDialog:
    """Test the TabNotificationDialog UI."""

    @pytest.fixture
    def dialog(self, qtbot):
        from src.ui.dialogs.tab_notification_dialog import TabNotificationDialog
        dlg = TabNotificationDialog(parent=None)
        qtbot.addWidget(dlg)
        return dlg

    @pytest.fixture
    def dialog_with_config(self, qtbot):
        from src.ui.dialogs.tab_notification_dialog import TabNotificationDialog
        config = {
            "enabled": True,
            "title": "My Tab",
            "message": "Got {{result[0][0]}}",
        }
        dlg = TabNotificationDialog(current_config=config, parent=None)
        qtbot.addWidget(dlg)
        return dlg

    def test_dialog_creates(self, dialog):
        """Dialog is created without errors."""
        assert dialog is not None

    def test_default_enable_unchecked(self, dialog):
        """Enable checkbox is unchecked by default (no config)."""
        assert not dialog._enable_cb.isChecked()

    def test_config_restores_enabled(self, dialog_with_config):
        """Config with enabled=True restores checkbox."""
        assert dialog_with_config._enable_cb.isChecked()

    def test_config_restores_title(self, dialog_with_config):
        """Config restores title input."""
        assert dialog_with_config._title_input.text() == "My Tab"

    def test_config_restores_message(self, dialog_with_config):
        """Config restores message input."""
        assert dialog_with_config._message_input.text() == "Got {{result[0][0]}}"

    def test_save_returns_config(self, dialog, qtbot):
        """Clicking save returns config dict."""
        dialog._enable_cb.setChecked(True)
        dialog._title_input.setText("Test Title")
        dialog._message_input.setText("Test Msg")
        dialog._on_save()
        config = dialog.get_config()
        assert config is not None
        assert config["enabled"] is True
        assert config["title"] == "Test Title"
        assert config["message"] == "Test Msg"
        assert "color" in config

    def test_cancel_returns_none(self, dialog):
        """get_config returns None if dialog not saved."""
        config = dialog.get_config()
        assert config is None

    def test_template_group_disabled_when_unchecked(self, dialog):
        """Template group is disabled when enable is unchecked."""
        dialog._enable_cb.setChecked(False)
        assert not dialog._template_group.isEnabled()

    def test_template_group_enabled_when_checked(self, dialog):
        """Template group is enabled when enable is checked."""
        dialog._enable_cb.setChecked(True)
        assert dialog._template_group.isEnabled()

    def test_color_picker_exists(self, dialog):
        """Color picker button exists."""
        assert hasattr(dialog, '_color_btn')
        assert hasattr(dialog, '_color_value')

    def test_color_default_is_green(self, dialog):
        """Default color is success green."""
        assert dialog._color_value == "#1e8a3e"

    def test_color_saved_in_config(self, dialog):
        """Color is included in saved config."""
        dialog._enable_cb.setChecked(True)
        dialog._color_value = "#ff5500"
        dialog._on_save()
        config = dialog.get_config()
        assert config["color"] == "#ff5500"

    def test_color_restored_from_config(self, qtbot):
        """Color is restored from existing config."""
        from src.ui.dialogs.tab_notification_dialog import TabNotificationDialog
        dlg = TabNotificationDialog(current_config={"enabled": True, "color": "#abc123"}, parent=None)
        qtbot.addWidget(dlg)
        assert dlg._color_value == "#abc123"

    def test_dialog_removes_per_tab_channels_and_exposes_rule_actions(self, dialog):
        """Per-tab dialog keeps actions local to rules and no longer exposes transport channels."""
        dialog._add_rule_row({
            "enabled": True,
            "left": "{{result[0][0]}}",
            "operator": "equals",
            "value": "Alert",
            "action": "set_color",
            "action_value": "#ff00aa",
        })

        row = dialog._rule_rows[-1]

        assert not hasattr(dialog, "_toast_channel_cb")
        assert not hasattr(dialog, "_telegram_channel_cb")
        assert not hasattr(dialog, "_email_channel_cb")
        assert row["action"].currentData() == "set_color"
        assert row["action_color_label"].text() == "#ff00aa"

    def test_save_returns_rules_without_per_tab_channels(self, dialog):
        """Saving stores rule actions but does not persist transport channels per tab."""
        dialog._enable_cb.setChecked(True)
        dialog._add_rule_row({
            "enabled": True,
            "left": "{{result[0][0]}}",
            "operator": "equals",
            "value": "Active",
            "action": "set_color",
            "action_value": "#ff00aa",
        })

        dialog._on_save()
        config = dialog.get_config()

        assert config is not None
        assert "channels" not in config
        assert len(config["rules"]) == 1
        assert config["rules"][0]["left"] == "{{result[0][0]}}"
        assert config["rules"][0]["operator"] == "equals"
        assert config["rules"][0]["action"] == "set_color"
        assert config["rules"][0]["action_value"] == "#ff00aa"

    def test_save_ignores_blank_rule_rows(self, dialog):
        """Saving ignores incomplete blank rules instead of persisting noisy entries."""
        dialog._enable_cb.setChecked(True)
        dialog._add_rule_row()
        dialog._on_save()

        assert dialog.get_config()["rules"] == []


# ==================== PER-TAB CONFIG ON SESSION WIDGET ====================


class TestSessionWidgetTabNotification:
    """Test the per-tab notification config on SessionWidget."""

    @pytest.fixture
    def widget(self, qtbot):
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session
        from src.core.theme_manager import ThemeManager

        session = Session(session_id="test-1", title="TestTab")
        tm = ThemeManager()
        w = SessionWidget(session=session, theme_manager=tm)
        qtbot.addWidget(w)
        return w

    def test_default_config_is_none(self, widget):
        """Default tab notification config is None."""
        assert widget.get_tab_notification_config() is None

    def test_set_and_get_config(self, widget):
        """Can set and retrieve tab notification config."""
        config = {"enabled": True, "title": "T", "message": "M"}
        widget.set_tab_notification_config(config)
        saved = widget.get_tab_notification_config()
        assert saved is not None
        assert saved["enabled"] is True
        assert saved["title"] == "T"
        assert saved["message"] == "M"
        assert saved["color"] == "#1e8a3e"
        assert saved["rules"] == []

    def test_clear_config(self, widget):
        """Can clear config by setting None."""
        widget.set_tab_notification_config({"enabled": True, "title": "T", "message": "M"})
        widget.set_tab_notification_config(None)
        assert widget.get_tab_notification_config() is None

    def test_set_tab_notification_config_updates_session_model(self, widget):
        """Setting tab notification config updates the backing session model immediately."""
        config = {
            "enabled": True,
            "title": "Alert",
            "message": "Value: {{result[0][0]}}",
            "rules": [
                {
                    "enabled": True,
                    "left": "{{result[0][0]}}",
                    "operator": "equals",
                    "value": "42",
                    "action": "suppress",
                }
            ],
        }

        widget.set_tab_notification_config(config)

        assert widget.session.notification_config is not None
        assert widget.session.notification_config["rules"][0]["action"] == "suppress"

    def test_widget_restores_notification_config_from_session(self, qtbot):
        """SessionWidget restores tab notification config when the session already has it."""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session
        from src.core.theme_manager import ThemeManager

        session = Session(session_id="test-restore", title="RestoredTab")
        session.notification_config = {
            "enabled": True,
            "title": "Loaded",
            "message": "Loaded {{result[0][0]}}",
            "rules": [
                {
                    "enabled": True,
                    "left": "{{result[0][0]}}",
                    "operator": "contains",
                    "value": "warn",
                    "action": "set_color",
                    "action_value": "#ffaa00",
                }
            ],
        }

        widget = SessionWidget(session=session, theme_manager=ThemeManager())
        qtbot.addWidget(widget)

        restored = widget.get_tab_notification_config()
        assert restored is not None
        assert restored["title"] == "Loaded"
        assert restored["rules"][0]["action"] == "set_color"
        assert restored["rules"][0]["action_value"] == "#ffaa00"

    def test_python_dataframe_result_updates_last_result(self, widget):
        """Python DataFrame results feed {{result[row][col]}} notifications."""
        widget._process_next_in_queue = MagicMock()
        df = pd.DataFrame({"value": [42]})

        widget._on_python_finished(df, "", "", {}, [])

        stored = widget.session.get_variable("_last_result")
        assert stored is not None
        assert stored.equals(df)
        assert widget._queue_last_rows == 1

    def test_internal_notification_keys_are_filtered_from_python_namespace(self, widget):
        """Internal notification variables are excluded from Python execution namespaces."""
        widget.session.set_variable("_last_result", pd.DataFrame({"value": [1]}))
        widget.session.set_variable("user_df", pd.DataFrame({"value": [2]}))

        filtered = widget._filter_internal_notification_namespace(widget.session.namespace)

        assert "_last_result" not in filtered
        assert "user_df" in filtered

    def test_python_finished_ignores_stale_last_result_from_worker_namespace(self, widget):
        """Worker namespace updates cannot overwrite the current notification result with a stale value."""
        widget._process_next_in_queue = MagicMock()
        stale_df = pd.DataFrame({"value": [10]})
        new_df = pd.DataFrame({"value": [20]})
        widget.session.set_variable("_last_result", stale_df)

        widget._on_python_finished(new_df, "", "", {"_last_result": stale_df, "answer": 7}, [])

        stored = widget.session.get_variable("_last_result")
        assert stored is not None
        assert stored.equals(new_df)
        assert widget.session.get_variable("answer") == 7

    def test_python_series_result_updates_last_result(self, widget):
        """Python Series results are normalized so notifications can index them."""
        widget._process_next_in_queue = MagicMock()
        series = pd.Series([10, 20], name="value")

        widget._on_python_finished(series, "", "", {}, [])

        stored = widget.session.get_variable("_last_result")
        assert stored is not None
        assert isinstance(stored, pd.DataFrame)
        assert list(stored.columns) == ["value"]
        assert stored.iloc[1, 0] == 20
        assert widget._queue_last_rows == 2

    def test_python_chart_and_dataframe_updates_last_result(self, widget):
        """Chart-producing Python blocks still keep the tabular result for notifications."""
        widget._process_next_in_queue = MagicMock()
        df = pd.DataFrame({"value": [99]})

        widget._on_python_finished(df, "", "", {}, [object()])

        stored = widget.session.get_variable("_last_result")
        assert stored is not None
        assert stored.equals(df)
        assert widget._queue_last_rows == 1

    def test_python_notification_renders_result_reference(self, widget, qtbot):
        """Per-tab notifications render {{result[row][col]}} after Python execution."""
        widget.set_tab_notification_config({
            "enabled": True,
            "title": "{{tab_name}}",
            "message": "Value: {{result[0][0]}}",
            "color": "#1e8a3e",
        })
        df = pd.DataFrame({"value": [42]})

        with qtbot.waitSignal(widget.execution_finished, timeout=1000) as blocker:
            widget._on_python_finished(df, "", "", {}, [])
            widget._emit_queue_notification()

        assert blocker.args == ["TestTab", "Value: 42", True]

    def test_python_notification_uses_latest_result_across_consecutive_runs(self, widget, qtbot):
        """Consecutive Python executions update {{result[row][col]}} instead of reusing the first value."""
        widget.set_tab_notification_config({
            "enabled": True,
            "title": "{{tab_name}}",
            "message": "Value: {{result[0][0]}}",
            "color": "#1e8a3e",
        })
        first_df = pd.DataFrame({"value": [42]})
        second_df = pd.DataFrame({"value": [99]})

        with qtbot.waitSignal(widget.execution_finished, timeout=1000) as first_blocker:
            widget._on_python_finished(first_df, "", "", {"_last_result": first_df}, [])
            widget._emit_queue_notification()

        with qtbot.waitSignal(widget.execution_finished, timeout=1000) as second_blocker:
            widget._on_python_finished(second_df, "", "", {"_last_result": first_df}, [])
            widget._emit_queue_notification()

        assert first_blocker.args == ["TestTab", "Value: 42", True]
        assert second_blocker.args == ["TestTab", "Value: 99", True]

    def test_python_notification_rule_suppresses_delivery_but_keeps_signal(self, widget, qtbot):
        """Matching per-tab rules suppress delivery without breaking execution_finished."""
        widget.set_tab_notification_config({
            "enabled": True,
            "title": "{{tab_name}}",
            "message": "Status: {{result[0][0]}}",
            "rules": [
                {
                    "enabled": True,
                    "left": "{{result[0][0]}}",
                    "operator": "equals",
                    "value": "Active",
                    "action": "suppress",
                }
            ],
        })
        df = pd.DataFrame({"status": ["Active"]})

        with qtbot.waitSignal(widget.execution_finished, timeout=1000) as blocker:
            widget._on_python_finished(df, "", "", {}, [])
            widget._emit_queue_notification()

        assert blocker.args == ["TestTab", "Status: Active", True]
        assert widget._last_notification_delivery["suppressed"] is True
        assert widget._last_notification_delivery["send_external"] is False

    def test_python_notification_rule_can_override_color(self, widget, qtbot):
        """Matching color rules override the tab notification color without suppressing delivery."""
        widget.set_tab_notification_config({
            "enabled": True,
            "title": "{{tab_name}}",
            "message": "Status: {{result[0][0]}}",
            "color": "#1e8a3e",
            "rules": [
                {
                    "enabled": True,
                    "left": "{{result[0][0]}}",
                    "operator": "equals",
                    "value": "Alert",
                    "action": "set_color",
                    "action_value": "#ff0000",
                }
            ],
        })
        df = pd.DataFrame({"status": ["Alert"]})

        with qtbot.waitSignal(widget.execution_finished, timeout=1000) as blocker:
            widget._on_python_finished(df, "", "", {}, [])
            widget._emit_queue_notification()

        assert blocker.args == ["TestTab", "Status: Alert", True]
        assert widget._last_notification_delivery["suppressed"] is False
        assert widget._last_notification_delivery["send_external"] is True
        assert widget._last_notification_delivery["color"] == "#ff0000"

    def test_rule_evaluation_stops_on_first_suppress_match(self, widget):
        """Color rules may apply first, but evaluation stops once a suppress rule matches."""
        config = widget._normalize_tab_notification_config({
            "enabled": True,
            "rules": [
                {
                    "enabled": True,
                    "left": "Active",
                    "operator": "equals",
                    "value": "Active",
                    "action": "set_color",
                    "action_value": "#ff9900",
                },
                {
                    "enabled": True,
                    "left": "Active",
                    "operator": "equals",
                    "value": "Active",
                    "action": "suppress",
                },
                {
                    "enabled": True,
                    "left": "Active",
                    "operator": "contains",
                    "value": "Act",
                    "action": "suppress",
                },
            ],
        })

        result = widget._evaluate_tab_notification_rules(config, lambda value: value)

        assert result["matched"] is True
        assert result["suppress"] is True
        assert result["color"] == "#ff9900"
        assert result["rule"]["operator"] == "equals"


# ==================== DPW PERSISTENCE ====================


class TestDPWNotificationPersistence:
    """Test that notification config is saved/loaded from DPW files."""

    def _build_file_io_harness(self, notif_config, blocks_data=None):
        from src.ui.main_window._file_io import FileIOMixin

        widget = MagicMock()
        widget.editor.to_list.return_value = blocks_data or [
            {"language": "sql", "code": "SELECT 1", "height": 400, "block_name": "", "is_active": True}
        ]
        widget.get_tab_notification_config.return_value = notif_config
        widget.session = SimpleNamespace(file_path=None, original_file_type=None, title="Current Tab")
        widget.file_path = None
        widget._original_file_type = None
        widget._content_hash = ""
        widget._is_modified = True

        class _Harness(FileIOMixin):
            def __init__(self, current_widget):
                self._current_widget = current_widget
                self.session_tabs = MagicMock()
                self.session_tabs.indexOf.return_value = 0
                self.main_statusbar = MagicMock()

            def _get_current_session_widget(self):
                return self._current_widget

            def _compute_widget_content_hash(self, _widget):
                return "hash"

            def _update_window_title(self):
                return None

        return _Harness(widget), widget

    def test_save_tab_as_dpw_includes_notification_rules(self, tmp_path):
        """Real DPW save writes notification rules when tab config exists."""
        dpw_file = tmp_path / "test.dpw"
        notif_config = {
            "enabled": True,
            "title": "My Tab",
            "message": "{{result[0][0]}}",
            "rules": [
                {
                    "enabled": True,
                    "left": "{{result[0][0]}}",
                    "operator": "equals",
                    "value": "Active",
                    "action": "suppress",
                }
            ],
        }

        harness, widget = self._build_file_io_harness(notif_config)
        harness._save_tab_as_dpw(str(dpw_file))

        loaded = json.loads(dpw_file.read_text(encoding="utf-8"))
        assert "notification_config" in loaded
        assert loaded["notification_config"]["enabled"] is True
        assert loaded["notification_config"]["title"] == "My Tab"
        assert loaded["notification_config"]["message"] == "{{result[0][0]}}"
        assert loaded["notification_config"]["rules"][0]["action"] == "suppress"
        assert widget.file_path == str(dpw_file)

    def test_save_tab_as_dpw_preserves_disabled_notification_rules(self, tmp_path):
        """Real DPW save keeps tab notification rules even when notifications are disabled."""
        dpw_file = tmp_path / "test.dpw"
        notif_config = {
            "enabled": False,
            "title": "Disabled tab",
            "message": "Disabled msg",
            "rules": [
                {
                    "enabled": True,
                    "left": "{{result[0][0]}}",
                    "operator": "contains",
                    "value": "warn",
                    "action": "set_color",
                    "action_value": "#ffaa00",
                }
            ],
        }

        harness, _widget = self._build_file_io_harness(notif_config)
        harness._save_tab_as_dpw(str(dpw_file))

        loaded = json.loads(dpw_file.read_text(encoding="utf-8"))
        assert loaded["notification_config"]["enabled"] is False
        assert loaded["notification_config"]["rules"][0]["action"] == "set_color"
        assert loaded["notification_config"]["rules"][0]["action_value"] == "#ffaa00"

    def test_save_tab_as_dpw_omits_notification_config_when_tab_has_none(self, tmp_path):
        """Real DPW save omits notification config only when the tab has none at all."""
        dpw_file = tmp_path / "test.dpw"
        harness, _widget = self._build_file_io_harness(None)

        harness._save_tab_as_dpw(str(dpw_file))

        loaded = json.loads(dpw_file.read_text(encoding="utf-8"))
        assert "notification_config" not in loaded

    def test_open_code_file_restores_notification_rules_into_widget_and_session(self, tmp_path):
        """Opening a DPW file restores notification config into both widget and session model."""
        from src.ui.main_window._file_io import FileIOMixin

        dpw_file = tmp_path / "opened.dpw"
        dpw_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "blocks": [{"language": "sql", "code": "SELECT 1", "height": 400, "block_name": "", "is_active": True}],
                    "notification_config": {
                        "enabled": True,
                        "title": "Loaded Tab",
                        "message": "Loaded {{result[0][0]}}",
                        "rules": [
                            {
                                "enabled": True,
                                "left": "{{result[0][0]}}",
                                "operator": "equals",
                                "value": "1",
                                "action": "suppress",
                            }
                        ],
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        created = {}

        class _Harness(FileIOMixin):
            def __init__(self):
                self._original_file_type = None
                self._original_file_path = None
                self.connection_manager = MagicMock()
                self.connection_manager.get_connection_config.return_value = None
                self.session_manager = MagicMock()
                self.main_statusbar = MagicMock()
                self.recent_files_manager = MagicMock()
                self.session_tabs = MagicMock()
                self.session_tabs.indexOf.return_value = 0

            def _get_current_session_widget(self):
                return None

            def _hide_empty_state(self):
                return None

            def _create_session_widget(self, session):
                widget = MagicMock()
                widget.session = session
                widget.editor = MagicMock()
                widget.editor.from_list = MagicMock()
                widget.set_tab_notification_config = MagicMock(
                    side_effect=lambda config: setattr(widget, "_tab_notification_config", config) or setattr(session, "notification_config", config)
                )
                created["widget"] = widget
                return widget

            def _compute_widget_content_hash(self, _widget):
                return "hash"

            def _update_window_title(self):
                return None

            def _switch_session_panels(self, _session_id):
                return None

            def _update_recent_menu(self):
                return None

        harness = _Harness()
        session = SimpleNamespace(
            title="opened.dpw",
            notification_config=None,
            session_id="test-session",
            connection_name=None,
        )
        harness.session_manager.create_session.return_value = session

        harness._open_code_file(str(dpw_file))

        widget = created["widget"]
        assert widget._tab_notification_config is not None
        assert widget._tab_notification_config["rules"][0]["action"] == "suppress"
        assert session.notification_config is not None
        assert session.notification_config["title"] == "Loaded Tab"

    def test_load_restores_notification_config(self, tmp_path):
        """Loading DPW with notification_config restores it."""
        dpw_content = {
            "version": "1.0",
            "blocks": [],
            "notification_config": {
                "enabled": True,
                "title": "Loaded Title",
                "message": "Loaded Msg with {{result[0][1]}}",
                "rules": [
                    {
                        "enabled": True,
                        "left": "{{result[0][1]}}",
                        "operator": "equals",
                        "value": "Active",
                        "action": "suppress",
                    }
                ],
            },
        }
        dpw_file = tmp_path / "test.dpw"
        dpw_file.write_text(json.dumps(dpw_content, indent=2), encoding="utf-8")

        loaded = json.loads(dpw_file.read_text(encoding="utf-8"))
        config = loaded.get("notification_config")
        assert config is not None
        assert config["enabled"] is True
        assert config["title"] == "Loaded Title"
        assert "{{result[0][1]}}" in config["message"]
        assert config["rules"][0]["action"] == "suppress"

    def test_load_without_notification_config(self, tmp_path):
        """Loading DPW without notification_config gives None."""
        dpw_content = {
            "version": "1.0",
            "blocks": [],
        }
        dpw_file = tmp_path / "test.dpw"
        dpw_file.write_text(json.dumps(dpw_content, indent=2), encoding="utf-8")

        loaded = json.loads(dpw_file.read_text(encoding="utf-8"))
        config = loaded.get("notification_config")
        assert config is None
