"""Unit tests for settings sidebar navigation."""

from src.ui.components.settings_nav import (
    SettingsNavNode,
    build_settings_search_text,
    section_nav_label,
)


def test_build_settings_search_text_includes_label_and_keywords():
    node = SettingsNavNode(
        id="general.language",
        label="Language",
        page_id="general",
        keywords=["idioma", "locale"],
    )
    blob = build_settings_search_text(node)
    assert "language" in blob
    assert "idioma" in blob
    assert "general" in blob


def test_section_nav_label_titleizes_uppercase():
    assert section_nav_label("section_language", "LANGUAGE") == "Language"


def test_filter_text_hides_non_matching_nodes(qapp):
    from src.ui.components.settings_nav import SettingsNavPanel

    panel = SettingsNavPanel()
    panel.register_nodes(
        [
            SettingsNavNode(id="general", label="General", page_id="general", is_category=True),
            SettingsNavNode(
                id="general.language",
                label="Language",
                page_id="general",
                parent_id="general",
                keywords=["idioma"],
            ),
            SettingsNavNode(
                id="general.display",
                label="Display",
                page_id="general",
                parent_id="general",
                keywords=["grid"],
            ),
            SettingsNavNode(id="shortcuts", label="Shortcuts", page_id="shortcuts", keywords=["f5"]),
        ]
    )

    first = panel.filter_text("idioma")
    assert first == "general.language"
    assert panel._items["general.display"].isHidden()
    assert not panel._items["general.language"].isHidden()

    panel.filter_text("")
    assert not panel._items["general.display"].isHidden()


def test_filter_text_no_results_shows_hint(qapp):
    from src.ui.components.settings_nav import SettingsNavPanel

    panel = SettingsNavPanel()
    panel.set_no_results_text("Nothing found")
    panel.register_nodes(
        [
            SettingsNavNode(id="shortcuts", label="Shortcuts", page_id="shortcuts"),
        ]
    )
    panel.show()
    qapp.processEvents()

    assert panel.filter_text("zzzz-not-found") is None
    assert not panel._no_results.isHidden()
    assert panel._tree.isHidden()
