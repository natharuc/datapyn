"""Notification templates/rules and explicit transport actions without Qt."""

from __future__ import annotations

from copy import deepcopy
from email.message import EmailMessage
import hashlib
import json
import os
from pathlib import Path
import re
import smtplib
import ssl

from .data_tools import atomic_destination
from .values import preview, scalar

METHODS = frozenset({"notifications.settings.get", "notifications.settings.set", "notifications.evaluate",
                     "notifications.send", "notifications.test"})
DEFAULTS = {"enabled": True, "sound": True, "success_title": "{{type}}", "success_message": "Concluído! {{rows}} linhas retornadas",
            "error_title": "{{type}}", "error_message": "Erro: {{error}}",
            "telegram": {"enabled": False, "chat_id": ""},
            "email": {"enabled": False, "host": "", "port": 587, "use_tls": True, "use_ssl": False,
                      "username": "", "from_address": "", "to": ""}}
OPERATORS = frozenset({"equals", "not_equals", "contains", "not_contains", "is_empty", "is_not_empty", "greater_than", "less_than"})
SECRET_NAMES = frozenset({"telegram_bot_token", "email_password"})


def _workspace():
    return Path(os.environ.get("DATAPYN_WORKSPACE_PATH", str(Path.home() / ".datapyn-tauri-preview"))).expanduser().resolve()


def _settings_path():
    path = _workspace() / "notifications.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _secret_service():
    return "DataPyn.Tauri.preview.notifications." + hashlib.sha256(str(_workspace()).encode()).hexdigest()[:20]


def secret_get(name):
    if name not in SECRET_NAMES:
        raise ValueError("Unknown notification secret")
    import keyring
    return keyring.get_password(_secret_service(), name) or ""


def secret_set(name, value):
    if name not in SECRET_NAMES or not isinstance(value, str):
        raise ValueError("Invalid notification secret")
    import keyring
    try:
        if value:
            keyring.set_password(_secret_service(), name, value)
        else:
            try:
                keyring.delete_password(_secret_service(), name)
            except keyring.errors.PasswordDeleteError:
                pass
    except Exception as error:
        raise RuntimeError("The OS credential store could not save the notification secret") from error


def _normalize_settings(value):
    if not isinstance(value, dict):
        raise ValueError("Notification settings must be an object")
    settings = deepcopy(DEFAULTS)
    for key in ("enabled", "sound"):
        settings[key] = bool(value.get(key, settings[key]))
    for key in ("success_title", "success_message", "error_title", "error_message"):
        settings[key] = str(value.get(key, settings[key]))[:4000]
    for channel in ("telegram", "email"):
        incoming = value.get(channel) or {}
        if not isinstance(incoming, dict):
            raise ValueError(f"{channel} settings must be an object")
        for key, default in settings[channel].items():
            item = incoming.get(key, default)
            settings[channel][key] = bool(item) if isinstance(default, bool) else str(item).strip() if isinstance(default, str) else item
    port = settings["email"]["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("SMTP port must be between 1 and 65535")
    if settings["email"]["use_tls"] and settings["email"]["use_ssl"]:
        raise ValueError("Choose STARTTLS or SSL, not both")
    return settings


def _load_settings():
    path = _settings_path()
    return _normalize_settings(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})


def settings_get(params=None):
    settings = _load_settings()
    errors = []
    credentials = {}
    for name in SECRET_NAMES:
        try:
            credentials[name] = bool(secret_get(name))
        except Exception:
            credentials[name] = False
            errors.append("The OS credential store is unavailable")
    settings["telegram"]["configured"] = bool(settings["telegram"]["chat_id"] and credentials["telegram_bot_token"])
    email = settings["email"]
    email["configured"] = bool(email["host"] and email["from_address"] and _recipients(email["to"]) and (not email["username"] or credentials["email_password"]))
    return {"settings": settings, "secrets_present": credentials, "credential_error": errors[0] if errors else None}


def settings_set(params):
    settings = _normalize_settings(params.get("settings") or {})
    for name, value in (params.get("secrets") or {}).items():
        secret_set(name, value)
    path = _settings_path()
    with atomic_destination(path) as temporary:
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings_get()


def normalize_config(config):
    if not config:
        return None
    if not isinstance(config, dict):
        raise ValueError("Per-session notification config must be an object")
    rules = []
    for rule in config.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        rules.append({"enabled": bool(rule.get("enabled", True)), "left": str(rule.get("left", ""))[:4000],
                      "operator": str(rule.get("operator", "equals")), "value": str(rule.get("value", ""))[:4000],
                      "action": str(rule.get("action", "suppress")), "action_value": str(rule.get("action_value", "#d64545"))})
        if len(rules) >= 100:
            break
    return {**config, "enabled": bool(config.get("enabled", False)), "title": str(config.get("title", "{{tab_name}}"))[:4000],
            "message": str(config.get("message", "{{rows}} linhas"))[:4000], "color": str(config.get("color", "#5b8def")), "rules": rules}


def _number(value):
    try:
        return float(str(value).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def rule_matches(left, operator, right):
    left, right = str("" if left is None else left).strip(), str("" if right is None else right).strip()
    operator = (operator or "equals").strip().lower()
    if operator in {"equals", "eq", "=="}:
        return left.casefold() == right.casefold()
    if operator in {"not_equals", "ne", "!=", "not equals"}:
        return left.casefold() != right.casefold()
    if operator in {"contains", "includes"}:
        return right.casefold() in left.casefold()
    if operator in {"not_contains", "does not contain"}:
        return right.casefold() not in left.casefold()
    if operator in {"is_empty", "empty"}:
        return left == ""
    if operator in {"is_not_empty", "not_empty"}:
        return left != ""
    a, b = _number(left), _number(right)
    if a is None or b is None:
        return False
    return a > b if operator in {"greater_than", "gt", ">"} else a < b if operator in {"less_than", "lt", "<"} else False


def render_template(template, context, namespace=None, result=None):
    context, namespace = context or {}, namespace or {}
    def replace(match):
        key = match.group(1).strip()
        result_match = re.fullmatch(r"result\[(\d+)\]\[(\d+)\]", key)
        if result_match:
            row, column = map(int, result_match.groups())
            try:
                if hasattr(result, "iloc"):
                    value = result.iloc[row, column]
                elif hasattr(result, "iter_rows"):
                    value = result[row, column]
                else:
                    value = result[row][column]
                return str(scalar(value))[:2000]
            except (IndexError, TypeError, KeyError):
                return match.group(0)
        if key in context:
            value = context[key]
            if key == "rows" and isinstance(value, int):
                return f"{value:,}"
            return str(value)[:2000]
        if key in namespace and not key.startswith("_"):
            value = namespace[key]
            return str(scalar(value))[:2000] if isinstance(value, (str, int, float, bool, type(None))) else preview(value, 2000)
        return match.group(0)
    return re.sub(r"\{\{([^{}]{1,200})\}\}", replace, str(template or "")[:4000])[:4000]


def evaluate(params, namespace=None, store=None, *, _loaded=None):
    loaded = _loaded if _loaded is not None else settings_get()
    settings = loaded["settings"]
    context = params.get("context") or {}
    success = bool(context.get("success", True))
    config = normalize_config(params.get("config"))
    custom = bool(config and config["enabled"])
    result = None
    if store is not None:
        if "_completion_result_id" in params:
            result_id = params["_completion_result_id"]
            result = store.frames.get(result_id) if result_id else None
        else:
            result_id = context.get("result_id") or params.get("result_id")
            result = store.frames.get(result_id) if result_id else next(reversed(store.frames.values()), None)
    render = lambda template: render_template(template, context, namespace, result)
    title = render(config["title"] if custom else settings["success_title" if success else "error_title"])
    message = render(config["message"] if custom else settings["success_message" if success else "error_message"])
    color, suppressed, matched = (config["color"] if custom else None), False, []
    if custom:
        for index, rule in enumerate(config["rules"]):
            if not rule["enabled"] or not rule_matches(render(rule["left"]), rule["operator"], render(rule["value"])):
                continue
            matched.append(index)
            if rule["action"] == "set_color" and rule["action_value"]:
                color = rule["action_value"]
            elif rule["action"] == "suppress":
                suppressed = True
                break
    configured_channels = config.get("channels", {}) if custom else {}
    channels = {name: bool(settings[name]["enabled"] and settings[name]["configured"] and configured_channels.get(name, True)) for name in ("telegram", "email")}
    return {"title": title, "message": message, "success": success, "color": color, "suppressed": suppressed,
            "is_tab_custom": custom, "matched_rules": matched, "enabled": settings["enabled"], "sound": settings["sound"],
            "send_external": bool(custom and not suppressed and settings["enabled"]), "channels": channels}


def _recipients(value):
    return [item.strip() for item in str(value).replace(";", ",").split(",") if item.strip()]


def deliver(channel, settings, notification, secrets=None):
    """Called only by notifications.send/test; errors never include credentials."""
    if channel == "telegram":
        import requests
        token = secrets.get("telegram_bot_token", "") if secrets is not None else secret_get("telegram_bot_token")
        if not token or not settings["telegram"]["chat_id"]:
            raise ValueError("Configure Telegram token and chat ID first")
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                 json={"chat_id": settings["telegram"]["chat_id"],
                                       "text": "\n".join(part for part in (notification["title"], notification["message"]) if part)[:4096]}, timeout=15)
        response.raise_for_status()
        if not response.json().get("ok"):
            raise RuntimeError("Telegram rejected the notification")
    elif channel == "email":
        config = settings["email"]
        message = EmailMessage()
        message["Subject"] = notification["title"] or "DataPyn"
        message["From"] = config["from_address"]
        message["To"] = ", ".join(_recipients(config["to"]))
        message.set_content(("Sucesso" if notification["success"] else "Erro") + "\n\n" + notification["message"])
        factory = smtplib.SMTP_SSL if config["use_ssl"] else smtplib.SMTP
        kwargs = {"timeout": 15, **({"context": ssl.create_default_context()} if config["use_ssl"] else {})}
        with factory(config["host"], config["port"], **kwargs) as server:
            if config["use_tls"] and not config["use_ssl"]:
                server.starttls(context=ssl.create_default_context())
            if config["username"]:
                password = secrets.get("email_password", "") if secrets is not None else secret_get("email_password")
                server.login(config["username"], password)
            server.send_message(message)
    else:
        raise ValueError("Choose telegram or email")


def prepare(params, namespace=None, store=None, *, _loaded=None):
    """Resolve the namespace in the kernel; deliver its result on the broker.

    This is an internal IPC payload, never a frontend RPC response or an event.
    Captured secrets must stay in memory and must not appear in logs/files.
    Capturing the settings and credentials together prevents a later workspace
    switch from selecting another profile's recipients or credential entries.
    """
    loaded = _loaded if _loaded is not None else settings_get()
    notification = evaluate(params, namespace, store, _loaded=loaded)
    secrets, errors = {}, {}
    if notification["send_external"]:
        for channel, enabled in notification["channels"].items():
            if enabled:
                try:
                    name = "telegram_bot_token" if channel == "telegram" else "email_password"
                    secrets[name] = secret_get(name)
                except Exception as error:
                    errors[channel] = {"status": "failed", "error": f"{type(error).__name__}: credential store unavailable"}
    return {"version": 1, "notification": notification, "_settings": deepcopy(loaded["settings"]),
            "_secrets": secrets, "_errors": errors}


def capture_completion(params, finished, namespace=None, store=None, *, connection_context=None):
    """Freeze only rendered text/rules for this execution before its next job.

    Credentials remain internal, and transport work runs on the broker. Local
    and suppressed notifications do not query the OS credential store at all.
    Notification failures must never change execution results or their status.
    """
    specification = params.get("notification")
    status = finished["status"]
    if specification is None:
        return None
    try:
        if status == "succeeded" and not specification.get("emit_notification", True):
            return None
        context = deepcopy(specification.get("context") or {})
        if connection_context is not None:
            context.update(connection_context)
        results = finished.get("results") or []
        result = results[-1] if results and status == "succeeded" else None
        if result is None and status == "succeeded" and "export" not in finished and store is not None:
            queue_result = specification.get("queue_result") or {}
            result_id = queue_result.get("result_id")
            if isinstance(result_id, str) and result_id in store.frames:
                # Only the exact result explicitly supplied by this queue is
                # eligible, never the latest unrelated frame in the session.
                result = store.descriptors.get(result_id)
        context.update({
            "session_id": finished["session_id"], "execution_id": finished["execution_id"],
            "success": status == "succeeded", "status": status, "type": params["language"],
            "error": "Execução cancelada." if status == "cancelled" else finished.get("error", ""),
            "rows": result["row_count"] if result else (finished.get("export") or {}).get("total_rows", 0) if status == "succeeded" else 0,
            "result_id": result["result_id"] if result else None,
        })
        config = normalize_config(specification.get("config"))
        settings = _load_settings()
        # Destination checks are enough to determine whether local rendering
        # needs credentials. The external path then uses the existing exact
        # settings/credential snapshot, including profile isolation.
        settings["telegram"]["configured"] = bool(settings["telegram"]["chat_id"])
        email = settings["email"]
        email["configured"] = bool(email["host"] and email["from_address"] and _recipients(email["to"]))
        # The legacy preview/send operation can use its most recent frame.
        # Completion rendering must explicitly select only this execution's
        # frame, including its absence, without changing that legacy behavior.
        rendered_params = {"config": config, "context": context, "_completion_result_id": context["result_id"]}
        preliminary = evaluate(rendered_params, namespace, store, _loaded={"settings": settings})
        if preliminary["send_external"] and any(preliminary["channels"].values()):
            prepared = prepare(rendered_params, namespace, store)
        else:
            prepared = {"version": 1, "notification": preliminary, "_settings": deepcopy(settings), "_secrets": {}, "_errors": {}}
        if status == "cancelled" and not (config and config["enabled"]):
            # Preserve configured templates, but the normal cancellation is
            # a clear status rather than an execution error notification.
            if prepared["_settings"]["error_title"] == DEFAULTS["error_title"]:
                prepared["notification"]["title"] = "Execução cancelada"
            if prepared["_settings"]["error_message"] == DEFAULTS["error_message"]:
                prepared["notification"]["message"] = "Execução cancelada."
        prepared["notification"]["status"] = status
        prepared["_completion_context"] = {key: context.get(key) for key in ("session_id", "execution_id", "block_id", "workspace_id")}
        finished["notification"] = deepcopy(prepared["notification"])
        return prepared
    except Exception as error:
        finished["notification_error"] = f"{type(error).__name__}: notification evaluation failed"
        return None


def deliver_prepared(payload):
    """Run only on a broker background worker; return a secret-free response."""
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Invalid internal notification payload")
    notification = payload["notification"]
    statuses = dict(payload.get("_errors") or {})
    secrets = payload.get("_secrets") or {}
    try:
        if notification["send_external"]:
            for channel, enabled in notification["channels"].items():
                if enabled and channel not in statuses:
                    try:
                        deliver(channel, payload["_settings"], notification, secrets)
                        statuses[channel] = {"status": "sent"}
                    except Exception as error:
                        statuses[channel] = {"status": "failed", "error": f"{type(error).__name__}: notification delivery failed"}
        return {**notification, "deliveries": statuses}
    finally:
        secrets.clear()
        payload.pop("_secrets", None)


def send(params, namespace=None, store=None):
    return deliver_prepared(prepare(params, namespace, store))


def test_send(params):
    channel = params.get("channel")
    if channel not in {"telegram", "email"}:
        raise ValueError("Choose telegram or email")
    settings = settings_get()["settings"]
    if not settings[channel]["configured"]:
        raise ValueError(f"Configure {channel} and save settings before sending a test")
    try:
        deliver(channel, settings, {"title": "DataPyn · teste", "message": "Teste de notificação solicitado no aplicativo.", "success": True})
    except Exception as error:
        raise RuntimeError(f"{type(error).__name__}: notification test delivery failed") from None
    return {"channel": channel, "status": "sent"}


def dispatch(method, params, namespace=None, store=None):
    if method == "notifications.settings.get":
        return settings_get(params)
    if method == "notifications.settings.set":
        return settings_set(params)
    if method == "notifications.evaluate":
        return evaluate(params, namespace, store)
    if method == "notifications.send":
        return send(params, namespace, store)
    if method == "notifications.test":
        return test_send(params)
    raise ValueError(f"Unknown notification operation: {method}")
