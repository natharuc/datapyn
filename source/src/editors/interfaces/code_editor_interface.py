"""
Abstract interface for code editors.

Defines the contract that any editor implementation must follow.
Allows swapping implementation (QScintilla, Monaco, Ace, etc.) without changing the rest of the application.

Uses Protocol (PEP 544) for structural duck typing - doesn't require explicit inheritance.
"""

from typing import Protocol, runtime_checkable
from PyQt6.QtWidgets import QWidget


@runtime_checkable
class ICodeEditor(Protocol):
    """
    Interface (Protocol) for code editors.

    Any concrete editor (QScintilla, Monaco, etc.) must implement these methods.
    The application should depend only on this interface, never on concrete implementation.

    Using Protocol, explicit inheritance is not necessary - just implement the methods.

    Expected signals (must be defined in implementation):
        - text_changed: Emitted when text changes
        - execute_requested: Emitted when user requests execution (F5)
        - focus_in: Emitted when editor gains focus
        - focus_out: Emitted when editor loses focus
    """

    # === Text Methods ===

    def get_text(self) -> str:
        """Returns all editor text."""
        ...

    def set_text(self, text: str) -> None:
        """Sets the editor text."""
        ...

    def get_selected_text(self) -> str:
        """Returns selected text or empty string."""
        ...

    def has_selection(self) -> bool:
        """Checks if there is selected text."""
        ...

    def clear(self) -> None:
        """Clears all editor text."""
        ...

    # === Settings ===

    def set_language(self, language: str) -> None:
        """
        Sets the language for syntax highlighting.

        Args:
            language: 'python', 'sql', 'cross', etc.
        """
        ...

    def get_language(self) -> str:
        """Returns the current language."""
        ...

    def set_theme(self, theme_name: str) -> None:
        """
        Sets the editor theme.

        Args:
            theme_name: Theme name ('dark', 'light', 'monokai', etc.)
        """
        ...

    def apply_theme(self) -> None:
        """Applies/updates the current ThemeManager theme."""
        ...

    # === Visual settings ===

    def set_font(self, family: str, size: int) -> None:
        """Sets the editor font."""
        ...

    def set_read_only(self, read_only: bool) -> None:
        """Sets if editor is read-only."""
        ...

    def set_line_numbers_visible(self, visible: bool) -> None:
        """Sets if line numbers are visible."""
        ...

    # === Helper methods ===

    def get_line_count(self) -> int:
        """Returns the number of lines."""
        ...

    def get_current_line(self) -> int:
        """Returns the current cursor line (0-indexed)."""
        ...

    def go_to_line(self, line: int) -> None:
        """Moves cursor to the specified line (0-indexed)."""
        ...

    # === Widget ===

    def get_widget(self) -> QWidget:
        """
        Returns the Qt widget of the editor to add to layouts.

        Can return `self` if the class inherits from QWidget.
        """
        ...
