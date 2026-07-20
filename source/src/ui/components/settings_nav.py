"""Sidebar navigation for the settings dialog (two-level tree)."""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from src.design_system.tokens import SPACING, get_colors, get_tree_stylesheet


@dataclass
class SettingsNavNode:
    """One entry in the settings navigation tree."""

    id: str
    label: str
    page_id: str
    keywords: list[str] = field(default_factory=list)
    parent_id: str | None = None
    is_category: bool = False


def build_settings_search_text(node: SettingsNavNode) -> str:
    """Lowercase blob used to match settings search queries."""
    parts = [node.label, node.page_id.replace(".", " "), node.id.replace(".", " ")]
    parts.extend(node.keywords)
    return " ".join(p.strip().lower() for p in parts if p and str(p).strip())


def _titleize_section(label: str) -> str:
    text = (label or "").strip()
    if not text:
        return text
    if text.isupper():
        return text.title()
    return text


class SettingsNavPanel(QWidget):
    """Tree sidebar for settings pages (search lives in the dialog header)."""

    node_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes: dict[str, SettingsNavNode] = {}
        self._search_texts: dict[str, str] = {}
        self._items: dict[str, QTreeWidgetItem] = {}
        self._filter_query = ""
        self._block_selection = False

        colors = get_colors()
        self.setFixedWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(SPACING.space_2)

        self._no_results = QLabel()
        self._no_results.setWordWrap(True)
        self._no_results.hide()
        self._no_results.setStyleSheet(
            f"color: {colors.text_tertiary}; font-size: 11px; padding: 8px 4px;"
        )
        layout.addWidget(self._no_results)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setStyleSheet(get_tree_stylesheet())
        self._tree.setFrameShape(QFrame.Shape.NoFrame)
        self._tree.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self._tree, 1)

        self.setStyleSheet(
            f"""
            SettingsNavPanel {{
                background-color: {colors.bg_secondary};
                border-right: 1px solid {colors.border_default};
            }}
            """
        )

    def set_no_results_text(self, text: str) -> None:
        self._no_results.setText(text)

    def register_nodes(self, nodes: list[SettingsNavNode]) -> None:
        self._nodes.clear()
        self._search_texts.clear()
        self._items.clear()
        self._tree.clear()

        for node in nodes:
            self._nodes[node.id] = node
            self._search_texts[node.id] = build_settings_search_text(node)

        categories = [n for n in nodes if n.is_category]
        for category in categories:
            cat_item = QTreeWidgetItem([category.label])
            cat_item.setData(0, Qt.ItemDataRole.UserRole, category.id)
            self._items[category.id] = cat_item
            self._tree.addTopLevelItem(cat_item)

        for node in nodes:
            if node.is_category:
                continue
            parent_item = None
            if node.parent_id:
                parent_item = self._items.get(node.parent_id)
            item = QTreeWidgetItem([node.label])
            item.setData(0, Qt.ItemDataRole.UserRole, node.id)
            self._items[node.id] = item
            if parent_item is not None:
                parent_item.addChild(item)
            else:
                self._tree.addTopLevelItem(item)

        self._tree.expandAll()

    def child_node_ids(self, parent_id: str) -> list[str]:
        return [
            node.id
            for node in self._nodes.values()
            if node.parent_id == parent_id and not node.is_category
        ]

    def node_by_id(self, node_id: str) -> SettingsNavNode | None:
        return self._nodes.get(node_id)

    def filter_text(self, query: str) -> str | None:
        """Filter visible tree nodes. Returns first visible leaf id, if any."""
        self._filter_query = (query or "").strip().lower()
        if not self._filter_query:
            for item in self._items.values():
                item.setHidden(False)
            self._tree.expandAll()
            self._no_results.hide()
            self._tree.show()
            return None

        first_match: str | None = None
        any_visible = False

        for node in self._nodes.values():
            item = self._items.get(node.id)
            if item is None:
                continue
            if node.is_category:
                continue
            matches = self._filter_query in self._search_texts.get(node.id, "")
            item.setHidden(not matches)
            if matches:
                any_visible = True
                if first_match is None:
                    first_match = node.id

        for node in self._nodes.values():
            if not node.is_category:
                continue
            cat_item = self._items.get(node.id)
            if cat_item is None:
                continue
            child_visible = any(
                not self._items[child_id].isHidden()
                for child_id in self._nodes
                if self._nodes[child_id].parent_id == node.id and child_id in self._items
            )
            cat_matches = self._filter_query in self._search_texts.get(node.id, "")
            cat_item.setHidden(not (child_visible or cat_matches))
            if cat_matches and not child_visible:
                cat_item.setExpanded(True)
            elif child_visible:
                cat_item.setExpanded(True)
                any_visible = True
            if cat_matches and first_match is None:
                first_match = node.id

        for node in self._nodes.values():
            if node.is_category or node.parent_id:
                continue
            item = self._items.get(node.id)
            if item is None:
                continue
            matches = self._filter_query in self._search_texts.get(node.id, "")
            item.setHidden(not matches)
            if matches:
                any_visible = True
                if first_match is None:
                    first_match = node.id

        if any_visible:
            self._no_results.hide()
            self._tree.show()
        else:
            self._no_results.show()
            self._tree.hide()

        if first_match:
            self.select_node(first_match, emit_signal=True)
        return first_match

    def current_filter_query(self) -> str:
        return self._filter_query

    def select_node(self, node_id: str, *, emit_signal: bool = False) -> None:
        item = self._items.get(node_id)
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self._block_selection = not emit_signal
        self._tree.setCurrentItem(item)
        self._block_selection = False
        if emit_signal:
            self.node_selected.emit(node_id)

    def _on_current_item_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if self._block_selection or current is None:
            return
        node_id = current.data(0, Qt.ItemDataRole.UserRole)
        if node_id:
            self.node_selected.emit(str(node_id))


def section_nav_label(section_attr: str, fallback: str) -> str:
    """Turn a settings section header into a tree label."""
    return _titleize_section(fallback)
