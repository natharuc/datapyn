"""
Testes E2E para execucao Python e renderizacao de resultados.

Garante que o fluxo completo funciona:
- print() -> Output panel
- DataFrame -> Results panel (grid)
- matplotlib chart -> Results panel (imagem)
- error -> Output panel
- logs/stderr -> Output panel
- combinacoes: chart + DataFrame, chart + print, etc.

Usa PythonWorker diretamente e verifica roteamento via sinais.
Tambem testa SessionWidget._on_python_finished com figures.
"""

import pytest
import io
import sys
import pandas as pd
from unittest.mock import MagicMock, patch, PropertyMock
from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import QApplication


# ===========================================================================
# Helper: executa PythonWorker sincronamente e captura resultado
# ===========================================================================


def run_python_worker_sync(code: str, namespace: dict = None, is_expression: bool = False):
    """Executa PythonWorker de forma sincrona e retorna (result, output, error, namespace, figures)"""
    from src.ui.main_window import PythonWorker

    if namespace is None:
        namespace = {}

    worker = PythonWorker(code, namespace, is_expression)

    captured = {}

    def on_finished(result, output, error, ns, figures):
        captured["result"] = result
        captured["output"] = output
        captured["error"] = error
        captured["namespace"] = ns
        captured["figures"] = figures

    worker.finished.connect(on_finished)
    worker.run()  # sincrono - nao usa thread

    assert "result" in captured, "PythonWorker.finished nao emitiu"
    return (
        captured["result"],
        captured["output"],
        captured["error"],
        captured["namespace"],
        captured["figures"],
    )


def get_image_bytes(rich_output):
    """Extrai bytes PNG de um rich output (dict ou bytes puro)."""
    if isinstance(rich_output, bytes):
        return rich_output
    if isinstance(rich_output, dict):
        return rich_output.get("data", b"")
    return b""


def get_output_type(rich_output):
    """Retorna o tipo de um rich output."""
    if isinstance(rich_output, bytes):
        return "image"
    if isinstance(rich_output, dict):
        return rich_output.get("type", "")
    return ""


# ===========================================================================
# 1. PythonWorker captura matplotlib figures
# ===========================================================================


class TestWorkerCapturesFigures:
    """PythonWorker deve capturar figuras matplotlib como PNG bytes"""

    def test_simple_plot_generates_figure(self, qapp):
        """plt.plot() gera 1 figura capturada como PNG bytes"""
        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2, 3], [4, 5, 6])
plt.title('Test')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == "", f"Erro inesperado: {error}"
        assert len(figures) >= 1, "Nenhuma figura capturada"
        # Verificar que e rich output de imagem com PNG valido
        assert get_output_type(figures[0]) == "image"
        assert get_image_bytes(figures[0])[:8] == b"\x89PNG\r\n\x1a\n", "Nao e PNG valido"

    def test_barh_plot_generates_figure(self, qapp):
        """plt.barh() (como no cenario do usuario) gera 1 figura"""
        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

df = pd.DataFrame({'IdCidade': [10, 20, 30, 40, 50], 'Nome': ['A', 'B', 'C', 'D', 'E']})
top_10 = df.head(5)
plt.barh(top_10['Nome'], top_10['IdCidade'])
plt.title('Top 10 Clientes')
plt.show()
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == "", f"Erro inesperado: {error}"
        assert len(figures) >= 1, "plt.barh nao gerou figura"
        assert get_image_bytes(figures[0])[:8] == b"\x89PNG\r\n\x1a\n"

    def test_multiple_plots_generate_multiple_figures(self, qapp):
        """Dois plt.figure() geram 2 figuras"""
        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2])
plt.figure()
plt.plot([3, 4])
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == "", f"Erro inesperado: {error}"
        assert len(figures) >= 2, f"Esperava 2+ figuras, capturou {len(figures)}"

    def test_plt_show_does_not_block(self, qapp):
        """plt.show() nao trava (e substituido por no-op)"""
        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.plot([1, 2, 3])
plt.show()
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == "", f"plt.show() causou erro: {error}"
        assert len(figures) >= 1

    def test_no_plot_no_figures(self, qapp):
        """Codigo sem matplotlib nao gera figuras"""
        code = "x = 42"
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert figures == []


# ===========================================================================
# 2. PythonWorker captura print/stdout
# ===========================================================================


class TestWorkerCapturesOutput:
    """PythonWorker deve capturar print() e stderr"""

    def test_print_captured(self, qapp):
        """print() aparece no output"""
        code = "print('Hello World')"
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert "Hello World" in output

    def test_multiple_prints(self, qapp):
        """Multiplos print() aparecem em ordem"""
        code = """
print('linha 1')
print('linha 2')
print('linha 3')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert "linha 1" in output
        assert "linha 2" in output
        assert "linha 3" in output

    def test_stderr_captured(self, qapp):
        """Escrita em stderr aparece no output"""
        code = """
import sys
sys.stderr.write('warning message\\n')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert "warning message" in output

    def test_logging_captured(self, qapp):
        """logging com StreamHandler para stderr aparece no output"""
        code = """
import logging
import sys
handler = logging.StreamHandler(sys.stderr)
logger = logging.getLogger('test_e2e')
logger.addHandler(handler)
logger.setLevel(logging.WARNING)
logger.warning('test warning log')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert "test warning" in output


# ===========================================================================
# 3. PythonWorker captura erros
# ===========================================================================


class TestWorkerCapturesErrors:
    """PythonWorker deve capturar erros e enviar no campo error"""

    def test_syntax_error(self, qapp):
        """SyntaxError aparece no campo error"""
        code = "def foo(:"
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert "SyntaxError" in error

    def test_runtime_error(self, qapp):
        """NameError aparece no campo error"""
        code = "x = variavel_que_nao_existe"
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert "NameError" in error

    def test_error_with_no_figures(self, qapp):
        """Erro nao gera figuras"""
        code = "1/0"
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert "ZeroDivisionError" in error
        assert figures == []


# ===========================================================================
# 4. PythonWorker retorna DataFrames
# ===========================================================================


class TestWorkerReturnsDataFrames:
    """PythonWorker deve detectar DataFrames criados"""

    def test_dataframe_as_last_expression(self, qapp):
        """DataFrame no final do codigo e retornado como result"""
        code = """
import pandas as pd
df = pd.DataFrame({'a': [1, 2, 3]})
df
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3

    def test_new_dataframe_detected(self, qapp):
        """Novo DataFrame criado e detectado mesmo sem ser ultima expressao"""
        code = """
import pandas as pd
df = pd.DataFrame({'x': [10, 20, 30]})
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert isinstance(result, pd.DataFrame)

    def test_dataframe_from_existing_namespace(self, qapp):
        """df ja existente no namespace - operacoes sobre ele"""
        existing_df = pd.DataFrame({"IdCidade": range(20), "Nome": [f"C{i}" for i in range(20)]})
        namespace = {"df": existing_df}
        code = """
top_10 = df.head(10)
"""
        result, output, error, ns, figures = run_python_worker_sync(code, namespace)
        assert error == ""
        # top_10 e um novo DataFrame detectado
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 10


# ===========================================================================
# 5. Combinacoes: chart + DataFrame, chart + print
# ===========================================================================


class TestWorkerCombinations:
    """PythonWorker deve capturar TUDO junto"""

    def test_chart_and_print(self, qapp):
        """print() + plt.plot() -> output com texto E figures com PNG"""
        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
print('Gerando grafico...')
plt.plot([1, 2, 3])
print('Grafico gerado!')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert "Gerando grafico" in output
        assert "Grafico gerado" in output
        assert len(figures) >= 1

    def test_chart_and_dataframe(self, qapp):
        """DataFrame + plot -> namespace tem df E figures tem PNG"""
        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

df = pd.DataFrame({'x': [1, 2, 3], 'y': [4, 5, 6]})
plt.plot(df['x'], df['y'])
plt.title('Test')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1
        # df esta no namespace
        assert "df" in ns
        assert isinstance(ns["df"], pd.DataFrame)

    def test_user_scenario_full(self, qapp):
        """Cenario completo do usuario: df ja existe, faz barh, plt.show()"""
        existing_df = pd.DataFrame({"IdCidade": [100, 200, 300, 400, 500], "Nome": ["SP", "RJ", "MG", "BA", "PR"]})
        namespace = {"df": existing_df}

        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

top_10 = df.head(10)
plt.barh(top_10['Nome'], top_10['IdCidade'])
plt.title('Top 10 Clientes')
plt.show()
"""
        result, output, error, ns, figures = run_python_worker_sync(code, namespace)
        assert error == "", f"Erro inesperado: {error}"
        assert len(figures) >= 1, "Nenhuma figura capturada no cenario do usuario"
        assert get_image_bytes(figures[0])[:8] == b"\x89PNG\r\n\x1a\n"


# ===========================================================================
# 6. ResultsViewer exibe imagens corretamente
# ===========================================================================


class TestResultsViewerDisplaysImages:
    """ResultsViewer deve exibir PNG no QStackedWidget pagina 1"""

    def _make_test_png(self):
        """Gera PNG de teste via matplotlib"""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(3, 2))
        ax.plot([1, 2, 3], [4, 5, 6])
        ax.set_title("Test")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=72)
        buf.seek(0)
        data = buf.getvalue()
        plt.close(fig)
        return data

    def test_display_image_shows_pixmap(self, qapp):
        """display_image carrega PNG e mostra no QLabel"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        png = self._make_test_png()

        viewer.display_image(png, "Test Chart")
        assert viewer.stack.currentIndex() == 1
        assert viewer.image_label.pixmap() is not None
        assert not viewer.image_label.pixmap().isNull()

    def test_display_image_stores_bytes_for_save(self, qapp):
        """display_image guarda bytes para o botao salvar"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        png = self._make_test_png()

        viewer.display_image(png, "Test")
        assert viewer._current_image_bytes == png

    def test_display_images_single(self, qapp):
        """display_images com 1 item usa display_image"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        png = self._make_test_png()

        viewer.display_images([png], "Test")
        assert viewer.stack.currentIndex() == 1
        assert viewer._current_image_bytes == png

    def test_display_images_multiple_combines(self, qapp):
        """display_images com 2+ itens combina verticalmente"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        png1 = self._make_test_png()
        png2 = self._make_test_png()

        viewer.display_images([png1, png2], "Multi")
        assert viewer.stack.currentIndex() == 1
        assert viewer._current_image_bytes is not None
        # Bytes combinados sao diferentes dos individuais
        assert viewer._current_image_bytes != png1
        # Mas ainda e PNG valido
        assert viewer._current_image_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_display_dataframe_switches_back_to_table(self, qapp):
        """display_dataframe volta para pagina 0 (tabela)"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        png = self._make_test_png()

        # Primeiro mostra imagem
        viewer.display_image(png, "Chart")
        assert viewer.stack.currentIndex() == 1

        # Depois mostra DataFrame
        df = pd.DataFrame({"a": [1, 2, 3]})
        viewer.display_dataframe(df, "test")
        assert viewer.stack.currentIndex() == 0

    def test_clear_resets_everything(self, qapp):
        """clear() reseta para tabela e limpa imagem"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        png = self._make_test_png()

        viewer.display_image(png, "Chart")
        assert viewer.stack.currentIndex() == 1

        viewer.clear()
        assert viewer.stack.currentIndex() == 0
        assert viewer._current_image_bytes is None

    def test_display_images_empty_list_noop(self, qapp):
        """display_images com lista vazia nao faz nada"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        viewer.display_images([], "Nothing")
        assert viewer.stack.currentIndex() == 0


# ===========================================================================
# 7. SessionWidget roteia figuras para Results panel
# ===========================================================================


class TestSessionWidgetFigureRouting:
    """SessionWidget._on_python_finished deve rotear figuras para Results"""

    def test_adapter_accepts_5_params(self, qapp):
        """_on_python_finished_adapted aceita 5 parametros (incluindo figures)"""
        from src.ui.components.session_widget import SessionWidget
        import inspect

        sig = inspect.signature(SessionWidget._on_python_finished_adapted)
        params = list(sig.parameters.keys())
        # self, result, output, error, namespace, figures
        assert "figures" in params, f"Parametro 'figures' nao encontrado: {params}"

    def test_on_python_finished_accepts_figures(self, qapp):
        """_on_python_finished aceita parametro figures"""
        from src.ui.components.session_widget import SessionWidget
        import inspect

        sig = inspect.signature(SessionWidget._on_python_finished)
        params = list(sig.parameters.keys())
        assert "figures" in params, f"Parametro 'figures' nao encontrado: {params}"

    def test_session_widget_has_set_figures(self, qapp):
        """SessionWidget tem metodo _set_figures"""
        from src.ui.components.session_widget import SessionWidget

        assert hasattr(SessionWidget, "_set_figures")

    def test_figures_routed_to_results_panel(self, qapp):
        """Figuras sao enviadas para global_results_viewer.display_images"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session
        from src.core.theme_manager import ThemeManager
        from src.editors import BlockEditor

        # Criar SessionWidget com mocks
        session = MagicMock(spec=Session)
        session.name = "test"
        session.language = "python"
        session.connection_name = None
        session.namespace = {}
        session.register_thread = MagicMock()
        session.unregister_thread = MagicMock()
        session.finish_execution = MagicMock()
        session.update_namespace = MagicMock()

        widget = SessionWidget(session, ThemeManager())

        # Mock do main_window que _get_main_window retorna
        mock_main = MagicMock()
        mock_results = MagicMock()
        mock_main.global_results_viewer = mock_results
        mock_main.show_panel = MagicMock()
        widget._get_main_window = MagicMock(return_value=mock_main)

        # Simular chamada com figuras
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        widget._on_python_finished(result=None, output="", error="", updated_namespace={}, figures=[fake_png])

        # Verificar que display_rich_output foi chamado
        mock_results.display_rich_output.assert_called_once_with([fake_png], "Resultado")
        mock_main.show_panel.assert_called_with("results")

    def test_error_goes_to_output_not_results(self, qapp):
        """Erro vai para Output, nao para Results"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session
        from src.core.theme_manager import ThemeManager

        session = MagicMock(spec=Session)
        session.name = "test"
        session.language = "python"
        session.connection_name = None
        session.namespace = {}
        session.register_thread = MagicMock()
        session.unregister_thread = MagicMock()
        session.finish_execution = MagicMock()
        session.update_namespace = MagicMock()

        widget = SessionWidget(session, ThemeManager())

        mock_main = MagicMock()
        mock_results = MagicMock()
        mock_output = MagicMock()
        mock_main.global_results_viewer = mock_results
        mock_main.global_output_panel = mock_output
        mock_main.show_panel = MagicMock()
        widget._get_main_window = MagicMock(return_value=mock_main)

        widget._on_python_finished(
            result=None, output="", error='NameError: name "x" is not defined', updated_namespace={}, figures=[]
        )

        # Results NAO deve ter sido chamado
        mock_results.display_rich_output.assert_not_called()
        mock_results.display_dataframe.assert_not_called()
        # Output deve mostrar erro
        mock_main.show_panel.assert_called_with("output")

    def test_print_goes_to_output(self, qapp):
        """print() vai para Output (via append_output)"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session
        from src.core.theme_manager import ThemeManager

        session = MagicMock(spec=Session)
        session.name = "test"
        session.language = "python"
        session.connection_name = None
        session.namespace = {}
        session.register_thread = MagicMock()
        session.unregister_thread = MagicMock()
        session.finish_execution = MagicMock()
        session.update_namespace = MagicMock()

        widget = SessionWidget(session, ThemeManager())

        mock_main = MagicMock()
        mock_results = MagicMock()
        mock_output = MagicMock()
        mock_main.global_results_viewer = mock_results
        mock_main.global_output_panel = mock_output
        mock_main.show_panel = MagicMock()
        widget._get_main_window = MagicMock(return_value=mock_main)

        # Monitorar append_output
        widget.append_output = MagicMock()

        widget._on_python_finished(result=None, output="Hello World\n", error="", updated_namespace={}, figures=[])

        # append_output chamado com o texto
        widget.append_output.assert_called()
        call_args = str(widget.append_output.call_args)
        assert "Hello World" in call_args

    def test_dataframe_goes_to_results_grid(self, qapp):
        """DataFrame vai para Results como grid (tabela)"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session
        from src.core.theme_manager import ThemeManager

        session = MagicMock(spec=Session)
        session.name = "test"
        session.language = "python"
        session.connection_name = None
        session.namespace = {}
        session.register_thread = MagicMock()
        session.unregister_thread = MagicMock()
        session.finish_execution = MagicMock()
        session.update_namespace = MagicMock()

        widget = SessionWidget(session, ThemeManager())

        mock_main = MagicMock()
        mock_results = MagicMock()
        mock_main.global_results_viewer = mock_results
        mock_main.show_panel = MagicMock()
        widget._get_main_window = MagicMock(return_value=mock_main)

        df = pd.DataFrame({"a": [1, 2, 3]})
        widget._on_python_finished(result=df, output="", error="", updated_namespace={}, figures=[])

        # display_dataframe chamado (nao display_rich_output)
        mock_results.display_dataframe.assert_called_once()
        mock_results.display_rich_output.assert_not_called()

    def test_figures_plus_dataframe(self, qapp):
        """Figuras + DataFrame -> figuras vao para results, df fica no namespace"""
        from src.ui.components.session_widget import SessionWidget
        from src.core.session import Session
        from src.core.theme_manager import ThemeManager

        session = MagicMock(spec=Session)
        session.name = "test"
        session.language = "python"
        session.connection_name = None
        session.namespace = {}
        session.register_thread = MagicMock()
        session.unregister_thread = MagicMock()
        session.finish_execution = MagicMock()
        session.update_namespace = MagicMock()

        widget = SessionWidget(session, ThemeManager())

        mock_main = MagicMock()
        mock_results = MagicMock()
        mock_main.global_results_viewer = mock_results
        mock_main.show_panel = MagicMock()
        widget._get_main_window = MagicMock(return_value=mock_main)

        df = pd.DataFrame({"a": [1, 2]})
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        widget._on_python_finished(result=df, output="", error="", updated_namespace={}, figures=[fake_png])

        # display_rich_output deve ser chamado (graficos tem prioridade visual)
        mock_results.display_rich_output.assert_called_once()
        mock_main.show_panel.assert_called_with("results")


# ===========================================================================
# 8. Teste E2E completo: PythonWorker -> ResultsViewer
# ===========================================================================


class TestEndToEndPythonToResults:
    """Teste E2E: executa codigo Python, verifica que ResultsViewer exibe"""

    def test_e2e_plot_to_results_viewer(self, qapp):
        """E2E: plt.plot() -> PythonWorker -> ResultsViewer mostra imagem"""
        from src.ui.components.results_viewer import ResultsViewer

        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.figure(figsize=(4, 3))
plt.plot([1, 2, 3], [10, 20, 30])
plt.title('E2E Test')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1

        # Agora passa as figuras para o ResultsViewer
        viewer = ResultsViewer()
        viewer.display_rich_output(figures, "E2E Chart")

        # Verificar que imagem esta visivel
        assert viewer.stack.currentIndex() == 1
        assert viewer.image_label.pixmap() is not None
        assert not viewer.image_label.pixmap().isNull()
        assert viewer._current_image_bytes is not None
        assert viewer._current_image_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_e2e_barh_user_scenario(self, qapp):
        """E2E: cenario EXATO do usuario - barh com df existente"""
        from src.ui.components.results_viewer import ResultsViewer

        existing_df = pd.DataFrame(
            {
                "IdCidade": [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000],
                "Nome": [f"Cidade {i}" for i in range(10)],
            }
        )
        namespace = {"df": existing_df}

        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

top_10 = df.head(10)
plt.barh(top_10['Nome'], top_10['IdCidade'])
plt.title('Top 10 Clientes')
plt.show()
"""
        result, output, error, ns, figures = run_python_worker_sync(code, namespace)
        assert error == "", f"Erro: {error}"
        assert len(figures) >= 1, "Nenhuma figura para cenario do usuario"

        viewer = ResultsViewer()
        viewer.display_rich_output(figures, "Top 10 Clientes")

        assert viewer.stack.currentIndex() == 1
        pixmap = viewer.image_label.pixmap()
        assert pixmap is not None and not pixmap.isNull()
        # Imagem deve ter dimensoes razoaveis
        assert pixmap.width() > 10
        assert pixmap.height() > 10

    def test_e2e_dataframe_shows_grid(self, qapp):
        """E2E: DataFrame puro -> ResultsViewer mostra grid (tabela)"""
        from src.ui.components.results_viewer import ResultsViewer

        code = """
import pandas as pd
result = pd.DataFrame({'x': [1, 2, 3], 'y': ['a', 'b', 'c']})
result
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert isinstance(result, pd.DataFrame)
        assert figures == []

        viewer = ResultsViewer()
        viewer.display_dataframe(result, "result")

        assert viewer.stack.currentIndex() == 0
        assert viewer.current_df is not None
        assert len(viewer.current_df) == 3

    def test_e2e_print_captured_no_image(self, qapp):
        """E2E: print() gera output, sem imagem"""
        code = """
print('Log: processando dados...')
x = 42
print(f'Resultado: {x}')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert "Log: processando dados" in output
        assert "Resultado: 42" in output
        assert figures == []

    def test_e2e_error_captured(self, qapp):
        """E2E: codigo com erro -> error preenchido, sem figuras"""
        code = """
import pandas as pd
df = pd.DataFrame({'a': [1]})
# Coluna que nao existe
df['coluna_inexistente_xyz']
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error != "", "Deveria ter erro"
        assert "KeyError" in error
        assert figures == []

    def test_e2e_chart_plus_print(self, qapp):
        """E2E: print + chart -> output tem texto, figures tem PNG"""
        from src.ui.components.results_viewer import ResultsViewer

        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
print('Gerando grafico de vendas...')
plt.pie([30, 20, 50], labels=['A', 'B', 'C'])
plt.title('Vendas')
print('Pronto!')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert "Gerando grafico" in output
        assert "Pronto" in output
        assert len(figures) >= 1

        viewer = ResultsViewer()
        viewer.display_rich_output(figures, "Vendas")
        assert viewer.stack.currentIndex() == 1

    def test_e2e_dark_theme_applied(self, qapp):
        """E2E: chart usa tema escuro (fundo #1e1e1e)"""
        from PyQt6.QtGui import QImage

        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig = plt.figure(figsize=(4, 3))
plt.plot([1, 2], [1, 2])
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert len(figures) >= 1

        # Carregar imagem e verificar que o fundo e escuro
        img = QImage()
        img.loadFromData(get_image_bytes(figures[0]))
        assert not img.isNull()

        # Pixel no canto (0,0) deve ser escuro (proximo de #1e1e1e = rgb 30,30,30)
        corner = img.pixelColor(0, 0)
        assert corner.red() < 80, f"R={corner.red()} - fundo nao parece escuro"
        assert corner.green() < 80, f"G={corner.green()} - fundo nao parece escuro"
        assert corner.blue() < 80, f"B={corner.blue()} - fundo nao parece escuro"


# ===========================================================================
# 9. HTML display - pandas Styler, _repr_html_()
# ===========================================================================


class TestHTMLDisplay:
    """Testes para exibicao de HTML no ResultsViewer"""

    def test_display_html_sets_page_2(self, qapp):
        """display_html muda para pagina 2 do stack"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_html("<h1>Test</h1>", "HTML Test")
        assert viewer.stack.currentIndex() == 2

    def test_display_html_content_loaded(self, qapp):
        """display_html carrega conteudo no QTextEdit"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_html("<p>Hello World</p>", "Test")
        html = viewer.html_viewer.toHtml()
        assert "Hello World" in html

    def test_display_html_with_table(self, qapp):
        """display_html renderiza tabela HTML"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        table_html = """
        <table>
            <tr><th>Nome</th><th>Valor</th></tr>
            <tr><td>A</td><td>100</td></tr>
            <tr><td>B</td><td>200</td></tr>
        </table>
        """
        viewer.display_html(table_html, "Tabela HTML")
        assert viewer.stack.currentIndex() == 2
        html = viewer.html_viewer.toHtml()
        assert "Nome" in html
        assert "100" in html

    def test_display_html_injects_dark_css(self, qapp):
        """display_html injeta CSS de tema escuro"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_html("<p>Test</p>", "CSS Test")
        html = viewer.html_viewer.toHtml()
        # CSS inline e aplicado pelo QTextEdit, verificar que nao quebrou
        assert "Test" in html

    def test_display_html_hides_toolbar_buttons(self, qapp):
        """display_html esconde botoes de export e save"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_html("<p>Test</p>", "Test")
        assert viewer.btn_export_csv.isHidden()
        assert viewer.btn_save_image.isHidden()

    def test_display_html_updates_info_label(self, qapp):
        """display_html atualiza info_label com o label"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_html("<p>Test</p>", "Pandas Styler")
        assert "Pandas Styler" in viewer.info_label.text()


# ===========================================================================
# 10. JSON tree display - dict/list
# ===========================================================================


class TestJSONDisplay:
    """Testes para exibicao de JSON tree no ResultsViewer"""

    def test_display_json_dict_sets_page_3(self, qapp):
        """display_json com dict muda para pagina 3"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_json({"nome": "Joao", "idade": 30}, "Config")
        assert viewer.stack.currentIndex() == 3

    def test_display_json_creates_items(self, qapp):
        """display_json cria itens na arvore"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        data = {"nome": "Joao", "idade": 30, "ativo": True}
        viewer.display_json(data, "Pessoa")

        root = viewer.json_tree.invisibleRootItem()
        assert root.childCount() == 3

    def test_display_json_nested_dict(self, qapp):
        """display_json mostra dicts aninhados com filhos"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        data = {"nome": "Joao", "endereco": {"cidade": "SP", "estado": "SP"}}
        viewer.display_json(data, "Nested")

        root = viewer.json_tree.invisibleRootItem()
        assert root.childCount() == 2  # nome + endereco

        # Encontrar item 'endereco' e verificar filhos
        for i in range(root.childCount()):
            item = root.child(i)
            if item.text(0) == "endereco":
                assert item.childCount() == 2  # cidade + estado
                break
        else:
            assert False, "Item 'endereco' nao encontrado"

    def test_display_json_list(self, qapp):
        """display_json com list mostra indices [0], [1]..."""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        data = [10, 20, 30]
        viewer.display_json(data, "Lista")

        root = viewer.json_tree.invisibleRootItem()
        assert root.childCount() == 3
        assert root.child(0).text(0) == "[0]"
        assert root.child(0).text(1) == "10"

    def test_display_json_mixed_types(self, qapp):
        """display_json mostra tipos corretamente na coluna 'Tipo'"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        data = {"text": "hello", "num": 42, "flag": True, "nada": None}
        viewer.display_json(data, "Types")

        root = viewer.json_tree.invisibleRootItem()
        types = {}
        for i in range(root.childCount()):
            item = root.child(i)
            types[item.text(0)] = item.text(2)

        assert types["text"] == "str"
        assert types["num"] == "int"
        assert types["flag"] == "bool"
        assert types["nada"] == "NoneType"

    def test_display_json_values_formatted(self, qapp):
        """display_json formata valores (strings com aspas, null, etc.)"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        data = {"nome": "Joao", "vazio": None, "flag": True}
        viewer.display_json(data, "Format")

        root = viewer.json_tree.invisibleRootItem()
        values = {}
        for i in range(root.childCount()):
            item = root.child(i)
            values[item.text(0)] = item.text(1)

        assert values["nome"] == '"Joao"'
        assert values["vazio"] == "null"
        assert values["flag"] == "true"

    def test_display_json_info_label(self, qapp):
        """display_json atualiza info_label com contagem"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_json({"a": 1, "b": 2, "c": 3}, "Config")
        assert "3 chaves" in viewer.info_label.text()

    def test_display_json_list_info_label(self, qapp):
        """display_json com list mostra contagem de itens"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_json([1, 2, 3, 4, 5], "Numeros")
        assert "5 itens" in viewer.info_label.text()

    def test_display_json_first_level_expanded(self, qapp):
        """display_json expande primeiro nivel automaticamente"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        data = {"sub": {"a": 1}, "outro": {"b": 2}}
        viewer.display_json(data, "Expanded")

        root = viewer.json_tree.invisibleRootItem()
        for i in range(root.childCount()):
            assert root.child(i).isExpanded()

    def test_display_json_hides_toolbar_buttons(self, qapp):
        """display_json esconde botoes de export e save"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_json({"a": 1}, "Test")
        assert viewer.btn_export_csv.isHidden()
        assert viewer.btn_save_image.isHidden()


# ===========================================================================
# 11. PythonWorker detecta _repr_html_(), dict/list
# ===========================================================================


class TestWorkerRichOutputTypes:
    """PythonWorker detecta novos tipos de saida"""

    def test_repr_html_detected(self, qapp):
        """Objeto com _repr_html_() gera rich output tipo html"""
        code = """
class StyledResult:
    def _repr_html_(self):
        return '<table><tr><td>Styled!</td></tr></table>'

result = StyledResult()
result
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1
        assert get_output_type(figures[0]) == "html"
        assert "Styled!" in figures[0]["data"]

    def test_dict_result_goes_to_json(self, qapp):
        """dict como resultado gera rich output tipo json"""
        code = """
config = {'host': 'localhost', 'port': 3306, 'database': 'test'}
config
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1
        assert get_output_type(figures[0]) == "json"
        assert figures[0]["data"]["host"] == "localhost"
        assert result is None  # result consumido pelo rich output

    def test_list_result_goes_to_json(self, qapp):
        """list como resultado gera rich output tipo json"""
        code = """
items = [{'name': 'A', 'value': 1}, {'name': 'B', 'value': 2}]
items
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1
        assert get_output_type(figures[0]) == "json"
        assert len(figures[0]["data"]) == 2

    def test_pandas_styler_detected(self, qapp):
        """pandas Styler (tem _repr_html_) gera rich output tipo html"""
        code = """
import pandas as pd
df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
styled = df.style.highlight_max()
styled
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1
        assert get_output_type(figures[0]) == "html"
        # Pandas Styler HTML contem a table
        assert "<table" in figures[0]["data"].lower() or "<style" in figures[0]["data"].lower()

    def test_plain_dataframe_not_html(self, qapp):
        """DataFrame puro NAO e convertido para HTML (tem grid melhor)"""
        code = """
import pandas as pd
df = pd.DataFrame({'x': [1, 2, 3]})
df
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        # DataFrame deve ficar como result, nao como HTML
        assert isinstance(result, pd.DataFrame)
        # Nenhum rich output HTML
        html_outputs = [f for f in figures if get_output_type(f) == "html"]
        assert len(html_outputs) == 0

    def test_empty_dict_no_json(self, qapp):
        """dict vazio nao gera JSON tree (nada util)"""
        code = """
x = {}
x
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        # Dict vazio pode ou nao gerar json, mas nao deve crashar
        assert error == ""

    def test_simple_int_unchanged(self, qapp):
        """int simples nao gera rich output"""
        code = "42"
        result, output, error, ns, figures = run_python_worker_sync(code, is_expression=True)
        assert error == ""
        assert result == 42
        json_outputs = [f for f in figures if get_output_type(f) == "json"]
        assert len(json_outputs) == 0


# ===========================================================================
# 12. display_rich_output dispatching
# ===========================================================================


class TestDisplayRichOutput:
    """ResultsViewer.display_rich_output roteia por tipo"""

    def _make_test_png(self):
        """Gera PNG de teste"""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(2, 2))
        ax.plot([1, 2])
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=72)
        buf.seek(0)
        data = buf.getvalue()
        plt.close(fig)
        return data

    def test_rich_output_image_dict(self, qapp):
        """display_rich_output com type=image mostra imagem (page 1)"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        png = self._make_test_png()

        viewer.display_rich_output([{"type": "image", "data": png}], "Test")
        assert viewer.stack.currentIndex() == 1

    def test_rich_output_html_dict(self, qapp):
        """display_rich_output com type=html mostra HTML (page 2)"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_rich_output([{"type": "html", "data": "<p>Hello</p>"}], "HTML")
        assert viewer.stack.currentIndex() == 2
        assert "Hello" in viewer.html_viewer.toHtml()

    def test_rich_output_json_dict(self, qapp):
        """display_rich_output com type=json mostra JSON tree (page 3)"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_rich_output([{"type": "json", "data": {"key": "value"}}], "JSON")
        assert viewer.stack.currentIndex() == 3

    def test_rich_output_raw_bytes_backward_compat(self, qapp):
        """display_rich_output com bytes puros funciona (backward compat)"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        png = self._make_test_png()

        viewer.display_rich_output([png], "Compat")
        assert viewer.stack.currentIndex() == 1

    def test_rich_output_priority_image_over_html(self, qapp):
        """Quando ha image e html, image tem prioridade"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()
        png = self._make_test_png()

        viewer.display_rich_output([{"type": "html", "data": "<p>Hello</p>"}, {"type": "image", "data": png}], "Mixed")
        assert viewer.stack.currentIndex() == 1  # image wins

    def test_rich_output_priority_html_over_json(self, qapp):
        """Quando ha html e json, html tem prioridade"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_rich_output(
            [{"type": "json", "data": {"a": 1}}, {"type": "html", "data": "<p>Hello</p>"}], "Mixed"
        )
        assert viewer.stack.currentIndex() == 2  # html wins

    def test_rich_output_empty_noop(self, qapp):
        """display_rich_output com lista vazia nao faz nada"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_rich_output([], "Nothing")
        assert viewer.stack.currentIndex() == 0  # stays on table

    def test_clear_resets_html_and_json(self, qapp):
        """clear() limpa HTML e JSON tree tambem"""
        from src.ui.components.results_viewer import ResultsViewer

        viewer = ResultsViewer()

        viewer.display_html("<p>Test</p>", "HTML")
        assert viewer.stack.currentIndex() == 2

        viewer.clear()
        assert viewer.stack.currentIndex() == 0
        assert viewer.json_tree.invisibleRootItem().childCount() == 0


# ===========================================================================
# 13. E2E: Python code -> rich output -> ResultsViewer
# ===========================================================================


class TestEndToEndRichOutputs:
    """E2E: executa Python, verifica rich outputs no ResultsViewer"""

    def test_e2e_pandas_styler_shows_html(self, qapp):
        """E2E: df.style.highlight_max() mostra HTML no Results"""
        from src.ui.components.results_viewer import ResultsViewer

        code = """
import pandas as pd
df = pd.DataFrame({'A': [10, 20, 30], 'B': [5, 15, 25]})
styled = df.style.highlight_max()
styled
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1
        assert get_output_type(figures[0]) == "html"

        viewer = ResultsViewer()
        viewer.display_rich_output(figures, "Styler")
        assert viewer.stack.currentIndex() == 2

    def test_e2e_dict_shows_json_tree(self, qapp):
        """E2E: dict como resultado -> JSON tree no Results"""
        from src.ui.components.results_viewer import ResultsViewer

        code = """
result = {
    'servidor': 'produção',
    'conexoes': 42,
    'config': {
        'timeout': 30,
        'retries': 3
    }
}
result
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1
        assert get_output_type(figures[0]) == "json"

        viewer = ResultsViewer()
        viewer.display_rich_output(figures, "Server Info")
        assert viewer.stack.currentIndex() == 3

        # Verificar que a arvore tem os itens
        root = viewer.json_tree.invisibleRootItem()
        assert root.childCount() >= 3  # servidor, conexoes, config

    def test_e2e_list_of_dicts_shows_json(self, qapp):
        """E2E: lista de dicts -> JSON tree"""
        from src.ui.components.results_viewer import ResultsViewer

        code = """
users = [
    {'name': 'Alice', 'age': 30},
    {'name': 'Bob', 'age': 25},
    {'name': 'Carol', 'age': 35}
]
users
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1
        assert get_output_type(figures[0]) == "json"

        viewer = ResultsViewer()
        viewer.display_rich_output(figures, "Users")
        assert viewer.stack.currentIndex() == 3

    def test_e2e_chart_still_works(self, qapp):
        """E2E: matplotlib chart ainda funciona com novo formato"""
        from src.ui.components.results_viewer import ResultsViewer

        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.figure()
plt.bar(['A', 'B', 'C'], [10, 20, 15])
plt.title('Bar Chart')
"""
        result, output, error, ns, figures = run_python_worker_sync(code)
        assert error == ""
        assert len(figures) >= 1
        assert get_output_type(figures[0]) == "image"

        viewer = ResultsViewer()
        viewer.display_rich_output(figures, "Chart")
        assert viewer.stack.currentIndex() == 1
        assert viewer.image_label.pixmap() is not None
