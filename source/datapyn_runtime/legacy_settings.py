"""The public Qt INI/shortcut representations, without importing Qt.

Opaque Qt variants and unknown lines are retained verbatim. Only the scalar
keys whose legacy readers are known are interpreted or changed.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

SHORTCUT_ACTIONS = {
    "execute_sql": "run", "execute_all": "runAll", "execute_block_advance": "runAdvance",
    "clear_results": "clearResults", "open_file": "open", "save_file": "save", "save_as": "saveAs",
    "export_script": "exportScript", "new_tab": "newTab", "new_session": "newSession", "close_tab": "closeSession",
    "add_block": "addBlock", "find": "find", "replace": "replace", "format_code": "formatCode",
    "show_entity_info": "entityInfo", "force_autocomplete": "autocomplete", "manage_connections": "manageConnections",
    "new_connection": "newConnection", "reload_schema": "reloadSchema", "settings": "settings",
    "copy_with_headers": "copyHeaders", "exit_app": "exit", "restore_view": "restoreView", "reset_layout": "resetLayout",
    "editor_newline": "editorNewline", "editor_duplicate_line": "editorDuplicateLine", "editor_cut_line": "editorCutLine",
    "editor_transpose_line": "editorTransposeLine", "editor_lowercase": "editorLowercase", "editor_uppercase": "editorUppercase",
    "editor_delete_line": "editorDeleteLine",
}

# Defaults are copied from ShortcutManager.DEFAULT_SHORTCUTS, verified against
# the real manager in the interoperability tests.
SHORTCUT_DEFAULTS = dict(zip(SHORTCUT_ACTIONS, (
    "F5", "Ctrl+F5", "Shift+Return", "Ctrl+Shift+L", "Ctrl+O", "Ctrl+S", "Ctrl+Shift+S", "Ctrl+Shift+E",
    "Ctrl+T", "Ctrl+N", "Ctrl+W", "Ctrl+Shift+B", "Ctrl+F", "Ctrl+H", "Ctrl+Shift+F", "Alt+F1", "Ctrl+.",
    "Ctrl+Shift+M", "Ctrl+Shift+D", "Ctrl+Shift+T", "Ctrl+,", "Ctrl+Shift+C", "Ctrl+Q", "Ctrl+Shift+R",
    "Ctrl+Shift+Alt+R", "", "Ctrl+D", "Ctrl+L", "", "Ctrl+U", "Ctrl+Shift+U", "Ctrl+Shift+K",
)))

PREFERENCE_KEYS = {
    "language": ("locale", str), "grid/display_row_limit": ("displayRowLimit", int),
    "connections/idle_timeout_sec": ("connectionIdleSeconds", int), "editor/maximize_first_block": ("maximizeFirstBlock", bool),
    "editor/code_font_size": ("editorFontSize", int), "results/grid_font_size": ("gridFontSize", int),
    "notifications/enabled": ("notifications", bool), "notifications/sound": ("notificationSound", bool),
    "parameters/shared_delimiter": ("sharedDelimiter", str),
}
SECRET_INI_KEYS = {"password", "token", "access_token", "client_secret", "telegram_bot_token", "email_password",
                   "notifications/telegram/bot_token", "notifications/email/password", "sources_v2"}


def _name(value):
    value = re.sub(r"%U([0-9a-fA-F]{4})", lambda match: chr(int(match[1], 16)), value)
    return unquote(value).replace("\\", "/")


def _line_key(line, section):
    text = line.decode("utf-8", errors="surrogateescape").strip()
    if not text or text.startswith((";", "#")) or "=" not in text:
        return None
    key = _name(text.split("=", 1)[0].strip())
    return f"{section}/{key}" if section else key


def _sections(lines):
    section = ""
    for index, line in enumerate(lines):
        text = line.decode("utf-8", errors="surrogateescape").strip().lstrip("\ufeff")
        if text.startswith("[") and text.endswith("]"):
            value = text[1:-1]
            section = "" if value == "General" else "General" if value == "%General" else _name(value)
        yield index, line, section, _line_key(line, section)


def scalar_value(raw):
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    # QVariant/QByteArray/QRect/etc are never decoded or executed here.
    if value.startswith("@") and not value.startswith("@@"):
        raise ValueError("Opaque Qt value is not a scalar preference")
    if value.startswith("@@"):
        value = value[1:]
    escapes = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "0": "\0"}
    return re.sub(r"\\(?:x([0-9a-fA-F]{1,4})|(.))", lambda match: chr(int(match[1], 16)) if match[1]
                  else escapes.get(match[2], match[2]), value)


def ini_values(raw):
    values = {}
    for _, line, _, key in _sections(raw.splitlines(keepends=True)):
        if key is not None:
            try:
                values[key] = scalar_value(line.decode("utf-8").split("=", 1)[1].rstrip("\r\n"))
            except (ValueError, UnicodeError):
                continue
    return values


def _secret(key):
    return key.lower() in SECRET_INI_KEYS or key.rsplit("/", 1)[-1].lower() in SECRET_INI_KEYS


def strip_ini_secrets(raw):
    return b"".join(line for _, line, _, key in _sections(raw.splitlines(keepends=True)) if key is None or not _secret(key))


def _encode(value):
    if isinstance(value, list):
        return ", ".join(_encode(item) for item in value) if value else "@Invalid()"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text.startswith("@"):
        text = "@" + text
    text = text.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t").replace('"', '\\"')
    if any(char in text for char in ",;=") or text.startswith(" ") or text.endswith(" "):
        text = '"' + text + '"'
    return text


def ini_string_list(raw, key):
    """Decode QStringList/plain scalars, plus Qt's singleton QVariantList.

    Only a bounded list of QString values is accepted from the binary form.
    Other QVariant types stay opaque and are never instantiated.
    """
    value = None
    for _, line, _, name in _sections(raw.splitlines(keepends=True)):
        if name == key:
            value = line.decode("utf-8").split("=", 1)[1].strip()
    if value is None:
        return None
    if value == "@Invalid()":
        return []
    if value.startswith("@Variant(") and value.endswith(")"):
        payload = value[9:-1]
        escapes = {"0": 0, "a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, "\\": 92, '"': 34}
        decoded = bytearray()
        index = 0
        while index < len(payload):
            if payload[index] != "\\":
                decoded.append(ord(payload[index]))
                index += 1
                continue
            index += 1
            if index >= len(payload):
                raise ValueError("Truncated Qt string-list escape")
            if payload[index] == "x":
                match = re.match(r"[0-9a-fA-F]{1,2}", payload[index + 1:])
                if not match:
                    raise ValueError("Invalid Qt string-list byte")
                decoded.append(int(match[0], 16))
                index += 1 + len(match[0])
            else:
                decoded.append(escapes.get(payload[index], ord(payload[index])))
                index += 1
        offset = 0
        def integer():
            nonlocal offset
            if offset + 4 > len(decoded):
                raise ValueError("Truncated Qt string list")
            number = int.from_bytes(decoded[offset:offset + 4], "big")
            offset += 4
            return number
        kind, count = integer(), integer()
        if kind not in {9, 11} or count > 64:
            raise ValueError("Only bounded Qt string lists are supported")
        result = []
        for _ in range(count):
            if kind == 9 and integer() != 10:
                raise ValueError("Only strings are supported in Qt package lists")
            length = integer()
            if length > 32768 or length % 2 or offset + length > len(decoded):
                raise ValueError("Invalid Qt string-list length")
            result.append(bytes(decoded[offset:offset + length]).decode("utf-16-be"))
            offset += length
        if offset != len(decoded):
            raise ValueError("Unexpected bytes in Qt string list")
        return result
    parts, start, quoted, escaped = [], 0, False, False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            parts.append(scalar_value(value[start:index]))
            start = index + 1
    parts.append(scalar_value(value[start:]))
    if quoted or len(parts) > 64:
        raise ValueError("Invalid or oversized Qt string list")
    return parts


def patch_ini(raw, updates):
    """Update known scalars while retaining every other byte, including CRLF."""
    lines = strip_ini_secrets(raw).splitlines(keepends=True)
    pending = dict(updates)
    handled = set()
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    for index, line, _, key in _sections(lines):
        if key in pending:
            prefix = line.split(b"=", 1)[0]
            lines[index] = prefix + b"=" + _encode(pending[key]).encode("utf-8") + newline
            handled.add(key)
    result = b"".join(lines)
    # Additional sections are legal in QSettings INI; repeated sections merge.
    for key, value in pending.items():
        if key in handled:
            continue
        section, _, leaf = key.partition("/")
        if not leaf:
            section, leaf = "General", section
        leaf = leaf.replace("/", "\\")
        if result and not result.endswith((b"\n", b"\r")):
            result += newline
        result += (f"[{section}]".encode() + newline + f"{leaf}={_encode(value)}".encode("utf-8") + newline)
    return result


def typed(value, kind):
    if kind is bool:
        lowered = str(value).lower()
        if lowered not in {"true", "false", "1", "0"}:
            raise ValueError("Invalid boolean preference")
        return lowered in {"true", "1"}
    return kind(value)


def preferences_from_ini(raw):
    values = ini_values(raw)
    result = {}
    for key, (field, kind) in PREFERENCE_KEYS.items():
        if key in values:
            result[field] = typed(values[key], kind)
    if "sharedDelimiter" in result:
        result["sharedDelimiter"] = {"double_brace": "{{name}}", "double_colon": "::name::", "single_brace": "{name}"}.get(
            result["sharedDelimiter"], result["sharedDelimiter"])
    return result


def shortcuts_from_document(document):
    if not isinstance(document, dict):
        raise ValueError("Shortcut settings must be an object")
    incoming = document.get("shortcuts", document)
    if not isinstance(incoming, dict) or any(not isinstance(value, str) for value in incoming.values()):
        raise ValueError("Shortcut sequences must be strings")
    merged = {**SHORTCUT_DEFAULTS, **incoming}
    return {SHORTCUT_ACTIONS[action]: sequence.replace("Return", "Enter") for action, sequence in merged.items() if action in SHORTCUT_ACTIONS}


def shortcuts_to_document(document, shortcuts):
    result = dict(document or {})
    bucket = dict(result.get("shortcuts", result))
    inverse = {value: key for key, value in SHORTCUT_ACTIONS.items()}
    for action, sequence in shortcuts.items():
        if not isinstance(sequence, str):
            raise ValueError("Shortcut sequences must be strings")
        bucket[inverse.get(action, action)] = sequence.replace("Enter", "Return")
    if "shortcuts" in result:
        result["shortcuts"] = bucket
        return result
    return {"shortcuts": bucket}
