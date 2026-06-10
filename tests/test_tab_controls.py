"""Tests for TabBarAccessoryStrip (the "+" button next to the last tab)."""

from PyQt6.QtWidgets import QTabBar

from src.design_system.tab_controls import TabBarAccessoryStrip


def _make_bar_with_strip(qtbot, titles):
    bar = QTabBar()
    qtbot.addWidget(bar)
    bar.setExpanding(False)  # app tab bars are compact, not stretched
    for title in titles:
        bar.addTab(title)
    strip = TabBarAccessoryStrip(bar)
    strip.add_button("mdi.plus")
    bar.resize(600, 32)
    bar.show()
    qtbot.wait(20)
    strip.reposition()
    return bar, strip


def _expected_x(bar):
    return bar.tabRect(bar.count() - 1).topRight().x() + 8


def test_strip_sits_after_last_tab(qtbot):
    bar, strip = _make_bar_with_strip(qtbot, ["alpha", "beta"])
    assert strip._strip.x() == _expected_x(bar)


def test_strip_follows_after_closing_middle_tab(qtbot):
    """Closing a non-current middle tab fires no QTabBar signal — the strip
    must still move back next to the (now closer) last tab."""
    bar, strip = _make_bar_with_strip(
        qtbot, ["aba", "uma aba bem comprida no meio", "fim"]
    )
    bar.setCurrentIndex(0)
    qtbot.wait(10)
    strip.reposition()
    x_before = strip._strip.x()

    bar.removeTab(1)  # middle tab, not current: no currentChanged, no resize
    bar.grab()        # force a render so the paint-driven drift detection runs
    qtbot.wait(30)

    assert strip._strip.x() == _expected_x(bar)
    assert strip._strip.x() < x_before


def test_strip_follows_after_adding_tab(qtbot):
    bar, strip = _make_bar_with_strip(qtbot, ["only"])
    x_before = strip._strip.x()

    bar.addTab("segunda aba")
    bar.grab()  # force a render so the paint-driven drift detection runs
    qtbot.wait(30)

    assert strip._strip.x() == _expected_x(bar)
    assert strip._strip.x() > x_before
