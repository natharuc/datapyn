"""An explicit, allowlisted support report without user data or exception text."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import metadata
import json
import platform
import re
import sys
import uuid

from .data_tools import _destination, atomic_destination

METHODS = frozenset({"diagnostics.info", "diagnostics.save"})
PACKAGES = {"pandas": "BSD-3-Clause", "numpy": "BSD-3-Clause", "polars": "MIT", "pyarrow": "Apache-2.0",
            "sqlalchemy": "MIT", "matplotlib": "PSF", "plotly": "MIT", "jedi": "MIT", "ruff": "MIT",
            "sqlparse": "BSD-3-Clause", "sqlglot": "MIT", "openpyxl": "MIT", "fastexcel": "MIT",
            "keyring": "MIT", "pyodbc": "MIT", "psycopg2-binary": "LGPL-3.0-or-later",
            "pymysql": "MIT", "databricks-sql-connector": "Apache-2.0"}
INCIDENTS = frozenset({"react_render", "javascript_error", "unhandled_rejection", "runtime_connection"})
COMPONENTS = frozenset({"app", "editor", "results", "connections", "explorer", "variables", "pynia", "packages", "notifications", "workspace"})


def _version(value):
    if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?", value) and len(value) <= 64:
        return value
    return None


def info(params=None):
    params = params or {}
    application = params.get("application") if isinstance(params.get("application"), dict) else {}
    packages = []
    for name, license_name in PACKAGES.items():
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            version = None
        packages.append({"name": name, "version": version, "license": license_name})
    report = {"report_version": 1, "report_id": uuid.uuid4().hex,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "application": {"name": "DataPyn Desktop", "version": _version(application.get("version")), "license": "MIT", "protocol_version": 1},
              "system": {"os": platform.system(), "os_release": platform.release(), "architecture": platform.machine()},
              "runtime": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                          "qt_loaded": any(name.startswith(("PyQt", "PySide")) for name in sys.modules)},
              "packages": packages}
    incident = params.get("incident")
    if isinstance(incident, dict) and incident.get("kind") in INCIDENTS:
        report["incident"] = {"kind": incident["kind"], "component": incident.get("component") if incident.get("component") in COMPONENTS else "app"}
    return report


def save(params):
    path = _destination(params)
    if path.suffix.lower() != ".json":
        raise ValueError("Choose a .json diagnostics report")
    report = info(params)
    data = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    encoded = data.encode("utf-8")
    with atomic_destination(path) as temporary:
        temporary.write_bytes(encoded)
    return {"path": str(path), "bytes": len(encoded), "report_id": report["report_id"]}


def dispatch(method, params):
    if method == "diagnostics.info":
        return info(params)
    if method == "diagnostics.save":
        return save(params)
    raise ValueError(f"Unknown diagnostics operation: {method}")
