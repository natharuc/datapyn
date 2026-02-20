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
    QMessageBox,
    QStackedWidget,
    QScrollArea,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QSpinBox,
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QSettings, QTimer
from PyQt6.QtGui import QColor, QImage, QPixmap, QFont
import pandas as pd
import json
from typing import Optional
import subprocess
import os
import qtawesome as qta

from src.core.theme_manager import ThemeManager
from src.language import S


class CSVExportDialog(QDialog):
    """Dialog to configure CSV export"""

    def __init__(self, parent=None, theme_manager: ThemeManager = None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self.setWindowTitle(S.csv_export.dialog_title)
        self.setMinimumWidth(400)

        # Remove maximize/minimize buttons
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # Delimiter
        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItem(S.csv_export.delimiter_semicolon, ";")
        self.delimiter_combo.addItem(S.csv_export.delimiter_comma, ",")
        self.delimiter_combo.addItem(S.csv_export.delimiter_tab, "\t")
        self.delimiter_combo.addItem(S.csv_export.delimiter_pipe, "|")
        form.addRow(S.csv_export.label_delimiter, self.delimiter_combo)

        # Encoding
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItem(S.csv_export.encoding_utf8bom, "utf-8-sig")
        self.encoding_combo.addItem(S.csv_export.encoding_utf8, "utf-8")
        self.encoding_combo.addItem(S.csv_export.encoding_latin1, "latin-1")
        self.encoding_combo.addItem(S.csv_export.encoding_cp1252, "cp1252")
        form.addRow(S.csv_export.label_encoding, self.encoding_combo)

        # Include header
        self.header_check = QCheckBox()
        self.header_check.setChecked(True)
        form.addRow(S.csv_export.label_include_header, self.header_check)

        # Open folder after export
        self.open_folder_check = QCheckBox()
        self.open_folder_check.setChecked(True)
        form.addRow(S.csv_export.label_open_folder, self.open_folder_check)

        layout.addLayout(form)

        # Buttons (reversing order: Cancel, OK)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Apply theme
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())

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


class PandasModel(QAbstractTableModel):
    """Model para exibir DataFrame do pandas no QTableView"""

    def __init__(self, df: pd.DataFrame = None, theme_manager: ThemeManager = None):
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()
        self.theme_manager = theme_manager or ThemeManager()
        self._update_colors()

    def _update_colors(self):
        """Atualiza as cores baseado no tema"""
        colors = self.theme_manager.get_table_colors()
        self._row_even = QColor(colors["row_even"])
        self._row_odd = QColor(colors["row_odd"])
        self._text_color = QColor(colors["text"])
        self._header_bg = QColor(colors["header_bg"])
        self._header_text = QColor(colors["header_text"])

    def set_theme_manager(self, theme_manager: ThemeManager):
        """Atualiza o theme manager e recarrega cores"""
        self.theme_manager = theme_manager
        self._update_colors()
        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()

        if role == Qt.ItemDataRole.DisplayRole:
            value = self._df.iloc[index.row(), index.column()]
            return str(value)

        if role == Qt.ItemDataRole.BackgroundRole:
            # Alternar cores das linhas
            if index.row() % 2 == 0:
                return self._row_even
            else:
                return self._row_odd

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._text_color

        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                # Manter case original do banco de dados
                return self._df.columns[section]
            else:
                return str(section + 1)

        if role == Qt.ItemDataRole.BackgroundRole:
            return self._header_bg

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._header_text

        return QVariant()

    def update_data(self, df: pd.DataFrame):
        """Atualiza o DataFrame"""
        self.beginResetModel()
        self._df = df
        self.endResetModel()


class ResultsViewer(QWidget):
    """Widget para visualizar resultados de queries"""

    def __init__(self, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self._setup_ui()
        self.current_df: Optional[pd.DataFrame] = None
        self._current_image_bytes: Optional[bytes] = None
        self._display_limit: int = self._load_display_limit()

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
        self.export_destination = QComboBox()
        self.export_destination.addItem(S.results.dest_clipboard, "clipboard")
        self.export_destination.setItemIcon(0, qta.icon("mdi.clipboard-text", color="#64b5f6"))
        self.export_destination.addItem(S.results.dest_file, "file")
        self.export_destination.setItemIcon(1, qta.icon("mdi.file-export", color="#64b5f6"))
        self.export_destination.setMinimumWidth(140)
        self.export_destination.setToolTip(S.results.tooltip_export_dest)
        self.toolbar.addWidget(self.export_destination)
        self.toolbar.addSeparator()

        # Toolbar buttons with icons
        self.btn_export_csv = QPushButton(S.results.btn_csv)
        self.btn_export_csv.setIcon(qta.icon("mdi.file-delimited-outline", color="#9d9d9d"))
        self.btn_export_excel = QPushButton(S.results.btn_excel)
        self.btn_export_excel.setIcon(qta.icon("mdi.file-excel-outline", color="#4caf50"))
        self.btn_export_json = QPushButton(S.results.btn_json)
        self.btn_export_json.setIcon(qta.icon("mdi.code-json", color="#ffc107"))
        self.btn_copy = QPushButton(S.results.btn_copy_all)
        self.btn_copy.setIcon(qta.icon("mdi.content-copy", color="#9d9d9d"))

        self.toolbar.addWidget(self.btn_export_csv)
        self.toolbar.addWidget(self.btn_export_excel)
        self.toolbar.addWidget(self.btn_export_json)
        self.toolbar.addWidget(self.btn_copy)

        # Export to Table button (database)
        self.toolbar.addSeparator()
        self.btn_export_table = QPushButton(S.results.btn_table)
        self.btn_export_table.setIcon(qta.icon("mdi.database-export", color="#4fc3f7"))
        self.btn_export_table.setToolTip(S.results.tooltip_export_table)
        self.toolbar.addWidget(self.btn_export_table)

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
        self.row_limit_spin.setStyleSheet("""
            QSpinBox {
                background-color: #2d2d30;
                color: #cccccc;
                border: 1px solid #3e3e42;
                border-radius: 0px;
                padding: 2px 6px;
                font-size: 11px;
            }
            QSpinBox:hover { border-color: #007acc; }
        """)
        self.row_limit_spin.valueChanged.connect(self._on_row_limit_changed)
        self.toolbar.addWidget(self.row_limit_spin)

        layout.addWidget(self.toolbar)

        # Save image button (hidden by default)
        self.btn_save_image = QPushButton(S.results.btn_save_image)
        self.btn_save_image.setVisible(False)
        self.toolbar.addWidget(self.btn_save_image)

        # QStackedWidget: page 0 = table, page 1 = image
        self.stack = QStackedWidget()

        # Page 0 - Table
        self.table_view = QTableView()
        self._apply_table_style()

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
        """)
        self.json_tree.setFont(QFont("Consolas", 10))
        self.stack.addWidget(self.json_tree)  # index 3

        layout.addWidget(self.stack)

        # Conectar sinais
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_export_excel.clicked.connect(self._export_excel)
        self.btn_export_json.clicked.connect(self._export_json)
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        self.btn_save_image.clicked.connect(self._save_image)
        self.btn_export_table.clicked.connect(self._export_to_table)

    def _apply_toolbar_style(self):
        """Aplica estilo na toolbar baseado no tema - moderno e limpo"""
        colors = self.theme_manager.get_app_colors()
        from src.design_system.tokens import RADIUS
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
        """)

    def _apply_table_style(self):
        """Aplica estilo na tabela baseado no tema - moderno e limpo"""
        table_colors = self.theme_manager.get_table_colors()
        colors = self.theme_manager.get_app_colors()
        from src.design_system.tokens import RADIUS
        self.table_view.setStyleSheet(f"""
            QTableView {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                gridline-color: transparent;
                selection-background-color: {colors["accent"]};
                font-size: 13px;
            }}
            QTableView::item {{
                padding: 8px 12px;
                border-bottom: 1px solid {colors["border"]};
            }}
            QTableView::item:selected {{
                background-color: {colors["accent"]};
                color: white;
            }}
            QTableView::item:hover {{
                background-color: rgba(75, 123, 236, 0.15);
            }}
            QHeaderView::section {{
                background-color: {table_colors["header_bg"]};
                color: {table_colors["header_text"]};
                padding: 10px 12px;
                border: none;
                border-bottom: 2px solid {colors["border"]};
                font-weight: 500;
                font-size: 12px;
            }}
            QHeaderView::section:hover {{
                background-color: {colors["border"]};
            }}
        """)

    def set_theme_manager(self, theme_manager: ThemeManager):
        """Atualiza o tema"""
        self.theme_manager = theme_manager
        self._apply_toolbar_style()
        self._apply_table_style()
        self.model.set_theme_manager(theme_manager)

    def display_dataframe(self, df: pd.DataFrame, var_name: str = "df"):
        """Exibe um DataFrame na tabela.

        Armazena o DataFrame completo para exportacao, mas exibe apenas
        ate o limite de linhas configurado para manter a interface fluida.
        """
        self.current_df = df

        # Atualiza info com totais reais
        rows = len(df)
        cols = len(df.columns)
        limit = self.row_limit_spin.value()

        # Alimentar modelo apenas com o slice limitado
        display_df = df.head(limit) if rows > limit else df
        self.model.update_data(display_df)

        # Ajustar colunas pelo conteudo visivel (nao bloqueia com 100k linhas)
        QTimer.singleShot(0, self._resize_columns)

        # Info label mostra total real e quantas estao exibidas
        if rows > limit:
            info_text = S.results.info_df_dimensions.format(
                var_name=var_name, rows=f"{rows:,}", cols=cols
            )
            showing = S.results.showing_limited.format(showing=f"{limit:,}") if hasattr(S.results, 'showing_limited') else f" (showing {limit:,})"
            self.info_label.setText(info_text + showing)
        else:
            self.info_label.setText(S.results.info_df_dimensions.format(var_name=var_name, rows=f"{rows:,}", cols=cols))

        # Mostrar tabela e botoes de export
        self.stack.setCurrentIndex(0)
        self.btn_export_csv.setVisible(True)
        self.btn_export_excel.setVisible(True)
        self.btn_export_json.setVisible(True)
        self.btn_copy.setVisible(True)
        self.btn_export_table.setVisible(True)
        self.export_destination.setVisible(True)
        self.btn_save_image.setVisible(False)

    def _resize_columns(self):
        """Ajusta largura das colunas pelo conteudo visivel (deferido via QTimer)."""
        self.table_view.resizeColumnsToContents()

    def _on_row_limit_changed(self, value: int):
        """Quando usuario muda o limite de linhas no spinner."""
        # Reaplicar exibicao com novo limite
        if self.current_df is not None:
            self.display_dataframe(self.current_df, self._current_var_name())

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
        self.export_destination.setVisible(False)
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

        combined = QImage(max_w, total_h, QImage.Format.Format_ARGB32)
        combined.fill(QColor("#1e1e1e"))

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
        self.export_destination.setVisible(False)
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
                font-family: 'Segoe UI', Consolas, monospace;
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
                border-radius: 0px;
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
        type_color = QColor(colors.get("accent", "#3369FF"))

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

    def _hide_all_toolbar_buttons(self):
        """Esconde todos os botoes da toolbar (usado para HTML e JSON pages)."""
        self.btn_export_csv.setVisible(False)
        self.btn_export_excel.setVisible(False)
        self.btn_export_json.setVisible(False)
        self.btn_copy.setVisible(False)
        self.btn_export_table.setVisible(False)
        self.export_destination.setVisible(False)
        self.btn_save_image.setVisible(False)

    def clear(self):
        """Clear visualization"""
        self.current_df = None
        self._current_image_bytes = None
        self.model.update_data(pd.DataFrame())
        self.image_label.clear()
        self.html_viewer.clear()
        self.json_tree.clear()
        self.info_label.setText(S.results.no_results)
        self.stack.setCurrentIndex(0)
        self.btn_save_image.setVisible(False)
        self.btn_export_csv.setVisible(True)
        self.btn_export_excel.setVisible(True)
        self.btn_export_json.setVisible(True)
        self.btn_copy.setVisible(True)
        self.btn_export_table.setVisible(True)
        self.export_destination.setVisible(True)

    def _get_export_destination(self) -> str:
        """Return selected destination: 'clipboard' or 'file'"""
        return self.export_destination.currentData()

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

        try:
            self.current_df.to_csv(filename, index=False, encoding=encoding, sep=delimiter, header=include_header)

            if open_folder:
                subprocess.run(["explorer", "/select,", os.path.normpath(filename)])

        except Exception as e:
            QMessageBox.critical(self, S.results.error_title, S.results.error_export_csv.format(error=str(e)))

    def _export_excel(self):
        """Export to Excel (clipboard or file)"""
        if self.current_df is None:
            return

        destination = self._get_export_destination()

        if destination == "clipboard":
            # Excel in clipboard - tab-separated format that Excel understands
            from PyQt6.QtWidgets import QApplication

            excel_text = self.current_df.to_csv(index=False, sep="\t")
            QApplication.instance().clipboard().setText(excel_text)
            self._show_clipboard_success("Excel (tab)")
            return

        # Export to file
        filename, _ = QFileDialog.getSaveFileName(self, S.results.save_excel_title, "", S.results.filter_excel)
        if filename:
            if not filename.lower().endswith(".xlsx"):
                filename += ".xlsx"
            try:
                self.current_df.to_excel(filename, index=False)
            except Exception as e:
                QMessageBox.critical(self, S.results.error_title, S.results.error_export_excel.format(error=str(e)))

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
        filename, _ = QFileDialog.getSaveFileName(self, S.results.save_json_title, "", S.results.filter_json)
        if filename:
            if not filename.lower().endswith(".json"):
                filename += ".json"
            try:
                self.current_df.to_json(filename, orient="records", indent=2, force_ascii=False)
            except Exception as e:
                QMessageBox.critical(self, S.results.error_title, S.results.error_export_json.format(error=str(e)))

    def _copy_to_clipboard(self):
        """Copy formatted data to clipboard"""
        from PyQt6.QtWidgets import QApplication

        if self.current_df is not None:
            text = self.current_df.to_string(index=False)
            QApplication.instance().clipboard().setText(text)
            self._show_clipboard_success("Table")

    def _save_image(self):
        """Save displayed image to file"""
        if not self._current_image_bytes:
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, S.results.save_image_title, "", S.results.filter_image
        )
        if filename:
            if not any(filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg")):
                filename += ".png"
            try:
                with open(filename, "wb") as f:
                    f.write(self._current_image_bytes)
            except Exception as e:
                QMessageBox.critical(self, S.results.error_title, S.results.error_save_image.format(error=str(e)))

    def _export_to_table(self):
        """Export current DataFrame to a database table"""
        if self.current_df is None or len(self.current_df) == 0:
            QMessageBox.warning(self, S.results.error_title, S.results.export_table_no_data)
            return

        # Get active connections from MainWindow
        main_window = self._get_main_window()
        if not main_window:
            QMessageBox.warning(self, S.results.error_title, S.results.export_table_no_window)
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
            QMessageBox.warning(
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
