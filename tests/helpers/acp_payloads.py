"""Representative ACP session/new payloads per agent (no live CLI required)."""

from __future__ import annotations

CLAUDE_SESSION_NEW = {
    "sessionId": "sess-claude-1",
    "models": {
        "availableModels": [
            {"modelId": "sonnet", "name": "Sonnet", "description": "Balanced"},
            {"modelId": "opus", "name": "Opus"},
        ],
        "currentModelId": "sonnet",
    },
    "configOptions": [
        {
            "configId": "mode",
            "name": "Mode",
            "category": "mode",
            "currentValue": "default",
            "options": [
                {"value": "default", "name": "Default"},
                {"value": "bypassPermissions", "name": "Bypass"},
            ],
        },
        {
            "configId": "model",
            "name": "Model",
            "category": "model",
            "currentValue": "sonnet",
            "options": [
                {"value": "sonnet", "name": "Sonnet", "description": "Balanced"},
                {"value": "opus", "name": "Opus"},
            ],
        },
    ],
}

COPILOT_SESSION_NEW = {
    "sessionId": "sess-copilot-1",
    "configOptions": [
        {
            "id": "model",
            "category": "model",
            "name": "Model",
            "currentValue": "gpt-5",
            "options": [
                {"value": "gpt-5", "name": "GPT-5"},
                {"value": "gpt-4.1", "name": "GPT-4.1"},
            ],
        },
        {
            "id": "thought_level",
            "category": "thought_level",
            "name": "Reasoning",
            "currentValue": "medium",
            "options": [
                {"value": "low", "name": "Low"},
                {"value": "medium", "name": "Medium"},
                {"value": "high", "name": "High"},
            ],
        },
        {
            "id": "mode",
            "category": "mode",
            "currentValue": "ask",
            "options": [{"value": "ask", "name": "Ask"}],
        },
    ],
}

CODEX_SESSION_NEW = {
    "sessionId": "sess-codex-1",
    "configOptions": [
        {
            "id": "model",
            "category": "model",
            "currentValue": "gpt-5.1-codex",
            "options": [
                {"value": "gpt-5.1-codex", "name": "GPT-5.1 Codex"},
                {"value": "o3", "name": "o3"},
            ],
        },
        {
            "id": "thought_level",
            "category": "thought_level",
            "currentValue": "high",
            "options": [
                {"value": "low", "name": "Low"},
                {"value": "high", "name": "High"},
            ],
        },
    ],
}

CURSOR_SESSION_NEW = {
    "sessionId": "sess-cursor-1",
    "configOptions": [],
}

SET_CONFIG_CURRENT_ONLY = {
    "configOptions": [
        {"id": "model", "category": "model", "currentValue": "opus"},
        {"id": "thought_level", "category": "thought_level", "currentValue": "high"},
    ]
}
