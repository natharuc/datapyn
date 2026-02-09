"""
FileImportDialog - Dialogo para configurar importacao de arquivos de dados

Quando o usuario arrasta CSV, JSON ou XLSX, este dialogo permite configurar:
- Nome da variavel (DataFrame)
- Separador (CSV)
- Encoding
- Sheet (XLSX)
- Limitar linhas
- Outras opcoes relevantes por tipo
"""

import os
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QGroupBox,
    QFormLayout,
    QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from src.core.theme_manager import ThemeManager
from src.services.file_import_service import FileImportService


# Encodings comuns
ENCODINGS = [
    "utf-8",
    "latin-1",
    "iso-8859-1",
    "cp1252",
    "ascii",
    "utf-16",
    "utf-32",
]

# Separadores comuns para CSV
CSV_SEPARATORS = [
    (";", "Ponto-e-virgula (;)"),
    (",", "Virgula (,)"),
    ("\\t", "Tab (\\t)"),
    ("|", "Pipe (|)"),
    (" ", "Espaco"),
]


class FileImportDialog(QDialog):
    """Dialogo para configurar importacao de arquivos de dados."""

    def __init__(self, file_path: str, theme_manager: ThemeManager = None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.theme_manager = theme_manager
        self._ext = os.path.splitext(file_path.lower())[1]
        self._result_code = None

        self.setWindowTitle("Importar Arquivo")
        self.setMinimumWidth(480)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Titulo
        title = QLabel("Importar Dados")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # Arquivo selecionado
        file_name = os.path.basename(self.file_path)
        file_label = QLabel(f"Arquivo: {file_name}")
        file_label.setStyleSheet("color: #808080; font-size: 11px;")
        layout.addWidget(file_label)

        # Grupo: Configuracoes gerais
        general_group = QGroupBox("Geral")
        general_form = QFormLayout(general_group)
        general_form.setSpacing(8)

        # Nome da variavel
        default_name = FileImportService._normalize_var_name(self.file_path)
        self.var_name_input = QLineEdit(default_name)
        self.var_name_input.setPlaceholderText("Nome do DataFrame")
        general_form.addRow("Variavel:", self.var_name_input)

        # Encoding
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(ENCODINGS)
        self.encoding_combo.setCurrentText("utf-8")
        general_form.addRow("Encoding:", self.encoding_combo)

        # Limitar linhas
        nrows_container = QWidget()
        nrows_layout = QHBoxLayout(nrows_container)
        nrows_layout.setContentsMargins(0, 0, 0, 0)
        nrows_layout.setSpacing(8)

        self.limit_rows_check = QCheckBox("Limitar")
        self.limit_rows_check.setChecked(False)
        nrows_layout.addWidget(self.limit_rows_check)

        self.nrows_spin = QSpinBox()
        self.nrows_spin.setMinimum(1)
        self.nrows_spin.setMaximum(10_000_000)
        self.nrows_spin.setValue(1000)
        self.nrows_spin.setEnabled(False)
        self.nrows_spin.setSuffix(" linhas")
        nrows_layout.addWidget(self.nrows_spin)
        nrows_layout.addStretch()

        self.limit_rows_check.toggled.connect(self.nrows_spin.setEnabled)
        general_form.addRow("Linhas:", nrows_container)

        layout.addWidget(general_group)

        # Grupo: Opcoes especificas do tipo
        if self._ext == ".csv":
            self._setup_csv_options(layout)
        elif self._ext in (".xlsx", ".xls"):
            self._setup_xlsx_options(layout)
        elif self._ext == ".json":
            self._setup_json_options(layout)

        # Botoes
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_import = QPushButton("Importar")
        btn_import.setDefault(True)
        btn_import.clicked.connect(self._on_import)
        btn_layout.addWidget(btn_import)

        layout.addLayout(btn_layout)

    def _setup_csv_options(self, layout):
        """Opcoes especificas de CSV"""
        csv_group = QGroupBox("CSV")
        csv_form = QFormLayout(csv_group)
        csv_form.setSpacing(8)

        # Separador
        self.separator_combo = QComboBox()
        for sep_val, sep_label in CSV_SEPARATORS:
            self.separator_combo.addItem(sep_label, sep_val)
        self.separator_combo.setCurrentIndex(0)  # ; por padrao
        csv_form.addRow("Separador:", self.separator_combo)

        # Header (linha do cabecalho)
        self.header_combo = QComboBox()
        self.header_combo.addItem("Primeira linha", 0)
        self.header_combo.addItem("Sem cabecalho", None)
        csv_form.addRow("Cabecalho:", self.header_combo)

        # Decimal
        self.decimal_combo = QComboBox()
        self.decimal_combo.addItem("Ponto (.)", ".")
        self.decimal_combo.addItem("Virgula (,)", ",")
        csv_form.addRow("Decimal:", self.decimal_combo)

        # Skip rows
        self.skip_rows_spin = QSpinBox()
        self.skip_rows_spin.setMinimum(0)
        self.skip_rows_spin.setMaximum(10000)
        self.skip_rows_spin.setValue(0)
        csv_form.addRow("Pular linhas:", self.skip_rows_spin)

        layout.addWidget(csv_group)

    def _setup_xlsx_options(self, layout):
        """Opcoes especificas de Excel"""
        xlsx_group = QGroupBox("Excel")
        xlsx_form = QFormLayout(xlsx_group)
        xlsx_form.setSpacing(8)

        # Sheet name
        self.sheet_input = QLineEdit()
        self.sheet_input.setPlaceholderText("0 (primeira sheet) ou nome da sheet")
        self.sheet_input.setText("0")
        xlsx_form.addRow("Sheet:", self.sheet_input)

        # Header
        self.xlsx_header_combo = QComboBox()
        self.xlsx_header_combo.addItem("Primeira linha", 0)
        self.xlsx_header_combo.addItem("Sem cabecalho", None)
        xlsx_form.addRow("Cabecalho:", self.xlsx_header_combo)

        # Skip rows
        self.xlsx_skip_rows_spin = QSpinBox()
        self.xlsx_skip_rows_spin.setMinimum(0)
        self.xlsx_skip_rows_spin.setMaximum(10000)
        self.xlsx_skip_rows_spin.setValue(0)
        xlsx_form.addRow("Pular linhas:", self.xlsx_skip_rows_spin)

        layout.addWidget(xlsx_group)

    def _setup_json_options(self, layout):
        """Opcoes especificas de JSON"""
        json_group = QGroupBox("JSON")
        json_form = QFormLayout(json_group)
        json_form.setSpacing(8)

        # Orient
        self.orient_combo = QComboBox()
        self.orient_combo.addItem("Auto-detectar", "")
        self.orient_combo.addItem("records", "records")
        self.orient_combo.addItem("columns", "columns")
        self.orient_combo.addItem("index", "index")
        self.orient_combo.addItem("split", "split")
        self.orient_combo.addItem("values", "values")
        json_form.addRow("Orientacao:", self.orient_combo)

        # Lines (JSON Lines format)
        self.json_lines_check = QCheckBox("JSON Lines (uma linha por registro)")
        json_form.addRow("Formato:", self.json_lines_check)

        layout.addWidget(json_group)

    def _apply_theme(self):
        """Aplica tema do ThemeManager"""
        if self.theme_manager:
            self.setStyleSheet(self.theme_manager.get_dialog_stylesheet())

    def _on_import(self):
        """Gera codigo de importacao e aceita o dialogo"""
        var_name = self.var_name_input.text().strip()
        if not var_name:
            var_name = "df"

        # Validar nome de variavel Python
        if not var_name.isidentifier():
            var_name = FileImportService._normalize_var_name(self.file_path)

        self._result_code = self._generate_code(var_name)
        self._result_var_name = var_name
        self.accept()

    def _generate_code(self, var_name: str) -> str:
        """Gera codigo Python de importacao baseado nas configuracoes."""
        safe_path = self.file_path.replace("\\", "/")
        encoding = self.encoding_combo.currentText()
        nrows = self.nrows_spin.value() if self.limit_rows_check.isChecked() else None

        if self._ext == ".csv":
            return self._generate_csv_code(var_name, safe_path, encoding, nrows)
        elif self._ext in (".xlsx", ".xls"):
            return self._generate_xlsx_code(var_name, safe_path, nrows)
        elif self._ext == ".json":
            return self._generate_json_code(var_name, safe_path, encoding, nrows)

        return f'import pandas as pd\n{var_name} = pd.read_csv("{safe_path}")\n{var_name}'

    def _generate_csv_code(self, var_name: str, path: str, encoding: str, nrows) -> str:
        """Gera codigo para importacao CSV"""
        sep = self.separator_combo.currentData()
        header_val = self.header_combo.currentData()
        decimal = self.decimal_combo.currentData()
        skip_rows = self.skip_rows_spin.value()

        parts = [f'"{path}"']
        parts.append(f'sep="{sep}"')
        parts.append(f'encoding="{encoding}"')

        if header_val is None:
            parts.append("header=None")

        if decimal != ".":
            parts.append(f'decimal="{decimal}"')

        if skip_rows > 0:
            parts.append(f"skiprows={skip_rows}")

        if nrows is not None:
            parts.append(f"nrows={nrows}")

        args = ", ".join(parts)
        lines = [
            "import pandas as pd",
            f"{var_name} = pd.read_csv({args})",
            var_name,
        ]
        return "\n".join(lines)

    def _generate_xlsx_code(self, var_name: str, path: str, nrows) -> str:
        """Gera codigo para importacao Excel usando fastexcel"""
        sheet_text = self.sheet_input.text().strip()
        header_val = self.xlsx_header_combo.currentData()
        skip_rows = self.xlsx_skip_rows_spin.value()

        # Determinar sheet (index ou nome)
        try:
            sheet_val = int(sheet_text)
        except ValueError:
            sheet_val = sheet_text if sheet_text else 0

        # Parametros para load_sheet / load_sheet_by_name
        sheet_params = []

        if header_val is None:
            sheet_params.append("header_row=None")

        if skip_rows > 0:
            sheet_params.append(f"skip_rows={skip_rows}")

        if nrows is not None:
            sheet_params.append(f"n_rows={nrows}")

        params_str = ", ".join(sheet_params)
        if params_str:
            params_str = ", " + params_str

        if isinstance(sheet_val, int):
            load_call = f".load_sheet({sheet_val}{params_str})"
        else:
            load_call = f'.load_sheet_by_name("{sheet_val}"{params_str})'

        lines = [
            "import fastexcel",
            f'{var_name} = fastexcel.read_excel("{path}"){load_call}.to_pandas()',
            var_name,
        ]
        return "\n".join(lines)

    def _generate_json_code(self, var_name: str, path: str, encoding: str, nrows) -> str:
        """Gera codigo para importacao JSON"""
        orient = self.orient_combo.currentData()
        lines_mode = self.json_lines_check.isChecked()

        parts = [f'"{path}"']
        parts.append(f'encoding="{encoding}"')

        if orient:
            parts.append(f'orient="{orient}"')

        if lines_mode:
            parts.append("lines=True")

        if nrows is not None:
            parts.append(f"nrows={nrows}")

        args = ", ".join(parts)
        lines = [
            "import pandas as pd",
            f"{var_name} = pd.read_json({args})",
            var_name,
        ]
        return "\n".join(lines)

    def get_result(self):
        """Retorna o codigo gerado e o nome da variavel.

        Returns:
            Tuple (code: str, var_name: str) ou (None, None) se cancelado
        """
        if self._result_code:
            return self._result_code, self._result_var_name
        return None, None
