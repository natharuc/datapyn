"""
Configuracao global do editor de codigo.

Usa QScintilla como editor padrao (nativo, rapido, com Find/Replace integrado).
Alternativa: Monaco Editor (QWebEngine - mais pesado).
"""

from typing import Literal

EDITOR_TYPE: Literal["monaco", "qscintilla"] = "qscintilla"


def get_code_editor_class():
    """
    Retorna a classe do editor configurado.

    Returns:
        CodeEditor (QScintilla, padrao) ou MonacoEditor
    """
    if EDITOR_TYPE == "monaco":
        from .monaco_editor import MonacoEditor

        return MonacoEditor
    else:
        from .code_editor import CodeEditor

        return CodeEditor
