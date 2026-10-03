import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import DataEditor, { CompactSelection, GridCellKind, type GridCell, type GridColumn, type GridSelection, type Item, type Rectangle } from "@glideapps/glide-data-grid";
import "@glideapps/glide-data-grid/dist/index.css";
import { Copy, Filter, ArrowDownAZ, LoaderCircle } from "lucide-react";
import { errorText, type Column, type Primitive, type ResultPage, type ResultRef, type RuntimeTransport } from "./runtime";
import { selectionRectangles } from "./gridSelection";

const PAGE_SIZE = 200;
const CACHE_PAGES = 40;
const MAX_COPY_CELLS = 200_000;
const emptySelection = (): GridSelection => ({ columns: CompactSelection.empty(), rows: CompactSelection.empty() });
export const displayCell = (value: Primitive) => value === null ? "∅" : String(value);
export const clipboardCell = (value: Primitive) => value === null ? "" : String(value).replace(/[\t\r\n]/g, " ");

interface Props { sessionId: string; result: ResultRef; transport: RuntimeTransport; onMessage: (message: string) => void; copySignal: number }

export function ResultGrid({ sessionId, result, transport, onMessage, copySignal }: Props) {
  const cache = useRef(new Map<number, ResultPage>()), pending = useRef(new Map<number, Promise<ResultPage>>());
  const generation = useRef(0);
  const [revision, setRevision] = useState(0), [selection, setSelection] = useState<GridSelection>(emptySelection);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [filter, setFilter] = useState(""), [filterQuery, setFilterQuery] = useState("");
  const [sort, setSort] = useState<{ column: string; direction: "asc" | "desc" }>();
  const [totalRows, setTotalRows] = useState(result.row_count);
  const [resultColumns, setResultColumns] = useState<Column[]>(result.columns);
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({});
  const columns = useMemo<GridColumn[]>(() => resultColumns.map((column) => ({ title: column.name,
    id: column.name, width: columnWidths[column.name] ?? 175, icon: column.dtype.includes("int") || column.dtype.includes("float") ? "headerNumber" : "headerString" })), [resultColumns, columnWidths]);
  const requestPage = useCallback((page: number): Promise<ResultPage> => {
    const saved = cache.current.get(page); if (saved) return Promise.resolve(saved);
    const inflight = pending.current.get(page); if (inflight) return inflight;
    const version = generation.current; setLoading(true);
    const promise = transport.request<ResultPage>("result.page", { session_id: sessionId, result_id: result.result_id,
      offset: page * PAGE_SIZE, limit: PAGE_SIZE, sort, filter: filterQuery ? { text: filterQuery } : undefined }).then((data) => {
      if (version !== generation.current) return data;
      if (!Array.isArray(data.rows)) throw new Error("Resposta de resultados inválida.");
      if (cache.current.size >= CACHE_PAGES) cache.current.delete(cache.current.keys().next().value!);
      cache.current.set(page, data); setTotalRows(data.total_rows); setResultColumns(data.columns); setRevision((value) => value + 1); setError("");
      return data;
    }).catch((failure) => {
      if (version === generation.current) { setError(errorText(failure)); onMessage(errorText(failure)); }
      throw failure;
    }).finally(() => { if (version === generation.current) { pending.current.delete(page); setLoading(pending.current.size > 0); } });
    pending.current.set(page, promise); return promise;
  }, [sessionId, result.result_id, sort, filterQuery, transport, onMessage]);

  useEffect(() => {
    generation.current++; cache.current.clear(); pending.current.clear(); setSelection(emptySelection());
    setTotalRows(result.row_count); setError(""); void requestPage(0).catch(() => {});
    return () => { generation.current++; };
  }, [requestPage, result.row_count]);
  useEffect(() => { const timer = setTimeout(() => setFilterQuery(filter.trim()), 250); return () => clearTimeout(timer); }, [filter]);

  const getCellContent = useCallback(([column, row]: Item): GridCell => {
    const pageIndex = Math.floor(row / PAGE_SIZE), page = cache.current.get(pageIndex);
    if (!page) { void requestPage(pageIndex).catch(() => {}); return { kind: GridCellKind.Loading, allowOverlay: false }; }
    const value = page.rows[row - page.offset]?.[column] ?? null;
    return { kind: GridCellKind.Text, data: displayCell(value), displayData: displayCell(value), allowOverlay: true,
      readonly: true, copyData: clipboardCell(value), themeOverride: value === null ? { textDark: "#657791" } : undefined };
  }, [requestPage, revision]);

  const getCells = useCallback((rectangle: Rectangle) => async () => {
    if (rectangle.width * rectangle.height > MAX_COPY_CELLS) throw new Error("Seleção muito grande para a área de transferência; reduza para até 200 mil células.");
    const pages = new Map<number, ResultPage>();
    for (let page = Math.floor(rectangle.y / PAGE_SIZE); page <= Math.floor((rectangle.y + rectangle.height - 1) / PAGE_SIZE); page++) pages.set(page, await requestPage(page));
    return Array.from({ length: rectangle.height }, (_, y) => Array.from({ length: rectangle.width }, (_, x) => {
      const row = rectangle.y + y, page = pages.get(Math.floor(row / PAGE_SIZE))!;
      const value = page.rows[row - page.offset]?.[rectangle.x + x] ?? null;
      return { kind: GridCellKind.Text, data: clipboardCell(value), displayData: displayCell(value), readonly: true, allowOverlay: false } as GridCell;
    }));
  }, [requestPage]);

  const copyHeaders = useCallback(async () => {
    try {
      const rectangles = selectionRectangles(selection, columns.length, totalRows);
      if (!rectangles.length) { onMessage("Selecione um intervalo de células para copiar com cabeçalhos."); return; }
      if (rectangles.reduce((total, rectangle) => total + rectangle.width * rectangle.height, 0) > MAX_COPY_CELLS) throw new Error("Seleção muito grande para a área de transferência; reduza para até 200 mil células.");
      const parts: string[] = [], version = generation.current;
      for (const rectangle of rectangles) {
        const cells = await getCells(rectangle)();
        if (version !== generation.current) throw new Error("Os resultados mudaram durante a cópia. Selecione novamente.");
        const header = columns.slice(rectangle.x, rectangle.x + rectangle.width).map((column) => column.title).join("\t");
        parts.push([header, ...cells.map((row) => row.map((cell) => cell.kind === GridCellKind.Text ? cell.data : "").join("\t"))].join("\n"));
      }
      await navigator.clipboard.writeText(parts.join("\n\n"));
      onMessage(`${rectangles.reduce((count, rectangle) => count + rectangle.height, 0).toLocaleString("pt-BR")} linhas copiadas com cabeçalhos.`);
    } catch (failure) { onMessage(errorText(failure)); }
  }, [selection, columns, totalRows, getCells, onMessage]);
  const copyRef = useRef(copyHeaders); copyRef.current = copyHeaders;
  const previousCopySignal = useRef(copySignal);
  useEffect(() => {
    if (copySignal !== previousCopySignal.current) { previousCopySignal.current = copySignal; void copyRef.current(); }
  }, [copySignal]);

  return <div className="result-grid-panel">
    <div className="grid-toolbar">
      <span className="result-meta"><span className="mono">{totalRows.toLocaleString("pt-BR")}</span> linhas <span className="dim">/ {columns.length} colunas</span></span>
      <label className="grid-filter"><Filter size={13} /><input aria-label="Filtrar resultados" placeholder="Filtrar valores…" value={filter} onChange={(event) => setFilter(event.target.value)} /></label>
      {sort && <button className="text-button" onClick={() => setSort(undefined)} title="Limpar ordenação"><ArrowDownAZ size={13} />{sort.column} {sort.direction === "asc" ? "↑" : "↓"}</button>}
      {loading && <LoaderCircle className="spin" size={13} />}
      <button className="text-button" onClick={() => void copyHeaders()} title="Copiar seleção com cabeçalhos (Ctrl+Shift+C)"><Copy size={13} /> Cabeçalhos</button>
    </div>
    {error ? <div className="empty-results error-state"><p>{error}</p><button onClick={() => { pending.current.clear(); void requestPage(0).catch(() => {}); }}>Tentar novamente</button></div> : <div className="grid-canvas">
      <DataEditor key={result.result_id} width="100%" height="100%" columns={columns} rows={totalRows} getCellContent={getCellContent}
        getCellsForSelection={getCells} gridSelection={selection} onGridSelectionChange={setSelection}
        rowMarkers="number" rowHeight={30} headerHeight={34} rangeSelect="multi-rect" smoothScrollY={false}
        onVisibleRegionChanged={(range) => {
          for (let page = Math.floor(range.y / PAGE_SIZE); page <= Math.floor((range.y + range.height) / PAGE_SIZE); page++) void requestPage(page).catch(() => {});
        }}
        onColumnResize={(column, width) => setColumnWidths((previous) => ({ ...previous, [column.id ?? column.title]: width }))}
        onHeaderClicked={(index) => setSort((previous) => ({ column: columns[index].title, direction: previous?.column === columns[index].title && previous.direction === "asc" ? "desc" : "asc" }))}
        onDelete={() => false}
        theme={{ accentColor: "#3369ff", accentLight: "#1d3158", bgCell: "#0e1522", bgCellMedium: "#121b2c", bgHeader: "#161f30",
          bgHeaderHasFocus: "#1e2c46", bgHeaderHovered: "#1b2940", bgIconHeader: "#657791", textDark: "#dce5f3", textMedium: "#9caec6",
          textLight: "#657791", textHeader: "#bccbdd", borderColor: "#243047", horizontalBorderColor: "#1a2538", fontFamily: "Ubuntu, sans-serif",
          baseFontStyle: "12px", headerFontStyle: "500 12px", cellHorizontalPadding: 12 }} />
    </div>}
  </div>;
}
