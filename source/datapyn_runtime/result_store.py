"""Opaque frame handles, positional view caches and bounded viewport pages."""

from collections import OrderedDict
import json
import uuid

from .values import scalar

MAX_PAGE_ROWS = 1000
MAX_PAGE_COLUMNS = 256
MAX_RESULT_HANDLES = 64
MAX_VIEW_BYTES = 256 * 1024 * 1024
MAX_CACHED_VIEWS = 64
MAX_PAGE_BYTES = 8 * 1024 * 1024


class ResultStore:
    def __init__(self, pd, pl):
        self.pd, self.pl = pd, pl
        self.frames = OrderedDict()
        self.descriptors = OrderedDict()
        self.views = OrderedDict()
        self._view_failures = OrderedDict()
        self.view_bytes = 0

    def invalidate_views(self):
        self.views.clear()
        self._view_failures.clear()
        self.view_bytes = 0
        for result_id, frame in self.frames.items():
            self.descriptors[result_id].update({"columns": self._columns(frame), "row_count": len(frame)})

    @staticmethod
    def _columns(frame):
        return [{"name": str(column), "dtype": str(dtype)} for column, dtype in zip(frame.columns, frame.dtypes)]

    def release(self, result_id):
        released = self.frames.pop(result_id, None) is not None
        self.descriptors.pop(result_id, None)
        for key in list(self.views):
            if key[0] == result_id:
                _positions, size = self.views.pop(key)
                self.view_bytes -= size
        for key in list(self._view_failures):
            if key[0] == result_id:
                del self._view_failures[key]
        return {"result_id": result_id, "released": released}

    def is_frame(self, value):
        return isinstance(value, (self.pd.DataFrame, self.pl.DataFrame, self.pd.Series, self.pl.Series))

    def register(self, value, variable_name):
        if isinstance(value, (self.pd.Series, self.pl.Series)):
            value = value.to_frame()
        result_id = uuid.uuid4().hex
        self.frames[result_id] = value
        descriptor = {"result_id": result_id, "variable_name": variable_name,
                      "columns": self._columns(value),
                      "row_count": len(value)}
        self.descriptors[result_id] = descriptor
        while len(self.frames) > MAX_RESULT_HANDLES:
            self.release(next(iter(self.frames)))
        return descriptor

    @staticmethod
    def column_label(frame, wire_name):
        from .frame_view import column_label
        return column_label(frame, wire_name)

    def _frame_and_positions(self, params):
        result_id = params["result_id"]
        if result_id not in self.frames:
            raise KeyError("Result is unavailable; it may have been released or the kernel restarted")
        frame = self.frames[result_id]
        filter_spec, sort = params.get("filter") or {}, params.get("sort") or {}
        if not filter_spec and not sort:
            return frame, None
        key = (result_id, frame.shape, json.dumps({"filter": filter_spec, "sort": sort}, sort_keys=True, allow_nan=False))
        if key in self._view_failures:
            self._view_failures.move_to_end(key)
            raise ValueError(self._view_failures[key])
        if key in self.views:
            self.views.move_to_end(key)
            return frame, self.views[key][0]
        from .frame_view import pandas_positions, polars_positions
        positions = polars_positions(frame, params) if isinstance(frame, self.pl.DataFrame) else pandas_positions(frame, params)
        size = positions.nbytes if positions is not None else 0
        if size > MAX_VIEW_BYTES:
            error = "Filtered/sorted row positions exceed the 256 MiB view cache; refine the filter before paging"
            self._view_failures[key] = error
            while len(self._view_failures) > MAX_CACHED_VIEWS:
                self._view_failures.popitem(last=False)
            raise ValueError(error)
        while self.views and (len(self.views) >= MAX_CACHED_VIEWS or self.view_bytes + size > MAX_VIEW_BYTES):
            _old_key, (_old_positions, old_size) = self.views.popitem(last=False)
            self.view_bytes -= old_size
        self.views[key] = (positions, size)
        self.view_bytes += size
        return frame, positions

    def view(self, params):
        """Explicit data actions may materialize the selected view once on demand."""
        frame, positions = self._frame_and_positions(params)
        if isinstance(frame, self.pl.DataFrame):
            return self.pandas_frame(frame if positions is None else frame[positions])
        return frame if positions is None else frame.iloc[positions]

    def pandas_frame(self, frame):
        """Arrow integers retain nullable UInt64 precision during explicit actions."""
        if not isinstance(frame, self.pl.DataFrame):
            return frame
        converted = frame.to_pandas(use_pyarrow_extension_array=True)
        for index, dtype in enumerate(frame.dtypes):
            if dtype.base_type() in {self.pl.Decimal, self.pl.Date, self.pl.Time}:
                converted.isetitem(index, converted.iloc[:, index].astype(object))
        return converted

    @staticmethod
    def _rows(iterator):
        rows, size = [], 128
        error = "Page exceeds 8 MiB; reduce its row/column range or export the original data to a file"
        for row in iterator:
            values = []
            for value in row:
                if isinstance(value, str) and len(value) > MAX_PAGE_BYTES or isinstance(value, bytes) and len(value) > MAX_PAGE_BYTES // 2:
                    raise ValueError(error)
                item = None if type(value).__name__ in {"NAType", "NaTType"} else scalar(value)
                size += len(json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf-8")) + 1
                if size > MAX_PAGE_BYTES:
                    raise ValueError(error)
                values.append(item)
            rows.append(values)
        return rows

    @staticmethod
    def _integer(value, name, minimum, maximum=None):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum or maximum is not None and value > maximum:
            raise ValueError(f"{name} must be an integer between {minimum} and {maximum}" if maximum is not None else f"{name} must be a non-negative integer")
        return value

    def page(self, params):
        offset = self._integer(params.get("offset", 0), "offset", 0)
        limit = self._integer(params.get("limit", 100), "limit", 1, MAX_PAGE_ROWS)
        start = self._integer(params.get("column_offset", 0), "column_offset", 0)
        projected = "column_offset" in params or "column_limit" in params
        column_limit = self._integer(params["column_limit"], "column_limit", 1, MAX_PAGE_COLUMNS) if "column_limit" in params else None
        include_columns = params.get("include_columns", True)
        if not isinstance(include_columns, bool):
            raise ValueError("include_columns must be a boolean")
        frame, positions = self._frame_and_positions(params)
        total_rows = len(frame) if positions is None else len(positions)
        total_columns = len(frame.columns)
        end = total_columns if column_limit is None else min(total_columns, start + column_limit)
        if start > total_columns:
            raise ValueError("column_offset exceeds the number of columns")
        count = min(limit, max(0, total_rows - offset))
        if start == end:
            rows = [[] for _ in range(count)]
        elif isinstance(frame, self.pl.DataFrame):
            tile = frame.select(frame.columns[start:end])
            tile = tile.slice(offset, limit) if positions is None else tile[positions[offset:offset + limit]]
            # Polars Python rows truncate nanosecond temporal values to us.
            # Arrow conversion is restricted to this bounded viewport tile.
            if any(getattr(dtype, "time_unit", None) == "ns" for dtype in tile.dtypes):
                rows = self._rows(tile.to_pandas(use_pyarrow_extension_array=True).itertuples(index=False, name=None))
            else:
                rows = self._rows(tile.iter_rows())
        else:
            # DataFrame column projection consolidates fragmented pandas blocks
            # and can copy entire 10M-row columns. Index each public ExtensionArray
            # directly instead: only selected rows/columns enter this tiny frame,
            # including strided NumPy arrays and nullable/temporal extension dtypes.
            selector = slice(offset, offset + limit) if positions is None else positions[offset:offset + limit]
            tile = self.pd.DataFrame({index: frame.iloc[:, index].array[selector] for index in range(start, end)}, copy=False)
            rows = self._rows(tile.itertuples(index=False, name=None))
        result = {"rows": rows, "total_rows": total_rows, "offset": offset, "columns": []}
        if include_columns:
            result["columns"] = self.descriptors[params["result_id"]]["columns"][start:end]
        if projected:
            result.update({"column_offset": start, "total_columns": total_columns})
        return result
