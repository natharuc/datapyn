"""
Teste Visual Manual - Simula um usuário humano usando a aplicação

Este teste abre a janela real e executa ações passo a passo,
permitindo visualizar o que está acontecendo.

Execute com: python -m tests.test_visual_manual
"""

import sys
import time

sys.path.insert(0, ".")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtTest import QTest

from src.ui.main_window import MainWindow


class VisualTester:
    """Executa testes visuais passo a passo"""

    def __init__(self, window: MainWindow):
        self.window = window
        self.step = 0
        self.steps = []

    def log(self, msg):
        """Loga mensagem no console e no output da sessão"""
        print(f"[TESTE] {msg}")
        try:
            widget = self.window._get_current_session_widget()
            if widget:
                widget.append_output(f"🧪 TESTE: {msg}")
        except:
            pass

    def wait(self, ms: int = 1000):
        """Espera um tempo"""
        QTest.qWait(ms)

    def run_test(self):
        """Executa o teste completo"""
        self.log("=" * 50)
        self.log("INICIANDO TESTE VISUAL")
        self.log("=" * 50)
        self.wait(500)

        try:
            self.test_01_verify_initial_state()
            self.test_02_add_sql_block()
            self.test_03_write_cross_syntax_and_change_language()
            self.test_04_add_python_block()
            self.test_05_execute_all()

            self.log("=" * 50)
            self.log("✅ TODOS OS TESTES PASSARAM!")
            self.log("=" * 50)

        except Exception as e:
            self.log(f"❌ ERRO NO TESTE: {e}")
            import traceback

            traceback.print_exc()

    def test_01_verify_initial_state(self):
        """Passo 1: Verifica estado inicial"""
        self.log("Passo 1: Verificando estado inicial...")

        widget = self.window._get_current_session_widget()
        assert widget is not None, "Deve ter uma sessão ativa"

        editor = widget.editor
        blocks = editor.get_blocks()
        assert len(blocks) >= 1, "Deve ter pelo menos 1 bloco"

        self.log(f"  Blocos encontrados: {len(blocks)}")
        self.log(f"  Linguagem do primeiro bloco: {blocks[0].get_language()}")

        self.wait(500)

    def test_02_add_sql_block(self):
        """Passo 2: Adiciona bloco SQL"""
        self.log("Passo 2: Adicionando bloco SQL...")

        widget = self.window._get_current_session_widget()
        editor = widget.editor

        # Limpa o primeiro bloco e configura como SQL
        blocks = editor.get_blocks()
        first_block = blocks[0]

        # Muda para SQL
        self.log("  → Mudando linguagem para SQL")
        first_block.set_language("sql")
        self.wait(300)

        # Escreve query
        self.log("  → Escrevendo: SELECT * FROM cliente LIMIT 5")
        first_block.set_code("SELECT * FROM cliente LIMIT 5")
        self.wait(300)

        # Verifica
        assert first_block.get_language() == "sql", f"Esperado sql, obteve {first_block.get_language()}"
        self.log(f"  Linguagem confirmada: {first_block.get_language()}")

        self.wait(500)

    def test_03_write_cross_syntax_and_change_language(self):
        """Passo 3: Escreve cross-syntax e muda linguagem"""
        self.log("Passo 3: Testando Cross-Syntax...")

        widget = self.window._get_current_session_widget()
        editor = widget.editor

        # Limpa todos os blocos
        while len(editor.get_blocks()) > 1:
            editor.remove_block(editor.get_blocks()[-1])

        # Configura o primeiro bloco como SQL inicialmente (simula o bug)
        first_block = editor.get_blocks()[0]
        first_block.set_language("sql")
        first_block.set_code("")

        # Adiciona novo bloco - inicialmente será python
        self.log("  → Adicionando novo bloco (padrão: python)")
        new_block = editor.add_block()
        self.wait(300)

        # Escreve código cross-syntax ENQUANTO AINDA É PYTHON!
        cross_code = "clientes = {{SELECT * FROM cliente LIMIT 3}}"
        self.log(f"  → Escrevendo cross-syntax ANTES de mudar linguagem: {cross_code}")
        new_block.set_code(cross_code)
        self.wait(300)

        # Verifica que ainda está como Python
        lang_before = new_block.get_language()
        self.log(f"  → Linguagem ANTES de mudar: '{lang_before}'")

        # IMPORTANTE: Muda para Cross-Syntax
        self.log("  → MUDANDO linguagem para Cross-Syntax")
        new_block.set_language("cross")
        self.wait(500)

        # Verifica que a linguagem mudou
        lang_after = new_block.get_language()
        self.log(f"  → Linguagem DEPOIS de mudar: '{lang_after}'")
        assert lang_after == "cross", f"Esperado 'cross', obteve '{lang_after}'"
        self.log(f"  Linguagem confirmada: {lang_after}")

        self.wait(500)

    def test_04_add_python_block(self):
        """Passo 4: Adiciona bloco Python"""
        self.log("Passo 4: Adicionando bloco Python...")

        widget = self.window._get_current_session_widget()
        editor = widget.editor

        # Adiciona bloco Python
        self.log("  → Adicionando bloco Python")
        python_block = editor.add_block(language="python")
        self.wait(300)

        # Escreve código
        python_code = 'print("Clientes:", type(clientes))'
        self.log(f"  → Escrevendo: {python_code}")
        python_block.set_code(python_code)
        self.wait(300)

        # Verifica
        assert python_block.get_language() == "python"
        self.log(f"  Linguagem confirmada: {python_block.get_language()}")

        # Mostra resumo dos blocos
        self.log("  → Resumo final dos blocos:")
        for i, block in enumerate(editor.get_blocks()):
            lang = block.get_language()
            code = block.get_code()[:50] if block.get_code() else "(vazio)"
            self.log(f"     Bloco {i + 1}: [{lang.upper()}] {code}...")

        self.wait(500)

    def test_05_execute_all(self):
        """Passo 5: Executa todos os blocos"""
        self.log("Passo 5: Executando todos os blocos com F5...")

        widget = self.window._get_current_session_widget()
        editor = widget.editor

        # Log dos blocos antes de executar
        self.log("  → Blocos que serão executados:")
        for i, block in enumerate(editor.get_blocks()):
            lang = block.get_language()
            code = block.get_code().strip()[:60]
            self.log(f"     [{i + 1}] {lang.upper()}: {code}")

        # Conecta para rastrear o que é emitido
        executed = []

        def on_sql(code):
            self.log(f"  📤 Sinal execute_sql emitido: {code[:50]}...")
            executed.append(("sql", code))

        def on_python(code):
            self.log(f"  📤 Sinal execute_python emitido: {code[:50]}...")
            executed.append(("python", code))

        def on_cross(code):
            self.log(f"  📤 Sinal execute_cross_syntax emitido: {code[:50]}...")
            executed.append(("cross", code))

        def on_queue(queue):
            self.log(f"  📤 Sinal execute_queue emitido com {len(queue)} itens:")
            for lang, code in queue:
                self.log(f"      - {lang}: {code[:40]}...")
                executed.append((lang, code))

        editor.execute_sql.connect(on_sql)
        editor.execute_python.connect(on_python)
        editor.execute_cross_syntax.connect(on_cross)
        editor.execute_queue.connect(on_queue)

        # Executa todos
        self.log("  → Chamando execute_all_blocks()...")
        editor.execute_all_blocks()
        self.wait(500)

        # Verifica que os sinais foram emitidos corretamente
        self.log(f"  → Total de execuções rastreadas: {len(executed)}")

        # Verifica que cross-syntax foi emitido como 'cross', não 'sql'
        for lang, code in executed:
            if "{{" in code and "}}" in code:
                assert lang == "cross", f"Cross-syntax deveria ser 'cross' mas foi '{lang}'"
                self.log(f"  Cross-syntax corretamente identificado como '{lang}'")

        self.wait(2000)  # Espera execução

        self.log("  Execução concluída!")


def main():
    """Função principal"""
    app = QApplication(sys.argv)

    print("=" * 60)
    print("TESTE VISUAL - Simula usuário humano")
    print("=" * 60)
    print()
    print("A janela vai abrir e os testes serão executados automaticamente.")
    print("Observe as ações acontecendo na tela.")
    print()

    # Cria janela principal
    window = MainWindow()
    window.show()

    # Agenda os testes para rodar após janela aparecer
    tester = VisualTester(window)
    QTimer.singleShot(1500, tester.run_test)

    # Executa
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
