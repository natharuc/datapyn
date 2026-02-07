"""
Configuração global do editor de código.

Usa QScintilla como editor padrão (nativo e mais rápido).
"""

def get_code_editor_class():
    """
    Retorna a classe do editor QScintilla.
    
    Returns:
        Classe CodeEditor (QScintilla)
    """
    from .code_editor import CodeEditor
    return CodeEditor
