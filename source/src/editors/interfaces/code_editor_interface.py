"""
Interface abstrata para editores de código.

Define o contrato que qualquer implementação de editor deve seguir.
Permite trocar a implementação (QScintilla, Monaco, Ace, etc.) sem alterar o resto da aplicação.

Usa Protocol (PEP 544) para duck typing estrutural - não requer herança explícita.
"""

from typing import Protocol, runtime_checkable
from PyQt6.QtWidgets import QWidget


@runtime_checkable
class ICodeEditor(Protocol):
    """
    Interface (Protocol) para editores de código.

    Qualquer editor concreto (QScintilla, Monaco, etc.) deve implementar estes métodos.
    A aplicação deve depender apenas desta interface, nunca da implementação concreta.

    Usando Protocol, não é necessário herdar explicitamente - basta implementar os métodos.

    Signals esperados (devem ser definidos na implementação):
        - text_changed: Emitido quando o texto muda
        - execute_requested: Emitido quando usuário pede execução (F5)
        - focus_in: Emitido quando editor ganha foco
        - focus_out: Emitido quando editor perde foco
    """

    # === Métodos de Texto ===

    def get_text(self) -> str:
        """Retorna todo o texto do editor."""
        ...

    def set_text(self, text: str) -> None:
        """Define o texto do editor."""
        ...

    def get_selected_text(self) -> str:
        """Retorna o texto selecionado ou string vazia."""
        ...

    def has_selection(self) -> bool:
        """Verifica se há texto selecionado."""
        ...

    def clear(self) -> None:
        """Limpa todo o texto do editor."""
        ...

    # === Configurações ===

    def set_language(self, language: str) -> None:
        """
        Define a linguagem para syntax highlighting.

        Args:
            language: 'python', 'sql', 'cross', etc.
        """
        ...

    def get_language(self) -> str:
        """Retorna a linguagem atual."""
        ...

    def set_theme(self, theme_name: str) -> None:
        """
        Define o tema do editor.

        Args:
            theme_name: Nome do tema ('dark', 'light', 'monokai', etc.)
        """
        ...

    def apply_theme(self) -> None:
        """Aplica/atualiza o tema atual do ThemeManager."""
        ...

    # === Configurações visuais ===

    def set_font(self, family: str, size: int) -> None:
        """Define a fonte do editor."""
        ...

    def set_read_only(self, read_only: bool) -> None:
        """Define se o editor é somente leitura."""
        ...

    def set_line_numbers_visible(self, visible: bool) -> None:
        """Define se os números de linha são visíveis."""
        ...

    # === Métodos auxiliares ===

    def get_line_count(self) -> int:
        """Retorna o número de linhas."""
        ...

    def get_current_line(self) -> int:
        """Retorna a linha atual do cursor (0-indexed)."""
        ...

    def go_to_line(self, line: int) -> None:
        """Move o cursor para a linha especificada (0-indexed)."""
        ...

    # === Widget ===

    def get_widget(self) -> QWidget:
        """
        Retorna o widget Qt do editor para adicionar em layouts.

        Pode retornar `self` se a classe herda de QWidget.
        """
        ...
