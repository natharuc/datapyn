"""Opt-in, bounded, content-free desktop diagnostics over an HTTPS connector.

No database/user identifiers, SQL, exception text, paths or result values enter
the queue. Telemetry has its own daemon; database and IPC threads never do I/O.
"""
from __future__ import annotations

from collections import deque
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler
import ssl

from .data_tools import atomic_destination
from .paths import state_root

DEFAULT_ENDPOINT = "https://telemetry.datapyn.com/v1/events"
EVENTS = {"app_start", "execution_finished", "connection_recovery", "runtime_error", "ui_error"}
DATABASES = {"sqlserver", "postgresql", "mysql", "mariadb", "databricks", "sqlite", "none"}
STATUSES = {"started", "succeeded", "failed", "cancelled", "recovering", "ready", "error", "blocked"}
ERRORS = {"none", "transport", "timeout", "authentication", "syntax", "cancelled", "unknown"}
ROW_BUCKETS = {"none", "0", "1-100", "101-10000", "10001-1000000", "1000000+"}
MAX_QUEUE = 256
BATCH_SIZE = 50
MAX_AGE = 24 * 3600
MAX_ATTEMPTS = 3


def endpoint_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) <= 32 for char in value):
        raise ValueError("Informe um endpoint HTTPS válido para telemetria.")
    parsed = urlsplit(value)
    try:
        hostname = (parsed.hostname or "").encode("idna").decode("ascii").rstrip(".").lower()
    except UnicodeError as error:
        raise ValueError("Informe um domínio HTTPS válido para telemetria.") from error
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or hostname == "localhost"
            or hostname.endswith((".localhost", ".local"))):
        raise ValueError("O endpoint deve usar HTTPS, sem credenciais, parâmetros ou fragmentos.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        # Reject legacy abbreviated/octal/hexadecimal IPv4 spellings rather
        # than letting the resolver reinterpret them as loopback addresses.
        if "." not in hostname or re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|\d+)(?:\.(?:0[xX][0-9a-fA-F]+|\d+))*", hostname):
            raise ValueError("O endpoint deve usar um domínio público HTTPS.")
    else:
        if not address.is_global:
            raise ValueError("O endpoint deve usar um endereço público HTTPS.")
    try:
        if parsed.port not in (None, 443):
            raise ValueError("Use a porta HTTPS padrão para telemetria.")
    except ValueError as error:
        raise ValueError("Use a porta HTTPS padrão para telemetria.") from error
    return value


def settings_path():
    return state_root() / "telemetry_settings.json"


def settings_get(path=None):
    file = Path(path) if path is not None else settings_path()
    defaults = {"enabled": False, "endpoint": DEFAULT_ENDPOINT, "provider": "cloudflare"}
    if not file.is_file():
        return defaults
    if file.stat().st_size > 4096:
        raise ValueError("Telemetry settings exceed 4 KiB")
    value = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
        raise ValueError("enabled must be a boolean")
    return {**defaults, "enabled": value["enabled"], "endpoint": endpoint_url(value.get("endpoint", DEFAULT_ENDPOINT))}


def settings_set(params, path=None):
    if not isinstance(params, dict) or not isinstance(params.get("enabled"), bool):
        raise ValueError("enabled must be a boolean")
    value = {"enabled": params["enabled"], "endpoint": endpoint_url(params.get("endpoint", DEFAULT_ENDPOINT)), "provider": "cloudflare"}
    file = Path(path) if path is not None else settings_path()
    file.parent.mkdir(parents=True, exist_ok=True)
    with atomic_destination(file) as temporary:
        temporary.write_text(json.dumps(value), encoding="utf-8")
    return value


def _choice(value, choices, fallback):
    return value if isinstance(value, str) and value in choices else fallback


def _number(value, maximum, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    value = max(0, min(maximum, value))
    return int(value) if integer else round(value, 3)


def _rows_bucket(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return "none"
    if value == 0:
        return "0"
    return "1-100" if value <= 100 else "101-10000" if value <= 10_000 else "10001-1000000" if value <= 1_000_000 else "1000000+"


def safe_event(params, *, version="dev", platform=None):
    """Construct from a whitelist; never regex-redact raw application payloads."""
    if not isinstance(params, dict) or not isinstance(params.get("event"), str) or params["event"] not in EVENTS:
        return None
    platform = platform or {"win32": "windows", "darwin": "macos", "linux": "linux"}.get(sys.platform, "other")
    version = version if isinstance(version, str) and re.fullmatch(r"(?:\d{1,3}\.\d{1,3}\.\d{1,3}|dev)", version) else "dev"
    return {"event": params["event"], "version": version,
            "platform": _choice(platform, {"windows", "macos", "linux", "other"}, "other"),
            "db_type": _choice(params.get("db_type"), DATABASES, "none"),
            "status": _choice(params.get("status"), STATUSES, "error"),
            "error_code": _choice(params.get("error_code"), ERRORS, "unknown"),
            "duration_ms": _number(params.get("duration_ms"), 86_400_000),
            "attempt": _number(params.get("attempt"), 10, integer=True),
            "rows_bucket": _choice(params.get("rows_bucket"), ROW_BUCKETS, "none")}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A changed collector cannot silently redirect diagnostic data elsewhere.
        return None


class HTTPSConnector:
    def __call__(self, endpoint, events):
        payload = json.dumps({"schema_version": 1, "events": events}, separators=(",", ":")).encode("utf-8")
        if len(payload) > 32_768:
            raise ValueError("Telemetry batch exceeds 32 KiB")
        request = Request(endpoint_url(endpoint), data=payload, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": "DataPyn-Telemetry/1"})
        opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(request, timeout=3) as response:
            if response.status not in (200, 202, 204):
                raise OSError("Collector did not accept the batch")


class TelemetryService:
    def __init__(self, path=None, *, sender=None, clock=time.monotonic, interval=30):
        self.path = path
        self._clock, self._interval = clock, interval
        self._sender = sender or HTTPSConnector()
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = False
        self._thread = None
        self._queue = deque()
        self._generation = 0
        self._sent = self._dropped = 0
        self._last_status = "disabled"
        self._failures = 0
        self._version = os.environ.get("DATAPYN_TAURI_VERSION", "dev")
        try:
            self._settings = settings_get(path)
        except Exception:
            # Corrupt consent must fail closed, without blocking app startup.
            self._settings = {"enabled": False, "endpoint": DEFAULT_ENDPOINT, "provider": "cloudflare"}
        if self._settings["enabled"]:
            self._last_status = "idle"
            self._start()

    def _start(self):
        if self._thread is None and not self._closed:
            try:
                self._thread = threading.Thread(target=self._loop, name="datapyn-telemetry", daemon=True)
                self._thread.start()
            except Exception:
                self._thread = None
                self._last_status = "unavailable"

    def client_info(self, params):
        with self._lock:
            version = params.get("version") if isinstance(params, dict) else None
            if not os.environ.get("DATAPYN_TAURI_VERSION") and isinstance(version, str) and re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", version):
                self._version = version
        self.record({"event": "app_start", "status": "started", "error_code": "none"})
        return {"accepted": True}

    def status(self):
        with self._lock:
            return {**self._settings, "queued": len(self._queue), "sent": self._sent,
                    "dropped": self._dropped, "last_status": self._last_status}

    def configure(self, params):
        configured = settings_set(params, self.path)
        with self._lock:
            self._generation += 1
            # Consent/endpoint transitions never send a previous queue to a new target.
            self._queue.clear()
            self._settings = configured
            self._last_status = "idle" if configured["enabled"] else "disabled"
            self._failures = 0
            if configured["enabled"]:
                self._start()
            self._wake.set()
        return self.status()

    def record(self, params):
        if not self._settings["enabled"] or self._closed:
            return {"accepted": False}
        with self._lock:
            generation, version = self._generation, self._version
        event = safe_event(params, version=version)
        if event is None:
            return {"accepted": False}
        with self._lock:
            if generation != self._generation or not self._settings["enabled"] or self._closed:
                return {"accepted": False}
            while len(self._queue) >= MAX_QUEUE:
                self._queue.popleft()
                self._dropped += 1
            self._queue.append({"event": event, "time": self._clock(), "attempts": 0})
        return {"accepted": True}

    def observe(self, message):
        try:
            self._observe(message)
        except Exception:
            # Observers are optional: no malformed metric or diagnostics bug
            # may withhold a query's completion/IPC response from its user.
            return

    def _observe(self, message):
        if not self._settings["enabled"] or not isinstance(message, dict):
            return
        event, payload = message.get("event"), message.get("payload")
        if not isinstance(event, str) or not isinstance(payload, dict):
            return
        if event == "execution.finished":
            status = payload.get("status")
            results = payload.get("results")
            results = results if isinstance(results, list) else []
            self.record({"event": "execution_finished", "status": status, "db_type": payload.get("db_type"),
                         "duration_ms": payload.get("duration_ms"), "rows_bucket": _rows_bucket(sum(
                             result.get("row_count", 0) for result in results[:1000]
                             if isinstance(result, dict) and isinstance(result.get("row_count"), int) and not isinstance(result["row_count"], bool))),
                         "error_code": "transport" if payload.get("connection_lost") else "cancelled" if status == "cancelled" else "unknown" if status == "failed" else "none"})
        elif event == "connection.recovery":
            self.record({"event": "connection_recovery", "status": payload.get("phase"), "db_type": payload.get("db_type"),
                         "attempt": payload.get("attempt"), "duration_ms": payload.get("duration_ms"),
                         "error_code": "transport" if payload.get("phase") in {"error", "blocked"} else "none"})
        elif event in {"session.error", "backend.exited", "session.reset"}:
            self.record({"event": "runtime_error", "status": "error", "error_code": "unknown"})

    def flush_once(self):
        """One bounded attempt; only the diagnostics daemon calls this in production."""
        if not self._send_lock.acquire(blocking=False):
            return
        try:
            with self._lock:
                if self._closed or not self._settings["enabled"]:
                    return
                now = self._clock()
                while self._queue and now - self._queue[0]["time"] > MAX_AGE:
                    self._queue.popleft()
                    self._dropped += 1
                batch = [self._queue.popleft() for _ in range(min(BATCH_SIZE, len(self._queue))) ]
                if not batch:
                    return
                generation, endpoint = self._generation, self._settings["endpoint"]
                self._last_status = "sending"
            try:
                self._sender(endpoint, [item["event"] for item in batch])
                success = True
            except Exception:
                # Do not store remote bodies, URLs or exception messages.
                success = False
            with self._lock:
                if generation != self._generation or self._closed:
                    return
                self._last_status = "sent" if success else "offline"
                self._failures = 0 if success else min(self._failures + 1, 4)
                if success:
                    self._sent += len(batch)
                else:
                    retry = []
                    for item in batch:
                        item["attempts"] += 1
                        if item["attempts"] < MAX_ATTEMPTS:
                            retry.append(item)
                        else:
                            self._dropped += 1
                    self._queue.extendleft(reversed(retry))
                    while len(self._queue) > MAX_QUEUE:
                        self._queue.popleft()
                        self._dropped += 1
        finally:
            self._send_lock.release()

    def _loop(self):
        while not self._closed:
            self._wake.wait(self._interval * 2 ** self._failures)
            self._wake.clear()
            if not self._closed:
                self.flush_once()

    def close(self):
        # Never flush network on application exit or wait for an offline collector.
        with self._lock:
            self._closed = True
            self._queue.clear()
            self._generation += 1
            self._wake.set()
