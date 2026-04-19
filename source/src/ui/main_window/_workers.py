"""
Worker classes for background SQL and Python execution.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, QObject
import ast
import io
import sys
import traceback
import pandas as pd
from io import StringIO
import logging

logger = logging.getLogger(__name__)


def _read_file_with_encoding_fallback(filepath: str) -> str:
    """
    Read file content with encoding fallback.

    Tries utf-8 first, then detects encoding with chardet,
    finally falls back to latin-1 (which never fails).
    """
    # Try utf-8 first (most common)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        pass

    # Try to detect encoding with chardet if available
    try:
        import chardet
        with open(filepath, "rb") as f:
            raw_data = f.read()
        detected = chardet.detect(raw_data)
        encoding = detected.get("encoding", "latin-1") or "latin-1"
        return raw_data.decode(encoding)
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback to latin-1 (never fails, but may produce garbage for some encodings)
    with open(filepath, "r", encoding="latin-1") as f:
        return f.read()




class SqlWorker(QObject):
    """Worker for executing SQL in background"""

    finished = pyqtSignal(object, str)  # (result_df or None, error_msg or '')

    def __init__(self, connector, query):
        super().__init__()
        self.connector = connector
        self.query = query

    def run(self):
        try:
            df = self.connector.execute_query(self.query)
            self.finished.emit(df, "")
        except Exception as e:
            self.finished.emit(None, str(e))




class PythonWorker(QObject):
    """Centralized worker for Python execution in background"""

    finished = pyqtSignal(object, str, str, dict, list)  # (result, output, error, namespace, figures)

    def __init__(self, code, namespace, is_expression):
        super().__init__()
        self.code = code
        self.namespace = namespace
        self.is_expression = is_expression

    def run(self):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        try:
            # Configure matplotlib for non-interactive backend (Agg) with dark theme
            self._setup_matplotlib_backend()

            # Snapshot of DataFrames before execution to detect new ones
            df_snapshot = {k: id(v) for k, v in self.namespace.items() if isinstance(v, pd.DataFrame)}

            # Capture stdout AND stderr to same buffer
            # Thus print(), logging.info(), warnings, sys.stderr.write()
            # all appear in output panel
            captured = StringIO()
            sys.stdout = captured
            sys.stderr = captured

            result_value = self._execute_centralized()

            sys.stdout = old_stdout
            sys.stderr = old_stderr
            output = captured.getvalue()

            # Capture pending matplotlib figures
            figures = self._capture_matplotlib_figures()

            # Se resultado e None, verificar se novos DataFrames foram criados
            if result_value is None:
                new_dfs = [
                    (k, v)
                    for k, v in self.namespace.items()
                    if isinstance(v, pd.DataFrame)
                    and not k.startswith("_")
                    and (k not in df_snapshot or id(v) != df_snapshot[k])
                ]
                if new_dfs:
                    result_value = new_dfs[-1][1]

            # Processar resultado rico (PIL Image, plotly, matplotlib Figure,
            # _repr_html_(), dict/list, etc.)
            result_value, extra_outputs = self._process_rich_result(result_value, has_captured_figures=bool(figures))
            figures.extend(extra_outputs)

            self.finished.emit(result_value, output, "", self.namespace, figures)
        except Exception as e:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.finished.emit(None, "", traceback.format_exc(), self.namespace, [])

    def _setup_matplotlib_backend(self):
        """Configures matplotlib to use Agg backend (non-interactive) with dark theme"""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            plt.close("all")
            # Substituir plt.show() por no-op para nao travar
            plt.show = lambda *args, **kwargs: None
            # Tema escuro para combinar com a IDE
            plt.rcParams.update(
                {
                    "figure.facecolor": "#1e1e1e",
                    "axes.facecolor": "#2d2d30",
                    "axes.edgecolor": "#555555",
                    "axes.labelcolor": "#d4d4d4",
                    "text.color": "#d4d4d4",
                    "xtick.color": "#d4d4d4",
                    "ytick.color": "#d4d4d4",
                    "grid.color": "#3e3e42",
                    "legend.facecolor": "#2d2d30",
                    "legend.edgecolor": "#555555",
                    "figure.edgecolor": "#1e1e1e",
                    "savefig.facecolor": "#1e1e1e",
                    "savefig.edgecolor": "#1e1e1e",
                }
            )
        except ImportError:
            pass  # matplotlib nao instalado, ignorar

    def _capture_matplotlib_figures(self) -> list:
        """Captures all open matplotlib figures as rich outputs.

        Returns:
            List of dicts {'type': 'image', 'data': bytes_png}
        """
        figures_data = []
        try:
            import matplotlib.pyplot as plt

            fig_nums = plt.get_fignums()
            if not fig_nums:
                return []

            for num in fig_nums:
                fig = plt.figure(num)
                buf = io.BytesIO()
                fig.savefig(
                    buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none"
                )
                buf.seek(0)
                figures_data.append({"type": "image", "data": buf.getvalue()})
                buf.close()

            plt.close("all")
        except ImportError:
            pass  # matplotlib nao instalado
        except Exception as e:
            logging.warning(f"Error capturing matplotlib figures: {e}")

        return figures_data

    def _execute_centralized(self):
        """Centralized execution using AST - all Python executions go through here.

        Usa o modulo ast para separar corretamente statements de expressoes,
        sem quebrar blocos multi-linha (for, if, try, def, class etc).
        """
        code = self.code.strip()
        if not code:
            return None

        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Deixar o exec levantar o erro com traceback correto
            exec(code, self.namespace)
            return None

        if not tree.body:
            return None

        last_node = tree.body[-1]

        # Se o ultimo node e uma expressao (nao assignment, for, if, etc),
        # executar tudo menos ele, depois avaliar a expressao e retornar o valor
        if isinstance(last_node, ast.Expr):
            if len(tree.body) > 1:
                exec_module = ast.Module(body=tree.body[:-1], type_ignores=[])
                ast.fix_missing_locations(exec_module)
                exec(compile(exec_module, "<exec>", "exec"), self.namespace)
            expr = ast.Expression(body=last_node.value)
            ast.fix_missing_locations(expr)
            return eval(compile(expr, "<eval>", "eval"), self.namespace)
        else:
            # Ultimo node e statement (assignment, for, if, etc) - executar tudo
            exec(compile(tree, "<exec>", "exec"), self.namespace)
            return None

    def _process_rich_result(self, result, has_captured_figures=False):
        """Converts rich objects into typed rich outputs.

        Detecta: matplotlib Figure, PIL Image, Plotly Figure,
        _repr_png_(), _repr_html_(), dict/list.

        Returns:
            (result, extra_outputs): resultado processado e lista de rich outputs.
            Rich outputs sao dicts: {'type': 'image'|'html'|'json', 'data': ...}
        """
        extra_outputs = []
        if result is None:
            return result, extra_outputs

        # matplotlib Figure retornado como valor de expressao
        try:
            from matplotlib.figure import Figure as MplFigure

            if isinstance(result, MplFigure):
                if has_captured_figures:
                    # Already captured by _capture_matplotlib_figures, don't duplicate
                    return None, extra_outputs
                buf = io.BytesIO()
                result.savefig(
                    buf, format="png", dpi=150, bbox_inches="tight", facecolor=result.get_facecolor(), edgecolor="none"
                )
                buf.seek(0)
                extra_outputs.append({"type": "image", "data": buf.getvalue()})
                buf.close()
                return None, extra_outputs
        except ImportError:
            pass

        # PIL/Pillow Image
        try:
            from PIL import Image as PILImage

            if isinstance(result, PILImage.Image):
                buf = io.BytesIO()
                # Converter RGBA para RGB se necessario (PNG suporta ambos)
                result.save(buf, format="PNG")
                buf.seek(0)
                extra_outputs.append({"type": "image", "data": buf.getvalue()})
                buf.close()
                return None, extra_outputs
        except ImportError:
            pass

        # Plotly Figure -> tenta PNG (kaleido), senao HTML interativo
        try:
            import plotly.graph_objects as go

            if isinstance(result, go.Figure):
                try:
                    img_bytes = result.to_image(format="png", scale=2, width=800, height=500)
                    extra_outputs.append({"type": "image", "data": img_bytes})
                    return None, extra_outputs
                except Exception:
                    # kaleido nao instalado - usar HTML interativo
                    try:
                        html_str = result.to_html(
                            include_plotlyjs="cdn", full_html=True, config={"displayModeBar": True}
                        )
                        extra_outputs.append({"type": "html", "data": html_str})
                        return None, extra_outputs
                    except Exception:
                        pass
        except ImportError:
            pass

        # Objeto com _repr_png_() (convencao IPython)
        if hasattr(result, "_repr_png_"):
            try:
                png_data = result._repr_png_()
                if png_data:
                    extra_outputs.append({"type": "image", "data": png_data})
                    return None, extra_outputs
            except Exception:
                pass

        # Objeto com _repr_html_() (pandas Styler, IPython.display.HTML etc.)
        # DO NOT apply for pure DataFrames (already has better grid)
        if hasattr(result, "_repr_html_") and not isinstance(result, pd.DataFrame):
            try:
                html_data = result._repr_html_()
                if html_data:
                    extra_outputs.append({"type": "html", "data": html_data})
                    return None, extra_outputs
            except Exception:
                pass

        # dict ou list -> JSON tree view
        if isinstance(result, (dict, list)) and not isinstance(result, pd.DataFrame):
            # So mostrar como JSON se nao e muito simples (mais de 1 item)
            if isinstance(result, dict) and len(result) >= 1:
                extra_outputs.append({"type": "json", "data": result})
                return None, extra_outputs
            elif isinstance(result, list) and len(result) >= 1:
                extra_outputs.append({"type": "json", "data": result})
                return None, extra_outputs

        return result, extra_outputs


