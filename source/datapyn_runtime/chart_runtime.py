"""Narrow shared DataViews and exact aggregation before bounded Plotly traces."""

from decimal import Decimal, InvalidOperation, localcontext
import math
from numbers import Integral, Number

MAX_SERIES = 50
MAX_GROUPS = 100_000
MAX_PIVOT_CELLS = 1_000_000


def _missing(value, pd):
    return value is None or value is pd.NA or value is pd.NaT or isinstance(value, (Number, Decimal)) and not isinstance(value, Integral) and pd.isna(value)


def _number(value, pd):
    if _missing(value, pd):
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, Number):
        return value if math.isfinite(value) else None
    if isinstance(value, str) and len(value) <= 1024:
        try:
            result = Decimal(value)
            return result if result.is_finite() and abs(result.adjusted()) <= 1000 else None
        except InvalidOperation:
            pass
    return None


def _zeros(value, pd):
    with pd.option_context("future.no_silent_downcasting", True):
        return value.fillna(0)


def _source(params, namespace, store, config):
    from .frame_view import pandas_positions, polars_positions
    from .data_tools import selected_frame
    if params.get("result_id"):
        frame, positions = store._frame_and_positions(params)
    else:
        name = params.get("variable_name")
        if name not in namespace or not store.is_frame(namespace[name]):
            raise ValueError("This chart requires an available DataFrame or Series")
        frame = namespace[name]
        if isinstance(frame, (store.pd.Series, store.pl.Series)):
            frame = frame.to_frame()
        positions = polars_positions(frame, params) if isinstance(frame, store.pl.DataFrame) else pandas_positions(frame, params)
    y_names = config.get("y_columns") or []
    if not isinstance(y_names, list) or not y_names or len(y_names) > MAX_SERIES or any(not isinstance(name, str) for name in y_names):
        raise ValueError("Choose between 1 and 50 Y columns")
    if len(set(y_names)) != len(y_names):
        raise ValueError("Choose each Y column only once")
    requested = list(dict.fromkeys([config.get("x_column"), *y_names, config.get("group_by")]))
    if config.get("group_by") and config.get("group_by") == config.get("x_column"):
        raise ValueError("Choose different X and grouping columns")
    requested = [name for name in requested if name]
    columns = [store.column_label(frame, name) for name in requested]
    indices = [list(frame.columns).index(name) for name in columns]
    native = isinstance(frame, store.pl.DataFrame)
    if native:
        narrow = frame.select(columns)
        if positions is not None:
            narrow = narrow[positions]
    else:
        selector = slice(None) if positions is None else positions
        narrow = store.pd.DataFrame({name: frame.iloc[:, index].array[selector] for name, index in zip(columns, indices)}, index=frame.index[selector], copy=False)
    if params.get("scope") is not None:
        # Keep the existing precise rectangular/row-range semantics, remapping
        # original column positions into the tiny projected source.
        scope = params["scope"]
        if not isinstance(scope, dict):
            raise ValueError("scope must be an object")
        mapped = dict(scope)
        if "column_indices" in mapped:
            original = mapped["column_indices"]
            if not isinstance(original, list) or any(isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(frame.columns) for index in original):
                raise ValueError("Invalid selection column indices")
            mapped["column_indices"] = [index for index, original_index in enumerate(indices) if original_index in original]
        if "rectangles" in mapped:
            rectangles = mapped["rectangles"]
            if not isinstance(rectangles, list):
                raise ValueError("Selection rectangles must be an array")
            remapped = []
            for rectangle in rectangles:
                if not isinstance(rectangle, dict) or any(isinstance(rectangle.get(key), bool) or not isinstance(rectangle.get(key), int) for key in ("x", "y", "width", "height")):
                    raise ValueError("Invalid selection rectangle")
                x, width = rectangle["x"], rectangle["width"]
                if x < 0 or width < 1 or x + width > len(frame.columns):
                    raise ValueError("Invalid selection rectangle columns")
                selected = [index for index, original_index in enumerate(indices) if x <= original_index < x + width]
                for index in selected:
                    remapped.append({**rectangle, "x": index, "width": 1})
            mapped["rectangles"] = remapped
        if native:
            narrow = store.pandas_frame(narrow)
        narrow = selected_frame({"variable_name": "chart_source", "scope": mapped}, {"chart_source": narrow}, store)
    return narrow, y_names, native and isinstance(narrow, store.pl.DataFrame)


def _bounds(work, x, ys, group, pd):
    groups = work[x].nunique(dropna=False)
    if groups > MAX_GROUPS:
        raise ValueError("Charts support at most 100000 X categories; filter or aggregate the source first")
    if group is not None and len(ys) == 1:
        seen = set()
        for value in work[group]:
            key = ("null",) if _missing(value, pd) else (type(value).__name__, value)
            seen.add(key)
            if len(seen) > MAX_SERIES:
                raise ValueError("Charts support at most 50 series; restrict grouping or choose fewer columns")
        if groups * len(seen) > MAX_PIVOT_CELLS:
            raise ValueError("Chart grouping exceeds one million pivot cells; restrict its categories or series")


def _object_aggregate(series, aggregation, pd):
    values = [value for value in series if not _missing(value, pd)]
    if not values:
        return 0 if aggregation == "sum" else None
    if any(isinstance(value, Decimal) for value in values):
        values = [value if isinstance(value, Decimal) else Decimal(str(value)) for value in values]
    if aggregation == "sum":
        return sum(values)
    if aggregation in {"min", "max"}:
        return (min if aggregation == "min" else max)(values)
    if aggregation == "mean":
        numerator = sum(Decimal(str(value)) for value in values)
        with localcontext() as context:
            context.prec = 80
            return numerator / len(values)
    values.sort()
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (Decimal(str(values[middle - 1])) + Decimal(str(values[middle]))) / 2


def _pandas_data(work, config, ys, store):
    pd = store.pd
    x = store.column_label(work, config["x_column"]) if config.get("x_column") else "__chart_index__"
    work = work.copy(deep=False)
    if not config.get("x_column"):
        while x in work.columns:
            x += "_"
        work[x] = [str(index) for index in work.index]
    ys = [store.column_label(work, name) for name in ys]
    group = store.column_label(work, config["group_by"]) if config.get("group_by") else None
    nulls, aggregation = config.get("nulls", "zero"), config.get("aggregation", "sum")
    if nulls == "drop":
        work = work.dropna(subset=list(dict.fromkeys([x, *ys, *([group] if group is not None else [])])))
    _bounds(work, x, ys, group, pd)
    exact_columns = set()
    for y in ys:
        series = work[y]
        if aggregation != "count":
            if pd.api.types.is_numeric_dtype(series.dtype):
                if pd.api.types.is_integer_dtype(series.dtype) and aggregation in {"sum", "mean", "median"}:
                    limit = 2**64 - 1 if pd.api.types.is_unsigned_integer_dtype(series.dtype) else 2**63 - 1
                    largest = max(abs(int(series.min() or 0)), abs(int(series.max() or 0))) if series.notna().any() else 0
                    if largest * max(1, len(series)) > limit or largest > 2**53 and aggregation in {"mean", "median"}:
                        series = series.astype(object)
                        exact_columns.add(y)
                elif pd.api.types.is_float_dtype(series.dtype):
                    series = series.replace([float("inf"), float("-inf")], float("nan"))
            else:
                series = series.map(lambda value: _number(value, pd)).astype(object)
                exact_columns.add(y)
        if nulls == "zero" and aggregation != "count":
            series = _zeros(series, pd)
        work[y] = series
    group_keys = [x, group] if group is not None and len(ys) == 1 else [x]
    grouped = work.groupby(group_keys, dropna=False, observed=True, sort=True)[ys]
    with localcontext() as context:
        context.prec = 1100
        functions = {y: (lambda series: len(series)) if aggregation == "count" and nulls == "zero" else (lambda series, agg=aggregation: _object_aggregate(series, agg, pd)) if y in exact_columns else aggregation for y in ys}
        data = grouped.agg(functions)
    if len(group_keys) == 2:
        data = data[ys[0]].astype(object).unstack(group)
    data.columns = [str(name) for name in data.columns]
    if len(set(data.columns)) != len(data.columns):
        raise ValueError("Chart series names collide after conversion to text")
    if any(len(name) > 1000 for name in data.columns):
        raise ValueError("Chart series labels exceed 1000 characters")
    data = _zeros(data, pd) if nulls == "zero" else data.dropna(how="all")
    return data


def _polars_data(work, config, ys, store):
    pl, pd = store.pl, store.pd
    x = config.get("x_column") or "__chart_index__"
    if not config.get("x_column"):
        while x in work.columns:
            x += "_"
        work = work.with_row_index(x).with_columns(pl.col(x).cast(pl.String))
    group = config.get("group_by") or None
    aggregation, nulls = config.get("aggregation", "sum"), config.get("nulls", "zero")
    floats = [name for name in work.columns if work[name].dtype.is_float()]
    if floats:
        work = work.with_columns([pl.col(name).fill_nan(None) for name in floats])
    # Decimal mean/median and numeric text need exact Python arithmetic. Convert
    # only the selected columns; native numeric sum/min/max/count stay native.
    fallback = any(not work[y].dtype.is_numeric() and work[y].dtype != pl.Boolean for y in ys) and aggregation != "count"
    fallback |= aggregation in {"mean", "median"} and any(work[y].dtype.base_type() == pl.Decimal or work[y].dtype.is_integer() and work[y].drop_nulls().abs().max() is not None and work[y].drop_nulls().abs().max() > 2**53 for y in ys)
    if aggregation == "sum":
        for y in ys:
            dtype = work[y].dtype
            if dtype == pl.Int128 or dtype.base_type() == pl.Decimal:
                limits = [abs(value) for value in (work[y].min(), work[y].max()) if value is not None]
                with localcontext() as context:
                    context.prec = 1100
                    limit = 2**127 - 1 if dtype == pl.Int128 else Decimal(10) ** ((dtype.precision or 38) - dtype.scale)
                    fallback |= bool(limits and max(limits) * len(work) >= limit)
    if fallback:
        converted = pd.DataFrame(work.to_dict(as_series=False), dtype=object) if pl.Int128 in work.dtypes else store.pandas_frame(work)
        return _pandas_data(converted, {**config, "x_column": x}, ys, store), "pandas_exact"
    if nulls == "drop":
        work = work.drop_nulls(list(dict.fromkeys([x, *ys, *([group] if group else [])])))
    categories = work[x].n_unique()
    if categories > MAX_GROUPS:
        raise ValueError("Charts support at most 100000 X categories; filter or aggregate the source first")
    if group and len(ys) == 1:
        seen = set()
        for value in work[group]:
            seen.add(("null",) if value is None else (type(value).__name__, value))
            if len(seen) > MAX_SERIES:
                raise ValueError("Charts support at most 50 series; restrict grouping or choose fewer columns")
        if categories * len(seen) > MAX_PIVOT_CELLS:
            raise ValueError("Chart grouping exceeds one million pivot cells; restrict its categories or series")
    expressions, aliases = [], {}
    for index, y in enumerate(ys):
        value = pl.col(y)
        if work[y].dtype.is_float():
            value = pl.when(value.is_finite()).then(value).otherwise(None)
        if work[y].dtype.is_integer() or work[y].dtype == pl.Boolean:
            value = value.cast(pl.Int128)
        if nulls == "zero":
            value = value.fill_null(0)
        alias = f"__chart_value_{index}__"
        while alias in work.columns:
            alias += "_"
        aliases[alias] = y
        expressions.append((pl.len() if aggregation == "count" and nulls == "zero" else getattr(value, aggregation)()).alias(alias))
    group_keys = [x, group] if group and len(ys) == 1 else [x]
    aggregated = work.group_by(group_keys, maintain_order=True).agg(expressions).sort(group_keys, nulls_last=True)
    if len(group_keys) == 2:
        aggregated = aggregated.with_columns(pl.col(group).cast(pl.String).fill_null("nan"))
        labels = set(aggregated[group])
        if len(labels) != len(seen):
            raise ValueError("Chart series names collide after conversion to text")
        if any(len(label) > 1000 for label in labels):
            raise ValueError("Chart series labels exceed 1000 characters")
        pivot_x = "__chart_pivot_index__"
        while pivot_x in labels or pivot_x in aggregated.columns:
            pivot_x += "_"
        aggregated = aggregated.rename({x: pivot_x})
        x = pivot_x
        aggregated = aggregated.pivot(on=group, index=x, values=next(iter(aliases)), aggregate_function=None, sort_columns=True)
    values = aggregated.to_dict(as_series=False)
    index = values.pop(x)
    if len(group_keys) != 2:
        values = {name: values[alias] for alias, name in aliases.items()}
    return pd.DataFrame(values, dtype=object, index=pd.Index(index)), "polars"


def prepare(params, namespace, store, config):
    from src.services.visualization.chart_data import chart_max_points, safe_chart_label
    frame, ys, native = _source(params, namespace, store, config)
    source_rows = len(frame)
    if not source_rows:
        raise ValueError("The selected data is empty")
    if native:
        data, engine = _polars_data(frame, config, ys, store)
    else:
        data, engine = _pandas_data(frame, config, ys, store), "pandas"
    if config.get("nulls", "zero") == "zero":
        data = _zeros(data, store.pd)
    else:
        data = data.dropna(how="all")
    if config.get("sort") == "y_desc" and not data.empty:
        data = data.sort_values(data.columns[0], ascending=False, kind="stable", na_position="last")
    if config.get("normalize") or config.get("stacking") == "percent":
        with localcontext() as context:
            context.prec = 80
            rows = []
            for values in data.itertuples(index=False, name=None):
                numeric = [Decimal(str(value)) if not _missing(value, store.pd) else Decimal(0) for value in values]
                total = sum(numeric)
                rows.append([value / total * 100 if total else Decimal(0) for value in numeric])
            data = store.pd.DataFrame(rows, columns=data.columns, index=data.index, dtype=object)
    total_points, max_points = len(data), chart_max_points(config)
    if config.get("type", "bar") == "pie" and not data.empty:
        data = data.iloc[:, :1]
        data = data.loc[data.iloc[:, 0].map(lambda value: not _missing(value, store.pd) and value > 0)]
        total_points = len(data)
    data = data.head(max_points)
    if data.empty:
        raise ValueError("There are no numeric values to chart")
    labels = [safe_chart_label(str(value)[:1000]) for value in data.index]
    return data, labels, {"source_rows": source_rows, "aggregated_point_count": total_points,
                          "point_count": len(data), "series_count": len(data.columns), "max_points": max_points,
                          "truncated_points": max(0, total_points - len(data)), "bounded": total_points > len(data),
                          "aggregation_engine": engine}


def trace_values(series, index, pd):
    values, custom, approximate = [], [], False
    for category, value in zip(index, series):
        exact = None if _missing(value, pd) else str(value)
        if exact is not None and len(exact) > 1024:
            raise ValueError("Chart numeric labels exceed 1024 characters")
        numeric = None if exact is None else float(value)
        if numeric is not None and not math.isfinite(numeric):
            raise ValueError("Chart values must fit finite numeric geometry")
        approximate |= isinstance(value, Decimal) or isinstance(value, Integral) and abs(value) > 2**53 - 1
        values.append(numeric)
        custom.append([str(category)[:1000], exact])
    return values, custom, bool(approximate)


def label_number(value, config):
    try:
        decimals = max(0, min(6, int(config.get("label_decimals", 1) or 0)))
        return f"{value:,.{decimals}f}"
    except (ValueError, TypeError):
        return "" if value is None else str(value)


def restyle(store, identifier, config):
    """Explicitly restyle the shown snapshot without reading mutable frames."""
    from .chart_snapshots import get
    from src.services.visualization.chart_data import safe_chart_label
    previous = get(store, identifier)
    keys = ("type", "x_column", "y_columns", "group_by", "aggregation", "nulls", "sort", "normalize")
    defaults = {"type": "bar", "x_column": "", "y_columns": [], "group_by": "", "aggregation": "sum", "nulls": "zero", "sort": "original", "normalize": False}
    def option(value, key):
        result = value.get(key, defaults[key])
        return "original" if key == "sort" and result == "none" else result
    if any(option(previous["config"], key) != option(config, key) for key in keys) or (previous["config"].get("stacking") == "percent") != (config.get("stacking") == "percent"):
        raise ValueError("Generate a new chart after changing its data configuration")
    traces = previous["figure"]["data"]
    categories = [item[0] for item in traces[0]["customdata"]]
    values = {trace.get("name", "value"): [Decimal(item[1]) if item[1] is not None else None for item in trace["customdata"]] for trace in traces}
    data = store.pd.DataFrame(values, index=store.pd.Index(categories), dtype=object)
    metrics = {key: previous[key] for key in ("source_rows", "aggregated_point_count", "point_count", "series_count", "max_points", "truncated_points", "bounded", "aggregation_engine", "geometry_approximate")}
    return data, [safe_chart_label(category) for category in categories], metrics
