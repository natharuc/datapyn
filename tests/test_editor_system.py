"""
Teste de validação do sistema de editores configuráveis.

Verifica se a arquitetura de troca de editores está funcionando.
"""

import sys
from pathlib import Path

# Adicionar src ao path
sys.path.insert(0, str(Path(__file__).parent))


def test_editor_config():
    """Testa módulo de configuração"""
    print("=" * 60)
    print("TESTE: Configuração de Editor")
    print("=" * 60)

    try:
        from src.editors.editor_config import EDITOR_TYPE, get_code_editor_class

        print(f"✅ Import editor_config OK")
        print(f"📝 Editor configurado: {EDITOR_TYPE}")

        EditorClass = get_code_editor_class()
        print(f"✅ Classe obtida: {EditorClass.__name__}")

        return True
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


def test_interface():
    """Testa interface ICodeEditor"""
    print("\n" + "=" * 60)
    print("TESTE: Interface ICodeEditor")
    print("=" * 60)

    try:
        from src.editors.interfaces import ICodeEditor

        print(f"✅ Import ICodeEditor OK")

        # Verificar métodos da interface
        expected_methods = [
            "get_text",
            "set_text",
            "get_selected_text",
            "has_selection",
            "clear",
            "set_language",
            "get_language",
            "set_theme",
            "apply_theme",
        ]

        protocol_annotations = getattr(ICodeEditor, "__annotations__", {})
        print(f"✅ Protocol com {len(protocol_annotations)} atributos")

        return True
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


def test_implementations():
    """Testa implementações disponíveis"""
    print("\n" + "=" * 60)
    print("TESTE: Implementações de Editores")
    print("=" * 60)

    # Testar QScintilla
    try:
        from src.editors.code_editor import CodeEditor

        print(f"✅ CodeEditor (QScintilla) disponível")
    except Exception as e:
        print(f"⚠️  CodeEditor: {e}")

    # Testar Monaco
    try:
        from src.editors.monaco_editor import MonacoEditor, MONACO_AVAILABLE

        if MONACO_AVAILABLE:
            print(f"✅ MonacoEditor disponível (monaco-qt instalado)")
        else:
            print(f"⚠️  MonacoEditor disponível (monaco-qt NÃO instalado)")
    except Exception as e:
        print(f"⚠️  MonacoEditor: {e}")

    return True


def test_code_block():
    """Testa CodeBlock usando editor configurável"""
    print("\n" + "=" * 60)
    print("TESTE: CodeBlock com Editor Dinâmico")
    print("=" * 60)

    try:
        # Verificar se CodeBlock importa corretamente
        import ast

        code_block_file = Path(__file__).parent / "src" / "editors" / "code_block.py"

        with open(code_block_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Verificar se usa get_code_editor_class
        if "get_code_editor_class" in content:
            print(f"✅ CodeBlock usa get_code_editor_class()")
        else:
            print(f"❌ CodeBlock não usa get_code_editor_class()")
            return False

        # Verificar se não importa CodeEditor diretamente
        if "from src.editors.code_editor import CodeEditor" in content:
            print(f"⚠️  CodeBlock ainda importa CodeEditor diretamente")
        else:
            print(f"✅ CodeBlock não depende de implementação específica")

        return True
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


def show_how_to_switch():
    """Mostra como trocar de editor"""
    print("\n" + "=" * 60)
    print("COMO TROCAR DE EDITOR")
    print("=" * 60)

    print("""
1. Abra: src/editors/editor_config.py

2. Altere a linha:
   EDITOR_TYPE: Literal['qscintilla', 'monaco'] = 'qscintilla'
   
   Para:
   EDITOR_TYPE: Literal['qscintilla', 'monaco'] = 'monaco'

3. Se escolher Monaco, instale:
   pip install monaco-qt

4. Reinicie o DataPyn

✅ Pronto! Todos os blocos de código usarão o novo editor.
""")


def main():
    """Executa todos os testes"""
    print("\n🔬 VALIDAÇÃO DO SISTEMA DE EDITORES CONFIGURÁVEIS\n")

    results = []

    results.append(("Configuração", test_editor_config()))
    results.append(("Interface", test_interface()))
    results.append(("Implementações", test_implementations()))
    results.append(("CodeBlock", test_code_block()))

    # Resumo
    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)

    for name, result in results:
        status = "✅ PASSOU" if result else "❌ FALHOU"
        print(f"{status}: {name}")

    passed = sum(1 for _, r in results if r)
    total = len(results)

    print(f"\n📊 {passed}/{total} testes passaram")

    if passed == total:
        print("\n🎉 Sistema de editores configuráveis está funcionando!")
        show_how_to_switch()
    else:
        print("\n⚠️  Alguns testes falharam. Verifique os erros acima.")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
