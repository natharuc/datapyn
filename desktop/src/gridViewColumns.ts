import type { DataView } from "./dataTypes";
import type { Column } from "./runtime";

/** Restore only labels the runtime can address uniquely in this result. */
export function reconcileGridView(view: DataView | undefined, columns: readonly Column[]): DataView | undefined {
  if (!view) return view;
  const counts = new Map<string, number>();
  for (const column of columns) counts.set(column.name, (counts.get(column.name) ?? 0) + 1);
  const valid = (name: unknown) => typeof name === "string" && counts.get(name) === 1;
  let filter = view.filter;
  if (filter) {
    let next = filter;
    if (filter.filters) {
      const kept = filter.filters.filter(rule => valid(rule.column));
      if (kept.length !== filter.filters.length) {
        next = { ...next };
        if (kept.length) next.filters = kept;
        else delete next.filters;
      }
    }
    if ("column" in filter && !valid(filter.column)) {
      const { column: _column, operator: _operator, value: _value, value_to: _upper, ...rest } = next;
      next = rest;
    }
    filter = next === filter || Object.keys(next).length ? next : undefined;
  }
  const sort = view.sort && !valid(view.sort.column) ? undefined : view.sort;
  if (filter === view.filter && sort === view.sort) return view;
  const next = { ...view };
  if (filter) next.filter = filter;
  else delete next.filter;
  if (sort) next.sort = sort;
  else delete next.sort;
  return Object.keys(next).length ? next : undefined;
}
