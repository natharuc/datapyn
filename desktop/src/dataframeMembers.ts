import type { CompletionContext, LanguageCompletion } from "./editorLanguage";

/** Shared public class metadata; no user objects or dataframe rows are inspected.
 * Generated with inspect.getattr_static(DataFrame, name) over dir(DataFrame).
 * Sources: pandas 2.3.3, polars 1.41.2; bundled runtime versions.
 */
export type DataFrameLibrary = "pandas" | "polars";

const pandas_methods = [
  "abs", "add", "add_prefix", "add_suffix", "agg", "aggregate", "align", "all", "any",
  "apply", "applymap", "asfreq", "asof", "assign", "astype", "at_time", "backfill", "between_time",
  "bfill", "bool", "boxplot", "clip", "combine", "combine_first", "compare", "convert_dtypes", "copy",
  "corr", "corrwith", "count", "cov", "cummax", "cummin", "cumprod", "cumsum", "describe",
  "diff", "div", "divide", "dot", "drop", "drop_duplicates", "droplevel", "dropna", "duplicated",
  "eq", "equals", "eval", "ewm", "expanding", "explode", "ffill", "fillna", "filter",
  "first", "first_valid_index", "floordiv", "from_dict", "from_records", "ge", "get", "groupby", "gt",
  "head", "hist", "idxmax", "idxmin", "infer_objects", "info", "insert", "interpolate", "isetitem",
  "isin", "isna", "isnull", "items", "iterrows", "itertuples", "join", "keys", "kurt",
  "kurtosis", "last", "last_valid_index", "le", "lt", "map", "mask", "max", "mean",
  "median", "melt", "memory_usage", "merge", "min", "mod", "mode", "mul", "multiply",
  "ne", "nlargest", "notna", "notnull", "nsmallest", "nunique", "pad", "pct_change", "pipe",
  "pivot", "pivot_table", "pop", "pow", "prod", "product", "quantile", "query", "radd",
  "rank", "rdiv", "reindex", "reindex_like", "rename", "rename_axis", "reorder_levels", "replace", "resample",
  "reset_index", "rfloordiv", "rmod", "rmul", "rolling", "round", "rpow", "rsub", "rtruediv",
  "sample", "select_dtypes", "sem", "set_axis", "set_flags", "set_index", "shift", "skew", "sort_index",
  "sort_values", "squeeze", "stack", "std", "sub", "subtract", "sum", "swapaxes", "swaplevel",
  "tail", "take", "to_clipboard", "to_csv", "to_dict", "to_excel", "to_feather", "to_gbq", "to_hdf",
  "to_html", "to_json", "to_latex", "to_markdown", "to_numpy", "to_orc", "to_parquet", "to_period", "to_pickle",
  "to_records", "to_sql", "to_stata", "to_string", "to_timestamp", "to_xarray", "to_xml", "transform", "transpose",
  "truediv", "truncate", "tz_convert", "tz_localize", "unstack", "update", "value_counts", "var", "where",
  "xs",
];
const pandas_properties = [
  "T", "at", "attrs", "axes", "columns", "dtypes", "empty", "flags", "iat",
  "iloc", "index", "loc", "ndim", "plot", "shape", "size", "sparse", "style",
  "values",
];

const polars_methods = [
  "approx_n_unique", "bottom_k", "cast", "clear", "clone", "collect_schema", "corr", "count", "describe",
  "deserialize", "drop", "drop_in_place", "drop_nans", "drop_nulls", "equals", "estimated_size", "explode", "extend",
  "fill_nan", "fill_null", "filter", "fold", "gather", "gather_every", "get_column", "get_column_index", "get_columns",
  "glimpse", "group_by", "group_by_dynamic", "hash_rows", "head", "hstack", "insert_column", "interpolate", "is_duplicated",
  "is_empty", "is_unique", "item", "iter_columns", "iter_rows", "iter_slices", "join", "join_asof", "join_where",
  "lazy", "limit", "map_columns", "map_rows", "match_to_schema", "max", "max_horizontal", "mean", "mean_horizontal",
  "median", "melt", "merge_sorted", "min", "min_horizontal", "n_chunks", "n_unique", "null_count", "partition_by",
  "pipe", "pivot", "product", "quantile", "rechunk", "remove", "rename", "replace_column", "reverse",
  "rolling", "row", "rows", "rows_by_key", "sample", "select", "select_seq", "serialize", "set_sorted",
  "shift", "show", "shrink_to_fit", "slice", "sort", "sql", "std", "sum", "sum_horizontal",
  "tail", "to_arrow", "to_dict", "to_dicts", "to_dummies", "to_init_repr", "to_jax", "to_numpy", "to_pandas",
  "to_series", "to_struct", "to_torch", "top_k", "transpose", "unique", "unnest", "unpivot", "unstack",
  "update", "upsample", "var", "vstack", "with_columns", "with_columns_seq", "with_row_count", "with_row_index", "write_avro",
  "write_clipboard", "write_csv", "write_database", "write_delta", "write_excel", "write_iceberg", "write_ipc", "write_ipc_stream", "write_json",
  "write_ndjson", "write_parquet",
];
const polars_properties = [
  "columns", "dtypes", "flags", "height", "plot", "schema", "shape", "style", "width",
];

const catalog: Record<DataFrameLibrary, LanguageCompletion[]> = {
  pandas: members("pandas", pandas_methods, pandas_properties),
  polars: members("polars", polars_methods, polars_properties),
};
const memberNames = { pandas: new Set(catalog.pandas.map(item => item.label)), polars: new Set(catalog.polars.map(item => item.label)) };
function members(library: DataFrameLibrary, methods: string[], properties: string[]): LanguageCompletion[] {
  return [...methods.map(label => ({ label, kind: "method", detail: `${library} DataFrame method`, insert_text: label, sortText: `1:${label}` })),
    ...properties.map(label => ({ label, kind: "property", detail: `${library} DataFrame property`, insert_text: label, sortText: `1:${label}` }))];
}
export function dataframeLibrary(variable: CompletionContext["variables"][number]): DataFrameLibrary {
  return variable.module?.startsWith("polars") ? "polars" : "pandas";
}
export function dataframeMembers(library: DataFrameLibrary): readonly LanguageCompletion[] { return catalog[library]; }
export function dataframeMemberNames(library: DataFrameLibrary): ReadonlySet<string> { return memberNames[library]; }
