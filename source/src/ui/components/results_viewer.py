"""
Visualizador de resultados em tabela
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableView,
    QLabel,
    QPushButton,
    QLineEdit,
    QToolBar,
    QDialog,
    QFormLayout,
    QComboBox,
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QStackedWidget,
    QScrollArea,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QSpinBox,
    QMenu,
    QAbstractButton,
    QTabWidget,
    QTabBar,
    QToolButton,
    QHeaderView,
    QFrame,
    QGridLayout,
    QAbstractItemView,
    QButtonGroup,
    QSplitter,
    QSizePolicy,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
)
from PyQt6.QtCore import Qt, QObject, QAbstractTableModel, QModelIndex, QVariant, QSettings, QTimer, QThread, pyqtSignal, QRect, QPoint, QSize, QSignalBlocker, QEvent
from PyQt6.QtGui import QColor, QImage, QPixmap, QFont, QKeySequence, QShortcut, QAction, QDoubleValidator, QPainter, QPen
import numpy as np
import pandas as pd
import io
import json
import time
from PyQt6 import sip
from dataclasses import dataclass
from datetime import date, datetime
from numbers import Integral, Real
from typing import Optional, Any
import re
import subprocess
import os
import qtawesome as qta

from src.design_system.app_dialogs import show_danger, show_warning
from src.core.theme_manager import ThemeManager
from src.language import S
from src.design_system.tokens import SCROLLBAR_STYLE
from src.workers import FileExportWorker
from src.ui.components.toggle_switch import LabeledToggleSwitch
from src.ui.components.plotly_chart_view import PlotlyChartView

GRID_ASYNC_ROW_THRESHOLD = 200
GRID_COLUMN_RESIZE_SAMPLE_ROWS = 50
GRID_COLUMN_MAX_WIDTH = 420
SUMMARIZE_MAX_EXPLICIT_CELLS = 5000
# Type detection on huge columns is sampled: converting 1M+ object values
# with pd.to_numeric just to discover the column type freezes everything.
GRID_TYPE_DETECTION_SAMPLE_ROWS = 10_000


class PreparedGridData:
    """Lazy display payload for the grid.

    Holds per-column Series/arrays and resolved format configs; cell text is
    produced on demand in display_value(). Qt only requests visible cells, so
    a 1M-row result costs no string materialization upfront (the old design
    pre-built len(df) x n_cols Python strings and froze the app).
    """

    __slots__ = (
        "columns",
        "column_values",
        "column_nulls",
        "column_format_configs",
        "numeric_column_indices",
        "row_count",
        "filtered_row_count",
        "total_row_count",
        "limited",
    )

    def __init__(
        self,
        columns: list[str],
        column_values: list,
        column_nulls: list,
        column_format_configs: list[dict],
        numeric_column_indices: frozenset[int],
        row_count: int,
        filtered_row_count: int,
        total_row_count: int,
        limited: bool,
    ):
        self.columns = columns
        self.column_values = column_values
        self.column_nulls = column_nulls
        self.column_format_configs = column_format_configs
        self.numeric_column_indices = numeric_column_indices
        self.row_count = row_count
        self.filtered_row_count = filtered_row_count
        self.total_row_count = total_row_count
        self.limited = limited

    def is_null(self, row: int, col: int) -> bool:
        nulls = self.column_nulls[col]
        if nulls is None:
            return False
        return bool(nulls[row])

    def display_value(self, row: int, col: int) -> str:
        if self.is_null(row, col):
            return "NULL"
        value = self.column_values[col].iat[row]
        return _grid_format_display_value(value, self.column_format_configs[col])


@dataclass
class GridPrepareResult:
    """Full grid refresh result including the filtered export dataframe."""

    prepared: PreparedGridData
    filtered_df: pd.DataFrame


def _grid_is_null_scalar(value) -> bool:
    try:
        if not pd.api.types.is_scalar(value):
            return False
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _dedupe_grid_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a frame with unique column names (pandas-style ``.1`` suffixes).

    A SQL result can have two columns with the same name; indexing such a frame
    by name returns a DataFrame (not a Series) and breaks the whole grid
    pipeline. We rename duplicates on a COPY so the caller's DataFrame (which
    may be a live namespace variable) is never mutated. No-op when unique.
    """
    if df is None or df.columns.empty:
        return df
    names = [str(c) for c in df.columns]
    if not df.columns.duplicated().any():
        return df
    seen: dict[str, int] = {}
    new_names: list[str] = []
    for name in names:
        if name in seen:
            seen[name] += 1
            new_names.append(f"{name}.{seen[name]}")
        else:
            seen[name] = 0
            new_names.append(name)
    out = df.copy()
    out.columns = new_names
    return out


def _grid_column_is_numeric(series: pd.Series) -> bool:
    """Detect numeric columns, including object columns with numeric strings."""
    # Defensive: duplicate column names can yield a DataFrame here; treat as
    # non-numeric rather than crashing pd.to_numeric.
    if isinstance(series, pd.DataFrame):
        return False
    if series is None or series.empty:
        return False
    if pd.api.types.is_numeric_dtype(series):
        return True
    if pd.api.types.is_bool_dtype(series):
        return False

    # Sample BEFORE dropna: a full dropna() on millions of object values is
    # itself a 100ms+ GIL-held pass per column.
    if len(series) > GRID_TYPE_DETECTION_SAMPLE_ROWS:
        non_null = series.head(GRID_TYPE_DETECTION_SAMPLE_ROWS).dropna()
        if non_null.empty:
            # Head was all-null; fall back to scanning for real values.
            non_null = series.dropna().head(GRID_TYPE_DETECTION_SAMPLE_ROWS)
    else:
        non_null = series.dropna()
    if non_null.empty:
        return False

    converted = pd.to_numeric(non_null, errors="coerce")
    numeric_count = int(converted.notna().sum())
    return numeric_count >= max(1, len(non_null) // 2)


def _grid_coerce_numeric_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series
    return pd.to_numeric(series, errors="coerce")


GRID_NULLMASK_CHUNK_ROWS = 200_000


def _grid_isna_chunked(series: pd.Series) -> "np.ndarray":
    """isna() in bounded slices with GIL yields.

    A single isna() over millions of object cells is one long C call that
    never releases the GIL and visibly stalls the UI thread.
    """
    n = len(series)
    if n <= GRID_NULLMASK_CHUNK_ROWS:
        return series.isna().to_numpy()
    parts = []
    for start in range(0, n, GRID_NULLMASK_CHUNK_ROWS):
        parts.append(series.iloc[start : start + GRID_NULLMASK_CHUNK_ROWS].isna().to_numpy())
        time.sleep(0.0005)
    return np.concatenate(parts)


def _grid_normalize_format_config(format_config) -> dict:
    if isinstance(format_config, dict):
        normalized = dict(format_config)
        normalized["type"] = str(normalized.get("type", "default") or "default")
        return normalized
    return {"type": str(format_config or "default")}


def _grid_format_decimals(format_config: dict, default: int = 2) -> int:
    try:
        decimals = int(format_config.get("decimals", default))
    except (TypeError, ValueError):
        decimals = default
    return max(0, min(decimals, 8))


_DATETIME_COLUMN_HINT = re.compile(
    r"(data|date|time|timestamp|created|updated|modified|evento|criacao|criado|nascimento)",
    re.IGNORECASE,
)


def _grid_column_name_suggests_datetime(column_name: str) -> bool:
    return bool(_DATETIME_COLUMN_HINT.search(str(column_name or "").strip()))


def _grid_epoch_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        if pd.isna(value):
            return None
        as_float = float(value)
        if not as_float.is_integer():
            return None
        if abs(as_float) > 9_007_199_254_740_992:
            return None
        return int(as_float)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            try:
                return int(stripped)
            except ValueError:
                return None
    return None


def _grid_parse_datetime_from_epoch_numeric(value: int) -> pd.Timestamp:
    abs_value = abs(int(value))
    if abs_value < 1_000_000_000:
        return pd.NaT

    units = ("ns", "us", "ms", "s")
    if abs_value >= 10**17:
        units = ("ns", "us", "ms", "s")
    elif abs_value >= 10**14:
        units = ("us", "ms", "s", "ns")
    elif abs_value >= 10**11:
        units = ("ms", "s", "us", "ns")
    else:
        units = ("s", "ms", "us", "ns")

    for unit in units:
        parsed = pd.to_datetime(value, unit=unit, errors="coerce")
        if pd.isna(parsed):
            continue
        if 1970 <= parsed.year <= 2100:
            return parsed
    return pd.NaT


def _grid_parse_datetime_value(value) -> pd.Timestamp:
    if value is None or (isinstance(value, Real) and not isinstance(value, bool) and pd.isna(value)):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value
    if isinstance(value, datetime):
        return pd.Timestamp(value)
    if isinstance(value, date):
        return pd.Timestamp(value)

    epoch_value = _grid_epoch_int(value)
    if epoch_value is not None:
        parsed = _grid_parse_datetime_from_epoch_numeric(epoch_value)
        if not pd.isna(parsed):
            return parsed

    parsed = pd.to_datetime(value, errors="coerce")
    if not pd.isna(parsed):
        return parsed
    return pd.NaT


def _grid_column_values_look_like_epoch(series: pd.Series) -> bool:
    if series is None or series.empty:
        return False

    checked = 0
    parsed = 0
    for value in series.dropna().head(25):
        epoch_value = _grid_epoch_int(value)
        if epoch_value is None:
            continue
        checked += 1
        if not pd.isna(_grid_parse_datetime_from_epoch_numeric(epoch_value)):
            parsed += 1

    return checked > 0 and parsed == checked


def _grid_should_auto_datetime_format(column_name: str, series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if not _grid_column_is_numeric(series):
        return False
    if not _grid_column_name_suggests_datetime(column_name):
        return False
    return _grid_column_values_look_like_epoch(series)


def _grid_resolve_display_format(column_name: str, series: pd.Series, format_config) -> dict:
    config = _grid_normalize_format_config(format_config)
    if config.get("type") != "default":
        return config
    if _grid_should_auto_datetime_format(column_name, series):
        return {"type": "datetime"}
    return config


def _grid_format_datetime_value(value, format_name: str) -> str:
    parsed = _grid_parse_datetime_value(value)
    if pd.isna(parsed):
        return str(value)
    pattern = "%Y-%m-%d" if format_name == "date" else "%Y-%m-%d %H:%M:%S"
    return parsed.strftime(pattern)


def _grid_format_display_value(value, format_config) -> str:
    config = _grid_normalize_format_config(format_config)
    format_name = config.get("type", "default")
    if format_name == "default":
        if isinstance(value, (pd.Timestamp, datetime, date)):
            return _grid_format_datetime_value(value, "datetime")
        return str(value)
    if format_name in {"number", "currency"}:
        number = pd.to_numeric(value, errors="coerce")
        if pd.isna(number):
            return str(value)
        decimals = _grid_format_decimals(config)
        prefix = str(config.get("prefix", "$ " if format_name == "currency" else ""))
        suffix = str(config.get("suffix", ""))
        return f"{prefix}{float(number):,.{decimals}f}{suffix}"
    if format_name == "percent":
        number = pd.to_numeric(value, errors="coerce")
        decimals = _grid_format_decimals(config)
        return str(value) if pd.isna(number) else f"{float(number):.{decimals}%}"
    if format_name in {"date", "datetime"}:
        return _grid_format_datetime_value(value, format_name)
    return str(value)


def _grid_normalize_filter_spec(value: Any) -> dict:
    if isinstance(value, dict):
        spec = dict(value)
        spec["type"] = str(spec.get("type", "text") or "text")
        return spec
    return {"type": "text", "operator": "contains", "value": str(value or "")}


def _grid_filter_spec_is_empty(spec: dict) -> bool:
    filter_type = str(spec.get("type", "text"))
    if filter_type == "number":
        return not str(spec.get("min", "")).strip() and not str(spec.get("max", "")).strip()
    if filter_type == "bool":
        return spec.get("value") in (None, "", "any")
    if filter_type == "date":
        return not str(spec.get("start", "")).strip() and not str(spec.get("end", "")).strip()
    return not str(spec.get("value", "")).strip()


def _grid_parse_float(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _grid_parse_bool_value(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "sim", "s"}:
        return True
    if text in {"0", "false", "f", "no", "n", "nao"}:
        return False
    return None


def _grid_column_filter_mask(df: pd.DataFrame, column, spec: dict):
    filter_type = str(spec.get("type", "text"))
    if filter_type == "number":
        values = pd.to_numeric(df[column], errors="coerce")
        mask = pd.Series(True, index=df.index)
        min_value = _grid_parse_float(spec.get("min"))
        max_value = _grid_parse_float(spec.get("max"))
        if min_value is not None:
            mask = mask & values.ge(min_value)
        if max_value is not None:
            mask = mask & values.le(max_value)
        return mask.fillna(False)
    if filter_type == "bool":
        desired = _grid_parse_bool_value(spec.get("value"))
        if desired is None:
            return pd.Series(True, index=df.index)
        values = df[column].map(_grid_parse_bool_value)
        return values.eq(desired).fillna(False)
    if filter_type == "date":
        values = pd.to_datetime(df[column], errors="coerce")
        mask = pd.Series(True, index=df.index)
        start = pd.to_datetime(spec.get("start"), errors="coerce") if str(spec.get("start", "")).strip() else None
        end = pd.to_datetime(spec.get("end"), errors="coerce") if str(spec.get("end", "")).strip() else None
        if start is not None and not pd.isna(start):
            mask = mask & values.ge(start)
        if end is not None and not pd.isna(end):
            mask = mask & values.le(end)
        return mask.fillna(False)

    value = str(spec.get("value", "")).strip()
    operator = str(spec.get("operator", "contains") or "contains")
    values = df[column].astype("string").fillna("")
    if operator == "equals":
        return values.str.lower().eq(value.lower())
    if operator == "starts_with":
        return values.str.lower().str.startswith(value.lower(), na=False)
    if operator == "ends_with":
        return values.str.lower().str.endswith(value.lower(), na=False)
    return values.str.contains(value, case=False, regex=False, na=False)


def filter_dataframe_with_specs(df: pd.DataFrame, column_filters: dict) -> pd.DataFrame:
    """Filter a DataFrame using active column filter specs."""
    if df is None:
        return pd.DataFrame()
    active_column_filters = [
        (column, _grid_normalize_filter_spec(value))
        for column, value in (column_filters or {}).items()
        if column in df.columns and not _grid_filter_spec_is_empty(_grid_normalize_filter_spec(value))
    ]
    if not active_column_filters:
        return df

    mask = pd.Series(True, index=df.index)
    for column, spec in active_column_filters:
        mask = mask & _grid_column_filter_mask(df, column, spec)
    return df.loc[mask]


def prepare_grid_data(
    source_df: pd.DataFrame,
    column_filters: dict,
    column_formats: dict,
    limit: int,
) -> GridPrepareResult:
    """Build the lazy grid payload. Safe to run off the UI thread.

    Only vectorized per-column work happens here (filter, numeric coercion,
    null masks). Cell text is NOT materialized — PreparedGridData formats
    visible cells on demand, so 1M+ rows stay cheap in time and memory.
    """
    if source_df is None:
        empty = pd.DataFrame()
        prepared = PreparedGridData([], [], [], [], frozenset(), 0, 0, 0, False)
        return GridPrepareResult(prepared, empty)

    total_rows = len(source_df)
    filtered_df = filter_dataframe_with_specs(source_df, column_filters)
    # Make column names unique so name-based access returns Series, not a
    # DataFrame (two columns with the same name otherwise crashes the grid).
    filtered_df = _dedupe_grid_columns(filtered_df)
    filtered_count = len(filtered_df)
    limited = filtered_count > limit
    display_df = filtered_df.head(limit) if limited else filtered_df

    columns = [str(column) for column in display_df.columns]
    format_map = dict(column_formats or {})

    column_values: list = []
    column_nulls: list = []
    column_format_configs: list[dict] = []
    numeric_indices: set[int] = set()

    for col_index, column in enumerate(columns):
        series = display_df[column]
        format_config = _grid_resolve_display_format(
            column,
            series,
            format_map.get(column, format_map.get(str(column), "default")),
        )
        format_type = format_config.get("type", "default")
        use_raw_values = format_type in {"date", "datetime"} or pd.api.types.is_datetime64_any_dtype(series)
        is_numeric = _grid_column_is_numeric(series)

        if is_numeric and not use_raw_values:
            values = _grid_coerce_numeric_series(series)
        else:
            values = series

        column_values.append(values)
        try:
            column_nulls.append(_grid_isna_chunked(values))
        except (TypeError, ValueError):
            column_nulls.append(None)
        column_format_configs.append(format_config)

        if is_numeric and format_type not in {"date", "datetime"}:
            numeric_indices.add(col_index)

        # Yield the GIL between columns: isna()/to_numeric on 1M-row object
        # columns are single C calls that would otherwise stack into one
        # long UI-starving stretch.
        if len(display_df) > GRID_TYPE_DETECTION_SAMPLE_ROWS:
            time.sleep(0.001)

    prepared = PreparedGridData(
        columns=columns,
        column_values=column_values,
        column_nulls=column_nulls,
        column_format_configs=column_format_configs,
        numeric_column_indices=frozenset(numeric_indices),
        row_count=len(display_df),
        filtered_row_count=filtered_count,
        total_row_count=total_rows,
        limited=limited,
    )
    return GridPrepareResult(prepared, filtered_df)


class GridPrepareWorker(QObject):
    """Prepare large grid payloads outside the UI thread."""

    finished = pyqtSignal(int, object)
    error = pyqtSignal(int, str)

    def __init__(
        self,
        job_id: int,
        source_df: pd.DataFrame,
        column_filters: dict,
        column_formats: dict,
        limit: int,
    ):
        super().__init__()
        self._job_id = job_id
        self._source_df = source_df
        self._column_filters = dict(column_filters or {})
        self._column_formats = dict(column_formats or {})
        self._limit = int(limit)

    def run(self):
        try:
            result = prepare_grid_data(
                self._source_df,
                self._column_filters,
                self._column_formats,
                self._limit,
            )
            self.finished.emit(self._job_id, result)
        except Exception as exc:
            self.error.emit(self._job_id, str(exc))


class ChartRenderWorker(QObject):
    """Renderiza graficos Plotly (HTML) fora da thread da UI."""

    finished = pyqtSignal(object, int, object)  # page_key, generation, image bytes
    error = pyqtSignal(object, int, str)
    done = pyqtSignal(object, int)

    def __init__(self, page_key: int, generation: int, df: pd.DataFrame, config: dict, renderer):
        super().__init__()
        self._page_key = page_key
        self._generation = generation
        self._df = df
        self._config = dict(config or {})
        self._renderer = renderer

    def run(self):
        try:
            image_bytes = self._renderer(self._df, self._config)
            self.finished.emit(self._page_key, self._generation, image_bytes)
        except Exception as exc:
            self.error.emit(self._page_key, self._generation, str(exc))
        finally:
            self.done.emit(self._page_key, self._generation)


class ResultGridHeader(QHeaderView):
    """Header com alvo visual de menu por coluna."""

    menuRequested = pyqtSignal(int, object)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._hovered_section = -1
        self.setSectionsClickable(True)
        self.setMouseTracking(True)

    def _menu_rect(self, section: int):
        x = self.sectionViewportPosition(section) + self.sectionSize(section) - 24
        return QRect(x, 0, 24, self.height())

    def _set_hovered_section(self, section: int):
        if self._hovered_section == section:
            return
        self._hovered_section = section
        self.viewport().update()

    def is_menu_button_visible(self, section: int) -> bool:
        return self._hovered_section == section

    def paintSection(self, painter, rect, logicalIndex):
        super().paintSection(painter, rect, logicalIndex)
        if self.orientation() != Qt.Orientation.Horizontal or logicalIndex < 0:
            return
        if not self.is_menu_button_visible(logicalIndex):
            return

        menu_rect = rect.adjusted(rect.width() - 22, 0, -4, 0)
        center_x = menu_rect.center().x()
        center_y = menu_rect.center().y()
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#858585"))
        for offset in (-4, 0, 4):
            painter.drawEllipse(center_x - 1, center_y + offset - 1, 2, 2)
        painter.restore()

    def mousePressEvent(self, event):
        if self.orientation() == Qt.Orientation.Horizontal:
            section = self.logicalIndexAt(event.position().toPoint())
            if section >= 0 and self._menu_rect(section).contains(event.position().toPoint()):
                self.menuRequested.emit(section, self.mapToGlobal(event.position().toPoint()))
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        section = self.logicalIndexAt(event.position().toPoint())
        if section >= 0:
            self._set_hovered_section(section)
            if self._menu_rect(section).contains(event.position().toPoint()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()
        else:
            self._set_hovered_section(-1)
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._set_hovered_section(-1)
        self.unsetCursor()
        super().leaveEvent(event)


class ResultTabBar(QTabBar):
    """Result tabs with a painted close control matching the main editor tabs."""

    closeRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered_close_index = -1
        self._pressed_close_index = -1
        self._connection_color = ""
        self.setMouseTracking(True)

    def set_connection_color(self, color: str):
        self._connection_color = str(color or "").strip()
        self.update()

    def clear_connection_color(self):
        self._connection_color = ""
        self.update()

    def _close_button_rect(self, index: int) -> QRect:
        if index < 0 or index >= self.count():
            return QRect()
        from src.design_system.tab_controls import tab_close_rect
        return tab_close_rect(self.tabRect(index))

    def _close_index_at(self, pos: QPoint) -> int:
        index = self.tabAt(pos)
        if index < 0:
            return -1
        return index if self._close_button_rect(index).contains(pos) else -1

    def paintEvent(self, event):
        super().paintEvent(event)
        from src.design_system.tab_controls import paint_tab_close_control
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_connection_indicator(painter)
        for index in range(self.count()):
            paint_tab_close_control(
                painter,
                self._close_button_rect(index),
                hovered=index == self._hovered_close_index,
            )

    def _paint_connection_indicator(self, painter: QPainter):
        color = QColor(self._connection_color)
        if not color.isValid():
            return
        pen = QPen(color)
        pen.setWidth(3)
        painter.setPen(pen)
        for index in range(self.count()):
            rect = self.tabRect(index)
            if rect.isValid():
                painter.drawLine(rect.left() + 2, rect.bottom() - 1, rect.right() - 2, rect.bottom() - 1)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        hovered = self._close_index_at(pos)
        if hovered != self._hovered_close_index:
            old_index = self._hovered_close_index
            self._hovered_close_index = hovered
            if old_index >= 0:
                self.update(self._close_button_rect(old_index))
            if hovered >= 0:
                self.update(self._close_button_rect(hovered))
        if hovered >= 0:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            close_index = self._close_index_at(event.position().toPoint())
            if close_index >= 0:
                self._pressed_close_index = close_index
                event.accept()
                return
        self._pressed_close_index = -1
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed_close_index >= 0:
            close_index = self._close_index_at(event.position().toPoint())
            if close_index == self._pressed_close_index:
                self.closeRequested.emit(close_index)
                self._pressed_close_index = -1
                event.accept()
                return
        self._pressed_close_index = -1
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        old_index = self._hovered_close_index
        self._hovered_close_index = -1
        self._pressed_close_index = -1
        self.unsetCursor()
        if old_index >= 0:
            self.update(self._close_button_rect(old_index))
        super().leaveEvent(event)


class CSVExportDialog(QDialog):
    """Dialog to configure CSV export"""

    def __init__(self, parent=None, theme_manager: ThemeManager = None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self.setWindowTitle(S.csv_export.dialog_title)
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        from src.design_system.frameless_dialog import install_frameless_shell
        from src.design_system.button import PrimaryButton, SecondaryButton
        from src.design_system.tokens import apply_combobox_style

        layout = install_frameless_shell(
            self,
            S.csv_export.dialog_title,
            min_width=420,
            min_height=260,
            content_margins=(16, 12, 16, 14),
            content_spacing=12,
        )

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItem(S.csv_export.delimiter_semicolon, ";")
        self.delimiter_combo.addItem(S.csv_export.delimiter_comma, ",")
        self.delimiter_combo.addItem(S.csv_export.delimiter_tab, "\t")
        self.delimiter_combo.addItem(S.csv_export.delimiter_pipe, "|")
        apply_combobox_style(self.delimiter_combo)
        form.addRow(S.csv_export.label_delimiter, self.delimiter_combo)

        self.encoding_combo = QComboBox()
        self.encoding_combo.addItem(S.csv_export.encoding_utf8bom, "utf-8-sig")
        self.encoding_combo.addItem(S.csv_export.encoding_utf8, "utf-8")
        self.encoding_combo.addItem(S.csv_export.encoding_latin1, "latin-1")
        self.encoding_combo.addItem(S.csv_export.encoding_cp1252, "cp1252")
        apply_combobox_style(self.encoding_combo)
        form.addRow(S.csv_export.label_encoding, self.encoding_combo)

        self.header_check = QCheckBox()
        self.header_check.setChecked(True)
        form.addRow(S.csv_export.label_include_header, self.header_check)

        self.open_folder_check = QCheckBox()
        self.open_folder_check.setChecked(True)
        form.addRow(S.csv_export.label_open_folder, self.open_folder_check)

        layout.addLayout(form)

        bar = QHBoxLayout()
        bar.addStretch()
        btn_ok = PrimaryButton(S.dialogs.btn_ok, size="sm")
        btn_cancel = SecondaryButton(S.dialogs.btn_cancel, size="sm")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        bar.addWidget(btn_ok)
        bar.addWidget(btn_cancel)
        layout.addLayout(bar)

    def _load_settings(self):
        """Load saved settings"""
        settings = QSettings("DataPyn", "CSVExport")

        # Delimiter
        delimiter = settings.value("delimiter", ";")
        index = self.delimiter_combo.findData(delimiter)
        if index >= 0:
            self.delimiter_combo.setCurrentIndex(index)

        # Encoding
        encoding = settings.value("encoding", "utf-8-sig")
        index = self.encoding_combo.findData(encoding)
        if index >= 0:
            self.encoding_combo.setCurrentIndex(index)

        # Header
        header = settings.value("header", True, type=bool)
        self.header_check.setChecked(header)

        # Open folder
        open_folder = settings.value("open_folder", True, type=bool)
        self.open_folder_check.setChecked(open_folder)

    def _save_settings(self):
        """Save settings"""
        settings = QSettings("DataPyn", "CSVExport")
        settings.setValue("delimiter", self.get_delimiter())
        settings.setValue("encoding", self.get_encoding())
        settings.setValue("header", self.get_include_header())
        settings.setValue("open_folder", self.get_open_folder())

    def accept(self):
        """Save settings when accepting"""
        self._save_settings()
        super().accept()

    def get_delimiter(self) -> str:
        return self.delimiter_combo.currentData()

    def get_encoding(self) -> str:
        return self.encoding_combo.currentData()

    def get_include_header(self) -> bool:
        return self.header_check.isChecked()

    def get_open_folder(self) -> bool:
        return self.open_folder_check.isChecked()


class ExportSettingsDialog(QDialog):
    """Dialog for global export settings"""

    SETTINGS_KEY = "DataPyn/ExportSettings"

    def __init__(self, parent=None, theme_manager: ThemeManager = None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self.setWindowTitle(S.export_settings.dialog_title)
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        from src.design_system.frameless_dialog import install_frameless_shell
        from src.design_system.button import PrimaryButton, SecondaryButton
        from src.design_system.tokens import get_combobox_stylesheet, get_dialog_base_stylesheet

        layout = install_frameless_shell(
            self,
            S.export_settings.dialog_title,
            min_width=400,
            min_height=220,
            content_margins=(16, 12, 16, 14),
            content_spacing=12,
            body_stylesheet_extra=get_dialog_base_stylesheet(),
        )
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        combo_style = get_combobox_stylesheet()

        self.copy_sep_combo = QComboBox()
        self.copy_sep_combo.setStyleSheet(combo_style)
        self.copy_sep_combo.addItem(S.export_settings.copy_sep_tab, "\t")
        self.copy_sep_combo.addItem(S.export_settings.copy_sep_comma, ",")
        self.copy_sep_combo.addItem(S.export_settings.copy_sep_semicolon, ";")
        form.addRow(S.export_settings.label_copy_with_tab, self.copy_sep_combo)

        self.null_combo = QComboBox()
        self.null_combo.setStyleSheet(combo_style)
        self.null_combo.addItem(S.export_settings.null_empty, "")
        self.null_combo.addItem(S.export_settings.null_text, "NULL")
        self.null_combo.addItem(S.export_settings.null_none, "None")
        form.addRow(S.export_settings.label_null_display, self.null_combo)

        self.open_folder_check = QCheckBox()
        self.open_folder_check.setChecked(True)
        form.addRow(S.export_settings.label_open_folder, self.open_folder_check)

        layout.addLayout(form)

        bar = QHBoxLayout()
        bar.addStretch()
        btn_ok = PrimaryButton("OK", size="sm")
        btn_cancel = SecondaryButton("Cancel", size="sm")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        bar.addWidget(btn_ok)
        bar.addWidget(btn_cancel)
        layout.addLayout(bar)

    def _load_settings(self):
        settings = QSettings("DataPyn", "ExportSettings")

        sep = settings.value("copy_separator", "\t")
        idx = self.copy_sep_combo.findData(sep)
        if idx >= 0:
            self.copy_sep_combo.setCurrentIndex(idx)

        null_val = settings.value("null_display", "")
        idx = self.null_combo.findData(null_val)
        if idx >= 0:
            self.null_combo.setCurrentIndex(idx)

        self.open_folder_check.setChecked(settings.value("open_folder", True, type=bool))

    def _save_settings(self):
        settings = QSettings("DataPyn", "ExportSettings")
        settings.setValue("copy_separator", self.copy_sep_combo.currentData())
        settings.setValue("null_display", self.null_combo.currentData())
        settings.setValue("open_folder", self.open_folder_check.isChecked())

    def accept(self):
        self._save_settings()
        super().accept()

    @staticmethod
    def get_settings() -> dict:
        """Read current export settings without opening the dialog."""
        settings = QSettings("DataPyn", "ExportSettings")
        return {
            "copy_separator": settings.value("copy_separator", "\t"),
            "null_display": settings.value("null_display", ""),
            "open_folder": settings.value("open_folder", True, type=bool),
        }


class NumberFormatDialog(QDialog):
    """Dialog compacto para formato numerico customizado."""

    def __init__(self, format_type: str, initial: dict = None, parent=None, theme_manager: ThemeManager = None):
        super().__init__(parent)
        self._format_type = format_type
        self._initial = dict(initial or {})
        self.theme_manager = theme_manager or ThemeManager()
        self.setWindowTitle(S.results.format_custom_title)
        self.setMinimumWidth(320)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(0, 8)
        try:
            decimals = int(self._initial.get("decimals", 2))
        except (TypeError, ValueError):
            decimals = 2
        self.decimals_spin.setValue(max(0, min(decimals, 8)))
        form.addRow(S.results.format_label_decimals, self.decimals_spin)

        self.prefix_edit = QLineEdit(str(self._initial.get("prefix", "$ " if self._format_type == "currency" else "")))
        form.addRow(S.results.format_label_prefix, self.prefix_edit)

        self.suffix_edit = QLineEdit(str(self._initial.get("suffix", "")))
        form.addRow(S.results.format_label_suffix, self.suffix_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())

    def get_format_config(self) -> dict:
        return {
            "type": self._format_type,
            "decimals": self.decimals_spin.value(),
            "prefix": self.prefix_edit.text(),
            "suffix": self.suffix_edit.text(),
        }


class VisualizationEditorDialog(QDialog):
    """Editor das configuracoes de graficos da sessao com pre-visualizacao."""

    def __init__(
        self,
        df: pd.DataFrame = None,
        config: dict = None,
        parent=None,
        theme_manager: ThemeManager = None,
        render_fn=None,
    ):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self._render_fn = render_fn
        self._df = df
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._columns = [str(column) for column in df.columns] if df is not None else []
        self._numeric_columns = [
            str(column)
            for column in df.columns
            if df is not None and pd.api.types.is_numeric_dtype(df[column])
        ]
        self._config = dict(config or {})
        self._y_column_combos = []
        self._preview_shutdown = False
        self._preview_error_log = ""
        self.setObjectName("visualizationEditorDialog")
        self.setWindowTitle(S.visualization.editor_title)
        flags = self.windowFlags() | Qt.WindowType.CustomizeWindowHint
        flags |= Qt.WindowType.Dialog
        flags |= Qt.WindowType.WindowTitleHint
        flags |= Qt.WindowType.WindowSystemMenuHint
        flags |= Qt.WindowType.WindowCloseButtonHint
        flags &= ~Qt.WindowType.WindowMinimizeButtonHint
        flags &= ~Qt.WindowType.WindowMaximizeButtonHint
        flags &= ~Qt.WindowType.WindowMinMaxButtonsHint
        self.setWindowFlags(flags)
        self.setMinimumSize(920, 640)
        self.resize(1000, 700)
        self._setup_ui()

    def _shutdown_preview(self) -> None:
        if self._preview_shutdown:
            return
        self._preview_shutdown = True
        self._preview_timer.stop()
        try:
            self._preview_timer.timeout.disconnect(self._refresh_preview)
        except (TypeError, RuntimeError):
            pass
        preview = getattr(self, "preview_chart", None)
        if preview is not None:
            preview.cleanup()

    def accept(self):
        self._shutdown_preview()
        super().accept()

    def reject(self):
        self._shutdown_preview()
        super().reject()

    def done(self, result: int):
        self._shutdown_preview()
        super().done(result)

    def closeEvent(self, event):
        self._shutdown_preview()
        super().closeEvent(event)

    def _wrap_tab_scroll(self, tab: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(tab)
        scroll.setStyleSheet(SCROLLBAR_STYLE)
        return scroll

    def _tab_layout(self, tab: QWidget) -> QVBoxLayout:
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)
        return layout

    def _form_layout(self) -> QFormLayout:
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return form

    def _column_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem(S.visualization.choose_column, "")
        for column in self._columns:
            combo.addItem(column, column)
        return combo

    def _set_combo_value(self, combo: QComboBox, value: Any):
        index = combo.findData(str(value or ""))
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _color_edit(self, key: str, object_name: str) -> QLineEdit:
        edit = QLineEdit(str(self._config.get(key, "") or ""))
        edit.setObjectName(object_name)
        edit.setPlaceholderText(S.visualization.color_placeholder)
        return edit

    def _default_x_column(self) -> str:
        configured = str(self._config.get("x_column", "") or "")
        if configured in self._columns:
            return configured
        for column in self._columns:
            if column not in self._numeric_columns:
                return column
        return ""

    def _default_y_columns(self) -> list:
        configured = [str(column) for column in self._config.get("y_columns", []) or []]
        valid = [column for column in configured if column in self._columns]
        if valid:
            return valid

        x_column = self._default_x_column()
        for column in self._numeric_columns:
            if column != x_column:
                return [column]
        for column in self._columns:
            if column != x_column:
                return [column]
        return self._columns[:1]

    def _setup_ui(self):
        from src.design_system.tokens import get_colors
        colors = get_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(14)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel(S.visualization.editor_title)
        title.setObjectName("visualizationTitle")
        header.addWidget(title)
        subtitle = QLabel(S.visualization.editor_subtitle)
        subtitle.setObjectName("visualizationSubtitle")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addLayout(header)

        type_form = self._form_layout()
        self.type_combo = QComboBox()
        self.type_combo.addItem(qta.icon("mdi.chart-bar", color=colors.info), S.visualization.type_bar, "bar")
        self.type_combo.addItem(qta.icon("mdi.chart-line", color=colors.info), S.visualization.type_line, "line")
        self.type_combo.addItem(qta.icon("mdi.chart-scatter-plot", color=colors.info), S.visualization.type_scatter, "scatter")
        self.type_combo.addItem(qta.icon("mdi.chart-areaspline", color=colors.info), S.visualization.type_area, "area")
        self.type_combo.addItem(qta.icon("mdi.chart-pie", color=colors.info), S.visualization.type_pie, "pie")
        self._set_combo_value(self.type_combo, self._config.get("type", "bar"))
        type_form.addRow(S.visualization.label_type, self.type_combo)
        layout.addLayout(type_form)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("visualizationSplitter")

        settings_host = QWidget()
        settings_layout = QVBoxLayout(settings_host)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(0)

        nav = QListWidget()
        nav.setObjectName("visualizationSectionNav")
        nav.setFixedWidth(152)
        nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.settings_stack = QStackedWidget()
        self.settings_stack.setObjectName("visualizationSettingsStack")
        sections = [
            ("mdi.tune", S.visualization.tab_general, self._create_general_tab()),
            ("mdi.axis-x-arrow", S.visualization.tab_x_axis, self._create_x_axis_tab()),
            ("mdi.axis-y-arrow", S.visualization.tab_y_axis, self._create_y_axis_tab()),
            ("mdi.chart-multiple", S.visualization.tab_series, self._create_series_tab()),
            ("mdi.palette", S.visualization.tab_colors, self._create_colors_tab()),
            ("mdi.brush", S.visualization.tab_style, self._create_style_tab()),
            ("mdi.label", S.visualization.tab_data_labels, self._create_data_labels_tab()),
        ]
        for icon_name, label, tab in sections:
            nav.addItem(QListWidgetItem(qta.icon(icon_name, color=colors.text_secondary), label))
            self.settings_stack.addWidget(self._wrap_tab_scroll(tab))
        nav.setCurrentRow(0)
        nav.currentRowChanged.connect(self.settings_stack.setCurrentIndex)

        settings_row = QHBoxLayout()
        settings_row.setContentsMargins(0, 0, 0, 0)
        settings_row.setSpacing(12)
        settings_row.addWidget(nav)
        settings_row.addWidget(self.settings_stack, 1)
        settings_layout.addLayout(settings_row)
        self._section_nav = nav
        splitter.addWidget(settings_host)

        preview_host = QFrame()
        preview_host.setObjectName("visualizationPreviewPanel")
        preview_layout = QVBoxLayout(preview_host)
        preview_layout.setContentsMargins(16, 14, 16, 14)
        preview_layout.setSpacing(10)

        preview_heading = QLabel(S.visualization.preview_title)
        preview_heading.setObjectName("visualizationPreviewTitle")
        preview_layout.addWidget(preview_heading)

        self.preview_chart = PlotlyChartView()
        self.preview_chart.setObjectName("visualizationPreviewChart")
        self.preview_chart.setMinimumSize(360, 300)
        preview_layout.addWidget(self.preview_chart, 1)

        self.preview_status = QLabel()
        self.preview_status.setObjectName("visualizationPreviewStatus")
        self.preview_status.setWordWrap(True)
        self.preview_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_status.hide()
        preview_layout.addWidget(self.preview_status)

        self.preview_error_panel = QFrame()
        self.preview_error_panel.setObjectName("visualizationPreviewErrorPanel")
        error_layout = QVBoxLayout(self.preview_error_panel)
        error_layout.setContentsMargins(0, 0, 0, 0)
        error_layout.setSpacing(8)

        error_header = QHBoxLayout()
        error_header.setSpacing(8)
        self.preview_error_summary = QLabel()
        self.preview_error_summary.setObjectName("visualizationPreviewErrorSummary")
        self.preview_error_summary.setWordWrap(True)
        error_header.addWidget(self.preview_error_summary, 1)

        self.preview_copy_error_btn = QToolButton()
        self.preview_copy_error_btn.setObjectName("visualizationPreviewCopyErrorButton")
        self.preview_copy_error_btn.setIcon(qta.icon("mdi.content-copy", color=colors.text_secondary, scale_factor=0.85))
        self.preview_copy_error_btn.setToolTip(S.visualization.preview_copy_error)
        self.preview_copy_error_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_copy_error_btn.clicked.connect(self._copy_preview_error_log)
        error_header.addWidget(self.preview_copy_error_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        error_layout.addLayout(error_header)

        self.preview_error_text = QTextEdit()
        self.preview_error_text.setObjectName("visualizationPreviewErrorText")
        self.preview_error_text.setReadOnly(True)
        self.preview_error_text.setMaximumHeight(140)
        self.preview_error_text.setStyleSheet(
            f"background-color: {colors.bg_primary}; color: {colors.text_secondary};"
            f"border: 1px solid {colors.border_muted}; border-radius: 6px; font-size: 11px;"
        )
        error_layout.addWidget(self.preview_error_text)
        self.preview_error_panel.hide()
        preview_layout.addWidget(self.preview_error_panel)

        splitter.addWidget(preview_host)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([480, 400])
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
            }}
            QLabel#visualizationTitle {{
                color: {colors.text_primary};
                font-size: 20px;
                font-weight: 700;
            }}
            QLabel#visualizationSubtitle {{
                color: {colors.text_secondary};
                font-size: 12px;
            }}
            QLabel#visualizationPreviewTitle {{
                color: {colors.text_primary};
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#visualizationPreviewStatus {{
                color: {colors.text_secondary};
                font-size: 11px;
            }}
            QLabel#visualizationPreviewErrorSummary {{
                color: {colors.text_secondary};
                font-size: 11px;
            }}
            QFrame#visualizationPreviewErrorPanel {{
                background: transparent;
            }}
            QFrame#visualizationPreviewPanel {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_muted};
                border-radius: 8px;
            }}
            QLabel {{
                color: {colors.text_primary};
                font-size: 12px;
            }}
            QListWidget#visualizationSectionNav {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_muted};
                border-radius: 8px;
                padding: 6px 4px;
                outline: none;
            }}
            QListWidget#visualizationSectionNav::item {{
                color: {colors.text_secondary};
                border-radius: 6px;
                padding: 10px 12px;
                margin: 2px 4px;
                font-size: 12px;
                font-weight: 600;
            }}
            QListWidget#visualizationSectionNav::item:selected {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
            }}
            QListWidget#visualizationSectionNav::item:hover:!selected {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
            }}
            QStackedWidget#visualizationSettingsStack {{
                background-color: {colors.bg_primary};
                border: 1px solid {colors.border_muted};
                border-radius: 8px;
            }}
            QComboBox, QLineEdit, QSpinBox {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 6px;
                padding: 8px 10px;
                min-height: 22px;
            }}
            QComboBox:hover, QLineEdit:focus, QSpinBox:focus {{
                border-color: {colors.interactive_primary};
            }}
            QPushButton, QToolButton {{
                background: transparent;
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 6px;
                padding: 7px 11px;
            }}
            QPushButton:hover, QToolButton:hover {{
                background-color: {colors.bg_tertiary};
                border-color: {colors.interactive_primary};
            }}
            QCheckBox {{
                color: {colors.text_primary};
                spacing: 8px;
            }}
            QDialogButtonBox QPushButton {{
                min-width: 88px;
            }}
        """)
        self._connect_preview_signals()
        if self._render_fn is not None and self._df is not None:
            self._schedule_preview()
        elif self._render_fn is None:
            self.preview_status.setText(S.visualization.chart_pending)
            self.preview_status.show()

    def _connect_preview_signals(self):
        if self._render_fn is None:
            return

        def bind(widget):
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._schedule_preview)
            elif isinstance(widget, (QLineEdit, QTextEdit)):
                widget.textChanged.connect(self._schedule_preview)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._schedule_preview)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._schedule_preview)
            elif isinstance(widget, LabeledToggleSwitch):
                widget.toggled.connect(self._schedule_preview)

        for widget in (
            self.type_combo,
            self.title_edit,
            self.x_combo,
            self.x_label_edit,
            self.sort_combo,
            self.y_label_edit,
            self.aggregation_combo,
            self.group_combo,
            self.stacking_combo,
            self.nulls_combo,
            self.palette_combo,
            self.custom_colors_edit,
            self.text_color_edit,
            self.label_color_edit,
            self.background_color_edit,
            self.grid_color_edit,
            self.axis_color_edit,
            self.line_style_combo,
            self.line_width_spin,
            self.marker_size_spin,
            self.bar_opacity_spin,
            self.area_opacity_spin,
            self.label_decimals_spin,
            self.horizontal_toggle,
            self.normalize_check,
            self.legend_check,
            self.show_grid_check,
            self.show_axis_line_check,
            self.show_line_check,
            self.show_markers_check,
            self.data_labels_check,
        ):
            bind(widget)

        for combo in self._y_column_combos:
            combo.currentIndexChanged.connect(self._schedule_preview)

    def _hide_preview_error(self) -> None:
        self._preview_error_log = ""
        self.preview_error_panel.hide()
        self.preview_error_text.clear()

    def _show_preview_error(self, error: BaseException) -> None:
        import traceback

        self._preview_error_log = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        ).strip() or str(error)
        summary = str(error)
        if len(summary) > 240:
            summary = summary[:237] + "..."
        self.preview_error_summary.setText(
            S.visualization.preview_error.format(error=summary)
        )
        self.preview_error_text.setPlainText(self._preview_error_log)
        self.preview_copy_error_btn.setToolTip(S.visualization.preview_copy_error)
        self.preview_status.hide()
        self.preview_error_panel.show()

    def _copy_preview_error_log(self) -> None:
        if not self._preview_error_log:
            return
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._preview_error_log)
        self.preview_copy_error_btn.setToolTip(S.visualization.preview_error_copied)

    def _schedule_preview(self):
        if self._preview_shutdown or self._render_fn is None:
            return
        self._hide_preview_error()
        self.preview_status.setText(S.visualization.preview_loading)
        self.preview_status.show()
        self._preview_timer.start(420)

    def _refresh_preview(self):
        if self._preview_shutdown or self._render_fn is None or self._df is None:
            return
        try:
            result = self._render_fn(self._df, self.get_config())
            if self._preview_shutdown:
                return
            if isinstance(result, bytes):
                self._show_preview_error(RuntimeError("PNG preview is not supported in the interactive editor."))
                self.preview_chart.clear()
                return
            self.preview_chart.set_html(result)
            self.preview_status.hide()
            self._hide_preview_error()
        except Exception as error:
            if self._preview_shutdown:
                return
            self.preview_chart.clear()
            self._show_preview_error(error)

    def _create_general_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("visualizationGeneralTab")
        layout = self._tab_layout(tab)

        form = self._form_layout()
        self.title_edit = QLineEdit(str(self._config.get("title", "")))
        self.title_edit.setObjectName("visualizationTitleInput")
        self.title_edit.setPlaceholderText(S.visualization.title_placeholder)
        form.addRow(S.visualization.label_title, self.title_edit)
        layout.addLayout(form)

        self.horizontal_toggle = LabeledToggleSwitch(
            S.visualization.horizontal_chart,
            checked=bool(self._config.get("horizontal", False)),
        )
        self.horizontal_toggle.setObjectName("visualizationHorizontalToggle")
        layout.addWidget(self.horizontal_toggle)

        layout.addStretch(1)
        return tab

    def _create_x_axis_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("visualizationXAxisTab")
        layout = self._tab_layout(tab)

        form = self._form_layout()
        self.x_combo = self._column_combo()
        self.x_combo.setObjectName("visualizationXColumnCombo")
        self._set_combo_value(self.x_combo, self._default_x_column())
        form.addRow(S.visualization.label_x_column, self.x_combo)

        self.x_label_edit = QLineEdit(str(self._config.get("x_label", "")))
        self.x_label_edit.setObjectName("visualizationXLabelInput")
        self.x_label_edit.setPlaceholderText(S.visualization.axis_label_placeholder)
        form.addRow(S.visualization.label_x_axis_title, self.x_label_edit)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("visualizationSortCombo")
        self.sort_combo.addItem(S.visualization.sort_original, "original")
        self.sort_combo.addItem(S.visualization.sort_x_asc, "x_asc")
        self.sort_combo.addItem(S.visualization.sort_y_desc, "y_desc")
        self._set_combo_value(self.sort_combo, self._config.get("sort", "original"))
        form.addRow(S.visualization.label_sort, self.sort_combo)
        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _create_y_axis_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("visualizationYAxisTab")
        layout = self._tab_layout(tab)

        y_label = QLabel(S.visualization.label_y_columns)
        layout.addWidget(y_label)
        self.y_rows = QWidget()
        self.y_rows_layout = QVBoxLayout(self.y_rows)
        self.y_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.y_rows_layout.setSpacing(6)
        layout.addWidget(self.y_rows)

        for column in self._default_y_columns():
            self._add_y_column(column)

        add_y_button = QPushButton(S.visualization.add_column)
        add_y_button.setObjectName("visualizationAddYButton")
        add_y_button.clicked.connect(lambda: self._add_y_column())
        layout.addWidget(add_y_button, alignment=Qt.AlignmentFlag.AlignLeft)

        form = self._form_layout()
        self.y_label_edit = QLineEdit(str(self._config.get("y_label", "")))
        self.y_label_edit.setObjectName("visualizationYLabelInput")
        self.y_label_edit.setPlaceholderText(S.visualization.axis_label_placeholder)
        form.addRow(S.visualization.label_y_axis_title, self.y_label_edit)

        self.aggregation_combo = QComboBox()
        self.aggregation_combo.setObjectName("visualizationAggregationCombo")
        self.aggregation_combo.addItem(S.visualization.agg_sum, "sum")
        self.aggregation_combo.addItem(S.visualization.agg_mean, "mean")
        self.aggregation_combo.addItem(S.visualization.agg_count, "count")
        self.aggregation_combo.addItem(S.visualization.agg_min, "min")
        self.aggregation_combo.addItem(S.visualization.agg_max, "max")
        self._set_combo_value(self.aggregation_combo, self._config.get("aggregation", "sum"))
        form.addRow(S.visualization.label_aggregation, self.aggregation_combo)
        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _create_series_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("visualizationSeriesTab")
        layout = self._tab_layout(tab)

        form2 = self._form_layout()
        self.group_combo = self._column_combo()
        self.group_combo.setObjectName("visualizationGroupCombo")
        self._set_combo_value(self.group_combo, self._config.get("group_by"))
        form2.addRow(S.visualization.label_group_by, self.group_combo)

        self.stacking_combo = QComboBox()
        self.stacking_combo.setObjectName("visualizationStackingCombo")
        self.stacking_combo.addItem(S.visualization.stacking_none, "none")
        self.stacking_combo.addItem(S.visualization.stacking_stacked, "stacked")
        self.stacking_combo.addItem(S.visualization.stacking_percent, "percent")
        self._set_combo_value(self.stacking_combo, self._config.get("stacking", "none"))
        form2.addRow(S.visualization.label_stacking, self.stacking_combo)

        self.nulls_combo = QComboBox()
        self.nulls_combo.setObjectName("visualizationNullsCombo")
        self.nulls_combo.addItem(S.visualization.nulls_zero, "zero")
        self.nulls_combo.addItem(S.visualization.nulls_drop, "drop")
        self.nulls_combo.addItem(S.visualization.nulls_keep, "keep")
        self._set_combo_value(self.nulls_combo, self._config.get("nulls", "zero"))
        form2.addRow(S.visualization.label_nulls, self.nulls_combo)
        layout.addLayout(form2)

        self.normalize_check = QCheckBox(S.visualization.normalize_values)
        self.normalize_check.setChecked(bool(self._config.get("normalize", False)))
        layout.addWidget(self.normalize_check)

        self.legend_check = QCheckBox(S.visualization.show_legend)
        self.legend_check.setObjectName("visualizationLegendCheck")
        self.legend_check.setChecked(bool(self._config.get("show_legend", True)))
        layout.addWidget(self.legend_check)
        layout.addStretch(1)
        return tab

    def _create_colors_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("visualizationColorsTab")
        layout = self._tab_layout(tab)

        form = self._form_layout()
        self.palette_combo = QComboBox()
        self.palette_combo.setObjectName("visualizationPaletteCombo")
        self.palette_combo.addItem(S.visualization.palette_default, "default")
        self.palette_combo.addItem(S.visualization.palette_categorical, "categorical")
        self.palette_combo.addItem(S.visualization.palette_teal, "teal")
        self.palette_combo.addItem(S.visualization.palette_warm, "warm")
        self.palette_combo.addItem(S.visualization.palette_ocean, "ocean")
        self._set_combo_value(self.palette_combo, self._config.get("palette", "default"))
        form.addRow(S.visualization.label_palette, self.palette_combo)

        colors = self._config.get("custom_colors", [])
        if isinstance(colors, list):
            colors_text = ", ".join(str(color) for color in colors)
        else:
            colors_text = str(colors or "")
        self.custom_colors_edit = QLineEdit(colors_text)
        self.custom_colors_edit.setObjectName("visualizationCustomColorsInput")
        self.custom_colors_edit.setPlaceholderText(S.visualization.custom_colors_placeholder)
        form.addRow(S.visualization.label_custom_colors, self.custom_colors_edit)

        self.text_color_edit = self._color_edit("text_color", "visualizationTextColorInput")
        form.addRow(S.visualization.label_text_color, self.text_color_edit)

        self.label_color_edit = self._color_edit("label_color", "visualizationLabelColorInput")
        form.addRow(S.visualization.label_data_label_color, self.label_color_edit)

        self.background_color_edit = self._color_edit("background_color", "visualizationBackgroundColorInput")
        form.addRow(S.visualization.label_background_color, self.background_color_edit)

        self.grid_color_edit = self._color_edit("grid_color", "visualizationGridColorInput")
        form.addRow(S.visualization.label_grid_color, self.grid_color_edit)

        self.axis_color_edit = self._color_edit("axis_color", "visualizationAxisColorInput")
        form.addRow(S.visualization.label_axis_color, self.axis_color_edit)

        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _create_style_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("visualizationStyleTab")
        layout = self._tab_layout(tab)

        self.show_grid_check = QCheckBox(S.visualization.show_grid)
        self.show_grid_check.setObjectName("visualizationShowGridCheck")
        self.show_grid_check.setChecked(bool(self._config.get("show_grid", True)))
        layout.addWidget(self.show_grid_check)

        self.show_axis_line_check = QCheckBox(S.visualization.show_axis_line)
        self.show_axis_line_check.setObjectName("visualizationShowAxisLineCheck")
        self.show_axis_line_check.setChecked(bool(self._config.get("show_axis_line", False)))
        layout.addWidget(self.show_axis_line_check)

        self.show_line_check = QCheckBox(S.visualization.show_line)
        self.show_line_check.setObjectName("visualizationShowLineCheck")
        self.show_line_check.setChecked(bool(self._config.get("show_line", True)))
        layout.addWidget(self.show_line_check)

        self.show_markers_check = QCheckBox(S.visualization.show_markers)
        self.show_markers_check.setObjectName("visualizationShowMarkersCheck")
        self.show_markers_check.setChecked(bool(self._config.get("show_markers", True)))
        layout.addWidget(self.show_markers_check)

        form = self._form_layout()
        self.line_style_combo = QComboBox()
        self.line_style_combo.setObjectName("visualizationLineStyleCombo")
        self.line_style_combo.addItem(S.visualization.line_style_solid, "solid")
        self.line_style_combo.addItem(S.visualization.line_style_dashed, "dashed")
        self.line_style_combo.addItem(S.visualization.line_style_dotted, "dotted")
        self.line_style_combo.addItem(S.visualization.line_style_dashdot, "dashdot")
        self._set_combo_value(self.line_style_combo, self._config.get("line_style", "solid"))
        form.addRow(S.visualization.label_line_style, self.line_style_combo)

        self.line_width_spin = QSpinBox()
        self.line_width_spin.setObjectName("visualizationLineWidthSpin")
        self.line_width_spin.setRange(1, 10)
        self.line_width_spin.setValue(self._bounded_int(self._config.get("line_width", 2), 1, 10, 2))
        form.addRow(S.visualization.label_line_width, self.line_width_spin)

        self.marker_size_spin = QSpinBox()
        self.marker_size_spin.setObjectName("visualizationMarkerSizeSpin")
        self.marker_size_spin.setRange(1, 18)
        self.marker_size_spin.setValue(self._bounded_int(self._config.get("marker_size", 5), 1, 18, 5))
        form.addRow(S.visualization.label_marker_size, self.marker_size_spin)

        self.bar_opacity_spin = QSpinBox()
        self.bar_opacity_spin.setObjectName("visualizationBarOpacitySpin")
        self.bar_opacity_spin.setRange(10, 100)
        self.bar_opacity_spin.setValue(self._bounded_int(self._config.get("bar_opacity", 94), 10, 100, 94))
        form.addRow(S.visualization.label_bar_opacity, self.bar_opacity_spin)

        self.area_opacity_spin = QSpinBox()
        self.area_opacity_spin.setObjectName("visualizationAreaOpacitySpin")
        self.area_opacity_spin.setRange(5, 90)
        self.area_opacity_spin.setValue(self._bounded_int(self._config.get("area_opacity", 20), 5, 90, 20))
        form.addRow(S.visualization.label_area_opacity, self.area_opacity_spin)

        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(maximum, number))

    def _create_data_labels_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("visualizationDataLabelsTab")
        layout = self._tab_layout(tab)

        self.data_labels_check = QCheckBox(S.visualization.show_data_labels)
        self.data_labels_check.setObjectName("visualizationDataLabelsCheck")
        self.data_labels_check.setChecked(bool(self._config.get("show_data_labels", False)))
        layout.addWidget(self.data_labels_check)

        form = self._form_layout()
        self.label_decimals_spin = QSpinBox()
        self.label_decimals_spin.setObjectName("visualizationLabelDecimalsSpin")
        self.label_decimals_spin.setRange(0, 6)
        self.label_decimals_spin.setValue(int(self._config.get("label_decimals", 1) or 0))
        form.addRow(S.visualization.label_label_decimals, self.label_decimals_spin)
        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _add_y_column(self, column: Any = None):
        row = QWidget(self.y_rows)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        combo = self._column_combo()
        self._set_combo_value(combo, column)
        remove_button = QToolButton()
        remove_button.setIcon(qta.icon("mdi.close", color="#a0a0a0", scale_factor=0.7))
        remove_button.setToolTip(S.visualization.remove_column)
        remove_button.clicked.connect(lambda checked=False, widget=row, cb=combo: self._remove_y_column(widget, cb))

        row_layout.addWidget(combo, 1)
        row_layout.addWidget(remove_button)
        self.y_rows_layout.addWidget(row)
        self._y_column_combos.append(combo)
        if self._render_fn is not None:
            combo.currentIndexChanged.connect(self._schedule_preview)

    def _remove_y_column(self, row: QWidget, combo: QComboBox):
        if combo in self._y_column_combos:
            self._y_column_combos.remove(combo)
        row.deleteLater()

    def get_config(self) -> dict:
        y_columns = [combo.currentData() for combo in self._y_column_combos if combo.currentData()]
        custom_colors = [
            color.strip()
            for color in self.custom_colors_edit.text().split(",")
            if color.strip()
        ]
        return {
            "type": self.type_combo.currentData() or "bar",
            "title": self.title_edit.text().strip(),
            "horizontal": self.horizontal_toggle.isChecked(),
            "x_column": self.x_combo.currentData() or "",
            "x_label": self.x_label_edit.text().strip(),
            "y_columns": y_columns,
            "y_label": self.y_label_edit.text().strip(),
            "aggregation": self.aggregation_combo.currentData() or "sum",
            "group_by": self.group_combo.currentData() or "",
            "stacking": self.stacking_combo.currentData() or "none",
            "normalize": self.normalize_check.isChecked(),
            "nulls": self.nulls_combo.currentData() or "zero",
            "sort": self.sort_combo.currentData() or "original",
            "palette": self.palette_combo.currentData() or "default",
            "custom_colors": custom_colors,
            "text_color": self.text_color_edit.text().strip(),
            "label_color": self.label_color_edit.text().strip(),
            "background_color": self.background_color_edit.text().strip(),
            "grid_color": self.grid_color_edit.text().strip(),
            "axis_color": self.axis_color_edit.text().strip(),
            "show_grid": self.show_grid_check.isChecked(),
            "show_axis_line": self.show_axis_line_check.isChecked(),
            "show_line": self.show_line_check.isChecked(),
            "show_markers": self.show_markers_check.isChecked(),
            "line_style": self.line_style_combo.currentData() or "solid",
            "line_width": self.line_width_spin.value(),
            "marker_size": self.marker_size_spin.value(),
            "bar_opacity": self.bar_opacity_spin.value(),
            "area_opacity": self.area_opacity_spin.value(),
            "show_legend": self.legend_check.isChecked(),
            "show_data_labels": self.data_labels_check.isChecked(),
            "label_decimals": self.label_decimals_spin.value(),
        }


class PandasModel(QAbstractTableModel):
    """Model para exibir DataFrame do pandas no QTableView"""

    def __init__(self, df: pd.DataFrame = None, theme_manager: ThemeManager = None):
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()
        self._prepared: Optional[PreparedGridData] = None
        self.theme_manager = theme_manager or ThemeManager()
        self._column_formats = {}
        self._update_colors()

    def _update_colors(self):
        """Atualiza as cores baseado no tema"""
        colors = self.theme_manager.get_table_colors()
        app_colors = self.theme_manager.get_app_colors()
        self._row_even = QColor(colors["row_even"])
        self._row_odd = QColor(colors["row_odd"])
        self._text_color = QColor(colors["text"])
        self._header_bg = QColor(colors["header_bg"])
        self._header_text = QColor(colors["header_text"])
        background = QColor(app_colors["background"])
        if background.lightness() > 140:
            self._null_bg = QColor("#fff4cc")
            self._null_text = QColor("#7a4f00")
        else:
            self._null_bg = QColor("#4a3920")
            self._null_text = QColor("#f5d78e")

    def set_theme_manager(self, theme_manager: ThemeManager):
        """Atualiza o theme manager e recarrega cores"""
        self.theme_manager = theme_manager
        self._update_colors()
        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        if self._prepared is not None:
            return self._prepared.row_count
        return len(self._df)

    def columnCount(self, parent=QModelIndex()):
        if self._prepared is not None:
            return len(self._prepared.columns)
        return len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()

        if self._prepared is not None:
            row = index.row()
            col = index.column()
            if role == Qt.ItemDataRole.DisplayRole:
                try:
                    return self._prepared.display_value(row, col)
                except (IndexError, KeyError):
                    return QVariant()
            if role == Qt.ItemDataRole.BackgroundRole:
                if self._prepared.is_null(row, col):
                    return self._null_bg
                return self._row_even if row % 2 == 0 else self._row_odd
            if role == Qt.ItemDataRole.ForegroundRole:
                if self._prepared.is_null(row, col):
                    return self._null_text
                return self._text_color
            if role == Qt.ItemDataRole.TextAlignmentRole:
                if col in self._prepared.numeric_column_indices:
                    return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            return QVariant()

        if role == Qt.ItemDataRole.DisplayRole:
            value = self._df.iloc[index.row(), index.column()]
            if self._is_null_value(value):
                return "NULL"
            column = self._df.columns[index.column()]
            format_config = self._column_formats.get(column, self._column_formats.get(str(column), "default"))
            return self._format_display_value(value, format_config)

        if role == Qt.ItemDataRole.BackgroundRole:
            value = self._df.iloc[index.row(), index.column()]
            if self._is_null_value(value):
                return self._null_bg
            if index.row() % 2 == 0:
                return self._row_even
            return self._row_odd

        if role == Qt.ItemDataRole.ForegroundRole:
            value = self._df.iloc[index.row(), index.column()]
            if self._is_null_value(value):
                return self._null_text
            return self._text_color

        if role == Qt.ItemDataRole.TextAlignmentRole:
            column = self._df.columns[index.column()]
            if pd.api.types.is_numeric_dtype(self._df[column]):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                if self._prepared is not None:
                    return self._prepared.columns[section]
                return self._df.columns[section]
            return str(section + 1)

        if role == Qt.ItemDataRole.BackgroundRole:
            return self._header_bg

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._header_text

        return QVariant()

    def update_prepared(self, prepared: PreparedGridData):
        """Atualiza o grid com payload precomputado."""
        self.beginResetModel()
        self._prepared = prepared
        self._df = pd.DataFrame()
        self.endResetModel()

    def update_data(self, df: pd.DataFrame):
        """Atualiza o DataFrame (caminho sincrono para datasets pequenos)."""
        limit = len(df) if df is not None else 0
        result = prepare_grid_data(df, {}, self._column_formats, limit)
        self.update_prepared(result.prepared)
        self._df = df if df is not None else pd.DataFrame()

    def set_column_formats(self, column_formats: dict):
        """Atualiza formatacoes visuais por coluna."""
        self._column_formats = dict(column_formats or {})
        self.layoutChanged.emit()

    def _normalize_format_config(self, format_config) -> dict:
        if isinstance(format_config, dict):
            normalized = dict(format_config)
            normalized["type"] = str(normalized.get("type", "default") or "default")
            return normalized
        return {"type": str(format_config or "default")}

    def _format_decimals(self, format_config: dict, default: int = 2) -> int:
        try:
            decimals = int(format_config.get("decimals", default))
        except (TypeError, ValueError):
            decimals = default
        return max(0, min(decimals, 8))

    def _is_null_value(self, value) -> bool:
        try:
            if not pd.api.types.is_scalar(value):
                return False
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False

    def _format_display_value(self, value, format_config) -> str:
        config = self._normalize_format_config(format_config)
        format_name = config.get("type", "default")
        if format_name == "default":
            return str(value)
        if format_name in {"number", "currency"}:
            number = pd.to_numeric(value, errors="coerce")
            if pd.isna(number):
                return str(value)
            decimals = self._format_decimals(config)
            prefix = str(config.get("prefix", "$ " if format_name == "currency" else ""))
            suffix = str(config.get("suffix", ""))
            return f"{prefix}{float(number):,.{decimals}f}{suffix}"
        if format_name == "percent":
            number = pd.to_numeric(value, errors="coerce")
            decimals = self._format_decimals(config)
            return str(value) if pd.isna(number) else f"{float(number):.{decimals}%}"
        if format_name in {"date", "datetime"}:
            return _grid_format_datetime_value(value, format_name)
        return str(value)


class ResultsViewer(QWidget):
    """Widget para visualizar resultados de queries"""

    grid_selection_changed = pyqtSignal()

    SETTINGS_KEY_GRID_FONT_SIZE = "results/grid_font_size"
    DEFAULT_GRID_FONT_SIZE = 9
    MIN_GRID_FONT_SIZE = 7
    MAX_GRID_FONT_SIZE = 24

    def __init__(self, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self._session = None
        self._column_filters: dict = {}
        self._column_formats: dict = {}
        self._chart_configs: list = []
        self._chart_pages: list = []
        self._chart_render_jobs: list = []
        self._chart_render_queue: list = []
        self._active_chart_render_job: Optional[dict] = None
        self._active_chart_index: int = 0
        self._column_filter_popup = None
        self._connection_color = ""
        self._grid_font_size = self._load_grid_font_size()
        self._bound_selection_model = None
        self._setup_ui()
        self.current_df: Optional[pd.DataFrame] = None
        self._current_image_bytes: Optional[bytes] = None
        self._display_limit: int = self._load_display_limit()
        # Background export tracking
        self._export_thread: Optional[QThread] = None
        self._export_worker: Optional[FileExportWorker] = None
        self._grid_prepare_job_serial = 0
        self._model_prepare_generation: dict[int, int] = {}
        self._active_grid_prepare_job: Optional[dict] = None
        self._grid_prepare_job_meta: dict[int, dict] = {}
        self._primary_grid_cache_key = None
        self._primary_filtered_df: Optional[pd.DataFrame] = None
        self._summarize_refresh_timer: Optional[QTimer] = None
        self._pending_result_tab_index: Optional[int] = None
        self._result_tab_switch_timer: Optional[QTimer] = None

    def _setup_ui(self):
        """Configura a interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Obter cores do tema
        colors = self.theme_manager.get_app_colors()

        # Toolbar
        self.toolbar = QToolBar()
        self._apply_toolbar_style()

        # Combobox de destino (Clipboard ou File)
        from src.design_system.tokens import get_colors
        colors_tk = get_colors()
        
        self.export_dest_widget = QWidget()
        self.export_dest_widget.setObjectName("exportDestSegment")
        export_dest_layout = QHBoxLayout(self.export_dest_widget)
        export_dest_layout.setContentsMargins(0, 0, 0, 0)
        export_dest_layout.setSpacing(0)

        self.btn_export_dest_clipboard = QToolButton()
        self.btn_export_dest_clipboard.setObjectName("exportDestBtnLeft")
        self.btn_export_dest_clipboard.setCheckable(True)
        self.btn_export_dest_clipboard.setChecked(True)
        self.btn_export_dest_clipboard.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_export_dest_clipboard.setToolTip(S.results.dest_clipboard)
        self.btn_export_dest_clipboard.setProperty("export_dest", "clipboard")
        self.btn_export_dest_clipboard.setIconSize(QSize(16, 16))

        self.btn_export_dest_file = QToolButton()
        self.btn_export_dest_file.setObjectName("exportDestBtnRight")
        self.btn_export_dest_file.setCheckable(True)
        self.btn_export_dest_file.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_export_dest_file.setToolTip(S.results.dest_file)
        self.btn_export_dest_file.setProperty("export_dest", "file")
        self.btn_export_dest_file.setIconSize(QSize(16, 16))

        self._export_dest_group = QButtonGroup(self)
        self._export_dest_group.setExclusive(True)
        self._export_dest_group.addButton(self.btn_export_dest_clipboard)
        self._export_dest_group.addButton(self.btn_export_dest_file)
        self._export_dest_group.buttonClicked.connect(self._refresh_export_dest_icons)

        export_dest_layout.addWidget(self.btn_export_dest_clipboard)
        export_dest_layout.addWidget(self.btn_export_dest_file)
        self.toolbar.addWidget(self.export_dest_widget)
        self.toolbar.addSeparator()

        # Toolbar buttons with icons
        self.btn_export_csv = QPushButton(S.results.btn_csv)
        self.btn_export_csv.setIcon(qta.icon("mdi.file-delimited-outline", color=colors_tk.text_tertiary))
        self.btn_export_excel = QPushButton(S.results.btn_excel)
        self.btn_export_excel.setIcon(qta.icon("mdi.file-excel-outline", color=colors_tk.success))
        self.btn_export_json = QPushButton(S.results.btn_json)
        self.btn_export_json.setIcon(qta.icon("mdi.code-json", color=colors_tk.warning))
        self.btn_copy = QPushButton(S.results.btn_copy_all)
        self.btn_copy.setIcon(qta.icon("mdi.content-copy", color=colors_tk.text_tertiary))

        self.toolbar.addWidget(self.btn_export_csv)
        self.toolbar.addWidget(self.btn_export_excel)
        self.toolbar.addWidget(self.btn_export_json)
        self.toolbar.addWidget(self.btn_copy)

        # Export to Table button (database)
        self.toolbar.addSeparator()
        self.btn_export_table = QPushButton(S.results.btn_table)
        self.btn_export_table.setIcon(qta.icon("mdi.database-export", color=colors_tk.info))
        self.btn_export_table.setToolTip(S.results.tooltip_export_table)
        self.toolbar.addWidget(self.btn_export_table)

        # Export to SQL INSERTs button
        self.btn_export_sql = QPushButton(S.results.btn_sql)
        self.btn_export_sql.setIcon(qta.icon("mdi.database-import-outline", color=colors_tk.warning))
        self.btn_export_sql.setToolTip(S.results.tooltip_export_sql)
        self.toolbar.addWidget(self.btn_export_sql)

        # Info label
        self.info_label = QLabel(S.results.no_results)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.info_label)

        # Spacer to push row limit to the right
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy())
        from PyQt6.QtWidgets import QSizePolicy
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)

        # Row limit spinner
        self.row_limit_label = QLabel(S.results.label_row_limit if hasattr(S.results, 'label_row_limit') else "Rows:")
        self.row_limit_label.setStyleSheet("color: #999; font-size: 10px; padding: 0 4px;")
        self.toolbar.addWidget(self.row_limit_label)

        self.row_limit_spin = QSpinBox()
        self.row_limit_spin.setRange(10, 1000000)
        self.row_limit_spin.setSingleStep(100)
        self.row_limit_spin.setValue(self._load_display_limit())
        self.row_limit_spin.setFixedWidth(90)
        self.row_limit_spin.setToolTip(
            S.results.tooltip_row_limit if hasattr(S.results, 'tooltip_row_limit')
            else "Max rows displayed in grid (exports use all data)"
        )
        self.row_limit_spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: {colors_tk.bg_secondary};
                color: {colors_tk.text_secondary};
                border: 1px solid {colors_tk.border_default};
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
            }}
            QSpinBox:hover {{ border-color: {colors_tk.interactive_primary}; }}
        """)
        self.row_limit_spin.valueChanged.connect(self._on_row_limit_changed)
        self.toolbar.addWidget(self.row_limit_spin)

        # Export settings button
        self.btn_export_settings = QPushButton()
        self.btn_export_settings.setIcon(qta.icon("mdi.cog", color=colors_tk.text_secondary))
        self.btn_export_settings.setToolTip(S.export_settings.tooltip_btn)
        self.btn_export_settings.setFixedSize(26, 26)
        self.btn_export_settings.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: {colors_tk.bg_secondary};
                border-color: {colors_tk.border_default};
            }}
        """)
        self.btn_export_settings.clicked.connect(self._open_export_settings)
        self.toolbar.addWidget(self.btn_export_settings)

        self._refresh_export_dest_icons()
        self._apply_export_dest_style()
        self._sync_export_dest_button_sizes()

        layout.addWidget(self.toolbar)

        self.filter_chip_bar = QWidget()
        self.filter_chip_bar.setObjectName("filterChipBar")
        self.filter_chip_bar.setVisible(False)
        self.filter_chip_layout = QHBoxLayout(self.filter_chip_bar)
        self.filter_chip_layout.setContentsMargins(12, 6, 12, 6)
        self.filter_chip_layout.setSpacing(6)
        self._apply_filter_chips_style()
        layout.addWidget(self.filter_chip_bar)

        # Save image button (hidden by default)
        self.btn_save_image = QPushButton(S.results.btn_save_image)
        self.btn_save_image.setVisible(False)
        self.toolbar.addWidget(self.btn_save_image)

        # QStackedWidget: page 0 = table, page 1 = image
        self.stack = QStackedWidget()

        # Page 0 - Table
        self.table_view = QTableView()
        self._install_table_header(self.table_view)
        self._apply_table_style()

        # Ctrl+C shortcut scoped to the grid only — a window-wide context would
        # steal Ctrl+C from the output panel and the Pynia chat.
        copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table_view)
        copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy_shortcut.activated.connect(self._copy_selection_to_clipboard)

        # Context menu on right-click (viewport + headers + corner)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_grid_context_menu)
        self.table_view.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.horizontalHeader().customContextMenuRequested.connect(
            self._show_header_context_menu
        )
        self.table_view.verticalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.verticalHeader().customContextMenuRequested.connect(
            self._show_header_context_menu
        )
        corner = self.table_view.findChild(QAbstractButton)
        if corner:
            corner.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            corner.customContextMenuRequested.connect(self._show_header_context_menu)

        self.model = PandasModel(theme_manager=self.theme_manager)
        self.table_view.setModel(self.model)

        # Cabecalho interativo - resize sera feito apos carregar dados (limitado)
        self.table_view.horizontalHeader().setSectionResizeMode(
            self.table_view.horizontalHeader().ResizeMode.Interactive
        )
        self.stack.addWidget(self.table_view)  # index 0

        # Pagina 1 - Imagem
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setStyleSheet(f"background-color: {colors['background']};")
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll.setWidget(self.image_label)
        self.stack.addWidget(self.image_scroll)  # index 1

        # Pagina 2 - HTML
        self.html_viewer = QTextEdit()
        self.html_viewer.setReadOnly(True)
        self.html_viewer.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                padding: 10px;
            }}
            {SCROLLBAR_STYLE}
        """)
        self.stack.addWidget(self.html_viewer)  # index 2

        # Pagina 3 - JSON Tree
        self.json_tree = QTreeWidget()
        self.json_tree.setHeaderLabels([S.results.json_header_key, S.results.json_header_value, S.results.json_header_type])
        self.json_tree.setAlternatingRowColors(True)
        self.json_tree.setColumnWidth(0, 250)
        self.json_tree.setColumnWidth(1, 400)
        self.json_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                alternate-background-color: {colors["border"]};
            }}
            QTreeWidget::item {{
                padding: 3px;
            }}
            QHeaderView::section {{
                background-color: {colors["border"]};
                color: {colors["foreground"]};
                border: none;
                padding: 5px;
                font-weight: bold;
            }}
            {SCROLLBAR_STYLE}
        """)
        self.json_tree.setFont(QFont("Consolas", 10))
        self.stack.addWidget(self.json_tree)  # index 3

        # Multi-result tabs wrapper. Tab 0 hosts the primary stack
        # (table/image/html/json). Additional tabs are created on demand
        # for executions that return multiple DataFrames and only host a
        # grid. The tab bar stays visible to keep the chart action in a
        # stable place even for single-result executions.
        self._result_tabs = QTabWidget()
        result_tab_bar = ResultTabBar(self._result_tabs)
        result_tab_bar.closeRequested.connect(self._on_result_tab_close_requested)
        self._result_tabs.setTabBar(result_tab_bar)
        self._result_tabs.setDocumentMode(True)
        self._result_tabs.setTabsClosable(False)
        self._result_tabs.setMovable(True)
        self._result_tabs.addTab(self.stack, S.results.tab_label.format(n=1))
        self._setup_result_tab_close_button(0)
        self._result_tabs.tabBar().setVisible(True)
        self._result_tabs.currentChanged.connect(self._on_result_tab_changed)
        self.stack.currentChanged.connect(self._on_stack_page_changed)

        from src.design_system.tab_controls import TabBarAccessoryStrip

        self._result_tab_accessory = TabBarAccessoryStrip(result_tab_bar, host=self._result_tabs)
        self.btn_visualization = self._result_tab_accessory.add_button(
            "mdi.chart-bar",
            tooltip=S.visualization.open_editor,
            callback=self._open_visualization_editor,
            object_name="visualizationButton",
        )
        self._result_tab_accessory.add_button(
            "mdi.plus",
            tooltip=S.visualization.new_chart_tab,
            callback=self._add_chart_tab_from_current_source,
            object_name="visualizationNewChartButton",
        )
        self._apply_result_tabs_style()

        # Secondary tab tracking. Preserve refs to primary table_view/
        # model so we can swap self.table_view / self.model on tab change
        # without breaking any handler that reads them.
        self._secondary_pages: list = []
        self._primary_table_view = self.table_view
        self._primary_model = self.model
        self._connect_active_selection_model()
        self._primary_df: Optional[pd.DataFrame] = None

        layout.addWidget(self._result_tabs)

        # Conectar sinais
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_export_excel.clicked.connect(self._export_excel)
        self.btn_export_json.clicked.connect(self._export_json)
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        self.btn_save_image.clicked.connect(self._save_image)
        self.btn_export_table.clicked.connect(self._export_to_table)
        self.btn_export_sql.clicked.connect(self._export_sql)

    def set_session(self, session):
        """Associa este viewer a uma sessao para persistir preferencias visuais."""
        self._session = session
        self._sync_connection_color_from_session()
        self.set_view_state(getattr(session, "result_view_state", None))

    def set_connection_color(self, color: str):
        """Atualiza a cor de conexao usada nas abas de resultados."""
        self._connection_color = str(color or "").strip()
        tab_bar = getattr(getattr(self, "_result_tabs", None), "tabBar", lambda: None)()
        if hasattr(tab_bar, "set_connection_color"):
            tab_bar.set_connection_color(self._connection_color)
        self._apply_result_tabs_style()

    def _sync_connection_color_from_session(self):
        connection_name = getattr(self._session, "connection_name", "") if self._session is not None else ""
        if not connection_name:
            return
        try:
            from src.database.connection_manager import ConnectionManager
            config = ConnectionManager().get_connection_config(connection_name)
            color = config.get("color", "") if config else ""
        except Exception:
            color = ""
        if color:
            self.set_connection_color(color)

    def get_view_state(self) -> dict:
        """Retorna estado serializavel de visualizacao da sessao."""
        return {
            "column_formats": self._serialize_column_formats(),
            "charts": {
                "active_index": self._active_chart_index,
                "configs": [dict(config) for config in self._chart_configs if isinstance(config, dict)],
            },
        }

    def set_view_state(self, state: Optional[dict]):
        """Restaura estado salvo de formatos e graficos."""
        normalized = self._normalize_view_state(state)
        self._column_formats = normalized["column_formats"]
        charts = normalized.get("charts", {})
        self._chart_configs = charts.get("configs", [])
        self._active_chart_index = charts.get("active_index", 0)
        if self._get_active_source_df() is not None:
            self._apply_active_dataframe_view(self._current_result_label())

    def _persist_view_state(self):
        if self._session is not None:
            self._session.result_view_state = self.get_view_state()
            self._mark_session_modified()

    def _mark_session_modified(self):
        main_window = self._get_main_window()
        if not main_window or not hasattr(main_window, "session_tabs"):
            return
        for index in range(main_window.session_tabs.count()):
            widget = main_window.session_tabs.widget(index)
            if getattr(widget, "session", None) is not self._session:
                continue
            widget._is_modified = True
            title = main_window.session_tabs.tabText(index)
            if title and not title.endswith(" *"):
                main_window.session_tabs.setTabText(index, title + " *")
            break

    def _normalize_view_state(self, state: Optional[dict]) -> dict:
        if not isinstance(state, dict):
            state = {}
        charts = state.get("charts", {}) if isinstance(state.get("charts", {}), dict) else {}
        configs = charts.get("configs", []) if isinstance(charts.get("configs", []), list) else []
        try:
            active_index = int(charts.get("active_index", 0) or 0)
        except (TypeError, ValueError):
            active_index = 0
        return {
            "column_formats": self._normalize_column_formats(state.get("column_formats", {})),
            "charts": {
                "active_index": max(0, active_index),
                "configs": [dict(config) for config in configs if isinstance(config, dict)],
            },
        }

    def _normalize_column_formats(self, column_formats: Any) -> dict:
        if not isinstance(column_formats, dict):
            return {}
        normalized = {}
        for column, format_config in column_formats.items():
            column_name = str(column)
            if isinstance(format_config, dict):
                config = dict(format_config)
                config["type"] = str(config.get("type", "default") or "default")
            else:
                config = {"type": str(format_config or "default")}
            if config.get("type") != "default":
                normalized[column_name] = config
        return normalized

    def _serialize_column_formats(self) -> dict:
        return self._normalize_column_formats(self._column_formats)

    def _apply_toolbar_style(self):
        """Aplica estilo na toolbar baseado no tema - moderno e limpo"""
        colors = self.theme_manager.get_app_colors()
        from src.design_system.tokens import RADIUS
        if hasattr(self, "export_dest_widget"):
            self._apply_export_dest_style()
        self.toolbar.setStyleSheet(f"""
            QToolBar {{
                background-color: {colors["background"]};
                border: none;
                border-bottom: 1px solid {colors["border"]};
                spacing: 6px;
                padding: 8px 12px;
            }}
            QPushButton {{
                background-color: transparent;
                color: {colors["foreground"]};
                border: 1px solid {colors["border"]};
                padding: 6px 12px;
                border-radius: {RADIUS.radius_sm}px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {colors["accent"]};
                color: white;
                border-color: {colors["accent"]};
            }}
            QLabel {{
                color: {colors["foreground"]};
                padding: 4px 8px;
                font-size: 12px;
            }}
            QLineEdit {{
                background-color: #2d2d2d;
                color: {colors["foreground"]};
                border: 1px solid {colors["border"]};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                min-width: 180px;
            }}
            QLineEdit:hover, QLineEdit:focus {{
                border-color: {colors["accent"]};
            }}
        """)

    def _apply_filter_chips_style(self):
        """Aplica estilo da faixa de filtros ativos."""
        from src.design_system.tokens import get_colors
        colors = get_colors()
        self.filter_chip_bar.setStyleSheet(f"""
            QWidget#filterChipBar {{
                background-color: {colors.bg_primary};
                border-bottom: 1px solid {colors.border_muted};
            }}
            QToolButton#filterChip {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QToolButton#filterChip:hover {{
                border-color: {colors.interactive_primary};
                background-color: {colors.bg_tertiary};
            }}
        """)

    def _install_table_header(self, table_view: QTableView):
        """Instala cabecalho com menu visual por coluna."""
        header = ResultGridHeader(Qt.Orientation.Horizontal, table_view)
        header.menuRequested.connect(self._show_column_header_menu)
        table_view.setHorizontalHeader(header)

    def _apply_table_style(self):
        """Aplica estilo compacto na tabela principal."""
        self._apply_table_style_to(self.table_view)

    def _apply_table_style_to(self, table_view: QTableView):
        """Aplica estilo compacto de resultados SQL a uma QTableView."""
        table_colors = self.theme_manager.get_table_colors()
        colors = self.theme_manager.get_app_colors()
        from src.design_system.tokens import SCROLLBAR_STYLE
        font_size = self._grid_font_size
        css_font_size = max(10, font_size + 3)
        row_height = max(18, font_size + 13)
        header_height = max(22, font_size + 15)
        table_view.setShowGrid(True)
        table_view.setAlternatingRowColors(False)
        table_view.setWordWrap(False)
        table_view.setTextElideMode(Qt.TextElideMode.ElideRight)
        table_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table_view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        if hasattr(table_view, "setUniformRowHeights"):
            table_view.setUniformRowHeights(True)
        table_view.setFont(QFont("Consolas", font_size))
        table_view.verticalHeader().setDefaultSectionSize(row_height)
        table_view.verticalHeader().setMinimumSectionSize(18)
        table_view.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table_view.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table_view.horizontalHeader().setFixedHeight(header_height)
        self._install_result_zoom_filter(table_view)
        table_view.setStyleSheet(f"""
            QTableView {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                gridline-color: {colors["border"]};
                selection-background-color: {colors["accent"]};
                selection-color: white;
                font-family: Consolas, "Cascadia Mono", monospace;
                font-size: {css_font_size}px;
            }}
            QTableView::item {{
                padding: 1px 6px;
                border: none;
            }}
            QTableView::item:selected {{
                background-color: {colors["accent"]};
                color: white;
            }}
            QTableView::item:hover {{
                background-color: rgba(75, 123, 236, 0.12);
            }}
            QHeaderView::section {{
                background-color: {table_colors["header_bg"]};
                color: {table_colors["header_text"]};
                padding: 2px 6px;
                border: none;
                border-right: 1px solid {colors["border"]};
                border-bottom: 1px solid {colors["border"]};
                font-weight: 500;
                font-size: {css_font_size}px;
            }}
            QHeaderView::section:hover {{
                background-color: {colors["border"]};
            }}
            {SCROLLBAR_STYLE}
        """)
        # Warm the font engine for the QSS-resolved font (Consolas at pixel
        # size). The FIRST text measurement/paint on a cold font config costs
        # ~200ms on Windows; pay it here (style time, behind splash/startup)
        # instead of mid-render of the first big result grid.
        table_view.ensurePolished()
        table_view.fontMetrics().horizontalAdvance("0")

    def _install_result_zoom_filter(self, table_view: QTableView):
        """Instala Ctrl+scroll no grid e no viewport do grid."""
        for target in (table_view, table_view.viewport()):
            if target.property("datapynResultZoomFilter"):
                continue
            target.installEventFilter(self)
            target.setProperty("datapynResultZoomFilter", True)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and watched.property("datapynResultZoomFilter"):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if self._handle_result_zoom_wheel(event.angleDelta().y()):
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _handle_result_zoom_wheel(self, delta: int) -> bool:
        if delta == 0:
            return False
        step = 1 if delta > 0 else -1
        self.set_grid_font_size(self._grid_font_size + step)
        return True

    def set_grid_font_size(self, size: int, persist: bool = True) -> int:
        """Atualiza e persiste o zoom do grid de resultados."""
        font_size = self._clamp_grid_font_size(size)
        self._grid_font_size = font_size
        if persist:
            self._save_grid_font_size(font_size)
        self._apply_table_style_to(self._primary_table_view)
        for page in list(getattr(self, "_secondary_pages", [])):
            table_view = getattr(page, "_table_view", None)
            if table_view is not None:
                self._apply_table_style_to(table_view)
        return font_size

    def get_grid_font_size(self) -> int:
        """Retorna o tamanho de fonte atual do grid de resultados."""
        return self._grid_font_size

    def set_theme_manager(self, theme_manager: ThemeManager):
        """Atualiza o tema"""
        self.theme_manager = theme_manager
        self._apply_toolbar_style()
        self._apply_table_style()
        self._apply_result_tabs_style()
        self._apply_filter_chips_style()
        self.model.set_theme_manager(theme_manager)

    def display_dataframe(self, df: pd.DataFrame, var_name: str = "df", restore_charts: bool = True):
        """Exibe um DataFrame na tabela.

        Armazena o DataFrame completo para exportacao, mas exibe apenas
        ate o limite de linhas configurado para manter a interface fluida.
        """
        tab_label = str(var_name or S.results.tab_label.format(n=1))
        # Collapse any secondary tabs from a previous multi-result execution
        self._collapse_to_primary()
        self._result_tabs.setTabText(0, tab_label)
        self._primary_df = df
        self._primary_grid_cache_key = None
        self._primary_filtered_df = None
        self._update_filter_columns(df)
        self._apply_active_dataframe_view(tab_label)

        # Mostrar tabela e botoes de export
        self.stack.setCurrentIndex(0)
        self._show_dataframe_toolbar_buttons()
        if restore_charts:
            self._restore_chart_tabs_for_current_data()

    def _resize_columns(self):
        """Ajusta largura das colunas pelo conteudo visivel (deferido via QTimer)."""
        self.table_view.resizeColumnsToContents()

    def display_dataframes(self, items):
        """Exibe varios DataFrames, cada um em sua propria aba.

        Args:
            items: lista de DataFrames OU lista de tuplas (label, DataFrame).
                   O primeiro item ocupa a aba primaria (que mantem suporte
                   completo a imagem/HTML/JSON). Os demais criam abas
                   secundarias somente-grid. Lista vazia e no-op.
        """
        if not items:
            return

        norm = []
        for i, item in enumerate(items):
            if isinstance(item, tuple):
                label, df = item
            else:
                label = S.results.tab_label.format(n=i + 1)
                df = item
            if not label:
                label = S.results.tab_label.format(n=i + 1)
            norm.append((label, df))

        # Limpa estado anterior para nao acumular abas entre execucoes
        self._collapse_to_primary()

        # Primeiro item vai para a aba primaria via fluxo normal
        first_label, first_df = norm[0]
        self.display_dataframe(first_df, first_label, restore_charts=False)
        self._result_tabs.setTabText(0, first_label)

        # Itens extras viram abas secundarias somente-grid
        for label, df in norm[1:]:
            page = self._create_secondary_page(df, label)
            self._secondary_pages.append(page)
            index = self._result_tabs.addTab(page, label)
            self._setup_result_tab_close_button(index)

        self._result_tabs.tabBar().setVisible(True)
        self.table_view = self._primary_table_view
        self.model = self._primary_model
        self._result_tabs.setCurrentIndex(0)
        self._restore_chart_tabs_for_current_data()
        self._schedule_summarize_refresh()

    def _create_secondary_page(self, df: pd.DataFrame, label: str = "") -> QWidget:
        """Cria uma pagina leve somente-grid para uma aba secundaria."""
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        table_view = QTableView()
        self._install_table_header(table_view)
        model = PandasModel(theme_manager=self.theme_manager)
        table_view.setModel(model)
        table_view.horizontalHeader().setSectionResizeMode(
            table_view.horizontalHeader().ResizeMode.Interactive
        )

        self._apply_table_style_to(table_view)

        # Carrega slice respeitando o limite atual (fora da thread principal quando grande)
        page._table_view = table_view
        page._model = model
        page._df = df
        self._request_grid_view_update(df, var_name=label, model=model, table_view=table_view, page=page)

        # Ctrl+C e menu de contexto delegam aos metodos da viewer,
        # que operam em self.table_view/self.model (trocados pelo handler
        # de mudanca de aba antes do usuario interagir).
        copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, table_view)
        copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy_shortcut.activated.connect(self._copy_selection_to_clipboard)
        table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table_view.customContextMenuRequested.connect(self._show_grid_context_menu)
        table_view.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table_view.horizontalHeader().customContextMenuRequested.connect(self._show_header_context_menu)

        vbox.addWidget(table_view)

        # Anexa metadados a pagina para o handler de mudanca de aba
        page._df = df
        return page

    def _collapse_to_primary(self):
        """Remove todas as abas secundarias e restaura referencias primarias."""
        tabs = getattr(self, "_result_tabs", None)
        if tabs is None:
            return
        self._pending_result_tab_index = None
        timer = self._result_tab_switch_timer
        if timer is not None:
            timer.stop()
        blocker = QSignalBlocker(tabs)
        if tabs.currentIndex() != 0:
            tabs.setCurrentIndex(0)
        while tabs.count() > 1:
            page = tabs.widget(1)
            if self._is_chart_page(page):
                self._dispose_chart_page(page)
            tabs.removeTab(1)
            if page is not None:
                page.deleteLater()
        self._secondary_pages.clear()
        self._chart_pages.clear()
        tabs.tabBar().setVisible(True)
        # Reset tab 0 label e referencias internas
        tabs.setTabText(0, S.results.tab_label.format(n=1))
        self._setup_result_tab_close_button(0)
        self.table_view = self._primary_table_view
        self.model = self._primary_model
        del blocker

    def _on_result_tab_changed(self, index: int):
        """Defer tab activation so the tab bar can repaint before heavy work."""
        self._pending_result_tab_index = index
        timer = self._result_tab_switch_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_pending_result_tab_changed)
            self._result_tab_switch_timer = timer
        timer.start(0)

    def _apply_pending_result_tab_changed(self):
        """Troca referencias internas (current_df, table_view, model) ao mudar de aba."""
        index = self._pending_result_tab_index
        self._pending_result_tab_index = None
        if index is None:
            return
        tabs = getattr(self, "_result_tabs", None)
        if tabs is None or index < 0:
            return
        if index == 0:
            if self._primary_df is not None:
                self._switch_to_grid_tab(index, self._primary_df)
            else:
                self.table_view = self._primary_table_view
                self.model = self._primary_model
                self._connect_active_selection_model()
                self._schedule_summarize_refresh()
            return

        page = tabs.widget(index)
        if self._is_chart_page(page):
            self._active_chart_index = getattr(page, "_chart_index", self._active_chart_index)
            self.current_df = None
            self._current_image_bytes = getattr(page, "_image_bytes", None)
            if getattr(page, "_chart_html", None):
                self._current_image_bytes = None
            self.info_label.setText(self._chart_tab_label(self._active_chart_index, getattr(page, "_config", {})))
            self._show_chart_toolbar_buttons()
            if not self._chart_page_has_content(page) and not getattr(page, "_rendering", False):
                self._render_visualization_page(page)
            self._schedule_summarize_refresh()
            return

        df = getattr(page, "_df", None)
        if df is None:
            return
        self._switch_to_grid_tab(
            index,
            df,
            page=page,
            model=getattr(page, "_model", None),
            table_view=getattr(page, "_table_view", None),
        )

    def _switch_to_grid_tab(
        self,
        index: int,
        source_df: pd.DataFrame,
        *,
        page=None,
        model=None,
        table_view=None,
    ):
        """Activate a grid tab without re-preparing when cached data is still valid."""
        tabs = getattr(self, "_result_tabs", None)
        var_name = tabs.tabText(index) if tabs is not None else self._current_result_label()

        if page is None:
            self.table_view = self._primary_table_view
            self.model = self._primary_model
            model = self._primary_model
            table_view = self._primary_table_view
        else:
            self.table_view = table_view or page._table_view
            self.model = model or page._model

        self._update_filter_columns(source_df)
        if self._can_use_cached_grid_view(source_df, self.model, page):
            self._activate_cached_grid_view(var_name, source_df, self.model, self.table_view, page)
        else:
            self._apply_active_dataframe_view(var_name)
        self._show_dataframe_toolbar_buttons()

    def _on_result_tab_close_requested(self, index: int):
        """Fecha aba.

        - Aba primaria (index 0): nao pode ser removida (hospeda a stack
          com table/image/html/json), entao fechar limpa o conteudo e
          colapsa todas as abas secundarias (equivalente a clear()).
        - Aba secundaria: remove e libera memoria.
        """
        tabs = self._result_tabs
        if index <= 0:
            self.clear()
            return
        page = tabs.widget(index)
        chart_index = -1
        if self._is_chart_page(page):
            chart_index = getattr(page, "_chart_index", -1)
            self._dispose_chart_page(page)
        blocker = QSignalBlocker(tabs)
        tabs.removeTab(index)
        if page in self._secondary_pages:
            self._secondary_pages.remove(page)
        if self._is_chart_page(page) and chart_index >= 0:
            self._remove_chart_config(chart_index)
        if page is not None:
            page.deleteLater()
        del blocker
        if tabs.count() <= 1:
            tabs.tabBar().setVisible(True)

    def _apply_result_tabs_style(self):
        """Aplica visual coerente com as abas principais (session_tabs)."""
        try:
            from src.design_system.tokens import get_colors, RADIUS
            colors = get_colors()
            self._result_tabs.setStyleSheet(f"""
                QTabWidget::pane {{
                    border: none;
                    border-top: 1px solid {colors.border_muted};
                    background-color: {colors.bg_primary};
                }}
                QTabWidget::tab-bar {{
                    alignment: left;
                }}
                QTabBar {{
                    background-color: {colors.bg_secondary};
                    border: none;
                }}
                QTabBar::tab {{
                    background-color: transparent;
                    color: {colors.text_secondary};
                    padding: 10px 16px;
                    padding-right: 28px;
                    border: none;
                    border-bottom: 2px solid transparent;
                    margin-right: 2px;
                    min-width: 80px;
                    font-size: 13px;
                }}
                QTabBar::tab:selected {{
                    background-color: {colors.bg_primary};
                    color: {colors.text_inverse};
                    border-bottom: 3px solid transparent;
                    border-top-left-radius: {RADIUS.radius_sm}px;
                    border-top-right-radius: {RADIUS.radius_sm}px;
                }}
                QTabBar::tab:hover:!selected {{
                    background-color: {colors.bg_tertiary};
                    color: {colors.text_primary};
                }}
            """)
            for index in range(self._result_tabs.count()):
                self._setup_result_tab_close_button(index)
            accessory = getattr(self, "_result_tab_accessory", None)
            if accessory is not None:
                accessory.reposition()
        except Exception:
            # Fallback silencioso (testes sem design_system disponivel)
            pass

    def _setup_result_tab_close_button(self, index: int):
        """Close controls are painted by ResultTabBar to avoid fragile child widgets."""
        tab_bar = self._result_tabs.tabBar()
        if hasattr(tab_bar, "update"):
            tab_bar.update(tab_bar.tabRect(index))

    def _is_chart_page(self, page) -> bool:
        return getattr(page, "_page_kind", "") == "chart"

    def _dispose_chart_page(self, page):
        if not self._is_chart_page(page):
            return
        page._disposed = True
        page._render_pending = False
        chart_view = getattr(page, "_chart_view", None)
        if chart_view is not None:
            chart_view.cleanup()
        self._chart_render_queue = [queued for queued in self._chart_render_queue if queued is not page]
        if page in self._chart_pages:
            self._chart_pages.remove(page)

    def _start_queued_chart_render(self, page_key: int):
        page = self._chart_page_by_key(page_key)
        if page is not None and not getattr(page, "_disposed", False):
            self._start_chart_render(page)

    def _chart_tab_label(self, chart_index: int, config: dict = None) -> str:
        config = config if isinstance(config, dict) else {}
        title = str(config.get("title", "") or "").strip()
        if title:
            return title
        return S.visualization.chart_tab_label.format(n=chart_index + 1)

    def list_visualizations(self) -> dict:
        """Return chart configs and available tabular sources for assistant tools."""
        return {
            "active_index": self._active_chart_index if self._chart_configs else None,
            "visualizations": [
                self._visualization_payload(index, config)
                for index, config in enumerate(self._chart_configs)
                if isinstance(config, dict)
            ],
            "sources": self._visualization_sources_payload(),
        }

    def get_visualization_config(self, chart_index: int) -> dict:
        """Return one chart configuration by index."""
        chart_index = int(chart_index)
        if not 0 <= chart_index < len(self._chart_configs):
            raise IndexError("visualization index out of range")
        return self._visualization_payload(chart_index, self._chart_configs[chart_index])

    def create_visualization(self, config: dict) -> dict:
        """Create a chart tab from a normalized config and return its metadata."""
        if not isinstance(config, dict):
            raise ValueError("config must be an object")
        source_df, source_label = self._source_dataframe_for_chart(config)
        if source_df is None:
            raise ValueError("no dataframe source is available for visualization")
        normalized = self._normalize_visualization_config(config, source_df, source_label)
        chart_index = len(self._chart_configs)
        self._chart_configs.append(normalized)
        self._add_visualization_tab(normalized, chart_index, make_current=True)
        self._active_chart_index = chart_index
        self._persist_view_state()
        return self._visualization_payload(chart_index, normalized)

    def update_visualization(self, chart_index: int, config: dict) -> dict:
        """Update an existing chart configuration and rerender its tab."""
        chart_index = int(chart_index)
        if not 0 <= chart_index < len(self._chart_configs):
            raise IndexError("visualization index out of range")
        if not isinstance(config, dict):
            raise ValueError("config must be an object")

        merged = dict(self._chart_configs[chart_index])
        merged.update(config)
        source_df, source_label = self._source_dataframe_for_chart(merged)
        if source_df is None:
            raise ValueError("no dataframe source is available for visualization")
        normalized = self._normalize_visualization_config(merged, source_df, source_label)
        self._chart_configs[chart_index] = normalized

        page = next((page for page in self._chart_pages if getattr(page, "_chart_index", -1) == chart_index), None)
        if page is None:
            page = self._add_visualization_tab(normalized, chart_index, make_current=True)
        elif page is not None:
            page._config = dict(normalized)
            page._source_df = source_df
            page._source_label = source_label
            page._image_bytes = None
            page._chart_html = None
            page._chart_ready = False
            self._render_visualization_page(page)
            tab_index = self._result_tabs.indexOf(page)
            if tab_index >= 0:
                self._result_tabs.setTabText(tab_index, self._chart_tab_label(chart_index, normalized))
                self._result_tabs.setCurrentIndex(tab_index)

        self._active_chart_index = chart_index
        self._persist_view_state()
        return self._visualization_payload(chart_index, normalized)

    def delete_visualization(self, chart_index: int) -> dict:
        """Delete a chart by index and return the remaining chart list."""
        chart_index = int(chart_index)
        if not 0 <= chart_index < len(self._chart_configs):
            raise IndexError("visualization index out of range")
        page = next((page for page in self._chart_pages if getattr(page, "_chart_index", -1) == chart_index), None)
        if page is not None:
            tab_index = self._result_tabs.indexOf(page)
            if tab_index >= 0:
                self._on_result_tab_close_requested(tab_index)
            else:
                self._chart_pages.remove(page)
                self._dispose_chart_page(page)
                page.deleteLater()
                self._remove_chart_config(chart_index)
        else:
            self._remove_chart_config(chart_index)
        return self.list_visualizations()

    def export_visualization(self, chart_index: int, file_path: str) -> dict:
        """Export a rendered chart image to a path."""
        chart_index = int(chart_index)
        if not 0 <= chart_index < len(self._chart_configs):
            raise IndexError("visualization index out of range")
        page = next((page for page in self._chart_pages if getattr(page, "_chart_index", -1) == chart_index), None)
        if page is None:
            page = self._add_visualization_tab(self._chart_configs[chart_index], chart_index, make_current=False)
        if page is None:
            raise ValueError("visualization could not be opened")
        chart_html = getattr(page, "_chart_html", None)
        image_bytes = getattr(page, "_image_bytes", None)
        if not chart_html and not image_bytes:
            self._render_visualization_page(page)
            raise ValueError("visualization is rendering; retry export after the chart appears")

        file_path = os.path.abspath(os.path.expanduser(str(file_path or "").strip()))
        if not file_path:
            raise ValueError("file_path is required")
        if chart_html:
            if not os.path.splitext(file_path)[1]:
                file_path += ".html"
            os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as html_file:
                html_file.write(chart_html)
            payload_bytes = len(chart_html.encode("utf-8"))
        else:
            if not os.path.splitext(file_path)[1]:
                file_path += ".png"
            os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
            with open(file_path, "wb") as image_file:
                image_file.write(image_bytes)
            payload_bytes = len(image_bytes)
        return {
            "path": file_path,
            "bytes": payload_bytes,
            "visualization": self._visualization_payload(chart_index, self._chart_configs[chart_index]),
        }

    def _visualization_payload(self, chart_index: int, config: dict) -> dict:
        config = dict(config or {})
        return {
            "index": chart_index,
            "title": self._chart_tab_label(chart_index, config),
            "config": config,
            "rendered": any(
                getattr(page, "_chart_index", -1) == chart_index and self._chart_page_has_content(page)
                for page in self._chart_pages
            ),
        }

    def _visualization_sources_payload(self) -> list:
        tabs = getattr(self, "_result_tabs", None)
        if tabs is None:
            return []
        sources = []
        for index in range(tabs.count()):
            page = tabs.widget(index)
            if self._is_chart_page(page):
                continue
            df = self._primary_df if index == 0 else getattr(page, "_df", None)
            if df is None:
                continue
            sources.append({
                "label": tabs.tabText(index),
                "rows": int(len(df)),
                "columns": [str(column) for column in df.columns],
                "numeric_columns": [str(column) for column in df.columns if pd.api.types.is_numeric_dtype(df[column])],
            })
        return sources

    def _remove_chart_config(self, chart_index: int):
        if 0 <= chart_index < len(self._chart_configs):
            self._chart_configs.pop(chart_index)
            self._active_chart_index = max(0, min(self._active_chart_index, len(self._chart_configs) - 1))
            self._sync_chart_page_indexes()
            self._persist_view_state()

    def _sync_chart_page_indexes(self):
        for new_index, page in enumerate(self._chart_pages):
            page._chart_index = new_index
            tab_index = self._result_tabs.indexOf(page)
            if tab_index >= 0:
                self._result_tabs.setTabText(tab_index, self._chart_tab_label(new_index, getattr(page, "_config", {})))

    def _current_data_source_for_visualization(self):
        tabs = getattr(self, "_result_tabs", None)
        if tabs is None or tabs.count() == 0:
            return None, "", None

        index = tabs.currentIndex()
        page = tabs.widget(index) if index >= 0 else None
        if self._is_chart_page(page):
            return getattr(page, "_source_df", None), getattr(page, "_source_label", ""), getattr(page, "_chart_index", None)
        if index > 0 and page is not None:
            return getattr(page, "_df", None), tabs.tabText(index), None
        return self._primary_df, tabs.tabText(0), None

    def _source_dataframe_for_chart(self, config: dict):
        tabs = getattr(self, "_result_tabs", None)
        source_label = str(config.get("source_label", "") or "") if isinstance(config, dict) else ""
        if tabs is None:
            return self._primary_df, source_label

        if source_label:
            for index in range(tabs.count()):
                page = tabs.widget(index)
                if self._is_chart_page(page):
                    continue
                if tabs.tabText(index) != source_label:
                    continue
                if index == 0:
                    return self._primary_df, source_label
                return getattr(page, "_df", None), source_label

        current_df, current_label, _ = self._current_data_source_for_visualization()
        if current_df is not None:
            return current_df, current_label
        return self._primary_df, tabs.tabText(0) if tabs.count() else source_label

    def _restore_chart_tabs_for_current_data(self):
        tabs = getattr(self, "_result_tabs", None)
        if tabs is None:
            return

        blocker = QSignalBlocker(tabs)
        for page in list(self._chart_pages):
            tab_index = tabs.indexOf(page)
            if tab_index >= 0:
                self._dispose_chart_page(page)
                tabs.removeTab(tab_index)
            page.deleteLater()
        self._chart_pages.clear()

        for chart_index, config in enumerate(list(self._chart_configs)):
            self._add_visualization_tab(config, chart_index, make_current=False)
        if tabs.count() > 0:
            tabs.setCurrentIndex(0)
        del blocker

    def _add_visualization_tab(self, config: dict, chart_index: int, make_current: bool = True):
        source_df, source_label = self._source_dataframe_for_chart(config)
        if source_df is None:
            return None

        normalized = self._normalize_visualization_config(config, source_df, source_label)
        if 0 <= chart_index < len(self._chart_configs):
            self._chart_configs[chart_index] = normalized

        page = self._create_visualization_page(normalized, chart_index, source_df, source_label)
        self._chart_pages.append(page)
        index = self._result_tabs.addTab(page, self._chart_tab_label(chart_index, normalized))
        self._setup_result_tab_close_button(index)
        self._result_tabs.tabBar().setVisible(True)
        if make_current:
            self._result_tabs.setCurrentIndex(index)
        self._render_visualization_page(page)
        accessory = getattr(self, "_result_tab_accessory", None)
        if accessory is not None:
            accessory.reposition()
        return page

    def _create_visualization_page(self, config: dict, chart_index: int, source_df: pd.DataFrame, source_label: str):
        from src.design_system.tokens import get_colors
        colors = get_colors()

        page = QWidget()
        page._page_kind = "chart"
        page._chart_index = chart_index
        page._config = dict(config)
        page._source_df = source_df
        page._source_label = source_label
        page._image_bytes = None
        page._chart_html = None
        page._chart_ready = False
        page._rendering = False
        page._render_pending = False
        page._render_generation = 0
        page._active_render_generation = None

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QFrame(page)
        toolbar.setObjectName("chartPageToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        title = QLabel(self._chart_tab_label(chart_index, config))
        title.setObjectName("chartPageTitle")
        toolbar_layout.addWidget(title, 1)

        edit_button = QToolButton(toolbar)
        edit_button.setObjectName("chartEditButton")
        edit_button.setIcon(qta.icon("mdi.pencil", color=colors.text_secondary, scale_factor=0.8))
        edit_button.setToolTip(S.visualization.edit_chart)
        edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_button.clicked.connect(lambda checked=False, p=page: self._edit_visualization_page(p))
        toolbar_layout.addWidget(edit_button)

        refresh_button = QToolButton(toolbar)
        refresh_button.setObjectName("chartRefreshButton")
        refresh_button.setIcon(qta.icon("mdi.refresh", color=colors.text_secondary, scale_factor=0.8))
        refresh_button.setToolTip(S.visualization.refresh_chart)
        refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_button.clicked.connect(lambda checked=False, p=page: self._render_visualization_page(p))
        toolbar_layout.addWidget(refresh_button)

        layout.addWidget(toolbar)

        status = QLabel(page)
        status.setObjectName("chartStatusLabel")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.setWordWrap(True)
        status.setText(S.visualization.chart_pending)
        status.setVisible(True)

        chart_view = PlotlyChartView(page)
        chart_view.setMinimumSize(640, 360)
        layout.addWidget(chart_view, 1)
        layout.addWidget(status)

        page._title_label = title
        page._status_label = status
        page._chart_view = chart_view

        page.setStyleSheet(f"""
            QFrame#chartPageToolbar {{
                background-color: {colors.bg_primary};
                border-bottom: 1px solid {colors.border_muted};
            }}
            QLabel#chartPageTitle {{
                color: {colors.text_primary};
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#chartStatusLabel {{
                color: {colors.text_secondary};
                padding: 12px;
            }}
            QToolButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 5px;
                padding: 4px;
            }}
            QToolButton:hover {{
                background-color: {colors.bg_tertiary};
                border-color: {colors.border_default};
            }}
        """)

        return page

    @staticmethod
    def _chart_page_has_content(page) -> bool:
        return bool(getattr(page, "_chart_html", None) or getattr(page, "_image_bytes", None))

    def _edit_visualization_page(self, page):
        if not self._is_chart_page(page):
            return
        tab_index = self._result_tabs.indexOf(page)
        if tab_index >= 0:
            self._result_tabs.setCurrentIndex(tab_index)
        self._open_visualization_editor()

    def _show_chart_toolbar_buttons(self):
        self._hide_all_toolbar_buttons()
        self.btn_save_image.setVisible(True)

    def _render_visualization_page(self, page):
        if not self._is_chart_page(page) or getattr(page, "_disposed", False):
            return
        if getattr(page, "_rendering", False):
            page._render_generation = int(getattr(page, "_render_generation", 0) or 0) + 1
            page._render_pending = True
            if not self._chart_page_has_content(page):
                page._status_label.setText(S.visualization.chart_rendering)
                page._status_label.setVisible(True)
            return
        page._render_pending = False
        self._start_chart_render(page)

    def _chart_page_by_key(self, page_key: int):
        for page in self._chart_pages:
            if id(page) == page_key:
                return page
        return None

    def _start_chart_render(self, page):
        if not self._is_chart_page(page) or getattr(page, "_disposed", False) or getattr(page, "_rendering", False):
            return

        if self._active_chart_render_job is not None:
            page._render_pending = True
            if page not in self._chart_render_queue:
                self._chart_render_queue.append(page)
            if not self._chart_page_has_content(page):
                page._status_label.setText(S.visualization.chart_rendering)
                page._status_label.setVisible(True)
            return

        page._rendering = True
        page._render_pending = False
        page._render_generation = int(getattr(page, "_render_generation", 0) or 0) + 1
        generation = page._render_generation
        page._active_render_generation = generation
        page_key = id(page)
        page._status_label.setText(S.visualization.chart_rendering)
        page._status_label.setVisible(not self._chart_page_has_content(page))

        source_df = page._source_df.copy(deep=True) if page._source_df is not None else page._source_df
        thread = QThread(self)
        worker = ChartRenderWorker(page_key, generation, source_df, page._config, self._render_chart_image)
        worker.moveToThread(thread)

        job = {"thread": thread, "worker": worker, "page_key": page_key, "generation": generation}
        self._active_chart_render_job = job
        self._chart_render_jobs.append(job)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_chart_render_complete)
        worker.error.connect(self._on_chart_render_error)
        worker.done.connect(self._on_chart_render_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda job=job: self._chart_render_jobs.remove(job) if job in self._chart_render_jobs else None)
        thread.start()

    def _on_chart_render_complete(self, page_key: int, generation: int, chart_payload):
        page = self._chart_page_by_key(page_key)
        if page is None or getattr(page, "_disposed", False):
            return
        if generation != getattr(page, "_render_generation", None):
            return
        try:
            page._chart_ready = True
            if isinstance(chart_payload, str):
                page._chart_html = chart_payload
                page._image_bytes = None
                chart_view = getattr(page, "_chart_view", None)
                if chart_view is not None and not getattr(chart_view, "_cleaned_up", False):
                    chart_view.set_html(chart_payload)
                if self._result_tabs.currentWidget() is page:
                    self._current_image_bytes = None
            else:
                image = QImage()
                if not image.loadFromData(chart_payload):
                    raise ValueError(S.visualization.chart_error_image)
                page._chart_html = None
                page._image_bytes = chart_payload
                page._chart_view.clear()
                if self._result_tabs.currentWidget() is page:
                    self._current_image_bytes = chart_payload
            page._status_label.clear()
            page._status_label.setVisible(False)
            page._title_label.setText(self._chart_tab_label(page._chart_index, page._config))
        except Exception as exc:
            self._on_chart_render_error(page_key, generation, str(exc))

    def _on_chart_render_error(self, page_key: int, generation: int, error: str):
        page = self._chart_page_by_key(page_key)
        if page is None or getattr(page, "_disposed", False):
            return
        if generation != getattr(page, "_render_generation", None):
            return
        page._image_bytes = None
        page._chart_html = None
        page._chart_ready = False
        chart_view = getattr(page, "_chart_view", None)
        if chart_view is not None and not getattr(chart_view, "_cleaned_up", False):
            chart_view.clear()
        page._status_label.setText(S.visualization.chart_error.format(error=error))
        page._status_label.setVisible(True)

    def _on_chart_render_done(self, page_key: int, generation: int):
        active_job = self._active_chart_render_job
        if active_job and active_job.get("page_key") == page_key and active_job.get("generation") == generation:
            self._active_chart_render_job = None

        page = self._chart_page_by_key(page_key)
        if page is not None and generation == getattr(page, "_active_render_generation", None):
            page._rendering = False
            page._active_render_generation = None
            if getattr(page, "_render_pending", False) and not getattr(page, "_disposed", False):
                page._render_pending = False
                QTimer.singleShot(0, lambda key=page_key: self._start_queued_chart_render(key))
                return

        while self._chart_render_queue:
            queued_page = self._chart_render_queue.pop(0)
            if queued_page in self._chart_pages and not getattr(queued_page, "_disposed", False):
                queued_page._render_pending = False
                QTimer.singleShot(0, lambda key=id(queued_page): self._start_queued_chart_render(key))
                break

    def _normalize_visualization_config(self, config: dict, df: pd.DataFrame = None, source_label: str = "") -> dict:
        config = dict(config or {})
        df_columns = [str(column) for column in df.columns] if df is not None else []
        numeric_columns = [str(column) for column in df.columns if df is not None and pd.api.types.is_numeric_dtype(df[column])]

        x_column = str(config.get("x_column", "") or "")
        if x_column not in df_columns:
            x_column = next((column for column in df_columns if column not in numeric_columns), "")

        y_columns = [str(column) for column in config.get("y_columns", []) or [] if str(column) in df_columns]
        if not y_columns:
            y_columns = [column for column in numeric_columns if column != x_column][:1]
        if not y_columns:
            y_columns = [column for column in df_columns if column != x_column][:1]
        if not y_columns and df_columns:
            y_columns = df_columns[:1]

        group_by = str(config.get("group_by", "") or "")
        if group_by not in df_columns:
            group_by = ""

        chart_type = str(config.get("type", "bar") or "bar")
        if chart_type not in {"bar", "line", "scatter", "area", "pie"}:
            chart_type = "bar"
        aggregation = str(config.get("aggregation", "sum") or "sum")
        if aggregation not in {"sum", "mean", "count", "min", "max"}:
            aggregation = "sum"
        stacking = str(config.get("stacking", "none") or "none")
        if stacking not in {"none", "stacked", "percent"}:
            stacking = "none"
        nulls = str(config.get("nulls", "zero") or "zero")
        if nulls not in {"zero", "drop", "keep"}:
            nulls = "zero"
        sort_mode = str(config.get("sort", "original") or "original")
        if sort_mode not in {"original", "x_asc", "y_desc"}:
            sort_mode = "original"

        try:
            label_decimals = int(config.get("label_decimals", 1) or 0)
        except (TypeError, ValueError):
            label_decimals = 1

        custom_colors = config.get("custom_colors", [])
        if not isinstance(custom_colors, list):
            custom_colors = [color.strip() for color in str(custom_colors or "").split(",") if color.strip()]

        line_style = str(config.get("line_style", "solid") or "solid")
        if line_style not in {"solid", "dashed", "dotted", "dashdot"}:
            line_style = "solid"

        return {
            "type": chart_type,
            "title": str(config.get("title", "") or "").strip(),
            "horizontal": bool(config.get("horizontal", False)),
            "x_column": x_column,
            "x_label": str(config.get("x_label", "") or "").strip(),
            "y_columns": y_columns,
            "y_label": str(config.get("y_label", "") or "").strip(),
            "aggregation": aggregation,
            "group_by": group_by,
            "stacking": stacking,
            "normalize": bool(config.get("normalize", False)),
            "nulls": nulls,
            "sort": sort_mode,
            "palette": str(config.get("palette", "default") or "default"),
            "custom_colors": [str(color).strip() for color in custom_colors if str(color).strip()],
            "text_color": self._valid_chart_color(config.get("text_color", "")),
            "label_color": self._valid_chart_color(config.get("label_color", "")),
            "background_color": self._valid_chart_color(config.get("background_color", "")),
            "grid_color": self._valid_chart_color(config.get("grid_color", "")),
            "axis_color": self._valid_chart_color(config.get("axis_color", "")),
            "show_grid": bool(config.get("show_grid", True)),
            "show_axis_line": bool(config.get("show_axis_line", False)),
            "show_line": bool(config.get("show_line", True)),
            "show_markers": bool(config.get("show_markers", True)),
            "line_style": line_style,
            "line_width": self._bounded_chart_int(config.get("line_width", 2), 1, 10, 2),
            "marker_size": self._bounded_chart_int(config.get("marker_size", 5), 1, 18, 5),
            "bar_opacity": self._bounded_chart_int(config.get("bar_opacity", 94), 10, 100, 94),
            "area_opacity": self._bounded_chart_int(config.get("area_opacity", 20), 5, 90, 20),
            "show_legend": bool(config.get("show_legend", True)),
            "show_data_labels": bool(config.get("show_data_labels", False)),
            "label_decimals": max(0, min(6, label_decimals)),
            "source_label": str(config.get("source_label", source_label) or source_label or ""),
        }

    def _resolve_df_column(self, df: pd.DataFrame, column_name: str):
        if df is None or not column_name:
            return None
        for column in df.columns:
            if str(column) == str(column_name):
                return column
        return None

    @staticmethod
    def _bounded_chart_int(value: Any, minimum: int, maximum: int, default: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(maximum, number))

    @staticmethod
    def _valid_chart_color(value: Any, fallback: str = "") -> str:
        color = str(value or "").strip()
        if not color:
            return fallback
        try:
            from matplotlib.colors import is_color_like
            return color if is_color_like(color) else fallback
        except Exception:
            return color if color.startswith("#") else fallback

    def _chart_color(self, config: dict, key: str, fallback: str) -> str:
        return self._valid_chart_color(config.get(key, ""), fallback)

    def _chart_alpha(self, config: dict, key: str, default_percent: int) -> float:
        value = self._bounded_chart_int(config.get(key, default_percent), 0, 100, default_percent)
        return value / 100.0

    @staticmethod
    def _chart_line_style(config: dict) -> str:
        return {
            "solid": "-",
            "dashed": "--",
            "dotted": ":",
            "dashdot": "-.",
        }.get(str(config.get("line_style", "solid") or "solid"), "-")

    def _safe_chart_label(self, value: Any) -> str:
        text = str(value)
        text = "".join(char if char.isprintable() else " " for char in text).strip()
        if len(text) > 36:
            text = text[:33] + "..."
        return text or " "

    def _chart_max_points(self, config: dict) -> int:
        chart_type = str(config.get("type", "bar") or "bar")
        if chart_type == "pie":
            return 24
        if chart_type in {"line", "scatter", "area"}:
            return 500
        return 120

    def _chart_layout_margins(self, labels: list, config: dict) -> dict:
        chart_type = str(config.get("type", "bar") or "bar")
        if chart_type == "pie":
            return {"left": 0.06, "right": 0.94, "top": 0.90, "bottom": 0.08}

        has_title = bool(str(config.get("title", "") or "").strip())
        has_many_labels = len(labels) > 8
        longest_label = max((len(str(label)) for label in labels), default=0)
        horizontal = bool(config.get("horizontal", False)) and chart_type == "bar"

        margins = {
            "left": 0.08,
            "right": 0.98,
            "top": 0.86 if has_title else 0.92,
            "bottom": 0.13,
        }
        if horizontal:
            margins["left"] = 0.18 if longest_label <= 22 else 0.25
            margins["bottom"] = 0.12
        elif has_many_labels:
            margins["bottom"] = 0.26 if longest_label <= 18 else 0.34
        return margins

    def _chart_palette(self, config: dict, count: int) -> list:
        try:
            from matplotlib.colors import is_color_like
        except Exception:
            is_color_like = lambda color: isinstance(color, str) and bool(str(color).strip())

        from src.services.visualization import resolve_palette

        return resolve_palette(config, count, is_color_like=is_color_like)

    def _render_chart_image(self, df: pd.DataFrame, config: dict) -> str:
        """Render interactive Plotly chart HTML (name kept for worker compatibility)."""
        from src.services.visualization.plotly_charts import render_session_chart_html

        return render_session_chart_html(df, config)

    def _prepare_chart_data(self, df: pd.DataFrame, config: dict):
        from src.services.visualization.chart_data import prepare_chart_data

        return prepare_chart_data(df, config)

    def _plot_cartesian_chart(self, axis, plot_data: pd.DataFrame, labels: list, config: dict, colors: list):
        import numpy as np

        chart_type = config.get("type", "bar")
        positions = np.arange(len(labels))
        series_names = list(plot_data.columns)
        stacked = config.get("stacking") in {"stacked", "percent"}

        if chart_type == "bar":
            self._plot_bar_chart(axis, plot_data, positions, series_names, config, colors, stacked)
            return

        if chart_type == "area":
            values = [plot_data[name].fillna(0).astype(float).to_numpy() for name in series_names]
            if stacked:
                axis.stackplot(positions, values, labels=series_names, colors=colors[:len(series_names)], alpha=self._chart_alpha(config, "area_opacity", 74))
            else:
                for index, name in enumerate(series_names):
                    series = plot_data[name].fillna(0).astype(float).to_numpy()
                    axis.fill_between(positions, series, color=colors[index], alpha=self._chart_alpha(config, "area_opacity", 20))
                    if config.get("show_line", True):
                        axis.plot(
                            positions,
                            series,
                            color=colors[index],
                            linewidth=config.get("line_width", 2),
                            linestyle=self._chart_line_style(config),
                            solid_capstyle="round",
                            label=str(name),
                        )
            return

        show_line = bool(config.get("show_line", True))
        show_markers = bool(config.get("show_markers", True))
        if not show_line and not show_markers and chart_type != "scatter":
            show_line = True
        marker_size = int(config.get("marker_size", 5) or 5)
        line_width = int(config.get("line_width", 2) or 2)
        line_style = self._chart_line_style(config)
        label_color = self._chart_color(config, "label_color", self._chart_color(config, "text_color", "#d4d4d4"))
        for index, name in enumerate(series_names):
            values = plot_data[name].astype(float).to_numpy()
            if chart_type == "scatter":
                axis.scatter(positions, values, color=colors[index], s=max(12, marker_size * marker_size * 2), alpha=0.92, edgecolors="none", label=str(name))
            elif not show_line:
                axis.scatter(positions, values, color=colors[index], s=max(12, marker_size * marker_size * 2), alpha=0.92, edgecolors="none", label=str(name))
            else:
                axis.plot(
                    positions,
                    values,
                    color=colors[index],
                    marker="o" if show_markers else None,
                    markersize=marker_size,
                    linewidth=line_width,
                    linestyle=line_style,
                    solid_capstyle="round",
                    label=str(name),
                )
            if config.get("show_data_labels") and len(values) <= 36:
                for x_pos, y_value in zip(positions, values):
                    axis.annotate(
                        self._format_chart_number(y_value, config),
                        (x_pos, y_value),
                        textcoords="offset points",
                        xytext=(0, 7),
                        ha="center",
                        fontsize=8,
                        color=label_color,
                    )

    def _plot_bar_chart(self, axis, plot_data: pd.DataFrame, positions, series_names: list, config: dict, colors: list, stacked: bool):
        import numpy as np
        from src.services.visualization.chart_style import lighten_edge_color

        horizontal = bool(config.get("horizontal", False))
        bar_alpha = self._chart_alpha(config, "bar_opacity", 94)
        if stacked:
            base = np.zeros(len(positions))
            for index, name in enumerate(series_names):
                values = plot_data[name].fillna(0).astype(float).to_numpy()
                fill = colors[index % len(colors)]
                edge = lighten_edge_color(fill, 0.1)
                if horizontal:
                    bars = axis.barh(
                        positions,
                        values,
                        left=base,
                        color=fill,
                        edgecolor=edge,
                        linewidth=0.5,
                        alpha=bar_alpha,
                        label=str(name),
                    )
                else:
                    bars = axis.bar(
                        positions,
                        values,
                        bottom=base,
                        color=fill,
                        edgecolor=edge,
                        linewidth=0.5,
                        alpha=bar_alpha,
                        label=str(name),
                    )
                self._label_bar_container(axis, bars, values, config)
                base = base + values
            return

        width = min(0.72, 0.78 / max(1, len(series_names)))
        offset_start = -width * (len(series_names) - 1) / 2
        for index, name in enumerate(series_names):
            values = plot_data[name].fillna(0).astype(float).to_numpy()
            offsets = positions + offset_start + index * width
            fill = colors[index % len(colors)]
            edge = lighten_edge_color(fill, 0.1)
            if horizontal:
                bars = axis.barh(
                    offsets,
                    values,
                    height=width,
                    color=fill,
                    edgecolor=edge,
                    linewidth=0.5,
                    alpha=bar_alpha,
                    label=str(name),
                )
            else:
                bars = axis.bar(
                    offsets,
                    values,
                    width=width,
                    color=fill,
                    edgecolor=edge,
                    linewidth=0.5,
                    alpha=bar_alpha,
                    label=str(name),
                )
            self._label_bar_container(axis, bars, values, config)

    def _plot_pie_chart(self, axis, plot_data: pd.DataFrame, config: dict, colors: list):
        from src.design_system.tokens import get_chart_colors
        chart_colors = get_chart_colors()

        series = plot_data.iloc[:, 0].fillna(0).astype(float)
        series = series[series > 0]
        if series.empty:
            raise ValueError(S.visualization.chart_no_data)

        autopct = None
        if config.get("show_data_labels"):
            decimals = int(config.get("label_decimals", 1) or 0)
            autopct = f"%1.{decimals}f%%"
        pie_result = axis.pie(
            series.to_numpy(),
            labels=[str(label) for label in series.index],
            autopct=autopct,
            colors=self._chart_palette(config, len(series)),
            startangle=90,
            counterclock=False,
            pctdistance=0.78,
            wedgeprops={"width": 0.72, "edgecolor": self._chart_color(config, "background_color", chart_colors.figure_bg), "linewidth": 2},
        )
        texts = pie_result[1]
        autotexts = pie_result[2] if len(pie_result) > 2 else []
        text_color = self._chart_color(config, "text_color", chart_colors.text)
        label_color = self._chart_color(config, "label_color", text_color)
        for text in texts:
            text.set_color(text_color)
            text.set_fontsize(9)
        for text in autotexts:
            text.set_color(label_color)
            text.set_fontsize(9)
        axis.axis("equal")

    def _label_bar_container(self, axis, bars, values, config: dict):
        if not config.get("show_data_labels"):
            return
        try:
            axis.bar_label(
                bars,
                labels=[self._format_chart_number(value, config) for value in values],
                padding=3,
                fontsize=8,
                color=self._chart_color(config, "label_color", self._chart_color(config, "text_color", "#d4d4d4")),
            )
        except Exception:
            return

    def _style_cartesian_axis(self, axis, labels: list, config: dict):
        from src.design_system.tokens import get_chart_colors
        chart_colors = get_chart_colors()

        if config.get("horizontal", False) and config.get("type") == "bar":
            ticks, tick_labels = self._chart_tick_subset(labels)
            axis.set_yticks(ticks)
            axis.set_yticklabels(tick_labels)
        else:
            ticks, tick_labels = self._chart_tick_subset(labels)
            axis.set_xticks(ticks)
            rotation = 35 if len(labels) > 8 else 0
            axis.set_xticklabels(tick_labels, rotation=rotation, ha="right" if rotation else "center")

        text_color = self._chart_color(config, "text_color", chart_colors.text)
        grid_color = self._chart_color(config, "grid_color", chart_colors.grid)
        axis_color = self._chart_color(config, "axis_color", chart_colors.axes_edge)

        x_label = config.get("x_label") or config.get("x_column") or ""
        y_label = config.get("y_label") or ("%" if config.get("normalize") or config.get("stacking") == "percent" else "")
        axis.set_xlabel(x_label, color=text_color, labelpad=10)
        axis.set_ylabel(y_label, color=text_color, labelpad=10)
        grid_axis = "x" if config.get("horizontal", False) and config.get("type") == "bar" else "y"
        if bool(config.get("show_grid", True)):
            axis.grid(True, axis=grid_axis, color=grid_color, alpha=0.42, linewidth=0.65, linestyle="--")
        else:
            axis.grid(False, axis=grid_axis)
        axis.set_axisbelow(True)
        axis.tick_params(axis="both", colors=text_color, labelsize=9, length=0)
        show_axis_line = bool(config.get("show_axis_line", False))
        for side in ("top", "right"):
            axis.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            axis.spines[side].set_visible(show_axis_line)
            axis.spines[side].set_color(axis_color)
        axis.title.set_color(text_color)
        axis.margins(x=0.03, y=0.14)

    def _chart_tick_subset(self, labels: list, max_ticks: int = 24):
        if len(labels) <= max_ticks:
            return list(range(len(labels))), labels
        step = max(1, (len(labels) + max_ticks - 1) // max_ticks)
        ticks = list(range(0, len(labels), step))
        return ticks, [labels[index] for index in ticks]

    def _format_chart_number(self, value: Any, config: dict) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        decimals = int(config.get("label_decimals", 1) or 0)
        return f"{number:,.{decimals}f}"

    def _on_row_limit_changed(self, value: int):
        """Quando usuario muda o limite de linhas no spinner."""
        self._save_display_limit(value)
        if self._get_active_source_df() is not None:
            self._apply_active_dataframe_view(self._current_result_label())

    def _clear_grid_filter(self):
        """Limpa todos os filtros de coluna do grid."""
        self._column_filters.clear()
        if self._get_active_source_df() is not None:
            self._apply_active_dataframe_view(self._current_result_label())
        self._refresh_filter_chips()

    def _set_column_filter(self, column, filter_value):
        """Define ou remove filtro especifico de coluna."""
        if isinstance(filter_value, dict):
            spec = self._normalize_filter_spec(filter_value)
            if self._filter_spec_is_empty(spec):
                self._column_filters.pop(column, None)
            else:
                self._column_filters[column] = spec
        else:
            value = str(filter_value or "").strip()
            if value:
                self._column_filters[column] = {"type": "text", "operator": "contains", "value": value}
            else:
                self._column_filters.pop(column, None)
        if self._get_active_source_df() is not None:
            self._apply_active_dataframe_view(self._current_result_label())
        self._refresh_filter_chips()

    def _remove_column_filter(self, column):
        """Remove filtro de uma coluna."""
        self._column_filters.pop(column, None)
        if self._get_active_source_df() is not None:
            self._apply_active_dataframe_view(self._current_result_label())
        self._refresh_filter_chips()

    def _get_active_source_df(self) -> Optional[pd.DataFrame]:
        """Retorna o DataFrame original da aba ativa."""
        tabs = getattr(self, "_result_tabs", None)
        if tabs is None or tabs.currentIndex() <= 0:
            return self._primary_df
        page = tabs.widget(tabs.currentIndex())
        return getattr(page, "_df", None)

    def _current_result_label(self) -> str:
        """Retorna o rotulo da aba ativa para mensagens do grid."""
        tabs = getattr(self, "_result_tabs", None)
        if tabs is not None and tabs.count() > 0 and tabs.currentIndex() >= 0:
            return tabs.tabText(tabs.currentIndex())
        return self._current_var_name()

    def _grid_view_cache_key(self, source_df: pd.DataFrame) -> tuple:
        filter_items = tuple(
            sorted((str(column), json.dumps(spec, sort_keys=True, default=str)) for column, spec in self._column_filters.items())
        )
        format_items = tuple(
            sorted((str(column), json.dumps(spec, sort_keys=True, default=str)) for column, spec in self._column_formats.items())
        )
        return (
            id(source_df),
            len(source_df),
            filter_items,
            format_items,
            int(self.row_limit_spin.value()),
        )

    def _can_use_cached_grid_view(self, source_df: pd.DataFrame, model, page=None) -> bool:
        if source_df is None or model is None:
            return False
        prepared = getattr(model, "_prepared", None)
        if prepared is None or not prepared.columns:
            return False
        cache_key = self._grid_view_cache_key(source_df)
        cached_key = getattr(page, "_grid_cache_key", None) if page is not None else self._primary_grid_cache_key
        if cached_key != cache_key:
            return False
        filtered_df = getattr(page, "_filtered_df", None) if page is not None else self._primary_filtered_df
        return filtered_df is not None

    def _activate_cached_grid_view(
        self,
        var_name: str,
        source_df: pd.DataFrame,
        model,
        table_view,
        page=None,
    ):
        """Reuse already prepared grid data when switching tabs."""
        self._cancel_grid_prepare_for_model(model)
        filtered_df = getattr(page, "_filtered_df", None) if page is not None else self._primary_filtered_df
        self.current_df = filtered_df
        prepared = model._prepared
        self._set_dataframe_info(
            var_name,
            prepared.filtered_row_count,
            prepared.total_row_count,
            len(prepared.columns),
            prepared.limited,
        )
        self._refresh_filter_chips()
        self._connect_active_selection_model()
        self._schedule_summarize_refresh()

    def _schedule_summarize_refresh(self):
        """Defer summarize panel refresh to keep tab switches responsive."""
        timer = self._summarize_refresh_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(48)
            timer.timeout.connect(self.grid_selection_changed.emit)
            self._summarize_refresh_timer = timer
        timer.start()

    def _update_filter_columns(self, df: Optional[pd.DataFrame]):
        """Remove filtros de coluna que nao existem mais no DataFrame ativo."""
        if df is not None:
            valid_columns = set(df.columns)
            self._column_filters = {
                column: value
                for column, value in self._column_filters.items()
                if column in valid_columns
            }

    def _filter_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filtra DataFrame pelos filtros de coluna ativos."""
        return filter_dataframe_with_specs(df, self._column_filters)

    def _show_grid_preparing(self, total_rows: int):
        preparing = getattr(S.results, "grid_preparing", "Preparing grid...")
        try:
            text = preparing.format(rows=f"{int(total_rows):,}")
        except (KeyError, IndexError):
            text = preparing
        self.info_label.setText(text)

    def _model_prepare_key(self, model) -> int:
        return id(model)

    def _cancel_grid_prepare_for_model(self, model):
        """Cancel in-flight prepare jobs for one grid model only."""
        if model is None:
            return
        model_key = self._model_prepare_key(model)
        self._model_prepare_generation[model_key] = self._model_prepare_generation.get(model_key, 0) + 1
        for job_id, job in list(self._grid_prepare_job_meta.items()):
            if job.get("model") is not model:
                continue
            thread = job.get("thread")
            if thread and thread.isRunning():
                thread.quit()
            self._grid_prepare_job_meta.pop(job_id, None)
            if self._active_grid_prepare_job is job:
                self._active_grid_prepare_job = None

    def _cancel_all_grid_prepare(self):
        """Cancel every in-flight grid prepare job."""
        for job_id, job in list(self._grid_prepare_job_meta.items()):
            thread = job.get("thread")
            if thread and thread.isRunning():
                thread.quit()
        self._grid_prepare_job_meta.clear()
        self._model_prepare_generation.clear()
        self._active_grid_prepare_job = None

    def _cancel_active_grid_prepare(self):
        self._cancel_all_grid_prepare()

    def _start_grid_prepare(
        self,
        source_df: pd.DataFrame,
        var_name: str,
        model: PandasModel,
        table_view: QTableView,
        page=None,
    ):
        self._cancel_grid_prepare_for_model(model)
        self._grid_prepare_job_serial += 1
        job_id = self._grid_prepare_job_serial
        model_key = self._model_prepare_key(model)
        model_generation = self._model_prepare_generation.get(model_key, 0)
        limit = self.row_limit_spin.value()

        thread = QThread(self)
        worker = GridPrepareWorker(
            job_id,
            source_df,
            self._column_filters,
            self._column_formats,
            limit,
        )
        worker.moveToThread(thread)

        job = {
            "thread": thread,
            "worker": worker,
            "var_name": var_name,
            "model": model,
            "model_key": model_key,
            "model_generation": model_generation,
            "table_view": table_view,
            "page": page,
        }
        self._active_grid_prepare_job = job
        self._grid_prepare_job_meta[job_id] = job

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_grid_prepare_finished)
        worker.error.connect(self._on_grid_prepare_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_grid_prepare_job(job))
        thread.start()

    def _clear_grid_prepare_job(self, job: dict):
        if self._active_grid_prepare_job is job:
            self._active_grid_prepare_job = None

    def _grid_prepare_job_is_current(self, job: dict) -> bool:
        if not job:
            return False
        model_key = job.get("model_key")
        if model_key is None:
            return False
        return job.get("model_generation") == self._model_prepare_generation.get(model_key)

    def _on_grid_prepare_finished(self, job_id: int, result: GridPrepareResult):
        job = self._grid_prepare_job_meta.pop(job_id, None)
        if not job or not self._grid_prepare_job_is_current(job):
            return
        self._apply_grid_prepare_result(
            result,
            var_name=job.get("var_name") or self._current_result_label(),
            model=job.get("model") or self.model,
            table_view=job.get("table_view") or self.table_view,
            page=job.get("page"),
        )

    def _on_grid_prepare_error(self, job_id: int, error: str):
        job = self._grid_prepare_job_meta.pop(job_id, None)
        if not job or not self._grid_prepare_job_is_current(job):
            return
        self.info_label.setText(str(error)[:240])

    def _apply_grid_prepare_result(
        self,
        result: GridPrepareResult,
        *,
        var_name: str,
        model: PandasModel,
        table_view: QTableView,
        page=None,
    ):
        prepared = result.prepared
        model.update_prepared(prepared)
        model.set_column_formats(self._column_formats)

        if page is not None:
            page._filtered_df = result.filtered_df
            source_df = getattr(page, "_df", None)
            if source_df is not None:
                page._grid_cache_key = self._grid_view_cache_key(source_df)
        else:
            self._primary_filtered_df = result.filtered_df
            if self._primary_df is not None:
                self._primary_grid_cache_key = self._grid_view_cache_key(self._primary_df)
        tabs = getattr(self, "_result_tabs", None)
        if page is None or (
            tabs is not None
            and tabs.currentIndex() > 0
            and tabs.widget(tabs.currentIndex()) is page
        ):
            self.current_df = result.filtered_df

        cols = len(prepared.columns)
        self._set_dataframe_info(
            var_name,
            prepared.filtered_row_count,
            prepared.total_row_count,
            cols,
            prepared.limited,
        )
        self._schedule_table_column_resize(table_view, prepared)
        self._refresh_filter_chips()
        if page is None or (
            tabs is not None
            and tabs.currentIndex() > 0
            and tabs.widget(tabs.currentIndex()) is page
        ) or (
            tabs is not None
            and tabs.currentIndex() == 0
            and page is None
        ):
            self._connect_active_selection_model()
            self._schedule_summarize_refresh()

    def _apply_grid_view_sync(
        self,
        source_df: pd.DataFrame,
        var_name: str,
        model: PandasModel,
        table_view: QTableView,
        page=None,
    ):
        limit = self.row_limit_spin.value()
        result = prepare_grid_data(source_df, self._column_filters, self._column_formats, limit)
        self._apply_grid_prepare_result(
            result,
            var_name=var_name,
            model=model,
            table_view=table_view,
            page=page,
        )

    def _request_grid_view_update(
        self,
        source_df: pd.DataFrame,
        *,
        var_name: str = None,
        model: PandasModel = None,
        table_view: QTableView = None,
        page=None,
    ):
        var_name = var_name or self._current_result_label()
        model = model or self.model
        table_view = table_view or self.table_view
        limit = self.row_limit_spin.value()
        rows_to_prepare = min(len(source_df), limit)
        use_async = (
            len(source_df) > GRID_ASYNC_ROW_THRESHOLD
            or rows_to_prepare > GRID_ASYNC_ROW_THRESHOLD
        )

        if use_async:
            self._show_grid_preparing(len(source_df))
            self._start_grid_prepare(source_df, var_name, model, table_view, page)
            return

        self._apply_grid_view_sync(source_df, var_name, model, table_view, page)

    def _schedule_table_column_resize(self, table_view: QTableView, prepared: PreparedGridData):
        def _table_view_is_valid(view) -> bool:
            if view is None:
                return False
            try:
                # PyQt6: deleted C++ wrapper check. (Never import shiboken6
                # here — it's PySide's lib, the failed import re-scans
                # sys.path on EVERY grid render and stalls the UI ~200ms.)
                return not sip.isdeleted(view)
            except (RuntimeError, TypeError):
                return True

        def resize_columns():
            if not _table_view_is_valid(table_view):
                return
            try:
                if prepared.row_count <= GRID_ASYNC_ROW_THRESHOLD:
                    table_view.resizeColumnsToContents()
                    return

                header = table_view.horizontalHeader()
                metrics = table_view.fontMetrics()
                sample_rows = min(GRID_COLUMN_RESIZE_SAMPLE_ROWS, prepared.row_count)
                for col_index, column_name in enumerate(prepared.columns):
                    max_width = metrics.horizontalAdvance(str(column_name)) + 24
                    for row_index in range(sample_rows):
                        cell_text = prepared.display_value(row_index, col_index)
                        max_width = max(max_width, metrics.horizontalAdvance(cell_text) + 24)
                    header.resizeSection(col_index, min(max_width, GRID_COLUMN_MAX_WIDTH))
            except RuntimeError:
                return

        QTimer.singleShot(0, resize_columns)

    def _normalize_filter_spec(self, value: Any) -> dict:
        return _grid_normalize_filter_spec(value)

    def _filter_spec_is_empty(self, spec: dict) -> bool:
        return _grid_filter_spec_is_empty(spec)

    def _column_filter_mask(self, df: pd.DataFrame, column, spec: dict):
        return _grid_column_filter_mask(df, column, spec)

    def _parse_float(self, value: Any) -> Optional[float]:
        return _grid_parse_float(value)

    def _parse_bool_value(self, value: Any) -> Optional[bool]:
        return _grid_parse_bool_value(value)

    def _apply_active_dataframe_view(self, var_name: str = None):
        """Aplica filtro/limite ao DataFrame original da aba ativa."""
        source_df = self._get_active_source_df()
        if source_df is None:
            return

        tabs = getattr(self, "_result_tabs", None)
        page = None
        model = self.model
        table_view = self.table_view
        if tabs is not None and tabs.currentIndex() > 0:
            page = tabs.widget(tabs.currentIndex())
            if page is not None and hasattr(page, "_model"):
                model = page._model
                table_view = page._table_view

        self._request_grid_view_update(
            source_df,
            var_name=var_name or self._current_result_label(),
            model=model,
            table_view=table_view,
            page=page,
        )

    def _refresh_filter_chips(self):
        """Atualiza chips visuais dos filtros ativos."""
        if not hasattr(self, "filter_chip_layout"):
            return

        while self.filter_chip_layout.count():
            item = self.filter_chip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        chips = []
        for column, value in self._column_filters.items():
            label = self._column_filter_label(column, value)
            chips.append((label, lambda checked=False, col=column: self._remove_column_filter(col)))

        if not chips:
            self.filter_chip_bar.setVisible(False)
            return

        for label, callback in chips:
            button = QToolButton(self.filter_chip_bar)
            button.setObjectName("filterChip")
            button.setText(label)
            button.setIcon(qta.icon("mdi.close", color="#a0a0a0", scale_factor=0.65))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(S.results.tooltip_remove_filter)
            button.clicked.connect(callback)
            self.filter_chip_layout.addWidget(button)

        self.filter_chip_layout.addStretch(1)
        self.filter_chip_bar.setVisible(True)

    def _column_filter_label(self, column, value: Any) -> str:
        spec = self._normalize_filter_spec(value)
        filter_type = spec.get("type", "text")
        if filter_type == "number":
            min_value = str(spec.get("min", "")).strip()
            max_value = str(spec.get("max", "")).strip()
            if min_value and max_value:
                return S.results.filter_chip_between.format(column=str(column), min=min_value, max=max_value)
            if min_value:
                return S.results.filter_chip_min.format(column=str(column), min=min_value)
            return S.results.filter_chip_max.format(column=str(column), max=max_value)
        if filter_type == "bool":
            bool_label = S.results.filter_bool_true if self._parse_bool_value(spec.get("value")) else S.results.filter_bool_false
            return S.results.filter_chip_equals.format(column=str(column), value=bool_label)
        if filter_type == "date":
            start = str(spec.get("start", "")).strip()
            end = str(spec.get("end", "")).strip()
            if start and end:
                return S.results.filter_chip_between.format(column=str(column), min=start, max=end)
            if start:
                return S.results.filter_chip_min.format(column=str(column), min=start)
            return S.results.filter_chip_max.format(column=str(column), max=end)
        operator = spec.get("operator", "contains")
        value_text = str(spec.get("value", ""))
        if operator == "equals":
            return S.results.filter_chip_equals.format(column=str(column), value=value_text)
        return S.results.filter_chip_column.format(column=str(column), value=value_text)

    def _set_dataframe_info(self, var_name: str, rows: int, total_rows: int, cols: int, limited: bool):
        """Atualiza info label considerando filtro e limite de exibicao."""
        if rows != total_rows:
            info_text = S.results.info_df_filtered.format(
                var_name=var_name,
                filtered=f"{rows:,}",
                rows=f"{total_rows:,}",
                cols=cols,
            )
        else:
            info_text = S.results.info_df_dimensions.format(var_name=var_name, rows=f"{rows:,}", cols=cols)

        if limited:
            info_text += S.results.showing_limited.format(showing=f"{self.row_limit_spin.value():,}")
        self.info_label.setText(info_text)

    def _open_export_settings(self):
        """Open the export settings dialog."""
        dialog = ExportSettingsDialog(self, theme_manager=self.theme_manager)
        dialog.exec()

    def _get_export_settings(self) -> dict:
        """Get current export settings."""
        return ExportSettingsDialog.get_settings()

    def _current_var_name(self) -> str:
        """Extrai nome da variavel do info_label atual."""
        text = self.info_label.text()
        if ":" in text:
            return text.split(":")[0].strip()
        return "df"

    @staticmethod
    def _load_display_limit() -> int:
        """Carrega o limite de linhas exibidas do QSettings."""
        settings = QSettings("DataPyn", "DataPyn")
        return int(settings.value("grid/display_row_limit", 100))

    @staticmethod
    def _save_display_limit(value: int):
        """Salva o limite de linhas exibidas no QSettings."""
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue("grid/display_row_limit", value)

    @classmethod
    def _clamp_grid_font_size(cls, size: int) -> int:
        try:
            value = int(size)
        except (TypeError, ValueError):
            value = cls.DEFAULT_GRID_FONT_SIZE
        return max(cls.MIN_GRID_FONT_SIZE, min(cls.MAX_GRID_FONT_SIZE, value))

    @classmethod
    def _load_grid_font_size(cls) -> int:
        """Carrega o zoom/tamanho de fonte do grid salvo pelo usuario."""
        settings = QSettings("DataPyn", "DataPyn")
        return cls._clamp_grid_font_size(settings.value(cls.SETTINGS_KEY_GRID_FONT_SIZE, cls.DEFAULT_GRID_FONT_SIZE))

    @classmethod
    def _save_grid_font_size(cls, size: int):
        """Salva o zoom/tamanho de fonte do grid."""
        settings = QSettings("DataPyn", "DataPyn")
        settings.setValue(cls.SETTINGS_KEY_GRID_FONT_SIZE, cls._clamp_grid_font_size(size))

    def display_image(self, image_bytes: bytes, label: str = None):
        """Exibe uma imagem (PNG bytes) no painel de resultados.

        Args:
            image_bytes: Bytes da imagem PNG
            label: Texto descritivo para a info label
        """
        if label is None:
            label = S.results.label_chart
        self._current_image_bytes = image_bytes

        img = QImage()
        if not img.loadFromData(image_bytes):
            return

        pixmap = QPixmap.fromImage(img)

        # Escalar ao viewport mantendo aspecto
        viewport_w = self.image_scroll.viewport().width()
        viewport_h = self.image_scroll.viewport().height()
        if viewport_w < 100:
            viewport_w = 800
        if viewport_h < 100:
            viewport_h = 600

        scaled = pixmap.scaled(
            viewport_w - 20,
            viewport_h - 20,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

        # Guardar pixmap original para redimensionar
        self._original_pixmap = pixmap

        self.info_label.setText(S.results.info_image_size.format(label=label, width=img.width(), height=img.height()))

        # Mostrar imagem e botao salvar, esconder export de dados
        self.stack.setCurrentIndex(1)
        self.btn_export_csv.setVisible(False)
        self.btn_export_excel.setVisible(False)
        self.btn_export_json.setVisible(False)
        self.btn_copy.setVisible(False)
        self.export_dest_widget.setVisible(False)
        self.btn_save_image.setVisible(True)

    def display_images(self, images_bytes_list: list, label: str = None):
        """Exibe multiplas imagens combinadas verticalmente.

        Args:
            images_bytes_list: Lista de bytes PNG
            label: Texto descritivo
        """
        if label is None:
            label = S.results.label_charts
        if not images_bytes_list:
            return

        if len(images_bytes_list) == 1:
            self.display_image(images_bytes_list[0], label)
            return

        # Combinar imagens verticalmente
        images = []
        total_h = 0
        max_w = 0
        for img_bytes in images_bytes_list:
            img = QImage()
            if img.loadFromData(img_bytes):
                images.append(img)
                total_h += img.height() + 10  # 10px spacing
                max_w = max(max_w, img.width())

        if not images:
            return

        # Criar imagem combinada
        from PyQt6.QtGui import QPainter
        from src.design_system.tokens import get_colors
        colors_tk = get_colors()

        combined = QImage(max_w, total_h, QImage.Format.Format_ARGB32)
        combined.fill(QColor(colors_tk.bg_primary))

        painter = QPainter(combined)
        y_offset = 0
        for img in images:
            x_offset = (max_w - img.width()) // 2
            painter.drawImage(x_offset, y_offset, img)
            y_offset += img.height() + 10
        painter.end()

        # Salvar como bytes para o botao salvar
        from PyQt6.QtCore import QBuffer, QIODevice

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        combined.save(buffer, "PNG")
        self._current_image_bytes = bytes(buffer.data())
        buffer.close()

        pixmap = QPixmap.fromImage(combined)
        self._original_pixmap = pixmap

        # Escalar ao viewport
        viewport_w = self.image_scroll.viewport().width()
        viewport_h = self.image_scroll.viewport().height()
        if viewport_w < 100:
            viewport_w = 800
        if viewport_h < 100:
            viewport_h = 600

        scaled = pixmap.scaled(
            viewport_w - 20,
            viewport_h - 20,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

        self.info_label.setText(S.results.info_images_count.format(label=label, count=len(images)))

        # Mostrar imagem e botao salvar
        self.stack.setCurrentIndex(1)
        self.btn_export_csv.setVisible(False)
        self.btn_export_excel.setVisible(False)
        self.btn_export_json.setVisible(False)
        self.btn_copy.setVisible(False)
        self.export_dest_widget.setVisible(False)
        self.btn_save_image.setVisible(True)

    def display_html(self, html_content: str, label: str = "HTML"):
        """Exibe conteudo HTML no painel de resultados.

        Usado para pandas Styler, IPython.display.HTML, etc.
        Injeta CSS para tema escuro automaticamente.

        Args:
            html_content: String HTML a renderizar
            label: Texto descritivo para a info label
        """
        colors = self.theme_manager.get_app_colors()

        # Injetar CSS de tema escuro no HTML
        dark_css = f"""
        <style>
            body, html {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                font-family: 'Ubuntu', 'Roboto', -apple-system, sans-serif;
                font-size: 13px;
                margin: 10px;
            }}
            table {{
                border-collapse: collapse;
                margin: 10px 0;
            }}
            th {{
                background-color: {colors["border"]};
                color: {colors["foreground"]};
                padding: 8px 12px;
                text-align: left;
                border: 1px solid {colors["border"]};
                font-weight: bold;
            }}
            td {{
                padding: 6px 12px;
                border: 1px solid {colors["border"]};
            }}
            tr:nth-child(even) {{
                background-color: {colors["border"]};
            }}
            a {{ color: {colors["accent"]}; }}
            pre, code {{
                background-color: {colors["border"]};
                padding: 4px 8px;
                border-radius: 6px;
                font-family: Consolas, monospace;
            }}
        </style>
        """

        # Envolver se nao tem <html> tag
        if "<html" not in html_content.lower():
            html_content = f"<html><head>{dark_css}</head><body>{html_content}</body></html>"
        else:
            # Injetar CSS no head existente
            html_content = html_content.replace("</head>", f"{dark_css}</head>", 1)

        self.html_viewer.setHtml(html_content)
        self.info_label.setText(label)

        self.stack.setCurrentIndex(2)
        self._hide_all_toolbar_buttons()

    def display_json(self, data, label: str = "JSON"):
        """Exibe dict/list como arvore colapsavel no painel de resultados.

        Args:
            data: dict, list, ou qualquer objeto serializavel
            label: Texto descritivo para a info label
        """
        self.json_tree.clear()

        colors = self.theme_manager.get_app_colors()
        from src.design_system.tokens import get_colors
        colors_tk = get_colors()
        type_color = QColor(colors.get("accent", colors_tk.interactive_primary))

        if isinstance(data, dict):
            self._populate_json_tree(self.json_tree.invisibleRootItem(), data, type_color)
            count = len(data)
            self.info_label.setText(S.results.info_json_dict.format(label=label, count=count))
        elif isinstance(data, list):
            self._populate_json_tree(self.json_tree.invisibleRootItem(), data, type_color)
            count = len(data)
            self.info_label.setText(S.results.info_json_list.format(label=label, count=count))
        else:
            # Tentar converter para dict/list via json
            try:
                parsed = json.loads(json.dumps(data, default=str))
                self._populate_json_tree(self.json_tree.invisibleRootItem(), parsed, type_color)
                self.info_label.setText(f"{label} ({type(data).__name__})")
            except (TypeError, ValueError):
                item = QTreeWidgetItem(self.json_tree, [str(type(data).__name__), str(data), type(data).__name__])
                self.info_label.setText(f"{label}")

        # Expandir primeiro nivel
        root = self.json_tree.invisibleRootItem()
        for i in range(root.childCount()):
            root.child(i).setExpanded(True)

        self.stack.setCurrentIndex(3)
        self._hide_all_toolbar_buttons()

    def _populate_json_tree(self, parent, data, type_color: QColor):
        """Popula arvore JSON recursivamente.

        Args:
            parent: QTreeWidgetItem pai
            data: dados a inserir (dict, list, ou valor primitivo)
            type_color: cor para a coluna de tipo
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    item = QTreeWidgetItem(parent)
                    item.setText(0, str(key))
                    type_name = "dict" if isinstance(value, dict) else "list"
                    count = len(value)
                    item.setText(1, S.results.json_dict_items.format(count=count) if isinstance(value, dict) else S.results.json_list_items.format(count=count))
                    item.setText(2, type_name)
                    item.setForeground(2, type_color)
                    self._populate_json_tree(item, value, type_color)
                else:
                    item = QTreeWidgetItem(parent)
                    item.setText(0, str(key))
                    item.setText(1, self._format_json_value(value))
                    item.setText(2, type(value).__name__)
                    item.setForeground(2, type_color)
        elif isinstance(data, list):
            for i, value in enumerate(data):
                if isinstance(value, (dict, list)):
                    item = QTreeWidgetItem(parent)
                    item.setText(0, f"[{i}]")
                    type_name = "dict" if isinstance(value, dict) else "list"
                    count = len(value)
                    item.setText(1, S.results.json_dict_items.format(count=count) if isinstance(value, dict) else S.results.json_list_items.format(count=count))
                    item.setText(2, type_name)
                    item.setForeground(2, type_color)
                    self._populate_json_tree(item, value, type_color)
                else:
                    item = QTreeWidgetItem(parent)
                    item.setText(0, f"[{i}]")
                    item.setText(1, self._format_json_value(value))
                    item.setText(2, type(value).__name__)
                    item.setForeground(2, type_color)

    def _format_json_value(self, value) -> str:
        """Formata valor para exibicao na arvore JSON."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            # Truncar strings muito longas
            if len(value) > 200:
                return f'"{value[:200]}..."'
            return f'"{value}"'
        return str(value)

    def display_rich_output(self, outputs: list, label: str = None):
        """Exibe rich outputs baseado no tipo de cada item.

        Aceita lista de dicts com tipo:
            {'type': 'image', 'data': bytes}     # PNG bytes
            {'type': 'html', 'data': str}        # HTML string
            {'type': 'json', 'data': object}     # dict/list

        Tambem aceita lista de bytes puros (backward compat com display_images).

        Prioridade quando ha tipos mistos: image > html > json
        """
        if label is None:
            label = S.results.label_result
        if not outputs:
            return

        # Backward compat: se todos sao bytes, tratar como imagens
        if all(isinstance(o, bytes) for o in outputs):
            self.display_images(outputs, label)
            return

        # Separar por tipo
        images = []
        html_items = []
        json_items = []

        for item in outputs:
            if isinstance(item, bytes):
                images.append(item)
            elif isinstance(item, dict):
                item_type = item.get("type", "")
                if item_type == "image" and "data" in item:
                    images.append(item["data"])
                elif item_type == "html" and "data" in item:
                    html_items.append(item["data"])
                elif item_type == "json" and "data" in item:
                    json_items.append(item["data"])

        # Prioridade: image > html > json
        if images:
            self.display_images(images, label)
        elif html_items:
            # Combinar multiplos HTML
            combined = "<hr>".join(html_items)
            self.display_html(combined, label)
        elif json_items:
            # Mostrar primeiro JSON (ou combinar em lista)
            if len(json_items) == 1:
                self.display_json(json_items[0], label)
            else:
                self.display_json(json_items, label)

    def _show_dataframe_toolbar_buttons(self):
        """Mostra botoes relevantes para DataFrame (tabela de dados)."""
        self.btn_export_csv.setVisible(True)
        self.btn_export_excel.setVisible(True)
        self.btn_export_json.setVisible(True)
        self.btn_copy.setVisible(True)
        self.btn_export_table.setVisible(True)
        self.btn_export_sql.setVisible(True)
        self.export_dest_widget.setVisible(True)
        self._refresh_filter_chips()
        self.btn_save_image.setVisible(False)

    def _hide_all_toolbar_buttons(self):
        """Esconde todos os botoes da toolbar (usado para HTML e JSON pages)."""
        self.btn_export_csv.setVisible(False)
        self.btn_export_excel.setVisible(False)
        self.btn_export_json.setVisible(False)
        self.btn_copy.setVisible(False)
        self.btn_export_table.setVisible(False)
        self.btn_export_sql.setVisible(False)
        self.export_dest_widget.setVisible(False)
        if hasattr(self, "filter_chip_bar"):
            self.filter_chip_bar.setVisible(False)
        self.btn_save_image.setVisible(False)

    def clear(self):
        """Clear visualization"""
        self._cancel_all_grid_prepare()
        self._grid_prepare_job_serial += 1
        self._grid_prepare_job_meta.clear()
        self._collapse_to_primary()
        self._column_filters.clear()
        self._refresh_filter_chips()
        self.current_df = None
        self._primary_df = None
        self._primary_filtered_df = None
        self._primary_grid_cache_key = None
        self._current_image_bytes = None
        self.model.update_data(pd.DataFrame())
        self.image_label.clear()
        self.html_viewer.clear()
        self.json_tree.clear()
        self.info_label.setText(S.results.no_results)
        self.stack.setCurrentIndex(0)
        self._show_dataframe_toolbar_buttons()
        self._schedule_summarize_refresh()

    def _get_export_destination(self) -> str:
        """Return selected destination: 'clipboard' or 'file'"""
        btn = self._export_dest_group.checkedButton()
        if btn is None:
            return "clipboard"
        return btn.property("export_dest") or "clipboard"

    def _refresh_export_dest_icons(self, _button: QAbstractButton | None = None):
        """Update segment icons for checked/unchecked state."""
        from src.design_system.tokens import get_colors

        colors = get_colors()
        icons = (
            (self.btn_export_dest_clipboard, "mdi.clipboard-arrow-down-outline"),
            (self.btn_export_dest_file, "mdi.file-download-outline"),
        )
        for btn, icon_name in icons:
            icon_color = "#ffffff" if btn.isChecked() else colors.text_tertiary
            btn.setIcon(qta.icon(icon_name, color=icon_color))

    def _sync_export_dest_button_sizes(self):
        """Keep Clipboard/File toggles the same height as CSV/Excel buttons."""
        self.toolbar.ensurePolished()
        self.btn_export_csv.ensurePolished()
        height = self.btn_export_csv.sizeHint().height()
        if height <= 0:
            height = 28
        width = max(28, height + 2)
        icon = max(12, height - 12)
        for btn in (self.btn_export_dest_clipboard, self.btn_export_dest_file):
            btn.setFixedSize(width, height)
            btn.setIconSize(QSize(icon, icon))
        self.export_dest_widget.setFixedHeight(height)

    def _apply_export_dest_style(self):
        """Segmented toggle matching toolbar button height."""
        colors = self.theme_manager.get_app_colors()
        from src.design_system.tokens import RADIUS

        self.export_dest_widget.setStyleSheet(f"""
            QToolButton#exportDestBtnLeft,
            QToolButton#exportDestBtnRight {{
                background-color: transparent;
                color: {colors["foreground"]};
                border: 1px solid {colors["border"]};
                padding: 0;
                margin: 0;
            }}
            QToolButton#exportDestBtnLeft {{
                border-top-left-radius: {RADIUS.radius_sm}px;
                border-bottom-left-radius: {RADIUS.radius_sm}px;
                border-right: none;
            }}
            QToolButton#exportDestBtnRight {{
                border-top-right-radius: {RADIUS.radius_sm}px;
                border-bottom-right-radius: {RADIUS.radius_sm}px;
            }}
            QToolButton#exportDestBtnLeft:checked,
            QToolButton#exportDestBtnRight:checked {{
                background-color: {colors["accent"]};
                border-color: {colors["accent"]};
            }}
            QToolButton#exportDestBtnLeft:hover:!checked,
            QToolButton#exportDestBtnRight:hover:!checked {{
                background-color: rgba(255, 255, 255, 0.06);
                border-color: {colors["accent"]};
            }}
        """)
        self._refresh_export_dest_icons()
        if hasattr(self, "btn_export_csv"):
            self._sync_export_dest_button_sizes()

    def _show_clipboard_success(self, format_name: str):
        """Show success feedback when copying to clipboard"""
        self.info_label.setText(S.results.clipboard_success.format(format=format_name))

    def _export_csv(self):
        """Export to CSV (clipboard or file)"""
        if self.current_df is None:
            return

        # Always open configuration dialog
        dialog = CSVExportDialog(self, theme_manager=self.theme_manager)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        delimiter = dialog.get_delimiter()
        encoding = dialog.get_encoding()
        include_header = dialog.get_include_header()
        open_folder = dialog.get_open_folder()

        destination = self._get_export_destination()

        if destination == "clipboard":
            # Export to clipboard with settings
            from PyQt6.QtWidgets import QApplication

            csv_text = self.current_df.to_csv(index=False, sep=delimiter, encoding=encoding, header=include_header)
            QApplication.instance().clipboard().setText(csv_text)
            self._show_clipboard_success("CSV")
            return

        # Export to file

        filename, _ = QFileDialog.getSaveFileName(self, S.results.save_csv_title, "", S.results.filter_csv)
        if not filename:
            return

        if not filename.lower().endswith(".csv"):
            filename += ".csv"

        # Export in background to avoid blocking UI
        self._start_export_background(
            filename, 
            "csv",
            encoding=encoding,
            sep=delimiter,
            header=include_header,
            open_folder=open_folder
        )

    def _export_excel(self):
        """Export to Excel (clipboard or file)"""
        if self.current_df is None:
            return

        destination = self._get_export_destination()

        if destination == "clipboard":
            # Excel in clipboard - tab-separated format that Excel understands
            from PyQt6.QtWidgets import QApplication

            excel_text = self.current_df.to_csv(index=False, sep="\t", header=True)
            QApplication.instance().clipboard().setText(excel_text)
            self._show_clipboard_success("Excel (tab)")
            return

        # Export to file
        es = self._get_export_settings()
        filename, _ = QFileDialog.getSaveFileName(self, S.results.save_excel_title, "", S.results.filter_excel)
        if filename:
            if not filename.lower().endswith(".xlsx"):
                filename += ".xlsx"
            # Export in background
            self._start_export_background(
                filename, "excel",
                open_folder=es["open_folder"],
            )

    def _export_json(self):
        """Export to JSON (clipboard or file)"""
        if self.current_df is None:
            return

        destination = self._get_export_destination()

        if destination == "clipboard":
            from PyQt6.QtWidgets import QApplication

            json_text = self.current_df.to_json(orient="records", indent=2, force_ascii=False)
            QApplication.instance().clipboard().setText(json_text)
            self._show_clipboard_success("JSON")
            return

        # Export to file
        es = self._get_export_settings()
        filename, _ = QFileDialog.getSaveFileName(self, S.results.save_json_title, "", S.results.filter_json)
        if filename:
            if not filename.lower().endswith(".json"):
                filename += ".json"
            # Export in background
            self._start_export_background(
                filename, "json",
                orient="records", indent=2, force_ascii=False,
                open_folder=es["open_folder"],
            )

    def _export_sql(self):
        """Export DataFrame as SQL INSERT statements (clipboard or file)"""
        if self.current_df is None or len(self.current_df) == 0:
            return

        # Get db_type from the active connection (for proper quoting)
        db_type = self._get_active_db_type()
        table_name = self._current_var_name() or "table1"

        from src.utils.sql_insert_generator import generate_inserts

        destination = self._get_export_destination()

        if destination == "clipboard":
            from PyQt6.QtWidgets import QApplication

            sql_text = generate_inserts(
                df=self.current_df,
                table_name=table_name,
                db_type=db_type,
                batch_size=1,
            )
            QApplication.instance().clipboard().setText(sql_text)
            self._show_clipboard_success("SQL")
            return

        # Export to file
        filename, _ = QFileDialog.getSaveFileName(
            self, S.results.save_sql_title, f"{table_name}.sql", S.results.filter_sql
        )
        if filename:
            if not filename.lower().endswith(".sql"):
                filename += ".sql"

            sql_text = generate_inserts(
                df=self.current_df,
                table_name=table_name,
                db_type=db_type,
                batch_size=1,
            )
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(sql_text)
                self.info_label.setText(
                    S.results.export_success if hasattr(S.results, "export_success") else "Export complete!"
                )
            except Exception as e:
                self.info_label.setText(
                    S.results.export_failed if hasattr(S.results, "export_failed") else "Export failed"
                )
                show_danger(self, S.results.error_title, str(e))

    def _get_active_db_type(self) -> str:
        """Determine the db_type from the active connection.

        Checks the focused block's connection first, then the session connection.
        Returns 'sqlserver' as default if no connection is found.
        """
        main_window = self._get_main_window()
        if not main_window:
            return "sqlserver"

        current_widget = main_window._get_current_session_widget()
        if not current_widget:
            return "sqlserver"

        # Check focused block first
        focused_block = current_widget.editor.get_focused_block()
        if focused_block:
            block_conn = focused_block.get_connection_name()
            if block_conn:
                connector = self._find_connector(main_window, block_conn)
                if connector:
                    return getattr(connector, "db_type", "sqlserver")

        # Fall back to session connection
        session = getattr(current_widget, "session", None)
        if session:
            connector = getattr(session, "connector", None)
            if connector:
                return getattr(connector, "db_type", "sqlserver")

        return "sqlserver"

    def _find_connector(self, main_window, connection_name: str):
        """Find an active connector by connection name across sessions."""
        if hasattr(main_window, "_session_widgets"):
            for widget in main_window._session_widgets.values():
                session = getattr(widget, "session", None)
                if session:
                    conn_name = getattr(session, "connection_name", None)
                    connector = getattr(session, "connector", None)
                    if conn_name == connection_name and connector:
                        return connector
        return None

    def _start_export_background(self, filepath: str, export_format: str, open_folder: bool = False, **options):
        """Start export in background thread"""
        # Cancel any existing export
        self._cleanup_export_thread()

        # Show progress indicator
        self.info_label.setText(S.results.exporting if hasattr(S.results, 'exporting') else "Exporting...")

        # Create thread and worker
        self._export_thread = QThread()
        self._export_worker = FileExportWorker(
            df=self.current_df.copy(),  # Copy to avoid issues
            file_path=filepath,
            export_format=export_format,
            **options
        )
        self._export_worker.moveToThread(self._export_thread)

        # Store open_folder flag
        self._export_open_folder = open_folder

        # Connect signals
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.export_complete.connect(self._on_export_complete)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.finished.connect(self._export_thread.quit)
        self._export_thread.finished.connect(self._cleanup_export_thread)

        # Start
        self._export_thread.start()

    def _on_export_complete(self, filepath: str):
        """Callback when export finishes successfully"""
        self.info_label.setText(S.results.export_success if hasattr(S.results, 'export_success') else "Export complete!")
        
        # Open folder if requested
        if getattr(self, '_export_open_folder', False):
            subprocess.run(["explorer", "/select,", os.path.normpath(filepath)])

    def _on_export_error(self, error_msg: str):
        """Callback when export fails"""
        self.info_label.setText(S.results.export_failed if hasattr(S.results, 'export_failed') else "Export failed")
        show_danger(self, S.results.error_title, error_msg)

    def _cleanup_export_thread(self):
        """Cleanup export thread and worker"""
        if self._export_worker is not None:
            self._export_worker.deleteLater()
            self._export_worker = None
        if self._export_thread is not None:
            if self._export_thread.isRunning():
                self._export_thread.quit()
                self._export_thread.wait(1000)
            self._export_thread.deleteLater()
            self._export_thread = None

    def _copy_to_clipboard(self, include_headers: bool = False):
        """Copy formatted data to clipboard"""
        from PyQt6.QtWidgets import QApplication

        if self.current_df is not None:
            es = self._get_export_settings()
            sep = es["copy_separator"]
            text = self.current_df.to_csv(index=False, sep=sep, header=include_headers)
            # Remove trailing newline from to_csv
            if text.endswith("\n"):
                text = text[:-1]
            QApplication.instance().clipboard().setText(text)
            self._show_clipboard_success("Table")

    def is_grid_active(self) -> bool:
        """Return True when the active result tab is showing a data grid."""
        tabs = getattr(self, "_result_tabs", None)
        if tabs is None or tabs.currentIndex() < 0:
            return False
        if tabs.currentIndex() == 0:
            return self.stack.currentIndex() == 0
        page = tabs.widget(tabs.currentIndex())
        if page is None or self._is_chart_page(page):
            return False
        return hasattr(page, "_table_view")

    def get_current_result_label(self) -> str:
        tabs = getattr(self, "_result_tabs", None)
        if tabs is None or tabs.currentIndex() < 0:
            return ""
        return tabs.tabText(tabs.currentIndex())

    def get_selection_cells(self) -> list[tuple[int, int]]:
        """Return exact selected (row, column) pairs for the active grid."""
        scope = self.get_summarize_selection_scope()
        return list(scope.get("cells") or [])

    def get_summarize_selection_scope(self) -> dict:
        """Build a selection scope without materializing huge Qt index lists."""
        empty_scope = {"cells": [], "row_ranges": None, "bound_cols": None}
        if not self.is_grid_active() or self.current_df is None:
            return empty_scope

        selection = self.table_view.selectionModel() if self.table_view is not None else None
        if selection is None or not selection.hasSelection():
            return empty_scope

        ranges = selection.selection()
        if not ranges:
            return empty_scope

        total_cells = 0
        row_ranges: list[tuple[int, int]] = []
        cols: set[int] = set()

        for item_range in ranges:
            top = item_range.top()
            left = item_range.left()
            bottom = item_range.bottom()
            right = item_range.right()
            height = bottom - top + 1
            width = right - left + 1
            total_cells += height * width
            row_ranges.append((top, bottom))
            cols.update(range(left, right + 1))

        if total_cells > SUMMARIZE_MAX_EXPLICIT_CELLS:
            return {
                "cells": [],
                "row_ranges": row_ranges,
                "bound_cols": sorted(cols),
            }

        cells = []
        for item_range in ranges:
            top = item_range.top()
            left = item_range.left()
            bottom = item_range.bottom()
            right = item_range.right()
            for row in range(top, bottom + 1):
                for col in range(left, right + 1):
                    cells.append((row, col))

        return {
            "cells": sorted(set(cells)),
            "row_ranges": None,
            "bound_cols": None,
        }

    @staticmethod
    def has_summarize_selection(scope: Optional[dict]) -> bool:
        from src.ui.components.summarize_stats import has_summarize_selection as _has_selection

        return _has_selection(scope)

    def build_summarize_payload(self) -> dict:
        from src.ui.components.summarize_stats import build_selection_summary

        scope = self.get_summarize_selection_scope()
        numeric_indices = None
        prepared = getattr(self.model, "_prepared", None)
        if prepared is not None and getattr(prepared, "numeric_column_indices", None):
            numeric_indices = set(prepared.numeric_column_indices)

        return build_selection_summary(
            self.current_df,
            scope.get("cells") or [],
            row_ranges=scope.get("row_ranges"),
            bound_cols=scope.get("bound_cols"),
            result_label=self.get_current_result_label(),
            column_formats=self._column_formats,
            numeric_column_indices=numeric_indices,
        )

    def get_selection_bounds(self) -> tuple[list[int], list[int]]:
        """Return selected row/column indexes for the active grid."""
        if not self.is_grid_active() or self.current_df is None:
            return [], []

        selection = self.table_view.selectionModel() if self.table_view is not None else None
        if selection is None or not selection.hasSelection():
            return [], []

        scope = self.get_summarize_selection_scope()
        if scope.get("row_ranges"):
            rows: set[int] = set()
            for start, end in scope["row_ranges"]:
                rows.update(range(int(start), int(end) + 1))
            return sorted(rows), list(scope.get("bound_cols") or [])

        cells = scope.get("cells") or []
        if cells:
            return sorted({row for row, _ in cells}), sorted({col for _, col in cells})

        indexes = selection.selectedIndexes()
        if not indexes:
            return [], []

        rows = sorted({idx.row() for idx in indexes})
        cols = sorted({idx.column() for idx in indexes})
        return rows, cols

    def show_column_format_menu(self, column, global_pos):
        """Open the column format menu (shared with grid header)."""
        source_df = self._get_active_source_df()
        if source_df is None:
            return
        if column not in source_df.columns:
            column = str(column)
            if column not in source_df.columns:
                return
        menu = self._create_column_menu(column, global_pos=global_pos)
        menu.exec(global_pos)

    def _connect_active_selection_model(self):
        table_view = getattr(self, "table_view", None)
        selection_model = table_view.selectionModel() if table_view is not None else None
        if selection_model is self._bound_selection_model:
            return
        if self._bound_selection_model is not None:
            try:
                self._bound_selection_model.selectionChanged.disconnect(self._on_grid_selection_changed)
            except (TypeError, RuntimeError):
                pass
        self._bound_selection_model = selection_model
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._on_grid_selection_changed)

    def _on_grid_selection_changed(self, *_args):
        self._schedule_summarize_refresh()

    def _on_stack_page_changed(self, _index: int):
        self._connect_active_selection_model()
        self._schedule_summarize_refresh()

    def _copy_selection_to_clipboard(self, include_headers: bool = False):
        """Copy selected cells/rows/columns from the table view to clipboard.

        Builds a separated text from the selection, preserving the
        row/column structure.
        """
        from PyQt6.QtWidgets import QApplication

        selection = self.table_view.selectionModel()
        if not selection or not selection.hasSelection():
            self._copy_to_clipboard(include_headers=include_headers)
            return

        # Huge selections (e.g. select-all on 1M rows) must NOT materialize
        # per-cell QModelIndex lists — that's millions of objects and a hard
        # freeze. Copy from the underlying DataFrame via vectorized to_csv.
        scope = self.get_summarize_selection_scope()
        if scope.get("row_ranges") and scope.get("bound_cols") is not None:
            if self._copy_selection_ranges_to_clipboard(
                scope["row_ranges"], scope["bound_cols"], include_headers
            ):
                return

        indexes = selection.selectedIndexes()
        if not indexes:
            self._copy_to_clipboard(include_headers=include_headers)
            return

        # Collect unique rows/cols and sort
        rows = sorted(set(idx.row() for idx in indexes))
        cols = sorted(set(idx.column() for idx in indexes))

        es = self._get_export_settings()
        sep = es["copy_separator"]

        # Build header line with column names
        lines = []
        if include_headers and self.current_df is not None:
            col_names = [str(self.current_df.columns[c]) for c in cols]
            lines.append(sep.join(col_names))

        # Build index set for fast lookup
        selected_set = set((idx.row(), idx.column()) for idx in indexes)

        # Build data rows
        for row in rows:
            cells = []
            for col in cols:
                if (row, col) in selected_set:
                    idx = self.model.index(row, col)
                    value = self.model.data(idx, Qt.ItemDataRole.DisplayRole)
                    cells.append(str(value) if value is not None else "")
                else:
                    cells.append("")
            lines.append(sep.join(cells))

        text = "\n".join(lines)
        QApplication.instance().clipboard().setText(text)

        n_rows = len(rows)
        n_cols = len(cols)
        self._show_clipboard_success(f"{n_rows} x {n_cols}")

    def _copy_selection_ranges_to_clipboard(
        self, row_ranges: list, bound_cols: list, include_headers: bool
    ) -> bool:
        """Vectorized copy for large range selections; returns True on success."""
        from PyQt6.QtWidgets import QApplication

        df = self.current_df
        if df is None or df.empty:
            return False

        cols = [c for c in sorted(set(bound_cols)) if 0 <= c < len(df.columns)]
        if not cols:
            return False

        parts = []
        total_rows = 0
        for start, end in row_ranges:
            start = max(0, int(start))
            end = min(len(df) - 1, int(end))
            if start > end:
                continue
            parts.append(df.iloc[start : end + 1, cols])
            total_rows += end - start + 1
        if not parts:
            return False

        selection_df = parts[0] if len(parts) == 1 else pd.concat(parts)
        es = self._get_export_settings()
        sep = es["copy_separator"]
        text = selection_df.to_csv(sep=sep, index=False, header=bool(include_headers))
        QApplication.instance().clipboard().setText(text)
        self._show_clipboard_success(f"{total_rows} x {len(cols)}")
        return True

    def _show_header_context_menu(self, pos):
        """Show context menu when right-clicking on column/row headers."""
        header = self.sender()
        if header is None or self.current_df is None:
            return
        self._show_grid_context_menu(pos, widget=header)

    def _show_column_header_menu(self, section: int, global_pos):
        """Show menu from the header menu target."""
        source_df = self._get_active_source_df()
        if source_df is None or section < 0 or section >= len(source_df.columns):
            return
        self._create_column_menu(source_df.columns[section], global_pos=global_pos).exec(global_pos)

    def _create_column_menu(self, column, global_pos=None) -> QMenu:
        """Cria menu simples e separado para a coluna."""
        from src.design_system.tokens import get_colors
        colors_tk = get_colors()

        menu = QMenu(self)
        act_filter_column = QAction(
            qta.icon("mdi.filter-outline", color=colors_tk.info),
            S.results.ctx_filter_column,
            menu,
        )
        act_filter_column.triggered.connect(
            lambda checked=False, col=column, pos=global_pos: QTimer.singleShot(
                0, lambda: self._show_column_filter_popup(col, pos)
            )
        )
        menu.addAction(act_filter_column)

        format_menu = QMenu(S.results.ctx_format_column, menu)
        format_menu.setIcon(qta.icon("mdi.format-list-text", color=colors_tk.text_primary))

        current_format = self._column_formats.get(str(column), self._column_formats.get(column, {"type": "default"}))

        def add_format_action(parent_menu, label, format_config):
            action = QAction(label, parent_menu)
            action.setCheckable(True)
            action.setChecked(self._format_matches(current_format, format_config))
            action.triggered.connect(
                lambda checked=False, col=column, fmt=format_config: self._set_column_format(col, fmt)
            )
            parent_menu.addAction(action)
            return action

        add_format_action(format_menu, S.results.format_default, {"type": "default"})

        number_menu = QMenu(S.results.format_number, format_menu)
        number_menu.setIcon(qta.icon("mdi.numeric", color=colors_tk.text_primary))
        add_format_action(number_menu, S.results.format_number_0, {"type": "number", "decimals": 0})
        add_format_action(number_menu, S.results.format_number_2, {"type": "number", "decimals": 2})
        add_format_action(number_menu, S.results.format_number_4, {"type": "number", "decimals": 4})
        custom_number = QAction(S.results.format_custom, number_menu)
        custom_number.triggered.connect(lambda checked=False, col=column: self._open_custom_format_dialog(col, "number"))
        number_menu.addAction(custom_number)
        format_menu.addMenu(number_menu)

        currency_menu = QMenu(S.results.format_currency, format_menu)
        currency_menu.setIcon(qta.icon("mdi.cash", color=colors_tk.success))
        currency_presets = [
            (S.results.format_currency_usd, {"type": "currency", "prefix": "$ ", "decimals": 2, "code": "USD"}),
            (S.results.format_currency_brl, {"type": "currency", "prefix": "R$ ", "decimals": 2, "code": "BRL"}),
            (S.results.format_currency_eur, {"type": "currency", "prefix": "EUR ", "decimals": 2, "code": "EUR"}),
            (S.results.format_currency_gbp, {"type": "currency", "prefix": "GBP ", "decimals": 2, "code": "GBP"}),
        ]
        for label, config in currency_presets:
            add_format_action(currency_menu, label, config)
        custom_currency = QAction(S.results.format_custom, currency_menu)
        custom_currency.triggered.connect(lambda checked=False, col=column: self._open_custom_format_dialog(col, "currency"))
        currency_menu.addAction(custom_currency)
        format_menu.addMenu(currency_menu)

        add_format_action(format_menu, S.results.format_percent, {"type": "percent", "decimals": 2})
        add_format_action(format_menu, S.results.format_date, {"type": "date"})
        add_format_action(format_menu, S.results.format_datetime, {"type": "datetime"})
        menu.addMenu(format_menu)
        return menu

    def _column_filter_kind(self, column) -> str:
        source_df = self._get_active_source_df()
        if source_df is None or column not in source_df.columns:
            return "text"
        series = source_df[column].dropna()
        if pd.api.types.is_bool_dtype(source_df[column]) or self._series_looks_bool(series):
            return "bool"
        if pd.api.types.is_numeric_dtype(source_df[column]):
            return "number"
        if pd.api.types.is_datetime64_any_dtype(source_df[column]):
            return "date"
        return "text"

    def _series_looks_bool(self, series: pd.Series) -> bool:
        if series.empty:
            return False
        values = {str(value).strip().lower() for value in series.unique()[:8]}
        return values.issubset({"0", "1", "true", "false", "t", "f", "yes", "no", "sim", "nao"})

    def _column_unique_values(self, column, limit: int = 50) -> list:
        source_df = self._get_active_source_df()
        if source_df is None or column not in source_df.columns:
            return []
        values = []
        for value in source_df[column].dropna().unique()[:limit]:
            text = str(value)
            if text not in values:
                values.append(text)
        return values

    def _show_column_filter_popup(self, column, global_pos=None):
        """Mostra popup leve para filtrar uma coluna."""
        if self._column_filter_popup is not None:
            self._column_filter_popup.close()
            self._column_filter_popup.deleteLater()
            self._column_filter_popup = None

        from src.design_system.tokens import get_colors
        colors = get_colors()

        current_spec = self._normalize_filter_spec(self._column_filters.get(column, {}))
        filter_kind = self._column_filter_kind(column)
        focus_widget = None

        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setObjectName("columnFilterPopup")
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        popup.setMinimumWidth(290)
        popup.setStyleSheet(f"""
            QFrame#columnFilterPopup {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 6px;
            }}
            QLabel {{
                color: {colors.text_primary};
                font-size: 12px;
                font-weight: 600;
            }}
            QLineEdit, QComboBox {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 5px;
                padding: 6px 8px;
                font-size: 12px;
                min-height: 18px;
            }}
            QLineEdit:focus, QComboBox:hover {{
                border-color: {colors.interactive_primary};
            }}
            QPushButton {{
                background-color: transparent;
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 5px;
                padding: 5px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
                border-color: {colors.interactive_primary};
            }}
            QPushButton#columnFilterApply {{
                background-color: {colors.interactive_primary};
                color: {colors.text_inverse};
                border-color: {colors.interactive_primary};
            }}
        """)

        layout = QVBoxLayout(popup)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel(S.results.filter_column_dialog_title.format(column=str(column)))
        layout.addWidget(title)

        form = QFormLayout()
        controls = {}

        if filter_kind == "number":
            min_edit = QLineEdit(str(current_spec.get("min", "")))
            min_edit.setObjectName("columnFilterMinInput")
            min_edit.setValidator(QDoubleValidator(min_edit))
            max_edit = QLineEdit(str(current_spec.get("max", "")))
            max_edit.setObjectName("columnFilterMaxInput")
            max_edit.setValidator(QDoubleValidator(max_edit))
            form.addRow(S.results.filter_number_min, min_edit)
            form.addRow(S.results.filter_number_max, max_edit)
            controls.update({"min": min_edit, "max": max_edit})
            focus_widget = min_edit
        elif filter_kind == "bool":
            bool_combo = QComboBox()
            bool_combo.setObjectName("columnFilterBoolInput")
            bool_combo.addItem(S.results.filter_bool_any, "any")
            bool_combo.addItem(S.results.filter_bool_true, True)
            bool_combo.addItem(S.results.filter_bool_false, False)
            current_bool = self._parse_bool_value(current_spec.get("value"))
            bool_combo.setCurrentIndex(1 if current_bool is True else 2 if current_bool is False else 0)
            form.addRow(S.results.filter_bool_value, bool_combo)
            controls["bool"] = bool_combo
            focus_widget = bool_combo
        elif filter_kind == "date":
            start_edit = QLineEdit(str(current_spec.get("start", "")))
            start_edit.setObjectName("columnFilterStartInput")
            start_edit.setPlaceholderText(S.results.filter_date_placeholder)
            end_edit = QLineEdit(str(current_spec.get("end", "")))
            end_edit.setObjectName("columnFilterEndInput")
            end_edit.setPlaceholderText(S.results.filter_date_placeholder)
            form.addRow(S.results.filter_date_start, start_edit)
            form.addRow(S.results.filter_date_end, end_edit)
            controls.update({"start": start_edit, "end": end_edit})
            focus_widget = start_edit
        else:
            operator_combo = QComboBox()
            operator_combo.setObjectName("columnFilterOperator")
            operator_combo.addItem(S.results.filter_operator_contains, "contains")
            operator_combo.addItem(S.results.filter_operator_equals, "equals")
            operator_combo.addItem(S.results.filter_operator_starts, "starts_with")
            operator_combo.addItem(S.results.filter_operator_ends, "ends_with")
            operator_index = operator_combo.findData(current_spec.get("operator", "contains"))
            operator_combo.setCurrentIndex(operator_index if operator_index >= 0 else 0)

            value_combo = QComboBox()
            value_combo.setObjectName("columnFilterValueCombo")
            value_combo.setEditable(True)
            value_combo.lineEdit().setObjectName("columnFilterInput")
            value_combo.lineEdit().setPlaceholderText(S.results.filter_column_popup_placeholder)
            for value in self._column_unique_values(column):
                value_combo.addItem(value, value)
            value_combo.setCurrentText(str(current_spec.get("value", "")))
            value_combo.lineEdit().selectAll()
            form.addRow(S.results.filter_text_operator, operator_combo)
            form.addRow(S.results.filter_text_value, value_combo)
            controls.update({"operator": operator_combo, "value": value_combo})
            focus_widget = value_combo.lineEdit()

        layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(6)
        button_row.addStretch(1)

        clear_button = QPushButton(S.results.filter_popup_clear)
        clear_button.setObjectName("columnFilterClear")
        apply_button = QPushButton(S.results.filter_popup_apply)
        apply_button.setObjectName("columnFilterApply")
        button_row.addWidget(clear_button)
        button_row.addWidget(apply_button)
        layout.addLayout(button_row)

        def build_filter_spec():
            if filter_kind == "number":
                return {"type": "number", "min": controls["min"].text(), "max": controls["max"].text()}
            if filter_kind == "bool":
                return {"type": "bool", "value": controls["bool"].currentData()}
            if filter_kind == "date":
                return {"type": "date", "start": controls["start"].text(), "end": controls["end"].text()}
            return {
                "type": "text",
                "operator": controls["operator"].currentData() or "contains",
                "value": controls["value"].currentText(),
            }

        def apply_filter():
            self._set_column_filter(column, build_filter_spec())
            popup.close()

        def clear_filter():
            self._remove_column_filter(column)
            popup.close()

        apply_button.clicked.connect(apply_filter)
        clear_button.clicked.connect(clear_filter)
        for line_edit in popup.findChildren(QLineEdit):
            line_edit.returnPressed.connect(apply_filter)

        popup.destroyed.connect(lambda *_: setattr(self, "_column_filter_popup", None))
        self._column_filter_popup = popup

        popup.adjustSize()
        popup.move(self._column_filter_popup_position(column, global_pos, popup))
        popup.show()
        if focus_widget is not None:
            QTimer.singleShot(0, focus_widget.setFocus)
        return popup

    def _column_filter_popup_position(self, column, global_pos=None, popup=None):
        """Calcula posicao do popup proxima ao cabecalho da coluna."""
        if global_pos is not None:
            return global_pos

        source_df = self._get_active_source_df()
        if source_df is None or column not in source_df.columns:
            return self.mapToGlobal(QPoint(12, 12))

        section = list(source_df.columns).index(column)
        header = self.table_view.horizontalHeader()
        x = header.sectionViewportPosition(section) + max(0, header.sectionSize(section) - 260)
        y = header.height()
        return header.mapToGlobal(QPoint(x, y))

    def _copy_column_name(self, column):
        """Copy a column name to the clipboard."""
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().clipboard().setText(str(column))

    def _format_config(self, format_config: Any) -> dict:
        if isinstance(format_config, dict):
            config = dict(format_config)
            config["type"] = str(config.get("type", "default") or "default")
            return config
        return {"type": str(format_config or "default")}

    def _format_matches(self, current_format: Any, expected_format: Any) -> bool:
        current = self._format_config(current_format)
        expected = self._format_config(expected_format)
        return current == expected

    def _open_custom_format_dialog(self, column, format_type: str):
        current = self._format_config(self._column_formats.get(str(column), self._column_formats.get(column, {})))
        if current.get("type") != format_type:
            current = {"type": format_type, "decimals": 2, "prefix": "$ " if format_type == "currency" else "", "suffix": ""}
        dialog = NumberFormatDialog(format_type, current, parent=self, theme_manager=self.theme_manager)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_column_format(column, dialog.get_format_config())

    def _set_column_format(self, column, format_name):
        """Define formatacao visual de uma coluna."""
        column_name = str(column)
        config = self._format_config(format_name)
        if config.get("type") == "default":
            self._column_formats.pop(column_name, None)
            self._column_formats.pop(column, None)
        else:
            self._column_formats[column_name] = config
        if self._get_active_source_df() is not None:
            self._apply_active_dataframe_view(self._current_result_label())
        self._persist_view_state()
        self._schedule_summarize_refresh()

    def _add_chart_tab_from_current_source(self):
        """Cria uma nova aba de grafico a partir da fonte de dados ativa."""
        source_df, source_label, _ = self._current_data_source_for_visualization()
        if source_df is None:
            return
        config = self._normalize_visualization_config(
            {"type": "bar", "source_label": source_label},
            source_df,
            source_label,
        )
        chart_index = len(self._chart_configs)
        self._chart_configs.append(config)
        self._add_visualization_tab(config, chart_index, make_current=True)
        self._active_chart_index = chart_index
        self._persist_view_state()

    def _open_visualization_editor(self):
        """Abre editor compacto de configuracoes de grafico."""
        source_df, source_label, chart_index = self._current_data_source_for_visualization()
        if source_df is None:
            return

        current_config = {"source_label": source_label}
        if chart_index is not None and 0 <= chart_index < len(self._chart_configs):
            current_config = dict(self._chart_configs[chart_index])
        current_config["source_label"] = current_config.get("source_label") or source_label
        dialog = VisualizationEditorDialog(
            source_df,
            current_config,
            parent=self,
            theme_manager=self.theme_manager,
            render_fn=self._render_chart_image,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_visualization_config(dialog.get_config())

    def _set_visualization_config(self, config: dict):
        if not isinstance(config, dict):
            return

        source_df, source_label, editing_index = self._current_data_source_for_visualization()
        if source_df is None:
            source_df, source_label = self._source_dataframe_for_chart(config)
        if source_df is None:
            return

        if not config.get("source_label"):
            config = dict(config)
            config["source_label"] = source_label
        normalized = self._normalize_visualization_config(config, source_df, source_label)

        if editing_index is not None and 0 <= editing_index < len(self._chart_configs):
            chart_index = editing_index
            self._chart_configs[chart_index] = normalized
            page = next((page for page in self._chart_pages if getattr(page, "_chart_index", -1) == chart_index), None)
            if page is not None:
                page._config = dict(normalized)
                page._source_df = source_df
                page._source_label = source_label
                self._render_visualization_page(page)
                tab_index = self._result_tabs.indexOf(page)
                if tab_index >= 0:
                    self._result_tabs.setTabText(tab_index, self._chart_tab_label(chart_index, normalized))
        else:
            chart_index = len(self._chart_configs)
            self._chart_configs.append(normalized)
            self._add_visualization_tab(normalized, chart_index, make_current=True)

        self._active_chart_index = chart_index
        self._persist_view_state()

    def _show_grid_context_menu(self, pos, widget=None, global_pos=None):
        """Show context menu on the results grid."""
        if self.current_df is None:
            return

        if widget is None:
            widget = self.table_view.viewport()

        from src.design_system.tokens import get_colors
        from src.core.shortcut_manager import ShortcutManager
        colors_tk = get_colors()

        # Read configurable shortcut for "copy with headers"
        sm = ShortcutManager()
        copy_headers_key = sm.get_shortcut("copy_with_headers") or "Ctrl+Shift+C"

        menu = QMenu(self)

        # Copy (no headers)
        act_copy = QAction(
            qta.icon("mdi.content-copy", color=colors_tk.text_primary),
            S.results.ctx_copy,
            menu,
        )
        act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        # Keep the menu hint, but don't register a window-wide Ctrl+C grab
        # (the grid's keyPressEvent already handles copy when it has focus).
        act_copy.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        act_copy.triggered.connect(lambda: self._copy_selection_to_clipboard(include_headers=False))
        menu.addAction(act_copy)

        # Copy with headers
        act_copy_headers = QAction(
            qta.icon("mdi.table-headers-eye", color=colors_tk.text_primary),
            S.results.ctx_copy_with_headers,
            menu,
        )
        act_copy_headers.setShortcut(copy_headers_key)
        act_copy_headers.triggered.connect(lambda: self._copy_selection_to_clipboard(include_headers=True))
        menu.addAction(act_copy_headers)

        menu.addSeparator()

        # Select All
        act_select_all = QAction(
            qta.icon("mdi.select-all", color=colors_tk.text_primary),
            S.results.ctx_select_all,
            menu,
        )
        act_select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        act_select_all.triggered.connect(self.table_view.selectAll)
        menu.addAction(act_select_all)

        menu.addSeparator()

        # Export CSV
        act_csv = QAction(
            qta.icon("mdi.file-delimited", color=colors_tk.info),
            S.results.btn_csv,
            menu,
        )
        act_csv.triggered.connect(self._export_csv)
        menu.addAction(act_csv)

        # Export Excel
        act_excel = QAction(
            qta.icon("mdi.file-excel", color=colors_tk.success),
            S.results.btn_excel,
            menu,
        )
        act_excel.triggered.connect(self._export_excel)
        menu.addAction(act_excel)

        # Export JSON
        act_json = QAction(
            qta.icon("mdi.code-json", color=colors_tk.warning),
            S.results.btn_json,
            menu,
        )
        act_json.triggered.connect(self._export_json)
        menu.addAction(act_json)

        if global_pos is None:
            global_pos = widget.mapToGlobal(pos)
        menu.exec(global_pos)

    def keyPressEvent(self, event):
        """Handle Ctrl+C to copy selected cells from the grid."""
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection_to_clipboard()
            return
        super().keyPressEvent(event)

    def _save_image(self):
        """Save displayed image or interactive chart HTML."""
        page = self._result_tabs.currentWidget()
        chart_html = getattr(page, "_chart_html", None) if self._is_chart_page(page) else None
        if chart_html:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                S.visualization.save_chart_html,
                "",
                S.visualization.filter_chart_html,
            )
            if filename:
                if not filename.lower().endswith(".html"):
                    filename += ".html"
                try:
                    with open(filename, "w", encoding="utf-8") as handle:
                        handle.write(chart_html)
                except Exception as error:
                    show_danger(
                        self,
                        S.results.error_title,
                        S.results.error_save_image.format(error=str(error)),
                    )
            return

        if not self._current_image_bytes:
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, S.results.save_image_title, "", S.results.filter_image
        )
        if filename:
            if not any(filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg")):
                filename += ".png"
            try:
                with open(filename, "wb") as handle:
                    handle.write(self._current_image_bytes)
            except Exception as error:
                show_danger(
                    self,
                    S.results.error_title,
                    S.results.error_save_image.format(error=str(error)),
                )

    def _export_to_table(self):
        """Export current DataFrame to a database table"""
        if self.current_df is None or len(self.current_df) == 0:
            show_warning(self, S.results.error_title, S.results.export_table_no_data)
            return

        # Get active connections from MainWindow
        main_window = self._get_main_window()
        if not main_window:
            show_warning(self, S.results.error_title, S.results.export_table_no_window)
            return

        # Collect active connections from all sessions
        connections = {}
        if hasattr(main_window, "_session_widgets"):
            for widget in main_window._session_widgets.values():
                session = getattr(widget, "session", None)
                if session:
                    conn_name = getattr(session, "connection_name", None)
                    connector = getattr(session, "connector", None)
                    if conn_name and connector and getattr(connector, "is_connected", False):
                        connections[conn_name] = connector

        if not connections:
            show_warning(
                self,
                S.results.error_title,
                S.results.export_table_no_connection,
            )
            return

        # Determine current connection (from focused block or session)
        current_connection = ""
        current_widget = main_window._get_current_session_widget()
        if current_widget:
            focused_block = current_widget.editor.get_focused_block()
            if focused_block:
                block_conn = focused_block.get_connection_name()
                if block_conn and block_conn in connections:
                    current_connection = block_conn
            if not current_connection:
                session_conn = getattr(current_widget.session, "connection_name", "")
                if session_conn and session_conn in connections:
                    current_connection = session_conn
            if not current_connection and connections:
                current_connection = next(iter(connections))

        from src.ui.dialogs.export_to_table_dialog import ExportToTableDialog

        dialog = ExportToTableDialog(
            df=self.current_df,
            connections=connections,
            current_connection=current_connection,
            theme_manager=self.theme_manager,
            parent=self,
        )
        dialog.exec()

    def _get_main_window(self):
        """Obtem referencia a MainWindow"""
        parent = self.parent()
        while parent and not hasattr(parent, "connection_manager"):
            parent = parent.parent()
        return parent

    def resizeEvent(self, event):
        """Reescala imagem quando o widget e redimensionado"""
        super().resizeEvent(event)
        if not hasattr(self, "stack"):
            return
        if self.stack.currentIndex() == 1 and hasattr(self, "_original_pixmap"):
            viewport_w = self.image_scroll.viewport().width()
            viewport_h = self.image_scroll.viewport().height()
            if viewport_w > 100 and viewport_h > 100:
                scaled = self._original_pixmap.scaled(
                    viewport_w - 20,
                    viewport_h - 20,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.image_label.setPixmap(scaled)
