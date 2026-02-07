"""
Visualizador de resultados em tabela
"""

import os
import subprocess
from typing import Optional

import pandas as pd
import qtawesome as qta
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSettings, Qt, QVariant
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

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

        # Info label
        self.info_label = QLabel("Nenhum resultado")
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.info_label)

        layout.addWidget(self.toolbar)

        # Tabela
        self.table_view = QTableView()
        self._apply_table_style()

        self.model = PandasModel(theme_manager=self.theme_manager)
        self.table_view.setModel(self.model)

        # Ajustar colunas automaticamente pelo conteúdo do cabeçalho
        self.table_view.horizontalHeader().setSectionResizeMode(
            self.table_view.horizontalHeader().ResizeMode.ResizeToContents
        )

        layout.addWidget(self.table_view)

        # Conectar sinais
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_export_excel.clicked.connect(self._export_excel)
        self.btn_export_json.clicked.connect(self._export_json)
        self.btn_copy.clicked.connect(self._copy_to_clipboard)

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
        self.info_label.setText(f"{var_name}: {rows:,} linhas × {cols} colunas")

    def clear(self):
        """Limpa a visualização"""
        self.current_df = None
        self.model.update_data(pd.DataFrame())
        self.info_label.setText("Nenhum resultado")

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
