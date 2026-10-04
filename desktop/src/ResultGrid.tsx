import { translate as t, useLocale, getLocale } from "./i18n";
import { featureTranslate as featureText } from "./featureTranslations";
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import DataEditor, { CompactSelection, GridCellKind, type DataEditorProps, type DataEditorRef, type GridCell, type GridColumn, type GridSelection, type Item, type Rectangle } from "@glideapps/glide-data-grid";
import "@glideapps/glide-data-grid/dist/index.css";
import { Copy, Filter, ArrowDownAZ, LoaderCircle, Settings2, X } from "lucide-react";
import { errorText, type Column, type ColumnValues, type Primitive, type ResultRef, type RuntimeTransport } from "./runtime";
import { selectionRectangles,selectedCellCount } from "./gridSelection";
import type { ColumnFilter, DataView } from "./dataTypes";
import { formatCell, type ColumnFormat, type ColumnFormats } from "./gridFormat";
import { cellSelected, MAX_COPY_CELLS, selectedLayout, type CopyFormat, type CopyTable } from "./gridClipboard";
import { formatClipboard } from "./clipboardFormatClient";
import { exportSource, requestSqlText } from "./dataExport";
import { Modal } from "./PanelControls";
import { useOwnerDocumentRevision } from "./useOwnerDocument";
import { GridPageCache, GRID_PAGE_COLUMNS, GRID_PAGE_ROWS, type GridPage, type GridTile } from "./gridPageCache";
import { GridPageScheduler, StaleGridRequest, viewportTiles } from "./gridPageScheduler";
import { pageDamage } from "./gridPageDamage";
import { GridRepaintScheduler } from "./gridRepaintScheduler";
import { ColumnHeaderPopup } from "./ColumnHeaderPopup";
import { filterSummary } from "./gridColumnFilters";
import { containsHeaderPoint, headerSortBounds } from "./gridHeaderControls";
import { reconcileGridView } from "./gridViewColumns";
import "./resultGrid.css";

const GridCanvas = memo(DataEditor);
const NO_DELETE = () => false;
const GRID_KEYBINDINGS = { copy: false } as const;
const LOADING_CELL: GridCell = { kind: GridCellKind.Loading, allowOverlay: false };
const NULL_THEME = { textDark: "#8391a5" };
const NO_COLUMN_FILTERS: ColumnFilter[] = [];
function consecutiveRuns(indexes: readonly number[], maximum: number) {
  const runs: { start: number; length: number }[] = [];
  for (const index of indexes) {
    const last = runs[runs.length - 1];
    if (last && index === last.start + last.length && last.length < maximum) last.length++;
    else runs.push({ start: index, length: 1 });
  }
  return runs;
}
const emptySelection = (): GridSelection => ({ columns: CompactSelection.empty(), rows: CompactSelection.empty() });
export const displayCell = (value: Primitive) => formatCell(value);
export const clipboardCell = (value: Primitive) => value === null ? "" : String(value).replace(/[\t\r\n]/g, " ");

export type GridView = DataView;
export interface CopySettings { copySeparator: string; nullDisplay: string }
export interface ResultGridProps { sessionId: string; result: ResultRef; transport: RuntimeTransport; onMessage: (message: string) => void; copySignal: number; onViewChange?: (view: GridView) => void; displayRowLimit?: number;
  initialView?: DataView; refreshRevision?: number;
  theme?: "dark" | "light" | "system"; uiFont?: string; uiFontSize?: number; dbType?: string;
  columnFormats?: ColumnFormats; onColumnFormatsChange?: (formats: ColumnFormats) => void;
  copySeparator?: string; nullDisplay?: string; onCopySettingsChange?: (settings: CopySettings) => void; onFontSizeChange?:(size:number)=>void;
  formatColumnRequest?: {column:string;revision:number}; onInsertSql?: (code: string) => void }

export function ResultGrid({ sessionId, result, transport, onMessage, copySignal, onViewChange, displayRowLimit = 100,
  initialView,refreshRevision=0,
  theme = "dark", uiFont = "Ubuntu", uiFontSize = 12, dbType = "postgresql", columnFormats, onColumnFormatsChange,
  copySeparator = "\t", nullDisplay = "", onCopySettingsChange,onFontSizeChange,formatColumnRequest,onInsertSql }: ResultGridProps) {
  useLocale();
  const panelRef = useRef<HTMLDivElement>(null);
  const ownerDocumentRevision = useOwnerDocumentRevision(panelRef);
  const [documentReady, setDocumentReady] = useState(false);
  useLayoutEffect(() => setDocumentReady(true), []);
  const hostDocument = panelRef.current?.ownerDocument;
  const cache = useRef(new GridPageCache());
  const editor = useRef<DataEditorRef>(null);
  const visible = useRef<Rectangle>({ x: 0, y: 0, width: Math.min(GRID_PAGE_COLUMNS, result.columns.length), height: Math.min(GRID_PAGE_ROWS, displayRowLimit, result.row_count) });
  const repaint = useRef<GridRepaintScheduler>();
  const generation = useRef(0);
  const message = useRef(onMessage); message.current = onMessage;
  const [selection, setSelection] = useState<GridSelection>(emptySelection);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [ready, setReady] = useState(false), [copying, setCopying] = useState(false);
  const restoredView = useMemo(() => reconcileGridView(initialView,result.columns),[initialView,result.columns]);
  const [filter, setFilter] = useState(restoredView?.filter?.text??""), [filterQuery, setFilterQuery] = useState(restoredView?.filter?.text??"");
  const [columnFilterState,setColumnFilters]=useState<ColumnFilter[]>(restoredView?.filter?.filters??(restoredView?.filter?.column?[{column:restoredView.filter.column,operator:restoredView.filter.operator,value:restoredView.filter.value,value_to:restoredView.filter.value_to}]:NO_COLUMN_FILTERS));
  const [headerPopup, setHeaderPopup] = useState<{index:number;anchor:Rectangle}>();
  const headerTargets = useRef(new Map<number, Rectangle>());
  const [sortState, setSort] = useState<DataView["sort"]>(restoredView?.sort);
  // Reconcile before any page/export RPC, including mutations of an existing handle.
  const validView = useMemo(() => reconcileGridView({filter:{filters:columnFilterState},sort:sortState},result.columns),[columnFilterState,sortState,result.columns]);
  const columnFilters = validView?.filter?.filters ?? NO_COLUMN_FILTERS, sort = validView?.sort;
  useEffect(() => { if (columnFilters !== columnFilterState) setColumnFilters(columnFilters); if (sort !== sortState) setSort(sort); },[columnFilters,columnFilterState,sort,sortState]);
  const [totalRows, setTotalRows] = useState(result.row_count);
  const [resultColumns, setResultColumns] = useState<Column[]>(result.columns);
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({});
  const [rowLimit, setRowLimit] = useState(displayRowLimit);
  const [fontSize,setFontSize]=useState(Math.max(7,Math.min(32,uiFontSize))),gridViewport=useRef<HTMLDivElement>(null),fontPixels=useRef(fontSize),fontChange=useRef(onFontSizeChange);
  fontPixels.current=fontSize;fontChange.current=onFontSizeChange;
  useEffect(()=>setFontSize(Math.max(7,Math.min(32,uiFontSize))),[uiFontSize]);
  useEffect(()=>{const element=gridViewport.current;if(!element)return;const zoom=(event:WheelEvent)=>{if(!(event.ctrlKey||event.metaKey)||!event.deltaY)return;event.preventDefault();const next=Math.max(7,Math.min(32,fontPixels.current+(event.deltaY<0?1:-1)));fontPixels.current=next;setFontSize(next);fontChange.current?.(next);};element.addEventListener("wheel",zoom,{passive:false});return()=>element.removeEventListener("wheel",zoom);},[!!error]);
  const [formats, setFormats] = useState<ColumnFormats>(columnFormats ?? {}), [columnDialog, setColumnDialog] = useState<number>();
  useEffect(()=>{
    if(!formatColumnRequest)return;
    const index=resultColumns.findIndex(column=>column.name===formatColumnRequest.column);
    if(index>=0)setColumnDialog(index);
  },[formatColumnRequest?.column,formatColumnRequest?.revision,result.result_id]);
  const [settingsDialog, setSettingsDialog] = useState(false), [separator, setSeparator] = useState(copySeparator), [copyNull, setCopyNull] = useState(nullDisplay);
  const [sqlDialog, setSqlDialog] = useState(false), [sqlTable, setSqlTable] = useState(result.variable_name ?? ""), [sqlError, setSqlError] = useState("");
  const formatChange = useRef(onColumnFormatsChange); formatChange.current = onColumnFormatsChange;
  const effectiveFilter = useMemo(() => columnFilters.length||filterQuery ? {text:filterQuery||undefined,filters:columnFilters}:undefined, [columnFilters, filterQuery]);
  const rectangles = useMemo(() => selectionRectangles(selection, resultColumns.length, totalRows), [selection, resultColumns.length, totalRows]);
  const viewChange = useRef(onViewChange); viewChange.current = onViewChange;
  useEffect(() => {
    const columnIndexes = [...new Set(rectangles.flatMap(r => Array.from({length:r.width},(_,i)=>r.x+i)))];
    viewChange.current?.({ filter:effectiveFilter, sort, scope: rectangles.length ? {rectangles,row_ranges:rectangles.map(r=>[r.y,r.y+r.height-1]),column_indices:columnIndexes} : undefined });
  }, [rectangles, effectiveFilter, sort]);
  useEffect(() => { setFormats(columnFormats ?? {}); }, [columnFormats]);
  useEffect(() => { setRowLimit(displayRowLimit); }, [displayRowLimit, result.result_id]);
  useEffect(() => { setSeparator(copySeparator); setCopyNull(nullDisplay); }, [copySeparator, nullDisplay]);
  const filteredColumns = useMemo(() => new Set(columnFilters.map(item => item.column)), [columnFilters]);
  const addressableColumns = useMemo(() => {
    const counts = new Map<string,number>();
    for (const column of resultColumns) counts.set(column.name,(counts.get(column.name)??0)+1);
    return new Set([...counts].filter(([,count])=>count===1).map(([name])=>name));
  }, [resultColumns]);
  const columns = useMemo<GridColumn[]>(() => resultColumns.map((column,index) => ({ title: column.name,
    id: String(index), width: columnWidths[index] ?? 175, hasMenu: true,
    icon: /bool/i.test(column.dtype) ? "headerBoolean" : /date|timestamp/i.test(column.dtype) ? "headerDate" : /int|float|decimal|number/i.test(column.dtype) ? "headerNumber" : "headerString" })), [resultColumns, columnWidths]);
  const cellContext = useRef({ formats, resultColumns, copyNull });
  cellContext.current = { formats, resultColumns, copyNull };
  const requestContext = useRef({ sessionId, resultId: result.result_id, sort, filter: effectiveFilter, transport });
  requestContext.current = { sessionId, resultId: result.result_id, sort, filter: effectiveFilter, transport };
  if (!repaint.current) repaint.current = new GridRepaintScheduler(
    () => panelRef.current?.ownerDocument.defaultView,
    regions => {
      const cells = pageDamage(regions, visible.current);
      if (cells.length) editor.current?.updateCells(cells);
    },
  );
  const queueDamage = useCallback((region: Rectangle) => repaint.current!.enqueue(region), []);
  const scheduler = useRef<GridPageScheduler<GridPage>>();
  if (!scheduler.current) scheduler.current = new GridPageScheduler<GridPage>({
    load: tile => {
      const context = requestContext.current;
      return context.transport.request<GridPage>("result.page", { session_id: context.sessionId, result_id: context.resultId,
        offset: tile.rowOffset, limit: tile.rowLimit, column_offset: tile.columnOffset, column_limit: tile.columnLimit,
        include_columns: false, sort: context.sort, filter: context.filter }).then(data => {
        if (!Array.isArray(data.rows)) throw new Error(t("Resposta de resultados inválida."));
        return data;
      });
    },
    cached: tile => cache.current.get(tile),
    receive: (data, tile) => {
      if (!cache.current.set(tile, data)) throw new Error(t("A página excede o limite de memória da grade. Reduza a visualização ou exporte os dados."));
      setTotalRows(previous => previous === data.total_rows ? previous : data.total_rows);
      setReady(true); setError("");
      queueDamage({ x: tile.columnOffset, y: data.offset, width: tile.columnLimit, height: data.rows.length });
    },
    failed: failure => { setError(errorText(failure)); message.current(errorText(failure)); },
    busy: setLoading, concurrency: 2, debounceMs: 35, maxQueued: 32,
  });
  const onVisibleRegionChanged = useCallback((range: Rectangle) => {
    visible.current = range;
    scheduler.current!.setViewport(viewportTiles(range, totalRowsRef.current, cellContext.current.resultColumns.length));
  }, []);
  const totalRowsRef = useRef(totalRows); totalRowsRef.current = Math.min(totalRows, rowLimit);
  const previousView = useRef("");
  const copyAbort = useRef<AbortController>();
  useLayoutEffect(() => {
    const key = JSON.stringify([sessionId, result.result_id, sort, effectiveFilter]);
    generation.current++; scheduler.current!.reset(); cache.current.clear(); copyAbort.current?.abort();
    const sameView = previousView.current === key;
    if (!sameView) setSelection(emptySelection());
    previousView.current = key; setReady(false); setTotalRows(result.row_count); setError("");
    setResultColumns(previous => previous.length === result.columns.length && previous.every((column, index) => column.name === result.columns[index].name && column.dtype === result.columns[index].dtype) ? previous : result.columns);
    const first = { x: 0, y: 0, width: Math.min(GRID_PAGE_COLUMNS, result.columns.length), height: Math.min(GRID_PAGE_ROWS, rowLimit, Math.max(1, result.row_count)) };
    // Even an empty filtered result must request its row count. No fetch originates from cell painting.
    const region = sameView && visible.current.width ? visible.current : first;
    visible.current = region;
    const tiles = viewportTiles(region, Math.max(1, result.row_count), result.columns.length);
    scheduler.current!.setViewport(tiles.length ? tiles : [{ rowOffset: 0, rowLimit: GRID_PAGE_ROWS, columnOffset: 0, columnLimit: Math.max(1, Math.min(GRID_PAGE_COLUMNS, result.columns.length)) }], true);
    queueDamage(region);
    return () => {
      generation.current++; scheduler.current!.reset(); copyAbort.current?.abort();
      repaint.current!.reset();
    };
  }, [sessionId, result.result_id, result.row_count, result.columns, sort, effectiveFilter, transport, refreshRevision, queueDamage]);
  useLayoutEffect(() => {
    // A cancelled frame in a closing popout may never fire. Start a fresh batch
    // in the adopted document without invalidating pages, result or view state.
    repaint.current!.reset();
    queueDamage(visible.current);
    return () => repaint.current!.reset();
  }, [ownerDocumentRevision, queueDamage]);
  useEffect(() => { const timer = setTimeout(() => setFilterQuery(filter.trim()), 250); return () => clearTimeout(timer); }, [filter]);
  useEffect(() => { queueDamage(visible.current); }, [formats, copyNull, queueDamage]);
  const retry = useCallback(() => {
    setError(""); scheduler.current!.setViewport(viewportTiles(visible.current, Math.max(1, totalRowsRef.current), cellContext.current.resultColumns.length), true);
  }, []);
  const getCellContent = useCallback(([column, row]: Item): GridCell => {
    const context = cellContext.current, cached = cache.current.value(column, row, context.resultColumns.length);
    if (!cached) return LOADING_CELL;
    const value = cached.value, text = formatCell(value, context.formats[context.resultColumns[column]?.name]);
    return { kind: GridCellKind.Text, data: text, displayData: text, allowOverlay: true, readonly: true,
      copyData: value === null ? context.copyNull : text, themeOverride: value === null ? NULL_THEME : undefined };
  }, []);

  const readSelection = useCallback(async (signal?: AbortSignal, selectedOverride?: Rectangle[]): Promise<CopyTable> => {
    const selected = selectedOverride ?? (rectangles.length ? rectangles : totalRows && columns.length ? [{ x: 0, y: 0, width: columns.length, height: totalRows }] : []);
    if (!selected.length) throw new Error(t("Não há resultados para copiar."));
    const layout = selectedLayout(selected), version = generation.current;
    const rowIndexes = new Map(layout.rows.map((row, index) => [row, index])), columnIndexes = new Map(layout.columns.map((column, index) => [column, index]));
    const rows: CopyTable["rows"] = layout.rows.map(() => Array<Primitive | undefined>(layout.columns.length).fill(undefined));
    const rowRuns = consecutiveRuns(layout.rows, GRID_PAGE_ROWS), columnRuns = consecutiveRuns(layout.columns, GRID_PAGE_COLUMNS);
    let yieldAt = performance.now() + 8;
    for (const rowRun of rowRuns) for (const columnRun of columnRuns) {
      if (signal?.aborted || version !== generation.current) throw new StaleGridRequest();
      const page = await scheduler.current!.read({ rowOffset: rowRun.start, rowLimit: rowRun.length, columnOffset: columnRun.start, columnLimit: columnRun.length }, signal);
      if (signal?.aborted || version !== generation.current) throw new StaleGridRequest();
      for (let y = 0; y < page.rows.length; y++) {
        const row = page.offset + y, values = page.rows[y], destination = rows[rowIndexes.get(row)!];
        for (let x = 0; x < values.length; x++) {
          const column = (page.column_offset ?? columnRun.start) + x;
          if (cellSelected(column, row, selected)) destination[columnIndexes.get(column)!] = values[x];
        }
      }
      if (performance.now() >= yieldAt) { await new Promise<void>(resolve => setTimeout(resolve, 0)); yieldAt = performance.now() + 8; }
    }
    return { columns: layout.columns.map(index => columns[index].title), rows };
  }, [rectangles, totalRows, columns]);
  const selectionReader = useRef(readSelection); selectionReader.current = readSelection;
  const getCells = useCallback((rectangle: Rectangle, signal: AbortSignal) => async () => {
    if (rectangle.width * rectangle.height > MAX_COPY_CELLS) throw new Error(t("Seleção muito grande para a área de transferência; reduza para até 200 mil células."));
    const table = await selectionReader.current(signal, [rectangle]), context = cellContext.current;
    return table.rows.map(row => row.map((value, x) => {
      const actual = value ?? null, text = formatCell(actual, context.formats[context.resultColumns[rectangle.x + x]?.name]);
      return { kind: GridCellKind.Text, data: actual === null ? context.copyNull : text, displayData: text, readonly: true, allowOverlay: false } as GridCell;
    }));
  }, []);
  const readSql = useCallback(async (tableName: string, signal?: AbortSignal) => {
    if (signal?.aborted) throw new StaleGridRequest();
    const version = generation.current;
    const operationId = crypto.randomUUID();
    const cancel = () => { void transport.request("result.export_cancel", { session_id: sessionId, operation_id: operationId }).catch(() => {}); };
    signal?.addEventListener("abort", cancel, { once: true });
    try {
      return await requestSqlText(transport,{...exportSource(sessionId,result.result_id,{filter:effectiveFilter,sort,scope:rectangles.length?{rectangles}:undefined},rectangles.length>0),operation_id:operationId},tableName,dbType,()=>version===generation.current&&!signal?.aborted);
    } finally { signal?.removeEventListener("abort", cancel); }
  },[sessionId,result.result_id,transport,effectiveFilter,sort,rectangles,dbType]);
  const copy = useCallback(async (format: CopyFormat="excel",headers=false,tableName?:string) => {
    if(copying||!ready) return; setCopying(true);
    const controller = new AbortController(), version = generation.current;
    copyAbort.current?.abort(); copyAbort.current = controller;
    try {
      const sql=format==="sql"?await readSql(tableName??"",controller.signal):undefined;
      const table=format==="sql"?undefined:await readSelection(controller.signal);
      const formatted=sql?undefined:await formatClipboard(table!,{format:format as "excel"|"plain"|"json",headers,separator,nullDisplay:copyNull},formats,controller.signal);
      if(controller.signal.aborted||version!==generation.current)throw new StaleGridRequest();
      const plain=sql?sql.text:formatted!.plain;
      const view=panelRef.current?.ownerDocument.defaultView as (Window & typeof globalThis)|null|undefined;
      const clipboard=view?.navigator.clipboard;
      if(!clipboard)throw new Error(t("Área de transferência indisponível nesta janela."));
      if(format==="excel"&&view?.ClipboardItem&&clipboard.write) {
        const html=formatted!.html!;
        try {await clipboard.write([new view.ClipboardItem({"text/plain":new view.Blob([plain],{type:"text/plain"}),"text/html":new view.Blob([html],{type:"text/html"})})]);} catch {await clipboard.writeText(plain);}
      } else await clipboard.writeText(plain);
      message.current(t("{count} linhas copiadas{headers} ({format}).",{count:(sql?.row_count??table!.rows.length).toLocaleString(getLocale()),headers:headers?t(" com cabeçalhos"):"",format:format==="sql"?"INSERT":format==="json"?"JSON":format==="excel"?"Excel":t("texto")}));
      if(format==="sql") {setSqlDialog(false);setSqlError("");}
    } catch(failure) {
      const text=controller.signal.aborted||failure instanceof StaleGridRequest?t("Cópia cancelada."):errorText(failure);
      if(format==="sql")setSqlError(text);message.current(text);
    } finally {if(copyAbort.current===controller){copyAbort.current=undefined;setCopying(false);}}
  },[copying,ready,readSelection,readSql,separator,copyNull,formats]);
  async function insertSelectedSql() {
    if (copying || !ready || !onInsertSql) return;
    setCopying(true); setSqlError("");
    const controller = new AbortController(), version = generation.current;
    copyAbort.current?.abort(); copyAbort.current = controller;
    try {
      const generated = await readSql(sqlTable, controller.signal);
      if (controller.signal.aborted || version !== generation.current) throw new StaleGridRequest();
      onInsertSql(generated.text); setSqlDialog(false);
    } catch (failure) {
      const text = controller.signal.aborted || failure instanceof StaleGridRequest ? t("Cópia cancelada.") : errorText(failure);
      setSqlError(text); message.current(text);
    } finally { if (copyAbort.current === controller) { copyAbort.current = undefined; setCopying(false); } }
  }
  const copyRef = useRef(copy); copyRef.current = copy;
  const previousCopySignal = useRef(copySignal);
  useEffect(() => {
    if (copySignal !== previousCopySignal.current) { previousCopySignal.current = copySignal; void copyRef.current("excel",true); }
  }, [copySignal]);
  const selectedCount = useMemo(()=>selectedCellCount(rectangles),[rectangles]);
  const light=theme==="light"||(theme==="system"&&hostDocument?.defaultView?.matchMedia("(prefers-color-scheme: light)").matches);

  const gridTheme = useMemo(() => ({ accentColor: "#3369ff", accentLight: light?"#e7edff":"#1d3158", bgCell: light?"#ffffff":"#0e1522", bgCellMedium:light?"#f8faff":"#121b2c", bgHeader:light?"#edf1f8":"#161f30",
          bgHeaderHasFocus:light?"#dfe7f5":"#1e2c46", bgHeaderHovered:light?"#e2e9f5":"#1b2940", bgIconHeader: "#657791", textDark:light?"#243047":"#dce5f3", textMedium:light?"#52627b":"#9caec6",
          textLight: "#657791", textHeader:light?"#384961":"#bccbdd", borderColor:light?"#d7dfea":"#243047", horizontalBorderColor:light?"#e7edf6":"#1a2538", fontFamily: `${uiFont}, sans-serif`,
          baseFontStyle: `${fontSize}px`, headerFontStyle: `500 ${fontSize}px`, markerFontStyle:`${fontSize-1}px`,editorFontSize:`${fontSize}px`,cellHorizontalPadding: 12 }), [light, fontSize, uiFont]);
  const columnsRef = useRef(columns); columnsRef.current = columns;
  const onColumnResize = useCallback<NonNullable<DataEditorProps["onColumnResize"]>>((column, width) => {
    const key = column.id ?? column.title;
    setColumnWidths(previous => previous[key] === width ? previous : { ...previous, [key]: width });
  }, []);
  const openHeaderPopup = useCallback((index:number, anchor?:Rectangle) => {
    const bounds = anchor ?? editor.current?.getBounds(index, -1) ?? panelRef.current?.getBoundingClientRect();
    if (bounds) setHeaderPopup({index, anchor:{x:bounds.x,y:bounds.y,width:bounds.width,height:anchor ? bounds.height : Math.min(36,bounds.height)}});
  }, []);
  useEffect(() => { setHeaderPopup(undefined); headerTargets.current.clear(); }, [sessionId,result.result_id,refreshRevision,ownerDocumentRevision]);
  const loadColumnValues = useCallback(() => transport.request<ColumnValues>("result.column_values", {
    session_id:sessionId,result_id:result.result_id,column:resultColumns[headerPopup?.index ?? -1]?.name,limit:50,
  }), [transport,sessionId,result.result_id,resultColumns,headerPopup?.index]);
  const drawHeader = useCallback<NonNullable<DataEditorProps["drawHeader"]>>((args, drawContent) => {
    if (args.columnIndex < 0) { drawContent(); return; }
    const {ctx,rect,menuBounds,columnIndex,theme} = args;
    const sortBounds = addressableColumns.has(args.column.title) ? headerSortBounds(rect,menuBounds) : undefined;
    const menuOnLeft = menuBounds.x < rect.x + rect.width/2;
    if (sortBounds) headerTargets.current.set(columnIndex, {...sortBounds,x:sortBounds.x-rect.x,y:sortBounds.y-rect.y});
    else headerTargets.current.delete(columnIndex);
    // Clip the column title before the independent sort/filter targets.
    ctx.save(); ctx.beginPath();
    const textStart = menuOnLeft ? (sortBounds?.x ?? menuBounds.x) + (sortBounds?.width ?? menuBounds.width) : rect.x;
    const textEnd = menuOnLeft ? rect.x + rect.width : sortBounds?.x ?? menuBounds.x;
    ctx.rect(textStart,rect.y,Math.max(0,textEnd-textStart),rect.height); ctx.clip(); drawContent(); ctx.restore();
    const filtered = filteredColumns.has(args.column.title), direction = sort?.column === args.column.title ? sort.direction : undefined;
    ctx.save(); ctx.lineWidth=1.5; ctx.lineCap="round"; ctx.lineJoin="round";
    if (sortBounds && (args.isHovered || args.isSelected || direction)) {
      const x=sortBounds.x+sortBounds.width/2,y=sortBounds.y+sortBounds.height/2,up=direction!=="desc";
      ctx.strokeStyle=direction?theme.accentColor:theme.textLight; ctx.beginPath();
      ctx.moveTo(x,y-5);ctx.lineTo(x,y+5);
      ctx.moveTo(x-4,up?y-1:y+1);ctx.lineTo(x,up?y-5:y+5);ctx.lineTo(x+4,up?y-1:y+1);ctx.stroke();
    }
    if (args.isHovered || args.isSelected || filtered) {
      const x=menuBounds.x+menuBounds.width/2,y=menuBounds.y+menuBounds.height/2;
      ctx.strokeStyle=filtered?theme.accentColor:theme.textHeader;ctx.beginPath();
      ctx.moveTo(x-6,y-5);ctx.lineTo(x+6,y-5);ctx.lineTo(x+2,y);ctx.lineTo(x+2,y+5);ctx.lineTo(x-2,y+3);ctx.lineTo(x-2,y);ctx.closePath();ctx.stroke();
    }
    ctx.restore();
  }, [filteredColumns,sort,addressableColumns]);
  const onHeaderClicked = useCallback<NonNullable<DataEditorProps["onHeaderClicked"]>>((index, event) => {
    const column = columnsRef.current[index];
    if (!column || !addressableColumns.has(column.title) || event.isEdge || event.ctrlKey || event.metaKey || event.shiftKey || !containsHeaderPoint(headerTargets.current.get(index),event.localEventX,event.localEventY)) return;
    event.preventDefault();
    setSort(previous => ({ column: column.title, direction: previous?.column === column.title && previous.direction === "asc" ? "desc" : "asc" }));
  }, [addressableColumns]);
  const onHeaderMenuClick = useCallback<NonNullable<DataEditorProps["onHeaderMenuClick"]>>((index, bounds) => openHeaderPopup(index,bounds), [openHeaderPopup]);
  const onHeaderContextMenu = useCallback<NonNullable<DataEditorProps["onHeaderContextMenu"]>>((index, event) => { event.preventDefault(); openHeaderPopup(index,event.bounds); }, [openHeaderPopup]);
  const onCellContextMenu = useCallback<NonNullable<DataEditorProps["onCellContextMenu"]>>((cell, event) => { event.preventDefault(); openHeaderPopup(cell[0]); }, [openHeaderPopup]);

  return <div ref={panelRef} className="result-grid-panel">
    <div className="grid-toolbar">
      <span className="result-meta"><span className="mono">{totalRows.toLocaleString(getLocale())}</span> {t("linhas")} <span className="dim">/ {columns.length} {t("colunas")}</span></span>
      {totalRows > rowLimit && <button className="text-button" title={t("Carregar todas as linhas na grade virtualizada")} onClick={()=>setRowLimit(totalRows)}>{t("Exibindo")} {rowLimit} {t("· Mostrar todas")}</button>}
      <label className="grid-filter"><Filter size={13} /><input aria-label={t("Filtrar resultados")} placeholder={t("Filtrar valores…")} value={filter} onChange={(event) => {setFilter(event.target.value);}} /></label>
      {columnFilters.length>0&&<div className="grid-filter-chips">{[...filteredColumns].map(column=><span className="grid-filter-chip" key={column}><button className="text-button" title={filterSummary(columnFilters.filter(item=>item.column===column),getLocale())} onClick={()=>openHeaderPopup(resultColumns.findIndex(item=>item.name===column))}><Filter size={13}/>{filterSummary(columnFilters.filter(item=>item.column===column),getLocale())}</button><button className="text-button" aria-label={`${t("Limpar filtro da coluna")} · ${column}`} onClick={()=>setColumnFilters(previous=>previous.filter(filter=>filter.column!==column))}><X size={12}/></button></span>)}</div>}
      {(columnFilters.length>0||filter)&&<button className="text-button" title={featureText("Limpar todos os filtros")} aria-label={featureText("Limpar todos os filtros")} onClick={()=>{setColumnFilters([]);setFilter("");setFilterQuery("");}}><X size={13}/></button>}
      {sort && <button className="text-button" onClick={() => setSort(undefined)} title={t("Limpar ordenação")}><ArrowDownAZ size={13} />{sort.column} {sort.direction === "asc" ? "↑" : "↓"}</button>}
      {loading && <LoaderCircle className="spin" size={13} />}
      {copying && <button className="text-button" onClick={() => copyAbort.current?.abort()} title={t("Cancelar")}><X size={13}/>{t("Cancelar")}</button>}
      <button className="text-button" disabled={!columns.length} onClick={()=>openHeaderPopup(selection.current?.cell[0]??selection.columns.first()??0)} title={t("Formatar ou filtrar uma coluna; clique direito no cabeçalho")}><Settings2 size={13}/>{t("Coluna")}</button>
      <button className="text-button" disabled={copying||!ready} onClick={() => void copy("excel",true)} title={t("Copiar seleção com cabeçalhos (Ctrl+Shift+C)")}><Copy size={13} /> {t("Cabeçalhos")}</button>
      <details className="grid-copy-menu"><summary title={t("Copiar resultados")}>{copying?<LoaderCircle className="spin" size={13}/>:<Copy size={13}/>}{t("Copiar ▾")}</summary><div>
        <button disabled={copying||!ready} onClick={()=>void copy("excel")}>Excel · Ctrl+C</button><button disabled={copying||!ready} onClick={()=>void copy("plain")}>{t("Texto delimitado")}</button><button disabled={copying||!ready} onClick={()=>void copy("json")}>{t("JSON")}</button><button disabled={copying||!ready} onClick={()=>{setSqlError("");setSqlDialog(true);}}>SQL INSERT…</button><button onClick={()=>setSettingsDialog(true)}>{t("Preferências de cópia…")}</button>
      </div></details>
    </div>
    {error ? <div className="empty-results error-state"><p>{t(error)}</p><button onClick={retry}>{t("Tentar novamente")}</button></div> : <div ref={gridViewport} className="grid-canvas" onKeyDownCapture={event=>{const target=event.target as HTMLElement;if(!(event.ctrlKey||event.metaKey)||event.key.toLowerCase()!=="c"||event.altKey||target.tagName==="INPUT"||target.tagName==="TEXTAREA"||target.isContentEditable)return;event.preventDefault();event.stopPropagation();void copy("excel",event.shiftKey);}}>
      {documentReady&&hostDocument&&<GridCanvas ref={editor} key={`${result.result_id}:${ownerDocumentRevision}`} ownerDocument={hostDocument} width="100%" height="100%" columns={columns} rows={Math.min(totalRows,rowLimit)} getCellContent={getCellContent}
        getCellsForSelection={getCells} gridSelection={selection} onGridSelectionChange={setSelection}
        rowMarkers="number" rowHeight={Math.max(30,fontSize+14)} headerHeight={Math.max(34,fontSize+18)} rangeSelect="multi-rect" smoothScrollY={false} keybindings={GRID_KEYBINDINGS}
        onVisibleRegionChanged={onVisibleRegionChanged}
        onColumnResize={onColumnResize}
        onHeaderClicked={onHeaderClicked}
        onHeaderMenuClick={onHeaderMenuClick}
        drawHeader={drawHeader}
        onHeaderContextMenu={onHeaderContextMenu}
        onCellContextMenu={onCellContextMenu}
        onDelete={NO_DELETE}
        theme={gridTheme} />}
    </div>}
    <div className="grid-selection-status" aria-live="polite">{selectedCount?t("{count} células selecionadas",{count:selectedCount.toLocaleString(getLocale())}):t("Ctrl+C: copiar · Shift+clique: intervalo · Ctrl+clique: múltiplos intervalos")}{copying&&t(" · Copiando…")}</div>
    {headerPopup&&hostDocument&&resultColumns[headerPopup.index]&&<ColumnHeaderPopup key={`${result.result_id}:${headerPopup.index}:${refreshRevision}:${ownerDocumentRevision}`} ownerDocument={hostDocument} anchor={headerPopup.anchor} column={resultColumns[headerPopup.index]} filters={columnFilters} sortDirection={sort?.column===resultColumns[headerPopup.index].name?sort.direction:undefined} locale={getLocale()} loadValues={addressableColumns.has(resultColumns[headerPopup.index].name)?loadColumnValues:undefined} filterDisabledReason={addressableColumns.has(resultColumns[headerPopup.index].name)?undefined:featureText("Renomeie as colunas com nomes repetidos para filtrar ou ordenar.")} onClose={()=>setHeaderPopup(undefined)} onApply={setColumnFilters}
      onSort={direction=>setSort(direction?{column:resultColumns[headerPopup.index].name,direction}:undefined)} onFormat={()=>setColumnDialog(headerPopup.index)}
      onCopyName={()=>{const clipboard=hostDocument.defaultView?.navigator.clipboard;if(!clipboard){message.current(t("Área de transferência indisponível nesta janela."));return;}void clipboard.writeText(resultColumns[headerPopup.index].name).catch(failure=>message.current(errorText(failure)));}}/>}
    {columnDialog!==undefined&&resultColumns[columnDialog]&&<ColumnDialog key={`${result.result_id}:${columnDialog}`} column={resultColumns[columnDialog]} format={formats[resultColumns[columnDialog].name]} onClose={()=>setColumnDialog(undefined)}
      onFormat={format=>{const next={...formats};if(format.type==="default")delete next[resultColumns[columnDialog].name];else next[resultColumns[columnDialog].name]=format;setFormats(next);formatChange.current?.(next);setColumnDialog(undefined);}}/>}
    {settingsDialog&&<Modal title={t("Preferências de cópia")} onClose={()=>setSettingsDialog(false)} className="grid-settings-modal"><div className="grid-settings-body"><label>{t("Separador")}<select value={separator} onChange={event=>setSeparator(event.target.value)}><option value={"\t"}>{t("Tabulação · Excel")}</option><option value=",">{t("Vírgula")}</option><option value=";">{t("Ponto e vírgula")}</option></select></label><label>{t("Valores nulos")}<select value={copyNull} onChange={event=>setCopyNull(event.target.value)}><option value="">{t("Em branco")}</option><option value="NULL">{t("NULL")}</option><option value="None">{t("None")}</option></select></label><p>{t("Texto e Excel usam a formatação visível. JSON e INSERT preservam os valores originais. Sem seleção, a cópia usa todas as linhas filtradas.")}</p></div><footer><button onClick={()=>{onCopySettingsChange?.({copySeparator:separator,nullDisplay:copyNull});setSettingsDialog(false);}}>{t("Salvar")}</button></footer></Modal>}
    {sqlDialog&&<Modal title={t("Copiar como SQL INSERT")} onClose={()=>{if(!copying)setSqlDialog(false);}} className="grid-settings-modal"><div className="grid-settings-body"><label>{t("Tabela de destino")}<input autoFocus value={sqlTable} onChange={event=>setSqlTable(event.target.value)} placeholder="schema.tabela"/></label><p>{t("Os comandos serão copiados para revisão.")}</p>{sqlError&&<p className="data-error" role="alert">{t(sqlError)}</p>}</div><footer><button disabled={copying} onClick={()=>setSqlDialog(false)}>{t("Cancelar")}</button>{onInsertSql&&<button disabled={copying||!sqlTable.trim()} onClick={()=>void insertSelectedSql()}>{featureText("Inserir em novo bloco")}</button>}<button disabled={copying||!sqlTable.trim()} onClick={()=>void copy("sql",false,sqlTable)}>{copying?t("Copiando…"):t("Copiar INSERT")}</button></footer></Modal>}
  </div>;
}

function ColumnDialog({column,format,onClose,onFormat}:{column:Column;format?:ColumnFormat;onClose:()=>void;onFormat:(format:ColumnFormat)=>void}) {
  useLocale();
  const [draft,setDraft]=useState<ColumnFormat>(format??{type:"default",decimals:2});
  const numeric=["number","currency","percent"].includes(draft.type);
  return <Modal title={t("Coluna · {name}",{name:column.name})} onClose={onClose} className="grid-settings-modal"><div className="grid-settings-body"><p className="dim">{column.dtype}</p><label>{t("Formato")}<select value={draft.type} onChange={event=>setDraft(previous=>({...previous,type:event.target.value as ColumnFormat["type"]}))}><option value="default">{t("Padrão")}</option><option value="number">{t("Número")}</option><option value="currency">{t("Moeda")}</option><option value="percent">{t("Percentual")}</option><option value="date">{t("Data · YYYY-MM-DD")}</option><option value="datetime">{t("Data e hora · YYYY-MM-DD HH:MM:SS")}</option></select></label>
    {numeric&&<><label>{t("Casas decimais")}<input type="number" min="0" max="8" value={draft.decimals??2} onChange={event=>setDraft(previous=>({...previous,decimals:Math.max(0,Math.min(8,Number(event.target.value)))}))}/></label><div className="grid-format-affixes"><label>{t("Prefixo")}<input value={draft.prefix??(draft.type==="currency"?"$ ":"")} onChange={event=>setDraft(previous=>({...previous,prefix:event.target.value}))} placeholder="R$ "/></label><label>{t("Sufixo")}<input value={draft.suffix??(draft.type==="percent"?"%":"")} onChange={event=>setDraft(previous=>({...previous,suffix:event.target.value}))}/></label></div></>}
    <button className="grid-modal-action" onClick={()=>onFormat(draft)}>{t("Aplicar formato")}</button>
  </div></Modal>;
}
