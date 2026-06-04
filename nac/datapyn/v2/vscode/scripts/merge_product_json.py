#!/usr/bin/env python3
"""Merge DataPyn keys into vscode checkout product.json (shallow overlay)."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for key, value in overlay.items():
        if key == "builtInExtensions" and key in out and isinstance(out[key], list):
            existing = {e.get("name") for e in out[key] if isinstance(e, dict)}
            merged = list(out[key])
            for entry in value:
                if isinstance(entry, dict) and entry.get("name") not in existing:
                    merged.append(entry)
            out[key] = merged
        else:
            out[key] = value
    return out


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: merge_product_json.py <overlay.json> <checkout/product.json>", file=sys.stderr)
        sys.exit(1)
    overlay_path = Path(sys.argv[1])
    target_path = Path(sys.argv[2])
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    base = json.loads(target_path.read_text(encoding="utf-8"))
    merged = merge(base, overlay)
    target_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[datapyn-v2] Updated {target_path}")


if __name__ == "__main__":
    main()
