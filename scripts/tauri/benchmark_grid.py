"""Reproducible large-frame paging benchmark; no databases or user state touched."""
from __future__ import annotations

import argparse
import ast
from collections import OrderedDict
import gc
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import ModuleType
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))


def elapsed(call):
    start = time.perf_counter()
    value = call()
    return value, round((time.perf_counter() - start) * 1000, 3)


def benchmark(rows=10_000_000, baseline=None):
    import numpy as np
    import pandas as pd
    import polars as pl
    from datapyn_runtime.result_store import ResultStore
    from datapyn_runtime.values import scalar

    store_class = ResultStore
    original_view = sys.modules.get("datapyn_runtime.frame_view")
    if baseline:
        source = subprocess.check_output(
            ["git", "show", f"{baseline}:source/datapyn_runtime/kernel.py"], cwd=ROOT, text=True,
        )
        definition = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "ResultStore")
        scope = {"__package__": "datapyn_runtime", "OrderedDict": OrderedDict, "uuid": uuid, "json": json, "scalar": scalar,
                 "MAX_RESULT_HANDLES": 64, "MAX_PAGE_ROWS": 1000}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), "baseline-result-store", "exec"), scope)
        store_class = scope["ResultStore"]
        # Use the baseline view implementation too, under identical installed dependencies.
        view_source = subprocess.check_output(
            ["git", "show", f"{baseline}:source/datapyn_runtime/frame_view.py"], cwd=ROOT, text=True,
        )
        baseline_view = ModuleType("datapyn_runtime.frame_view")
        exec(compile(view_source, "baseline-frame-view", "exec"), baseline_view.__dict__)
        sys.modules["datapyn_runtime.frame_view"] = baseline_view

    ids = np.arange(rows, dtype=np.int64)
    frame = pd.DataFrame({"id": ids, "group": ids % 10, **{f"value_{index}": ids + index for index in range(6)}}, copy=False)
    store = store_class(pd, pl)
    descriptor, registration_ms = elapsed(lambda: store.register(frame, "large"))
    params = {"result_id": descriptor["result_id"], "limit": 200, "sort": {"column": "id", "direction": "desc"}}
    if not baseline:
        params.update(column_offset=0, column_limit=2, include_columns=False)
    measurements = []
    try:
        for offset in (0, 200, 400, rows - 200, rows // 2):
            page, timing = elapsed(lambda: store.page({**params, "offset": offset}))
            assert len(page["rows"]) == 200
            assert page["rows"][0][:2] == [rows - 1 - offset, (rows - 1 - offset) % 10]
            measurements.append(timing)
    finally:
        if baseline:
            if original_view is None:
                sys.modules.pop("datapyn_runtime.frame_view", None)
            else:
                sys.modules["datapyn_runtime.frame_view"] = original_view
    cached_bytes = store.view_bytes
    report = {
        "mode": f"baseline:{baseline}" if baseline else "current", "rows": rows, "columns": 8,
        "frame_bytes": int(frame.memory_usage(index=True, deep=False).sum()),
        "register_ms": registration_ms, "sort_cold_ms": measurements[0],
        "sort_cached_median_ms": round(statistics.median(measurements[1:]), 3),
        "page_times_ms": measurements, "cached_view_bytes": int(cached_bytes),
        "page_cells": sum(len(row) for row in page["rows"]),
        "page_json_bytes": len(json.dumps(page, ensure_ascii=False).encode("utf-8")),
    }
    del store, frame
    gc.collect()
    if not baseline:
        native = pl.DataFrame({"id": pl.Series(ids), "group": pl.Series(ids % 10)})
        store = store_class(pd, pl)
        ref, timing = elapsed(lambda: store.register(native, "native"))
        assert store.frames[ref["result_id"]] is native
        page, page_ms = elapsed(lambda: store.page({"result_id": ref["result_id"], "offset": rows - 200,
                                                    "limit": 200, "column_offset": 1, "column_limit": 1, "include_columns": False}))
        assert page["rows"][0] == [(rows - 200) % 10]
        report["polars"] = {"register_ms": timing, "last_page_ms": page_ms, "retained_native": True}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10_000_000)
    parser.add_argument("--baseline", help="Git ref containing the pre-optimization ResultStore")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.rows < 400:
        parser.error("--rows must be at least 400")
    result = benchmark(args.rows, args.baseline)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
