"""
Dialogo para exportar DataFrame para uma tabela no banco de dados.

Permite escolher:
- Nome da tabela (suporta #tabela para temporarias)
- Conexao de destino (entre as conexoes ativas da aba)
- Comportamento se tabela existe (append, replace, fail)
- Tamanho do chunk para insercao
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDialogButtonBox,
    QProgressBar,
    QGroupBox,
    QPushButton,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont
import pandas as pd
import polars as pl
import logging
import qtawesome as qta

from src.core.theme_manager import ThemeManager

logger = logging.getLogger(__name__)


class ExportToTableWorker(QObject):
    """Worker para exportar DataFrame via raw cursor + Polars (executemany).

    Bypassa pandas.to_sql() e SQLAlchemy, usando cursor.executemany()
    com fast_executemany para maxima performance de INSERT.
    """

    progress = pyqtSignal(int, int)  # (linhas_inseridas, total)
    finished = pyqtSignal(bool, str)  # (success, message)
    status = pyqtSignal(str)  # mensagem de status

    def __init__(self, df_polars, engine, table_name, if_exists, chunksize, schema=None):
        super().__init__()
        self.df = df_polars  # pl.DataFrame
        self.engine = engine
        self.table_name = table_name
        self.if_exists = if_exists
        self.chunksize = chunksize
        self.schema = schema
        self._cancelled = False
        self._dialect = getattr(engine.dialect, "name", "mssql")

    def cancel(self):
        """Solicita cancelamento da exportacao"""
        self._cancelled = True

    # ---- helpers SQL ----

    def _quote(self, name):
        """Quoting de identificadores por dialeto"""
        if self._dialect in ("mysql", "mariadb"):
            return f"`{name}`"
        if self._dialect == "mssql":
            return f"[{name}]"
        return f'"{name}"'

    def _qualified_name(self):
        """Retorna nome qualificado (schema.tabela) com quoting"""
        if self.table_name.startswith("#"):
            return self.table_name
        q = self._quote
        if self.schema:
            return f"{q(self.schema)}.{q(self.table_name)}"
        return q(self.table_name)

    def _placeholder(self):
        """Placeholder do driver: ? para pyodbc/sqlite3/mariadb, %s para pymysql/psycopg2"""
        if self._dialect in ("mssql", "sqlite", "mariadb"):
            return "?"
        return "%s"

    def _get_sql_type(self, dtype):
        """Mapeia tipo Polars para tipo SQL do dialeto"""
        is_mssql = self._dialect == "mssql"
        if dtype.is_integer():
            if dtype in (pl.Int8, pl.UInt8):
                return "TINYINT" if is_mssql else "SMALLINT"
            if dtype in (pl.Int16, pl.UInt16):
                return "SMALLINT"
            if dtype in (pl.Int32, pl.UInt32):
                return "INT" if is_mssql else "INTEGER"
            return "BIGINT"
        if dtype.is_float():
            return "FLOAT" if is_mssql else "DOUBLE PRECISION"
        if dtype == pl.Boolean:
            return "BIT" if is_mssql else "BOOLEAN"
        if dtype == pl.Date:
            return "DATE"
        if dtype.is_temporal():
            return "DATETIME2" if is_mssql else "TIMESTAMP"
        # String, Categorical, Binary, Object, Null, nested -> text
        return "NVARCHAR(MAX)" if is_mssql else "TEXT"

    def _create_table_ddl(self):
        """Gera DDL CREATE TABLE baseado nos dtypes do DataFrame"""
        cols = []
        for name, dtype in zip(self.df.columns, self.df.dtypes):
            sql_type = self._get_sql_type(dtype)
            cols.append(f"{self._quote(name)} {sql_type}")
        return f"CREATE TABLE {self._qualified_name()} ({', '.join(cols)})"

    # ---- execucao principal ----

    def run(self):
        """Executa a exportacao via raw cursor + executemany"""
        try:
            total_rows = self.df.height
            if total_rows == 0:
                self.finished.emit(False, "DataFrame vazio, nada para exportar")
                return

            self.status.emit(f"Preparando {total_rows:,} linhas...")

            # Cast tipos complexos para string (Binary, List, Struct)
            cast_exprs = []
            for col, dtype in zip(self.df.columns, self.df.dtypes):
                if dtype == pl.Binary or dtype.is_nested():
                    cast_exprs.append(pl.col(col).cast(pl.Utf8))
            if cast_exprs:
                self.df = self.df.with_columns(cast_exprs)

            qualified = self._qualified_name()
            raw_conn = self.engine.raw_connection()
            try:
                cursor = raw_conn.cursor()

                # fast_executemany para pyodbc (SQL Server)
                if hasattr(cursor, "fast_executemany"):
                    cursor.fast_executemany = True

                # DDL: tratar if_exists
                if self.if_exists == "replace":
                    cursor.execute(f"DROP TABLE IF EXISTS {qualified}")
                    raw_conn.commit()
                    cursor.execute(self._create_table_ddl())
                    raw_conn.commit()
                elif self.if_exists == "fail":
                    # CREATE TABLE falha naturalmente se tabela ja existe
                    cursor.execute(self._create_table_ddl())
                    raw_conn.commit()
                elif self.if_exists == "append":
                    # Cria se nao existe; ignora erro se ja existe
                    try:
                        cursor.execute(self._create_table_ddl())
                        raw_conn.commit()
                    except Exception:
                        raw_conn.rollback()

                # INSERT parametrizado
                cols_sql = ", ".join(self._quote(c) for c in self.df.columns)
                phs = ", ".join([self._placeholder()] * len(self.df.columns))
                insert_sql = f"INSERT INTO {qualified} ({cols_sql}) VALUES ({phs})"

                self.status.emit(
                    f"Exportando {total_rows:,} linhas para '{self.table_name}'..."
                )

                rows_done = 0
                for start in range(0, total_rows, self.chunksize):
                    if self._cancelled:
                        raw_conn.rollback()
                        self.finished.emit(
                            False,
                            f"Exportacao cancelada. {rows_done:,} linhas foram inseridas.",
                        )
                        return

                    end = min(start + self.chunksize, total_rows)
                    chunk = self.df.slice(start, end - start)
                    data = chunk.rows()  # list[tuple] - muito eficiente

                    cursor.executemany(insert_sql, data)
                    raw_conn.commit()

                    rows_done = end
                    self.progress.emit(rows_done, total_rows)
                    self.status.emit(
                        f"Exportando... {rows_done:,}/{total_rows:,} linhas"
                    )

                self.finished.emit(
                    True,
                    f"{total_rows:,} linhas exportadas para '{self.table_name}'",
                )

            finally:
                try:
                    raw_conn.close()
                except Exception:
                    pass

        except Exception as e:
            error_msg = str(e)
            if len(error_msg) > 300:
                error_msg = error_msg[:300] + "..."
            self.finished.emit(False, f"Erro ao exportar: {error_msg}")


class ExportToTableDialog(QDialog):
    """Dialogo para exportar DataFrame para tabela no banco de dados"""

    def __init__(
        self,
        df: pd.DataFrame,
        connections: dict,
        current_connection: str = "",
        theme_manager: ThemeManager = None,
        parent=None,
    ):
        """
        Args:
            df: DataFrame a exportar
            connections: dict {nome: DatabaseConnector} com conexoes ativas
            current_connection: nome da conexao pre-selecionada (bloco/aba)
            theme_manager: gerenciador de tema
        """
        super().__init__(parent)
        self.df = df
        self.connections = connections
        self.current_connection = current_connection
        self.theme_manager = theme_manager or ThemeManager()

        self._thread = None
        self._worker = None
        self._is_exporting = False

        self.setWindowTitle("Exportar para Tabela")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumWidth(480)
        self.setFixedHeight(380)

        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        """Configura a interface"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # Info do DataFrame
        info_label = QLabel(f"{len(self.df):,} linhas  x  {len(self.df.columns)} colunas")
        info_label.setFont(QFont("Segoe UI", 9))
        info_label.setStyleSheet("color: #888; margin-bottom: 4px;")
        layout.addWidget(info_label)

        # Formulario
        form_layout = QFormLayout()
        form_layout.setSpacing(8)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Nome da tabela
        self.table_name_edit = QLineEdit()
        self.table_name_edit.setPlaceholderText("ex: minha_tabela ou #temp")
        self.table_name_edit.setToolTip(
            "Use # no inicio para criar tabela temporaria (SQL Server)\n"
            "Ex: #dados_temp, minha_tabela, schema.tabela"
        )
        form_layout.addRow("Tabela:", self.table_name_edit)

        # Conexao de destino
        self.connection_combo = QComboBox()
        self.connection_combo.setMinimumWidth(250)
        for name in sorted(self.connections.keys()):
            connector = self.connections[name]
            if connector and connector.is_connected():
                db_type = getattr(connector, "db_type", "")
                db_name = connector.get_current_database()
                label = f"{name} ({db_type} - {db_name})" if db_name else f"{name} ({db_type})"
                self.connection_combo.addItem(label, name)

        # Pre-selecionar conexao atual
        if self.current_connection:
            for i in range(self.connection_combo.count()):
                if self.connection_combo.itemData(i) == self.current_connection:
                    self.connection_combo.setCurrentIndex(i)
                    break

        form_layout.addRow("Conexao:", self.connection_combo)

        # Se tabela existe
        self.if_exists_combo = QComboBox()
        self.if_exists_combo.addItem("Substituir (DROP + CREATE)", "replace")
        self.if_exists_combo.addItem("Acrescentar (INSERT)", "append")
        self.if_exists_combo.addItem("Falhar (erro se existir)", "fail")
        self.if_exists_combo.setCurrentIndex(0)
        form_layout.addRow("Se existir:", self.if_exists_combo)

        # Chunk size
        self.chunk_spin = QSpinBox()
        self.chunk_spin.setMinimum(100)
        self.chunk_spin.setMaximum(100000)
        self.chunk_spin.setValue(1000)
        self.chunk_spin.setSuffix(" linhas")
        self.chunk_spin.setToolTip("Numero de linhas por lote de insercao")
        form_layout.addRow("Lote:", self.chunk_spin)

        layout.addLayout(form_layout)

        # Progresso
        self.progress_group = QGroupBox("Progresso")
        progress_layout = QVBoxLayout(self.progress_group)
        progress_layout.setContentsMargins(8, 16, 8, 8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Pronto para exportar")
        self.status_label.setFont(QFont("Segoe UI", 9))
        progress_layout.addWidget(self.status_label)

        self.progress_group.setVisible(False)
        layout.addWidget(self.progress_group)

        layout.addStretch()

        # Botoes
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("btnCancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_export = QPushButton("  Exportar")
        self.btn_export.setIcon(qta.icon("mdi.database-export", color="white"))
        self.btn_export.setDefault(True)
        self.btn_export.clicked.connect(self._on_export)
        btn_layout.addWidget(self.btn_export)

        layout.addLayout(btn_layout)

    def _apply_style(self):
        """Aplica estilo dark theme consistente com outros dialogos"""
        base = self.theme_manager.get_dialog_stylesheet()
        colors = self.theme_manager.get_app_colors()
        # Complementar com estilos especificos do progress bar e disabled
        extra = f"""
            QProgressBar {{
                background-color: {colors["border"]};
                border: 1px solid {colors["border"]};
                border-radius: 3px;
                text-align: center;
                color: {colors["foreground"]};
                min-height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {colors["accent"]};
                border-radius: 2px;
            }}
            QPushButton:disabled {{
                background-color: {colors["border"]};
                color: #666;
            }}
        """
        self.setStyleSheet(base + extra)

    def _validate(self) -> bool:
        """Valida campos antes de exportar"""
        table_name = self.table_name_edit.text().strip()
        if not table_name:
            QMessageBox.warning(self, "Validacao", "Informe o nome da tabela")
            self.table_name_edit.setFocus()
            return False

        if self.connection_combo.count() == 0:
            QMessageBox.warning(self, "Validacao", "Nenhuma conexao ativa disponivel")
            return False

        return True

    def _on_export(self):
        """Inicia a exportacao"""
        if not self._validate():
            return

        if self._is_exporting:
            return

        table_name = self.table_name_edit.text().strip()
        conn_name = self.connection_combo.currentData()
        if_exists = self.if_exists_combo.currentData()
        chunksize = self.chunk_spin.value()

        connector = self.connections.get(conn_name)
        if not connector or not connector.engine:
            QMessageBox.critical(self, "Erro", f"Conexao '{conn_name}' nao esta ativa")
            return

        # Separar schema.table se aplicavel
        schema = None
        actual_table = table_name
        if "." in table_name and not table_name.startswith("#"):
            parts = table_name.split(".", 1)
            schema = parts[0]
            actual_table = parts[1]

        # Desabilitar campos durante exportacao
        self._is_exporting = True
        self.btn_export.setEnabled(False)
        self.table_name_edit.setEnabled(False)
        self.connection_combo.setEnabled(False)
        self.if_exists_combo.setEnabled(False)
        self.chunk_spin.setEnabled(False)
        self.btn_cancel.setText("Cancelar Exportacao")

        # Mostrar progresso
        self.progress_group.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Iniciando exportacao...")

        # Converter para Polars para exportacao rapida
        try:
            df_polars = pl.from_pandas(self.df)
        except Exception:
            try:
                # Fallback: converter tipos nullable pandas (Int64, StringDtype)
                # para tipos simples numpy-backed antes da conversao
                df_clean = self.df.copy()
                for col in df_clean.columns:
                    if pd.api.types.is_extension_array_dtype(df_clean[col]):
                        df_clean[col] = df_clean[col].astype(object)
                df_polars = pl.from_pandas(df_clean)
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao converter DataFrame: {e}")
                self._is_exporting = False
                self.btn_export.setEnabled(True)
                self.table_name_edit.setEnabled(True)
                self.connection_combo.setEnabled(True)
                self.if_exists_combo.setEnabled(True)
                self.chunk_spin.setEnabled(True)
                self.btn_cancel.setText("Cancelar")
                return

        # Criar worker
        self._thread = QThread()
        self._worker = ExportToTableWorker(
            df_polars=df_polars,
            engine=connector.engine,
            table_name=actual_table,
            if_exists=if_exists,
            chunksize=chunksize,
            schema=schema,
        )
        self._worker.moveToThread(self._thread)

        # Conectar sinais
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.status.connect(self._on_status)
        self._worker.finished.connect(self._on_finished)

        self._thread.start()

    def _on_progress(self, current, total):
        """Atualiza barra de progresso"""
        if total > 0:
            pct = int(current / total * 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(f"{current:,}/{total:,} ({pct}%)")

    def _on_status(self, message):
        """Atualiza label de status"""
        self.status_label.setText(message)

    def _cleanup_thread(self):
        """Aguarda thread finalizar e limpa referencias"""
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
        self._worker = None

    def _on_finished(self, success, message):
        """Exportacao finalizada"""
        self._is_exporting = False
        self._cleanup_thread()

        if success:
            self.progress_bar.setValue(100)
            self.status_label.setText(message)
            QMessageBox.information(self, "Exportacao Concluida", message)
            self.accept()
        else:
            self.status_label.setText(f"Erro: {message}")
            QMessageBox.critical(self, "Erro na Exportacao", message)

            # Reabilitar campos
            self.btn_export.setEnabled(True)
            self.table_name_edit.setEnabled(True)
            self.connection_combo.setEnabled(True)
            self.if_exists_combo.setEnabled(True)
            self.chunk_spin.setEnabled(True)
            self.btn_cancel.setText("Cancelar")

    def _on_cancel(self):
        """Cancela exportacao ou fecha dialogo"""
        if self._is_exporting and self._worker:
            self._worker.cancel()
            self.status_label.setText("Cancelando...")
        else:
            self.reject()

    def closeEvent(self, event):
        """Impede fechar durante exportacao"""
        if self._is_exporting:
            event.ignore()
            self._on_cancel()
        else:
            self._cleanup_thread()
            super().closeEvent(event)
