"""
Configuracao global do editor de codigo.

Usa Monaco Editor (VS Code) como editor padrao.
Alternativa: QScintilla (descomente para usar).
"""

from typing import Literal

EDITOR_TYPE: Literal["monaco", "qscintilla"] = "monaco"


def get_code_editor_class():
    """
    Retorna a classe do editor configurado.

    Returns:
        MonacoEditor (padrao) ou CodeEditor (QScintilla)
    """
    if EDITOR_TYPE == "monaco":
        from .monaco_editor import MonacoEditor
        return MonacoEditor
    else:
        from .code_editor import CodeEditor
        return CodeEditor
