"""Bounded rich Python results and atomic export of kernel-owned artifacts."""

from __future__ import annotations

import base64
from collections import OrderedDict
from itertools import islice
import io
import json
import os
from pathlib import Path
import sys
import uuid

from .values import scalar

MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_ARTIFACTS = 64
MAX_RETAINED_BYTES = 32 * 1024 * 1024
MAX_EXECUTION_ARTIFACTS = 8


def json_preview(value, depth=0, budget=None, seen=None):
    """Preserve useful JSON structure without traversing unbounded containers."""
    budget = [10000] if budget is None else budget
    seen = set() if seen is None else seen
    budget[0] -= 1
    if budget[0] < 0 or depth > 16:
        return "[DataPyn: preview truncated]"
    if isinstance(value, (dict, list, tuple)):
        if id(value) in seen:
            return "[circular reference]"
        seen.add(id(value))
        try:
            if isinstance(value, dict):
                result = {str(key)[:1000]: json_preview(item, depth + 1, budget, seen)
                          for key, item in islice(value.items(), 1000)}
                if len(value) > 1000:
                    result["…"] = f"{len(value) - 1000} more entries"
                return result
            result = [json_preview(item, depth + 1, budget, seen) for item in islice(value, 1000)]
            if len(value) > 1000:
                result.append(f"[DataPyn: {len(value) - 1000} more entries]")
            return result
        finally:
            seen.remove(id(value))
    result = scalar(value)
    return result[:8192] if isinstance(result, str) else result


class RichOutputs:
    def __init__(self):
        self.artifacts = OrderedDict()
        self.total_bytes = 0
        self.outputs = []

    def begin(self):
        self.outputs = []

    def add(self, output):
        if len(self.outputs) >= MAX_EXECUTION_ARTIFACTS:
            return False
        size = len(json.dumps(output, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if size > MAX_ARTIFACT_BYTES:
            return False
        while self.artifacts and (len(self.artifacts) >= MAX_ARTIFACTS or self.total_bytes + size > MAX_RETAINED_BYTES):
            _identifier, (_old, old_size) = self.artifacts.popitem(last=False)
            self.total_bytes -= old_size
        output = {**output, "artifact_id": uuid.uuid4().hex}
        self.artifacts[output["artifact_id"]] = (output, size)
        self.total_bytes += size
        self.outputs.append(output)
        return True

    def image(self, data):
        if isinstance(data, str):
            data = base64.b64decode(data, validate=True)
        if not isinstance(data, bytes) or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return False
        return self.add({"type": "image", "mime": "image/png", "data": base64.b64encode(data).decode("ascii")})

    def capture(self, value):
        if value is None:
            return False
        module, name = type(value).__module__, type(value).__name__
        if module.startswith("plotly.") and hasattr(value, "to_json"):
            encoded = value.to_json()
            if len(encoded.encode("utf-8")) <= MAX_ARTIFACT_BYTES:
                return self.add({"type": "plotly", "data": json.loads(encoded)})
            return False
        if module.startswith("matplotlib.") and name == "Figure":
            plt = sys.modules.get("matplotlib.pyplot")
            if plt is not None and getattr(value, "number", None) in plt.get_fignums():
                return True  # The normal figure collector captures it once.
            buffer = io.BytesIO()
            value.savefig(buffer, format="png", dpi=120, bbox_inches="tight")
            return self.image(buffer.getvalue())
        if module.startswith("PIL.") and hasattr(value, "save"):
            buffer = io.BytesIO()
            value.save(buffer, format="PNG")
            return self.image(buffer.getvalue())
        for method, kind in (("_repr_png_", "image"), ("_repr_html_", "html"), ("_repr_json_", "json")):
            representation = getattr(value, method, None)
            if callable(representation):
                try:
                    data = representation()
                    if isinstance(data, tuple):
                        data = data[0]
                    if kind == "image" and data and self.image(data):
                        return True
                    if kind == "html" and isinstance(data, str) and self.add({"type": kind, "data": data}):
                        return True
                    if kind == "json" and self.add({"type": kind, "data": json_preview(data)}):
                        return True
                except Exception:
                    continue
        if isinstance(value, (dict, list)) and value:
            return self.add({"type": "json", "data": json_preview(value)})
        return False

    def display(self, *values, **options):
        for value in values:
            if not self.capture(value):
                print(value)

    def write(self, params):
        identifier = params.get("artifact_id")
        if identifier not in self.artifacts:
            raise KeyError("Artifact is unavailable; its kernel may have restarted")
        artifact = self.artifacts[identifier][0]
        export_format = params.get("format") or {"image": "png", "html": "html", "json": "json", "plotly": "html"}[artifact["type"]]
        if not isinstance(params.get("path"), str) or not params["path"].strip():
            raise ValueError("Choose an artifact destination")
        path = Path(params["path"]).expanduser().resolve()
        if not path.parent.is_dir() or path.is_dir():
            raise ValueError("Choose a file inside an existing directory")
        if path.suffix.lower() != "." + export_format:
            raise ValueError(f"Choose a .{export_format} destination")
        if artifact["type"] == "image" and export_format == "png":
            data = base64.b64decode(artifact["data"], validate=True)
        elif artifact["type"] == "html" and export_format == "html":
            data = artifact["data"].encode("utf-8")
        elif artifact["type"] in {"json", "plotly"} and export_format == "json":
            data = json.dumps(artifact["data"], ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
        elif artifact["type"] == "plotly" and export_format == "html":
            from plotly.io import to_html
            data = to_html(artifact["data"], include_plotlyjs=True, full_html=True).encode("utf-8")
        else:
            raise ValueError("Choose an export format supported by this artifact")
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"path": str(path), "bytes": len(data), "format": export_format}
