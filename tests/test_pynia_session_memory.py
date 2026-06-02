"""Session memory helpers for API providers."""

from src.services.pynia.session_memory import (
    build_api_messages,
    history_from_ui_messages,
    rolling_summary_from_history,
)


def test_history_from_ui_messages_truncates_assistant():
    ui = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "x" * 5000},
        {"role": "user", "content": "next"},
    ]
    hist = history_from_ui_messages(ui, exclude_last=True)
    assert len(hist) == 2
    assert len(hist[1]["content"]) <= 4003


def test_build_api_messages_includes_history():
    ui = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second"},
    ]
    msgs = build_api_messages(
        system_prompt="sys",
        current_user_prompt="current",
        ui_messages=ui,
    )
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["content"] == "current"
    roles = [m["role"] for m in msgs]
    assert "user" in roles and "assistant" in roles


def test_rolling_summary():
    hist = history_from_ui_messages(
        [
            {"role": "user", "content": "analyze sales"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "add chart"},
        ],
        exclude_last=False,
    )
    recap = rolling_summary_from_history(hist)
    assert "Session recap" in recap
    assert "analyze" in recap
