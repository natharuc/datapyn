import { translate as t, useLocale, getLocale } from "./i18n";
import { featureTranslate as featureText } from "./featureTranslations";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import DataEditor, { CompactSelection, GridCellKind, type GridCell, type GridColumn, type GridSelection, type Item, type Rectangle } from "@glideapps/glide-data-grid";
import "@glideapps/glide-data-grid/dist/index.css";
import { Copy, Filter, ArrowDownAZ, LoaderCircle, Settings2, X } from "lucide-react";
import { errorText, type Column, type Primitive, type ResultPage, type ResultRef, type RuntimeTransport } from "./runtime";
import { selectionRectangles,selectedCellCount } from "./gridSelection";
import type { DataView } from "./dataTypes";
import { formatCell, type ColumnFormat, type ColumnFormats } from "./gridFormat";
import { boundedClipboard, cellSelected, htmlClipboard, jsonClipboard, MAX_COPY_CELLS, plainClipboard, selectedLayout, type CopyFormat, type CopyTable } from "./gridClipboard";
import { exportSource, requestSqlText } from "./dataExport";
import { Modal } from "./PanelControls";
import { useOwnerDocumentRevision } from "./useOwnerDocument";
import "./resultGrid.css";

const PAGE_SIZE = 200;
const CACHE_PAGES = 40;
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
  const cache = useRef(new Map<number, ResultPage>()), pending = useRef(new Map<number, Promise<ResultPage>>());
  const generation = useRef(0);
  const message = useRef(onMessage); message.current = onMessage;
  const [revision, setRevision] = useState(0), [selection, setSelection] = useState<GridSelection>(emptySelection);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [ready, setReady] = useState(false), [copying, setCopying] = useState(false);
  const [filter, setFilter] = useState(initialView?.filter?.text??""), [filterQuery, setFilterQuery] = useState(initialView?.filter?.text??"");
  const [columnFilters,setColumnFilters]=useState<NonNullable<NonNullable<DataView["filter"]>["filters"]>>(initialView?.filter?.filters??(initialView?.filter?.column?[{column:initialView.filter.column,operator:initialView.filter.operator,value:initialView.filter.value}]:[]));
  const [sort, setSort] = useState<{ column: string; direction: "asc" | "desc" }|undefined>(initialView?.sort);
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
  const columns = useMemo<GridColumn[]>(() => resultColumns.map((column,index) => ({ title: column.name,
    id: String(index), width: columnWidths[index] ?? 175, icon: /int|float|decimal|number/i.test(column.dtype) ? "headerNumber" : "headerString" })), [resultColumns, columnWidths]);
  const requestPage = useCallback((page: number): Promise<ResultPage> => {
    const saved = cache.current.get(page); if (saved) return Promise.resolve(saved);
    const inflight = pending.current.get(page); if (inflight) return inflight;
    const version = generation.current; setLoading(true);
    const promise = transport.request<ResultPage>("result.page", { session_id: sessionId, result_id: result.result_id,
      offset: page * PAGE_SIZE, limit: PAGE_SIZE, sort, filter: effectiveFilter }).then((data) => {
      if (version !== generation.current) return data;
      if (!Array.isArray(data.rows)) throw new Error(t("Resposta de resultados inválida."));
      if (cache.current.size >= CACHE_PAGES) cache.current.delete(cache.current.keys().next().value!);
      cache.current.set(page, data); setTotalRows(data.total_rows); setResultColumns(data.columns); setRevision((value) => value + 1); setError("");
      if (page === 0) setReady(true);
      return data;
    }).catch((failure) => {
      if (version === generation.current) { setError(errorText(failure)); message.current(errorText(failure)); }
      throw failure;
    }).finally(() => { if (version === generation.current) { pending.current.delete(page); setLoading(pending.current.size > 0); } });
    pending.current.set(page, promise); return promise;
  }, [sessionId, result.result_id, sort, effectiveFilter, transport]);

  const previousView=useRef("");
  useEffect(() => {
    const key=JSON.stringify([sessionId,result.result_id,sort,effectiveFilter]);
    generation.current++; cache.current.clear(); pending.current.clear(); if(previousView.current!==key)setSelection(emptySelection()); previousView.current=key; setReady(false);
    setTotalRows(result.row_count); setResultColumns(result.columns); setError(""); void requestPage(0).catch(() => {});
    return () => { generation.current++; };
  }, [requestPage, result.row_count,refreshRevision]);
  useEffect(() => { const timer = setTimeout(() => setFilterQuery(filter.trim()), 250); return () => clearTimeout(timer); }, [filter]);

  const getCellContent = useCallback(([column, row]: Item): GridCell => {
    const pageIndex = Math.floor(row / PAGE_SIZE), page = cache.current.get(pageIndex);
    if (!page) { void requestPage(pageIndex).catch(() => {}); return { kind: GridCellKind.Loading, allowOverlay: false }; }
    const value = page.rows[row - page.offset]?.[column] ?? null;
    const text = formatCell(value, formats[resultColumns[column]?.name]);
    return { kind: GridCellKind.Text, data: text, displayData: text, allowOverlay: true,
      readonly: true, copyData: formatCell(value,formats[resultColumns[column]?.name],copyNull), themeOverride: value === null ? { textDark: "#8391a5" } : undefined };
  }, [requestPage, revision,formats,resultColumns,copyNull]);

  const getCells = useCallback((rectangle: Rectangle) => async () => {
    if (rectangle.width * rectangle.height > MAX_COPY_CELLS) throw new Error(t("Seleção muito grande para a área de transferência; reduza para até 200 mil células."));
    const pages = new Map<number, ResultPage>(), version = generation.current;
    for (let page = Math.floor(rectangle.y / PAGE_SIZE); page <= Math.floor((rectangle.y + rectangle.height - 1) / PAGE_SIZE); page++) { pages.set(page, await requestPage(page)); if(version!==generation.current) throw new Error(t("Os resultados mudaram durante a cópia. Selecione novamente.")); }
    return Array.from({ length: rectangle.height }, (_, y) => Array.from({ length: rectangle.width }, (_, x) => {
      const row = rectangle.y + y, page = pages.get(Math.floor(row / PAGE_SIZE))!;
      const value = page.rows[row - page.offset]?.[rectangle.x + x] ?? null;
      return { kind: GridCellKind.Text, data: formatCell(value,formats[resultColumns[rectangle.x+x]?.name],copyNull), displayData: formatCell(value,formats[resultColumns[rectangle.x+x]?.name]), readonly: true, allowOverlay: false } as GridCell;
    }));
  }, [requestPage,formats,resultColumns,copyNull]);

  const readSelection = useCallback(async (): Promise<CopyTable> => {
    const selected = rectangles.length ? rectangles : totalRows && columns.length ? [{x:0,y:0,width:columns.length,height:totalRows}] : [];
    if (!selected.length) throw new Error(t("Não há resultados para copiar."));
    const layout = selectedLayout(selected), version = generation.current, pages = new Map<number,ResultPage>();
    const pageIndexes = [...new Set(layout.rows.map(row=>Math.floor(row/PAGE_SIZE)))];
    for(let first=0;first<pageIndexes.length;first+=4) {
      const batch = await Promise.all(pageIndexes.slice(first,first+4).map(async index=>[index,await requestPage(index)] as const));
      if(version!==generation.current) throw new Error(t("Os resultados mudaram durante a cópia. Selecione novamente."));
      batch.forEach(([index,page])=>pages.set(index,page));
    }
    return {columns:layout.columns.map(index=>columns[index].title),rows:layout.rows.map(row=>{const page=pages.get(Math.floor(row/PAGE_SIZE))!;return layout.columns.map(column=>cellSelected(column,row,selected)?page.rows[row-page.offset]?.[column]??null:undefined);})};
  },[rectangles,totalRows,columns,requestPage]);
  const readSql = useCallback(async (tableName: string) => {
    const version = generation.current;
    return requestSqlText(transport,exportSource(sessionId,result.result_id,{filter:effectiveFilter,sort,scope:rectangles.length?{rectangles}:undefined},rectangles.length>0),tableName,dbType,()=>version===generation.current);
  },[sessionId,result.result_id,transport,effectiveFilter,sort,rectangles,dbType]);
  const copy = useCallback(async (format: CopyFormat="excel",headers=false,tableName?:string) => {
    if(copying||!ready) return; setCopying(true);
    try {
      const sql=format==="sql"?await readSql(tableName??""):undefined;
      const table=format==="sql"?undefined:await readSelection(),options={headers,separator,nullDisplay:copyNull,formats};
      const plain=sql?sql.text:boundedClipboard(format==="json"?jsonClipboard(table!):plainClipboard(table!,options));
      const view=panelRef.current?.ownerDocument.defaultView as (Window & typeof globalThis)|null|undefined;
      const clipboard=view?.navigator.clipboard;
      if(!clipboard)throw new Error(t("Área de transferência indisponível nesta janela."));
      if(format==="excel"&&view?.ClipboardItem&&clipboard.write) {
        const html=boundedClipboard(htmlClipboard(table!,options));
        try {await clipboard.write([new view.ClipboardItem({"text/plain":new view.Blob([plain],{type:"text/plain"}),"text/html":new view.Blob([html],{type:"text/html"})})]);} catch {await clipboard.writeText(plain);}
      } else await clipboard.writeText(plain);
      message.current(t("{count} linhas copiadas{headers} ({format}).",{count:(sql?.row_count??table!.rows.length).toLocaleString(getLocale()),headers:headers?t(" com cabeçalhos"):"",format:format==="sql"?"INSERT":format==="json"?"JSON":format==="excel"?"Excel":t("texto")}));
      if(format==="sql") {setSqlDialog(false);setSqlError("");}
    } catch(failure) {if(format==="sql")setSqlError(errorText(failure));message.current(errorText(failure));} finally {setCopying(false);}
  },[copying,ready,readSelection,readSql,separator,copyNull,formats]);
  async function insertSelectedSql() {
    if (copying || !ready || !onInsertSql) return;
    setCopying(true); setSqlError("");
    try { onInsertSql((await readSql(sqlTable)).text); setSqlDialog(false); }
    catch (failure) {setSqlError(errorText(failure));message.current(errorText(failure));}
    finally {setCopying(false);}
  }
  const copyRef = useRef(copy); copyRef.current = copy;
  const previousCopySignal = useRef(copySignal);
  useEffect(() => {
    if (copySignal !== previousCopySignal.current) { previousCopySignal.current = copySignal; void copyRef.current("excel",true); }
  }, [copySignal]);
  const selectedCount = useMemo(()=>selectedCellCount(rectangles),[rectangles]);
  const light=theme==="light"||(theme==="system"&&hostDocument?.defaultView?.matchMedia("(prefers-color-scheme: light)").matches);

  return <div ref={panelRef} className="result-grid-panel">
    <div className="grid-toolbar">
      <span className="result-meta"><span className="mono">{totalRows.toLocaleString(getLocale())}</span> {t("linhas")} <span className="dim">/ {columns.length} {t("colunas")}</span></span>
      {totalRows > rowLimit && <button className="text-button" title={t("Carregar todas as linhas na grade virtualizada")} onClick={()=>setRowLimit(totalRows)}>{t("Exibindo")} {rowLimit} {t("· Mostrar todas")}</button>}
      <label className="grid-filter"><Filter size={13} /><input aria-label={t("Filtrar resultados")} placeholder={t("Filtrar valores…")} value={filter} onChange={(event) => {setFilter(event.target.value);}} /></label>
      {columnFilters.length>0&&<div className="grid-filter-chips">{columnFilters.map(item=><button key={item.column} className="text-button" title={`${t("Limpar filtro da coluna")} · ${item.operator}: ${item.value??""}`} onClick={()=>setColumnFilters(previous=>previous.filter(filter=>filter.column!==item.column))}><Filter size={13}/>{item.column}<X size={12}/></button>)}</div>}
      {sort && <button className="text-button" onClick={() => setSort(undefined)} title={t("Limpar ordenação")}><ArrowDownAZ size={13} />{sort.column} {sort.direction === "asc" ? "↑" : "↓"}</button>}
      {loading && <LoaderCircle className="spin" size={13} />}
      <button className="text-button" disabled={!columns.length} onClick={()=>setColumnDialog(selection.current?.cell[0]??0)} title={t("Formatar ou filtrar uma coluna; clique direito no cabeçalho")}><Settings2 size={13}/>{t("Coluna")}</button>
      <button className="text-button" disabled={copying||!ready} onClick={() => void copy("excel",true)} title={t("Copiar seleção com cabeçalhos (Ctrl+Shift+C)")}><Copy size={13} /> {t("Cabeçalhos")}</button>
      <details className="grid-copy-menu"><summary title={t("Copiar resultados")}>{copying?<LoaderCircle className="spin" size={13}/>:<Copy size={13}/>}{t("Copiar ▾")}</summary><div>
        <button disabled={copying||!ready} onClick={()=>void copy("excel")}>Excel · Ctrl+C</button><button disabled={copying||!ready} onClick={()=>void copy("plain")}>{t("Texto delimitado")}</button><button disabled={copying||!ready} onClick={()=>void copy("json")}>{t("JSON")}</button><button disabled={copying||!ready} onClick={()=>{setSqlError("");setSqlDialog(true);}}>SQL INSERT…</button><button onClick={()=>setSettingsDialog(true)}>{t("Preferências de cópia…")}</button>
      </div></details>
    </div>
    {error ? <div className="empty-results error-state"><p>{t(error)}</p><button onClick={() => { pending.current.clear(); void requestPage(0).catch(() => {}); }}>{t("Tentar novamente")}</button></div> : <div ref={gridViewport} className="grid-canvas" onKeyDownCapture={event=>{const target=event.target as HTMLElement;if(!(event.ctrlKey||event.metaKey)||event.key.toLowerCase()!=="c"||event.altKey||target.tagName==="INPUT"||target.tagName==="TEXTAREA"||target.isContentEditable)return;event.preventDefault();event.stopPropagation();void copy("excel",event.shiftKey);}}>
      {documentReady&&hostDocument&&<DataEditor key={`${result.result_id}:${ownerDocumentRevision}`} ownerDocument={hostDocument} width="100%" height="100%" columns={columns} rows={Math.min(totalRows,rowLimit)} getCellContent={getCellContent}
        getCellsForSelection={getCells} gridSelection={selection} onGridSelectionChange={setSelection}
        rowMarkers="number" rowHeight={Math.max(30,fontSize+14)} headerHeight={Math.max(34,fontSize+18)} rangeSelect="multi-rect" smoothScrollY={false} keybindings={{copy:false}}
        onVisibleRegionChanged={(range) => {
          if(range.height) for (let page = Math.floor(range.y / PAGE_SIZE); page <= Math.floor((range.y + range.height-1) / PAGE_SIZE); page++) void requestPage(page).catch(() => {});
        }}
        onColumnResize={(column, width) => setColumnWidths((previous) => ({ ...previous, [column.id ?? column.title]: width }))}
        onHeaderClicked={(index,event) => {if(!columns[index]||event.ctrlKey||event.metaKey||event.shiftKey)return;setSort((previous) => ({ column: columns[index].title, direction: previous?.column === columns[index].title && previous.direction === "asc" ? "desc" : "asc" }));}}
        onHeaderContextMenu={(index,event)=>{event.preventDefault();setColumnDialog(index);}}
        onCellContextMenu={(cell,event)=>{event.preventDefault();setColumnDialog(cell[0]);}}
        onDelete={() => false}
        theme={{ accentColor: "#3369ff", accentLight: light?"#e7edff":"#1d3158", bgCell: light?"#ffffff":"#0e1522", bgCellMedium:light?"#f8faff":"#121b2c", bgHeader:light?"#edf1f8":"#161f30",
          bgHeaderHasFocus:light?"#dfe7f5":"#1e2c46", bgHeaderHovered:light?"#e2e9f5":"#1b2940", bgIconHeader: "#657791", textDark:light?"#243047":"#dce5f3", textMedium:light?"#52627b":"#9caec6",
          textLight: "#657791", textHeader:light?"#384961":"#bccbdd", borderColor:light?"#d7dfea":"#243047", horizontalBorderColor:light?"#e7edf6":"#1a2538", fontFamily: `${uiFont}, sans-serif`,
          baseFontStyle: `${fontSize}px`, headerFontStyle: `500 ${fontSize}px`, markerFontStyle:`${fontSize-1}px`,editorFontSize:`${fontSize}px`,cellHorizontalPadding: 12 }} />}
    </div>}
    <div className="grid-selection-status" aria-live="polite">{selectedCount?t("{count} células selecionadas",{count:selectedCount.toLocaleString(getLocale())}):t("Ctrl+C: copiar · Shift+clique: intervalo · Ctrl+clique: múltiplos intervalos")}{copying&&t(" · Copiando…")}</div>
    {columnDialog!==undefined&&resultColumns[columnDialog]&&<ColumnDialog key={`${result.result_id}:${columnDialog}`} column={resultColumns[columnDialog]} format={formats[resultColumns[columnDialog].name]} currentFilter={columnFilters.find(item=>item.column===resultColumns[columnDialog].name)} onClose={()=>setColumnDialog(undefined)}
      onFormat={format=>{const next={...formats};if(format.type==="default")delete next[resultColumns[columnDialog].name];else next[resultColumns[columnDialog].name]=format;setFormats(next);formatChange.current?.(next);setColumnDialog(undefined);}}
      onFilter={next=>{setColumnFilters(previous=>{const kept=previous.filter(item=>item.column!==resultColumns[columnDialog].name);return next?.column?[...kept,{column:next.column,operator:next.operator,value:next.value}]:kept;});setColumnDialog(undefined);}}/>}
    {settingsDialog&&<Modal title={t("Preferências de cópia")} onClose={()=>setSettingsDialog(false)} className="grid-settings-modal"><div className="grid-settings-body"><label>{t("Separador")}<select value={separator} onChange={event=>setSeparator(event.target.value)}><option value={"\t"}>{t("Tabulação · Excel")}</option><option value=",">{t("Vírgula")}</option><option value=";">{t("Ponto e vírgula")}</option></select></label><label>{t("Valores nulos")}<select value={copyNull} onChange={event=>setCopyNull(event.target.value)}><option value="">{t("Em branco")}</option><option value="NULL">{t("NULL")}</option><option value="None">{t("None")}</option></select></label><p>{t("Texto e Excel usam a formatação visível. JSON e INSERT preservam os valores originais. Sem seleção, a cópia usa todas as linhas filtradas.")}</p></div><footer><button onClick={()=>{onCopySettingsChange?.({copySeparator:separator,nullDisplay:copyNull});setSettingsDialog(false);}}>{t("Salvar")}</button></footer></Modal>}
    {sqlDialog&&<Modal title={t("Copiar como SQL INSERT")} onClose={()=>{if(!copying)setSqlDialog(false);}} className="grid-settings-modal"><div className="grid-settings-body"><label>{t("Tabela de destino")}<input autoFocus value={sqlTable} onChange={event=>setSqlTable(event.target.value)} placeholder="schema.tabela"/></label><p>{t("Os comandos serão copiados para revisão.")}</p>{sqlError&&<p className="data-error" role="alert">{t(sqlError)}</p>}</div><footer><button disabled={copying} onClick={()=>setSqlDialog(false)}>{t("Cancelar")}</button>{onInsertSql&&<button disabled={copying||!sqlTable.trim()} onClick={()=>void insertSelectedSql()}>{featureText("Inserir em novo bloco")}</button>}<button disabled={copying||!sqlTable.trim()} onClick={()=>void copy("sql",false,sqlTable)}>{copying?t("Copiando…"):t("Copiar INSERT")}</button></footer></Modal>}
  </div>;
}

function ColumnDialog({column,format,currentFilter,onClose,onFormat,onFilter}:{column:Column;format?:ColumnFormat;currentFilter?:DataView["filter"];onClose:()=>void;onFormat:(format:ColumnFormat)=>void;onFilter:(filter:DataView["filter"])=>void}) {
  useLocale();
  const [draft,setDraft]=useState<ColumnFormat>(format??{type:"default",decimals:2});
  const [operator,setOperator]=useState(currentFilter?.column===column.name?currentFilter.operator??"contains":"contains"),[value,setValue]=useState(currentFilter?.column===column.name?String(currentFilter.value??""):"");
  const numeric=["number","currency","percent"].includes(draft.type);
  const nullOperator=operator==="is_null"||operator==="not_null",booleanColumn=/bool/i.test(column.dtype),dateColumn=/date|timestamp/i.test(column.dtype);
  return <Modal title={t("Coluna · {name}",{name:column.name})} onClose={onClose} className="grid-settings-modal"><div className="grid-settings-body"><p className="dim">{column.dtype}</p><label>{t("Formato")}<select value={draft.type} onChange={event=>setDraft(previous=>({...previous,type:event.target.value as ColumnFormat["type"]}))}><option value="default">{t("Padrão")}</option><option value="number">{t("Número")}</option><option value="currency">{t("Moeda")}</option><option value="percent">{t("Percentual")}</option><option value="date">{t("Data · YYYY-MM-DD")}</option><option value="datetime">{t("Data e hora · YYYY-MM-DD HH:MM:SS")}</option></select></label>
    {numeric&&<><label>{t("Casas decimais")}<input type="number" min="0" max="8" value={draft.decimals??2} onChange={event=>setDraft(previous=>({...previous,decimals:Math.max(0,Math.min(8,Number(event.target.value)))}))}/></label><div className="grid-format-affixes"><label>{t("Prefixo")}<input value={draft.prefix??(draft.type==="currency"?"$ ":"")} onChange={event=>setDraft(previous=>({...previous,prefix:event.target.value}))} placeholder="R$ "/></label><label>{t("Sufixo")}<input value={draft.suffix??(draft.type==="percent"?"%":"")} onChange={event=>setDraft(previous=>({...previous,suffix:event.target.value}))}/></label></div></>}
    <button className="grid-modal-action" onClick={()=>onFormat(draft)}>{t("Aplicar formato")}</button><hr/><label>{t("Filtro da coluna")}<select value={operator} onChange={event=>setOperator(event.target.value)}><option value="contains">{t("Contém")}</option><option value="equals">{t("Igual a")}</option><option value="gt">{t("Maior que")}</option><option value="lt">{t("Menor que")}</option><option value="gte">{t("Maior ou igual")}</option><option value="lte">{t("Menor ou igual")}</option><option value="is_null">{t("É nulo")}</option><option value="not_null">{t("Não é nulo")}</option></select></label><label>{t("Valor")}{booleanColumn?<select disabled={nullOperator} value={value} onChange={event=>setValue(event.target.value)}><option value="">—</option><option value="true">True</option><option value="false">False</option></select>:<input disabled={nullOperator} type={dateColumn?(/datetime|timestamp/i.test(column.dtype)?"datetime-local":"date"):"text"} value={value} onChange={event=>setValue(event.target.value)} onKeyDown={event=>{if(event.key==="Enter"&&(value||nullOperator))onFilter({column:column.name,operator,value});}}/>}</label><div className="grid-modal-actions"><button onClick={()=>onFilter(undefined)}>{t("Limpar filtro")}</button><button disabled={!value&&!nullOperator} onClick={()=>onFilter({column:column.name,operator,value})}>{t("Filtrar")}</button></div>
  </div></Modal>;
}
