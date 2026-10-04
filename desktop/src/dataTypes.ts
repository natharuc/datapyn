import type { Primitive } from "./runtime";

export interface ColumnFilter { column: string; operator?: string; value?: Primitive; value_to?: Primitive }
export interface DataView {
  filter?: { text?: string; column?: string; operator?: string; value?: Primitive; value_to?: Primitive; filters?: ColumnFilter[] };
  sort?: { column: string; direction: "asc" | "desc" };
  scope?: { row_ranges?: number[][]; column_indices?: number[]; rectangles?: Array<{x: number; y: number; width: number; height: number}> };
}
export interface ColumnSummary {
  name: string; dtype: string; count: number; null_count: number;
  min?: Primitive; max?: Primitive; sum?: Primitive; mean?: Primitive; median?: Primitive; std?: Primitive; coefficient?: Primitive;
  numeric_count?: number; distinct?: number; sampled?: boolean; distinct_sampled?: boolean; sample_rows?: number; top?: Array<{value: string; count: number}>;
}
export interface ResultSummary { row_count: number; column_count: number; cell_count?: number; columns: ColumnSummary[]; columns_truncated: boolean;
  aggregates?: {count_numeric: number; sum?: Primitive; mean?: Primitive; min?: Primitive; max?: Primitive; median?: Primitive; std?: Primitive; coefficient?: Primitive} }
export type ChartConfig = Record<string, unknown> & { type?: string; x_column?: string; y_columns?: string[] };
export interface ChartResponse { figure: { data: unknown[]; layout: Record<string, unknown> }; config: ChartConfig; source_rows: number; point_count: number; bounded: boolean }
