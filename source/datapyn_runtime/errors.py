"""Protocol error envelopes shared by isolated runtime workers."""

from __future__ import annotations

from .connection_catalog import without_secrets


def serialize_runtime_error(error, *, default_code="operation_failed"):
    """Keep actionable SSH trust challenges across IPC without exposing secrets."""
    code = getattr(error, "code", None)
    if not isinstance(code, str):
        code = default_code
    result = {"code": code, "message": f"{type(error).__name__}: {error}"}
    details = getattr(error, "details", None)
    if code.startswith("ssh_") and isinstance(details, dict):
        # Only the server's public identity belongs in a trust confirmation.
        fields = {"host", "port", "key_type", "public_key", "fingerprint", "expected_fingerprint"}
        result["details"] = without_secrets({key: value for key, value in details.items() if key in fields})
    return result
