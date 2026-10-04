"""Qt-free data actions beside the namespace; frames never leave the kernel."""

from __future__ import annotations

from contextlib import contextmanager
import itertools
import json
import keyword
import os
from pathlib import Path
import re
import tempfile

from .values import describe_variables, preview, scalar

METHODS = frozenset({"data.import", "variable.inspect", "variable.delete", "result.export", "result.export_text",
                     "result.summary", "result.chart", "result.chart_export", "result.export_table", "document.read",
                     "document.script_export", "variable.archive.list", "variable.archive.export", "variable.archive.import"})
RUNTIME_VARIABLES = frozenset({"pd", "np", "pl", "db_engine", "db_type", "db_database", "db_host", "db_username"})


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _destination(params):
    value = params.get("path")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Choose a destination file")
    path = Path(value).expanduser().resolve()
    if not path.parent.is_dir():
        raise FileNotFoundError("The destination directory does not exist")
    if path.is_dir():
        raise ValueError("The destination must be a file")
    return path


@contextmanager
def atomic_destination(path):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=path.suffix, dir=path.parent)
    os.close(descriptor)
    try:
        yield Path(temporary)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _variable_name(value, path=None):
    if not value:
        if path is None:
            raise ValueError("A variable name is required")
        value = re.sub(r"\W+", "_", Path(path).stem.lower(), flags=re.UNICODE).strip("_") or "df"
        if value[0].isdigit() or keyword.iskeyword(value):
            value = f"df_{value}"
    if not isinstance(value, str) or not value.isidentifier() or keyword.iskeyword(value) or value.startswith("_"):
        raise ValueError("Use a valid public Python variable name")
    return value


def _frame(params, namespace, store):
    result_id = params.get("result_id")
    if result_id:
        if result_id not in store.frames:
            raise KeyError("Result is unavailable; the session may have restarted")
        frame = store.frames[result_id]
    else:
        name = params.get("variable_name")
        if name not in namespace:
            raise KeyError(f"Unknown variable: {name}")
        frame = namespace[name]
    if not store.is_frame(frame):
        raise TypeError("This action requires a DataFrame or Series")
    if isinstance(frame, (store.pd.Series, store.pl.Series)):
        frame = frame.to_frame()
    if isinstance(frame, store.pl.DataFrame):
        frame = frame.to_pandas()
    return frame


def selected_frame(params, namespace, store):
    """Use view ordering before exact selection, without copying the full frame."""
    if params.get("result_id"):
        # Reuse the bounded kernel view cache across paging, summaries, exports
        # and chart requests. Selection is applied after that shared view.
        frame = store.view(params)
    else:
        frame = _frame(params, namespace, store)
        from .frame_view import apply_view
        frame = apply_view(frame, params)
    scope = params.get("scope")
    if scope is not None:
        if not isinstance(scope, dict):
            raise ValueError("scope must be an object")
        if scope.get("rectangles") is not None:
            return _rectangular_selection(frame, scope["rectangles"], store.pd)
        columns = scope.get("column_indices")
        if columns is not None:
            if not isinstance(columns, list) or not columns:
                raise ValueError("Selection must contain at least one column")
            columns = sorted(set(_integer(item, "column index", 0, len(frame.columns) - 1) for item in columns))
        ranges = scope.get("row_ranges")
        if ranges is not None:
            if not isinstance(ranges, list) or not ranges:
                raise ValueError("Selection must contain at least one row")
            validated = []
            for pair in ranges:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError("Each selected range requires its first and last row")
                start = _integer(pair[0], "range start", 0, len(frame) - 1)
                end = _integer(pair[1], "range end", start, len(frame) - 1)
                validated.append((start, end))
            merged = []
            for start, end in sorted(validated):
                if merged and start <= merged[-1][1] + 1:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])
            parts = [frame.iloc[start:end + 1] for start, end in merged]
            frame = parts[0] if len(parts) == 1 else store.pd.concat(parts)
        if columns is not None:
            frame = frame.iloc[:, columns]
    return frame


def _merge_ranges(ranges):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _rectangular_selection(frame, rectangles, pd):
    """A tabular export has empty holes; statistics count only selected cells."""
    if not isinstance(rectangles, list) or not 1 <= len(rectangles) <= 1000:
        raise ValueError("Selection requires between 1 and 1000 rectangles")
    validated = []
    for rectangle in rectangles:
        if not isinstance(rectangle, dict):
            raise ValueError("Each rectangle must be an object")
        x = _integer(rectangle.get("x"), "selection x", 0, len(frame.columns) - 1)
        y = _integer(rectangle.get("y"), "selection y", 0, len(frame) - 1)
        width = _integer(rectangle.get("width"), "selection width", 1, len(frame.columns) - x)
        height = _integer(rectangle.get("height"), "selection height", 1, len(frame) - y)
        validated.append((x, y, width, height))
    rows = _merge_ranges([(y, y + height - 1) for _, y, _, height in validated])
    columns = sorted({column for x, _, width, _ in validated for column in range(x, x + width)})
    parts = [frame.iloc[start:end + 1, columns] for start, end in rows]
    selected = parts[0] if len(parts) == 1 else pd.concat(parts)
    selected_rows = {}
    for output_column, source_column in enumerate(columns):
        allowed = _merge_ranges([(y, y + height - 1) for x, y, width, height in validated if x <= source_column < x + width])
        translated, offset = [], 0
        for start, end in rows:
            for first, last in allowed:
                a, b = max(start, first), min(end, last)
                if a <= b:
                    translated.append((offset + a - start, offset + b - start))
            offset += end - start + 1
        translated = _merge_ranges(translated)
        selected_rows[output_column] = translated
        if translated != [[0, len(selected) - 1]]:
            series = selected.iloc[:, output_column].copy()
            if pd.api.types.is_integer_dtype(series):
                series = series.astype("UInt64" if pd.api.types.is_unsigned_integer_dtype(series) else "Int64")
            elif pd.api.types.is_bool_dtype(series):
                series = series.astype("boolean")
            cursor = 0
            for first, last in translated:
                if cursor < first:
                    series.iloc[cursor:first] = pd.NA
                cursor = last + 1
            if cursor < len(series):
                series.iloc[cursor:] = pd.NA
            selected.isetitem(output_column, series)
    selected.attrs["_datapyn_selected_rows"] = selected_rows
    return selected


def import_data(params, namespace, store):
    path = Path(params["path"]).expanduser().resolve(strict=True)
    name = _variable_name(params.get("variable_name"), path)
    if name in RUNTIME_VARIABLES:
        raise ValueError("This variable belongs to the runtime")
    options = params.get("options") or {}
    extension = path.suffix.lower()
    if extension in {".csv", ".tsv", ".txt"}:
        delimiter = options.get("delimiter", "\t" if extension == ".tsv" else ";")
        if delimiter is not None and (not isinstance(delimiter, str) or len(delimiter) != 1):
            raise ValueError("Delimiter must be one character or null for automatic detection")
        frame = store.pd.read_csv(path, sep=delimiter, encoding=options.get("encoding", "utf-8-sig"),
                                  decimal=options.get("decimal", "."), engine="python" if delimiter is None else "c")
    elif extension in {".xlsx", ".xls"}:
        import fastexcel
        frame = fastexcel.read_excel(str(path)).load_sheet(options.get("sheet", 0)).to_pandas()
    elif extension == ".parquet":
        frame = store.pd.read_parquet(path)
    elif extension == ".json":
        frame = store.pd.read_json(path, orient=options.get("orient", "records"))
    else:
        raise ValueError(f"Unsupported data format: {extension}")
    if name in namespace and not params.get("overwrite", False):
        raise ValueError(f"Variable {name} already exists; choose another name or enable replacement")
    namespace[name] = frame
    return {"variable_name": name, "result": store.register(frame, name), "variables": describe_variables(namespace)}


def inspect_variable(params, namespace, store):
    name = _variable_name(params.get("name"))
    if name not in namespace:
        raise KeyError(f"Unknown variable: {name}")
    value = namespace[name]
    offset = _integer(params.get("offset", 0), "offset", 0, 2**31 - 1)
    limit = _integer(params.get("limit", 100), "limit", 1, 200)
    result = {"name": name, "type": type(value).__name__, "preview": preview(value, 8192), "offset": offset}
    if store.is_frame(value):
        result.update({"result": store.register(value, name), "shape": list(value.shape), "entries": [], "total_entries": 0})
    else:
        if isinstance(value, dict):
            pairs = value.items()
            total = len(value)
        elif isinstance(value, (list, tuple, set, frozenset)):
            pairs = enumerate(value)
            total = len(value)
        else:
            # Avoid invoking arbitrary descriptors/properties during inspection.
            attributes = vars(value) if hasattr(value, "__dict__") else {}
            pairs, total = attributes.items(), len(attributes)
        result["total_entries"] = total
        result["entries"] = [{"key": preview(key), "type": type(item).__name__, "value": preview(item, 2000)}
                             for key, item in itertools.islice(pairs, offset, offset + limit)]
    return result


def delete_variable(params, namespace, store):
    name = _variable_name(params.get("name"))
    if name in RUNTIME_VARIABLES:
        raise ValueError("This variable belongs to the runtime")
    if name not in namespace:
        raise KeyError(f"Unknown variable: {name}")
    value = namespace.pop(name)
    for result_id, frame in list(store.frames.items()):
        descriptor = getattr(store, "descriptors", {}).get(result_id)
        if descriptor and descriptor.get("variable_name") == name or descriptor is None and frame is value:
            if callable(getattr(store, "release", None)):
                store.release(result_id)
            else:
                store.frames.pop(result_id, None)
    return {"variables": describe_variables(namespace)}


def _export_options(params):
    options = params.get("options") or {}
    if not isinstance(options, dict):
        raise ValueError("Export options must be an object")
    return options


def export_result(params, namespace, store, progress=None, cancelled=None):
    from .export_control import ExportControl
    from .export_formats import write_file
    frame = selected_frame(params, namespace, store)
    path = _destination(params)
    export_format = str(params.get("format") or path.suffix.lstrip(".")).lower()
    control = ExportControl(len(frame), progress, cancelled)
    control.check()
    with atomic_destination(path) as temporary:
        write_file(frame, temporary, export_format, _export_options(params), control)
        control.check()
    control.complete()
    return {"path": str(path), "format": export_format, "row_count": len(frame), "column_count": len(frame.columns)}


def export_text(params, namespace, store, progress=None, cancelled=None):
    from .export_control import ExportControl
    from .export_formats import BoundedText, write_text
    frame = selected_frame(params, namespace, store)
    export_format = str(params.get("format", "csv")).lower()
    control = ExportControl(len(frame), progress, cancelled)
    control.check()
    with BoundedText() as output:
        write_text(frame, output, export_format, _export_options(params), control)
        content = output.getvalue()
    control.check()
    control.complete()
    return {"text": content, "format": export_format, "row_count": len(frame), "column_count": len(frame.columns)}


def summarize_result(params, namespace, store):
    from .summary_stats import summarize_frame
    frame = selected_frame(params, namespace, store)
    return summarize_frame(frame, store.pd)


def build_chart(params, namespace, store):
    """Original aggregation and palettes, with at most 500 points on the wire."""
    import plotly.graph_objects as go
    from plotly.utils import PlotlyJSONEncoder
    from src.services.visualization.chart_data import prepare_chart_data, chart_palette, chart_color, chart_max_points, format_chart_number
    from src.language import init_language
    init_language(params.get("language", "pt-BR"))
    frame = selected_frame(params, namespace, store)
    config = params.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("Chart config must be an object")
    chart_type = config.get("type", "bar")
    if chart_type not in {"bar", "line", "area", "scatter", "pie"}:
        raise ValueError("Choose bar, line, area, scatter or pie")
    if config.get("aggregation", "sum") not in {"sum", "mean", "min", "max", "count", "median"}:
        raise ValueError("Unsupported aggregation")
    if frame.empty:
        raise ValueError("The selected data is empty")
    data, labels = prepare_chart_data(frame, config)
    if data.empty:
        raise ValueError("There are no numeric values to chart")
    if len(data.columns) > 50:
        raise ValueError("Charts support at most 50 series; restrict grouping or choose fewer columns")
    colors = chart_palette(config, len(data.columns))
    background = chart_color(config, "background_color", "#101725")
    text_color = chart_color(config, "text_color", "#d6dce8")
    label_color = chart_color(config, "label_color", text_color)
    grid_color = chart_color(config, "grid_color", "#253044")
    axis_color = chart_color(config, "axis_color", "#697b98")
    def number(key, default, low, high):
        try:
            return max(low, min(high, int(config.get(key, default))))
        except (ValueError, TypeError):
            return default
    def rgba(color, opacity):
        from matplotlib.colors import to_rgb
        red, green, blue = to_rgb(color)
        return f"rgba({int(red * 255)},{int(green * 255)},{int(blue * 255)},{opacity:.3f})"
    figure = go.Figure()
    if chart_type == "pie":
        series = data.iloc[:, 0].fillna(0)
        series = series[series > 0]
        if series.empty:
            raise ValueError("Pie charts require positive values")
        figure.add_trace(go.Pie(labels=[str(value) for value in series.index], values=series.astype(float).tolist(),
                               hole=0.42, marker={"colors": chart_palette(config, len(series)), "line": {"color": background, "width": 2}}, sort=False,
                               textfont={"color": label_color},
                               textinfo="label+percent" if config.get("show_data_labels") else "label"))
    else:
        for index, name in enumerate(data.columns):
            values, color = [scalar(value) for value in data[name]], colors[index % len(colors)]
            text = [format_chart_number(value, config) for value in values] if config.get("show_data_labels") else None
            if chart_type == "bar":
                horizontal = config.get("horizontal", False)
                figure.add_trace(go.Bar(x=values if horizontal else labels, y=labels if horizontal else values,
                                       orientation="h" if horizontal else "v", name=str(name), marker_color=color,
                                       opacity=number("bar_opacity", 94, 10, 100) / 100,
                                       text=text, textfont={"color": label_color}, textposition="auto" if horizontal else "outside"))
            else:
                stacked = config.get("stacking") in {"stacked", "percent"}
                show_line, show_markers = config.get("show_line", True), config.get("show_markers", True)
                mode = "markers" if chart_type == "scatter" or not show_line else "lines+markers" if show_markers and chart_type != "area" else "lines"
                if text:
                    mode += "+text"
                figure.add_trace(go.Scatter(x=labels, y=values, name=str(name),
                                           mode=mode,
                                           line={"color": color, "width": number("line_width", 2, 1, 10),
                                                 "dash": {"dashed": "dash", "dotted": "dot", "dashdot": "dashdot"}.get(config.get("line_style"), "solid")},
                                           marker={"color": color, "size": number("marker_size", 5, 1, 18)}, text=text,
                                           textfont={"color": label_color}, textposition="top center",
                                           fill="tonexty" if chart_type == "area" and stacked and index else "tozeroy" if chart_type == "area" else None,
                                           fillcolor=rgba(color, number("area_opacity", 20, 5, 90) / 100) if chart_type == "area" else None,
                                           stackgroup="series" if chart_type == "area" and stacked else None))
    axis_style = {"showgrid": bool(config.get("show_grid", True)), "gridcolor": grid_color,
                  "linecolor": axis_color, "showline": bool(config.get("show_axis_line", False)), "zeroline": False,
                  "tickfont": {"size": 11, "color": text_color}}
    title = str(config.get("title", ""))[:1000]
    figure.update_layout(title={"text": title, "x": 0, "xanchor": "left", "font": {"size": 16, "color": text_color}}, paper_bgcolor=background, plot_bgcolor=background,
                         font={"family": "Segoe UI, Roboto, Helvetica Neue, Arial, Ubuntu, sans-serif", "color": text_color, "size": 12},
                         barmode="relative" if config.get("stacking") in {"stacked", "percent"} else "group",
                         showlegend=config.get("show_legend", True), hovermode="x unified",
                         hoverlabel={"bgcolor": background, "bordercolor": axis_color, "font": {"color": text_color}},
                         legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0, "font": {"color": text_color}, "bgcolor": "rgba(0,0,0,0)"},
                         margin={"l": 56, "r": 24, "t": 56 if title else 32, "b": 72},
                         xaxis={**axis_style, "title": {"text": config.get("x_label") or config.get("x_column", ""), "font": {"size": 12, "color": text_color}}},
                         yaxis={**axis_style, "title": {"text": config.get("y_label") or ("%" if config.get("normalize") or config.get("stacking") == "percent" else ""), "font": {"size": 12, "color": text_color}}})
    if chart_type == "pie":
        figure.update_layout(xaxis={"visible": False}, yaxis={"visible": False}, margin={"l": 12, "r": 12, "t": 48, "b": 12})
    elif chart_type == "bar" and config.get("horizontal"):
        figure.update_yaxes(categoryorder="array", categoryarray=labels)
    else:
        figure.update_xaxes(categoryorder="array", categoryarray=labels)
        if len(labels) > 8:
            figure.update_xaxes(tickangle=-35)
            figure.update_layout(margin={"b": 96})
    return {"figure": json.loads(json.dumps(figure.to_dict(), cls=PlotlyJSONEncoder)), "config": config,
            "source_rows": len(frame), "point_count": len(data), "bounded": len(data) >= chart_max_points(config)}


def export_to_table(params, namespace, store, connector, progress=None, cancelled=None):
    from .table_export import export_table
    frame = selected_frame(params, namespace, store)
    return export_table(frame, params, connector, progress, cancelled)


def read_document(params):
    path = Path(params["path"]).expanduser().resolve(strict=True)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Code documents may contain at most 16 MiB")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        import chardet
        text = raw.decode(chardet.detect(raw).get("encoding") or "latin-1")
    if path.suffix.lower() == ".ipynb":
        notebook = json.loads(text)
        if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
            raise ValueError("Invalid notebook: cells must be an array")
        blocks = []
        for cell in notebook["cells"]:
            if not isinstance(cell, dict):
                raise ValueError("Invalid notebook cell")
            source = cell.get("source", [])
            code = "".join(source) if isinstance(source, list) and all(isinstance(item, str) for item in source) else source
            if not isinstance(code, str):
                raise ValueError("Invalid notebook cell source")
            cell_type = cell.get("cell_type", "code")
            if cell_type not in {"code", "markdown", "raw"}:
                raise ValueError("Invalid notebook cell type")
            blocks.append({"language": "python", "code": code, "cell_type": cell_type,
                           "notebook_metadata": cell.get("metadata", {})})
        return {"path": str(path), "blocks": blocks, "notebook_metadata": notebook.get("metadata", {})}
    if path.suffix.lower() not in {".py", ".sql"}:
        raise ValueError("Open a Python, SQL or Jupyter document")
    return {"path": str(path), "blocks": [{"language": "python" if path.suffix.lower() == ".py" else "sql", "code": text, "cell_type": "code"}]}


def export_script(params):
    from src.core.parameter_settings import use_shared_parameter_delimiter
    with use_shared_parameter_delimiter(params.get("shared_delimiter", "{{name}}")):
        return _export_script(params)


def _export_script(params):
    path = _destination(params)
    blocks = params.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("blocks must be an array")
    shared = params.get("shared_parameters") or [] if params.get("shared_parameters_enabled", True) else []
    export_format = params.get("format") or path.suffix.lstrip(".").lower()
    if export_format == "ipynb":
        if any(block.get("language", "python") == "sql" for block in blocks):
            raise ValueError("SQL blocks cannot be exported to a Python notebook; export the analysis as .py")
        cells = [{"cell_type": block.get("cell_type", "code"), "metadata": block.get("notebook_metadata", {}),
                  "source": (_prepared_python(str(block.get("code", "")), shared) if block.get("cell_type", "code") == "code" else str(block.get("code", ""))).splitlines(keepends=True),
                  **({"outputs": [], "execution_count": None} if block.get("cell_type", "code") == "code" else {})}
                 for block in blocks]
        metadata = params.get("notebook_metadata")
        if metadata is None:
            metadata = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}
        document = {"nbformat": 4, "nbformat_minor": 5, "metadata": metadata, "cells": cells}
        content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    elif export_format == "sql":
        from .script_parameters import literal_sql
        content = "\n\n".join(literal_sql(str(block.get("code", "")), (block.get("sql_parameters") or block.get("parameters") or []) + shared,
                                        params.get("db_type", "sqlserver")) for block in blocks if block.get("language") == "sql") + "\n"
    elif export_format == "py":
        lines = ["# Exported from DataPyn", "import pandas as pd", "import numpy as np", "import polars as pl",
                 "import datetime", "from decimal import Decimal", "from uuid import UUID"]
        if any(block.get("language") == "sql" for block in blocks):
            lines += ["import os", "from sqlalchemy import create_engine, text", "", "# Set the database URL in the environment; credentials are never exported.",
                      "db_engine = create_engine(os.environ['DATAPYN_DATABASE_URL'])"]
        for index, block in enumerate(blocks, 1):
            code = str(block.get("code", ""))
            name = block.get("block_name") or block.get("name") or block.get("variableName") or f"df_block_{index}"
            lines += ["", f"# --- Block {index} ---"]
            if block.get("cell_type", "code") != "code":
                lines.extend("# " + line for line in code.splitlines())
            elif block.get("language") == "sql":
                name = _variable_name(name)
                parameters = (block.get("sql_parameters") or block.get("parameters") or []) + shared
                if parameters:
                    from src.utils.sql_parameter_service import prepare_generic_sql
                    prepared = prepare_generic_sql(code, parameters)
                    lines += [f"{name} = pd.read_sql(text({prepared.query!r}), db_engine, params={prepared.params!r})"]
                else:
                    lines += [f"{name} = pd.read_sql(text({code!r}), db_engine)"]
            else:
                lines.append(_prepared_python(code, shared))
        content = "\n".join(lines) + "\n"
    else:
        raise ValueError("Export a .py, .sql or .ipynb script")
    with atomic_destination(path) as temporary:
        temporary.write_text(content, encoding="utf-8")
    return {"path": str(path), "format": export_format, "block_count": len(blocks)}


def _prepared_python(code, shared):
    from src.utils.sql_parameter_service import prepare_python_code_with_shared_parameters
    return prepare_python_code_with_shared_parameters(code, shared)


def dispatch(method, params, namespace, store, connector=None, progress=None, cancelled=None):
    handlers = {"data.import": import_data, "variable.inspect": inspect_variable,
                "variable.delete": delete_variable,
                "result.summary": summarize_result, "result.chart": build_chart}
    if method in handlers:
        return handlers[method](params, namespace, store)
    if method == "result.export":
        return export_result(params, namespace, store, progress, cancelled)
    if method == "result.export_text":
        return export_text(params, namespace, store, progress, cancelled)
    if method == "result.export_table":
        return export_to_table(params, namespace, store, connector, progress, cancelled)
    if method.startswith("variable.archive."):
        from .variable_archive import dispatch as archive_dispatch
        return archive_dispatch(method, params, namespace, store, progress=progress, cancelled=cancelled)
    if method == "result.chart_export":
        from .chart_artifacts import export_chart
        return export_chart(params, namespace, store)
    if method == "document.read":
        return read_document(params)
    if method == "document.script_export":
        return export_script(params)
    raise ValueError(f"Unknown data operation: {method}")
