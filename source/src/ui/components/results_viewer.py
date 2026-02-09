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
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QSettings
from PyQt6.QtGui import QColor, QImage, QPixmap, QFont
import pandas as pd
import json
from typing import Optional
import subprocess
import os
import qtawesome as qta

from src.core.theme_manager import ThemeManager


class CSVExportDialog(QDialog):
    """Diálogo para configurar exportação CSV"""

    def __init__(self, parent=None, theme_manager: ThemeManager = None):
        super().__init__(parent)
        self.theme_manager = theme_manager or ThemeManager()
        self.setWindowTitle("Exportar CSV")
        self.setMinimumWidth(400)

        # Remover botões maximizar/minimizar
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # Delimitador
        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItem("Ponto e Vírgula (;)", ";")
        self.delimiter_combo.addItem("Vírgula (,)", ",")
        self.delimiter_combo.addItem("Tab (\\t)", "\t")
        self.delimiter_combo.addItem("Pipe (|)", "|")
        form.addRow("Delimitador:", self.delimiter_combo)

        # Encoding
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItem("UTF-8 com BOM (Excel)", "utf-8-sig")
        self.encoding_combo.addItem("UTF-8", "utf-8")
        self.encoding_combo.addItem("Latin-1 (ISO-8859-1)", "latin-1")
        self.encoding_combo.addItem("Windows-1252", "cp1252")
        form.addRow("Codificação:", self.encoding_combo)

        # Incluir cabeçalho
        self.header_check = QCheckBox()
        self.header_check.setChecked(True)
        form.addRow("Incluir cabeçalho:", self.header_check)

        # Abrir pasta após exportar
        self.open_folder_check = QCheckBox()
        self.open_folder_check.setChecked(True)
        form.addRow("Abrir pasta após exportar:", self.open_folder_check)

        layout.addLayout(form)

        # Botões (invertendo ordem: Cancel, OK)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Aplicar tema
        self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())

    def _load_settings(self):
        """Carrega configurações salvas"""
        settings = QSettings("DataPyn", "CSVExport")

        # Delimitador
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

        # Abrir pasta
        open_folder = settings.value("open_folder", True, type=bool)
        self.open_folder_check.setChecked(open_folder)

    def _save_settings(self):
        """Salva configurações"""
        settings = QSettings("DataPyn", "CSVExport")
        settings.setValue("delimiter", self.get_delimiter())
        settings.setValue("encoding", self.get_encoding())
        settings.setValue("header", self.get_include_header())
        settings.setValue("open_folder", self.get_open_folder())

    def accept(self):
        """Salva configurações ao aceitar"""
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
        self.export_destination.addItem("Clipboard", "clipboard")
        self.export_destination.setItemIcon(0, qta.icon("mdi.clipboard-text", color="#64b5f6"))
        self.export_destination.addItem("Arquivo", "file")
        self.export_destination.setItemIcon(1, qta.icon("mdi.file-export", color="#64b5f6"))
        self.export_destination.setMinimumWidth(140)
        self.export_destination.setToolTip("Destino da exportação")
        self.toolbar.addWidget(self.export_destination)
        self.toolbar.addSeparator()

        # Botões da toolbar
        self.btn_export_csv = QPushButton("CSV")
        self.btn_export_excel = QPushButton("Excel")
        self.btn_export_json = QPushButton("JSON")
        self.btn_copy = QPushButton("Copiar Tudo")

        self.toolbar.addWidget(self.btn_export_csv)
        self.toolbar.addWidget(self.btn_export_excel)
        self.toolbar.addWidget(self.btn_export_json)
        self.toolbar.addWidget(self.btn_copy)

        # Botao Exportar para Tabela (banco de dados)
        self.toolbar.addSeparator()
        self.btn_export_table = QPushButton("  Tabela")
        self.btn_export_table.setIcon(qta.icon("mdi.database-export", color="#4fc3f7"))
        self.btn_export_table.setToolTip("Exportar dados para uma tabela no banco de dados (to_sql)")
        self.toolbar.addWidget(self.btn_export_table)

        # Info label
        self.info_label = QLabel("Nenhum resultado")
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.info_label)

        layout.addWidget(self.toolbar)

        # Botao salvar imagem (oculto por padrao)
        self.btn_save_image = QPushButton("Salvar Imagem")
        self.btn_save_image.setVisible(False)
        self.toolbar.addWidget(self.btn_save_image)

        # QStackedWidget: pagina 0 = tabela, pagina 1 = imagem
        self.stack = QStackedWidget()

        # Pagina 0 - Tabela
        self.table_view = QTableView()
        self._apply_table_style()

        self.model = PandasModel(theme_manager=self.theme_manager)
        self.table_view.setModel(self.model)

        # Ajustar colunas automaticamente pelo conteudo do cabecalho
        self.table_view.horizontalHeader().setSectionResizeMode(
            self.table_view.horizontalHeader().ResizeMode.ResizeToContents
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
        self.json_tree.setHeaderLabels(["Chave", "Valor", "Tipo"])
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
        """Aplica estilo na toolbar baseado no tema"""
        colors = self.theme_manager.get_app_colors()
        self.toolbar.setStyleSheet(f"""
            QToolBar {{
                background-color: {colors["border"]};
                border-bottom: 1px solid {colors["border"]};
                spacing: 5px;
                padding: 5px;
            }}
            QPushButton {{
                background-color: {colors["accent"]};
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {colors["accent"]};
            }}
            QLabel {{
                color: {colors["foreground"]};
                padding: 5px;
            }}
        """)

    def _apply_table_style(self):
        """Aplica estilo na tabela baseado no tema"""
        table_colors = self.theme_manager.get_table_colors()
        colors = self.theme_manager.get_app_colors()
        self.table_view.setStyleSheet(f"""
            QTableView {{
                background-color: {colors["background"]};
                color: {colors["foreground"]};
                border: none;
                gridline-color: {colors["border"]};
            }}
            QTableView::item:selected {{
                background-color: {colors["accent"]};
            }}
            QHeaderView::section {{
                background-color: {table_colors["header_bg"]};
                color: {table_colors["header_text"]};
                padding: 5px;
                border: 1px solid {colors["border"]};
                font-weight: bold;
                text-transform: none;
            }}
        """)

    def set_theme_manager(self, theme_manager: ThemeManager):
        """Atualiza o tema"""
        self.theme_manager = theme_manager
        self._apply_toolbar_style()
        self._apply_table_style()
        self.model.set_theme_manager(theme_manager)

    def display_dataframe(self, df: pd.DataFrame, var_name: str = "df"):
        """Exibe um DataFrame na tabela"""
        self.current_df = df
        self.model.update_data(df)

        # Atualiza info
        rows = len(df)
        cols = len(df.columns)
        self.info_label.setText(f"{var_name}: {rows:,} linhas x {cols} colunas")

        # Mostrar tabela e botoes de export
        self.stack.setCurrentIndex(0)
        self.btn_export_csv.setVisible(True)
        self.btn_export_excel.setVisible(True)
        self.btn_export_json.setVisible(True)
        self.btn_copy.setVisible(True)
        self.btn_export_table.setVisible(True)
        self.export_destination.setVisible(True)
        self.btn_save_image.setVisible(False)

    def display_image(self, image_bytes: bytes, label: str = "Grafico"):
        """Exibe uma imagem (PNG bytes) no painel de resultados.

        Args:
            image_bytes: Bytes da imagem PNG
            label: Texto descritivo para a info label
        """
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

        self.info_label.setText(f"{label} ({img.width()} x {img.height()} px)")

        # Mostrar imagem e botao salvar, esconder export de dados
        self.stack.setCurrentIndex(1)
        self.btn_export_csv.setVisible(False)
        self.btn_export_excel.setVisible(False)
        self.btn_export_json.setVisible(False)
        self.btn_copy.setVisible(False)
        self.export_destination.setVisible(False)
        self.btn_save_image.setVisible(True)

    def display_images(self, images_bytes_list: list, label: str = "Graficos"):
        """Exibe multiplas imagens combinadas verticalmente.

        Args:
            images_bytes_list: Lista de bytes PNG
            label: Texto descritivo
        """
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

        self.info_label.setText(f"{label} ({len(images)} imagens)")

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
                border-radius: 3px;
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
            self.info_label.setText(f"{label} (dict: {count} chaves)")
        elif isinstance(data, list):
            self._populate_json_tree(self.json_tree.invisibleRootItem(), data, type_color)
            count = len(data)
            self.info_label.setText(f"{label} (list: {count} itens)")
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
                    item.setText(1, f"{{{count} itens}}" if isinstance(value, dict) else f"[{count} itens]")
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
                    item.setText(1, f"{{{count} itens}}" if isinstance(value, dict) else f"[{count} itens]")
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

    def display_rich_output(self, outputs: list, label: str = "Resultado"):
        """Exibe rich outputs baseado no tipo de cada item.

        Aceita lista de dicts com tipo:
            {'type': 'image', 'data': bytes}     # PNG bytes
            {'type': 'html', 'data': str}        # HTML string
            {'type': 'json', 'data': object}     # dict/list

        Tambem aceita lista de bytes puros (backward compat com display_images).

        Prioridade quando ha tipos mistos: image > html > json
        """
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
        """Limpa a visualizacao"""
        self.current_df = None
        self._current_image_bytes = None
        self.model.update_data(pd.DataFrame())
        self.image_label.clear()
        self.html_viewer.clear()
        self.json_tree.clear()
        self.info_label.setText("Nenhum resultado")
        self.stack.setCurrentIndex(0)
        self.btn_save_image.setVisible(False)
        self.btn_export_csv.setVisible(True)
        self.btn_export_excel.setVisible(True)
        self.btn_export_json.setVisible(True)
        self.btn_copy.setVisible(True)
        self.btn_export_table.setVisible(True)
        self.export_destination.setVisible(True)

    def _get_export_destination(self) -> str:
        """Retorna o destino selecionado: 'clipboard' ou 'file'"""
        return self.export_destination.currentData()

    def _show_clipboard_success(self, format_name: str):
        """Mostra feedback de sucesso ao copiar para clipboard"""
        self.info_label.setText(f"{format_name} copiado!")

    def _export_csv(self):
        """Exporta para CSV (clipboard ou arquivo)"""
        if self.current_df is None:
            return

        # Sempre abrir diálogo de configuração
        dialog = CSVExportDialog(self, theme_manager=self.theme_manager)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        delimiter = dialog.get_delimiter()
        encoding = dialog.get_encoding()
        include_header = dialog.get_include_header()
        open_folder = dialog.get_open_folder()

        destination = self._get_export_destination()

        if destination == "clipboard":
            # Exportar para clipboard com configurações
            from PyQt6.QtWidgets import QApplication

            csv_text = self.current_df.to_csv(index=False, sep=delimiter, encoding=encoding, header=include_header)
            QApplication.instance().clipboard().setText(csv_text)
            self._show_clipboard_success("CSV")
            return

        # Exportar para arquivo

        filename, _ = QFileDialog.getSaveFileName(self, "Salvar CSV", "", "CSV Files (*.csv)")
        if not filename:
            return

        if not filename.lower().endswith(".csv"):
            filename += ".csv"

        try:
            self.current_df.to_csv(filename, index=False, encoding=encoding, sep=delimiter, header=include_header)

            if open_folder:
                subprocess.run(["explorer", "/select,", os.path.normpath(filename)])

        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao exportar CSV:\n{str(e)}")

    def _export_excel(self):
        """Exporta para Excel (clipboard ou arquivo)"""
        if self.current_df is None:
            return

        destination = self._get_export_destination()

        if destination == "clipboard":
            # Excel no clipboard - formato tab-separated que Excel entende
            from PyQt6.QtWidgets import QApplication

            excel_text = self.current_df.to_csv(index=False, sep="\t")
            QApplication.instance().clipboard().setText(excel_text)
            self._show_clipboard_success("Excel (tab)")
            return

        # Exportar para arquivo
        filename, _ = QFileDialog.getSaveFileName(self, "Salvar Excel", "", "Excel Files (*.xlsx)")
        if filename:
            if not filename.lower().endswith(".xlsx"):
                filename += ".xlsx"
            try:
                self.current_df.to_excel(filename, index=False)
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao exportar Excel:\n{str(e)}")

    def _export_json(self):
        """Exporta para JSON (clipboard ou arquivo)"""
        if self.current_df is None:
            return

        destination = self._get_export_destination()

        if destination == "clipboard":
            from PyQt6.QtWidgets import QApplication

            json_text = self.current_df.to_json(orient="records", indent=2, force_ascii=False)
            QApplication.instance().clipboard().setText(json_text)
            self._show_clipboard_success("JSON")
            return

        # Exportar para arquivo
        filename, _ = QFileDialog.getSaveFileName(self, "Salvar JSON", "", "JSON Files (*.json)")
        if filename:
            if not filename.lower().endswith(".json"):
                filename += ".json"
            try:
                self.current_df.to_json(filename, orient="records", indent=2, force_ascii=False)
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao exportar JSON:\n{str(e)}")

    def _copy_to_clipboard(self):
        """Copia dados formatados para clipboard"""
        from PyQt6.QtWidgets import QApplication

        if self.current_df is not None:
            text = self.current_df.to_string(index=False)
            QApplication.instance().clipboard().setText(text)
            self._show_clipboard_success("Tabela")

    def _save_image(self):
        """Salva a imagem exibida em arquivo"""
        if not self._current_image_bytes:
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, "Salvar Imagem", "", "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)"
        )
        if filename:
            if not any(filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg")):
                filename += ".png"
            try:
                with open(filename, "wb") as f:
                    f.write(self._current_image_bytes)
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao salvar imagem:\n{str(e)}")

    def _export_to_table(self):
        """Exporta o DataFrame atual para uma tabela no banco de dados"""
        if self.current_df is None or len(self.current_df) == 0:
            QMessageBox.warning(self, "Exportar para Tabela", "Nenhum dado para exportar")
            return

        # Obter conexoes ativas da MainWindow
        main_window = self._get_main_window()
        if not main_window:
            QMessageBox.warning(self, "Exportar para Tabela", "Janela principal nao encontrada")
            return

        # Coletar conexoes ativas de todas as sessoes
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
                "Exportar para Tabela",
                "Nenhuma conexao ativa disponivel.\n\nConecte-se a um banco de dados primeiro.",
            )
            return

        # Determinar conexao atual (do bloco focado ou da sessao)
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
