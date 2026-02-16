"""
Configuracao global do editor de codigo.

Usa QScintilla como editor (nativo, rapido, com Find/Replace integrado).
"""


def get_code_editor_class():
    """
    Retorna a classe do editor configurado.

    Returns:
        CodeEditor (QScintilla)
    """
    from .code_editor import CodeEditor

    return CodeEditor
