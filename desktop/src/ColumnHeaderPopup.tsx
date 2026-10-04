import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { ArrowDownAZ, ArrowUpAZ, Check, Copy, SlidersHorizontal, X } from "lucide-react";
import { useLocale, type Locale } from "./i18n";
import { errorText, type Column } from "./runtime";
import type { ColumnFilter } from "./dataTypes";
import {
  columnFilterDraft, draftToColumnFilters, headerPopupPosition, replaceColumnFilters,
  type ColumnFilterDraft, type ColumnFilterOperator, type ColumnValueSuggestions, type HeaderPopupAnchor,
} from "./gridColumnFilters";
import "./columnHeaderPopup.css";

export interface ColumnHeaderPopupProps {
  ownerDocument: Document;
  anchor: HeaderPopupAnchor;
  column: Column;
  filters: ColumnFilter[];
  sortDirection?: "asc" | "desc";
  onApply: (filters: ColumnFilter[]) => void;
  onSort: (direction: "asc" | "desc" | null) => void;
  onCopyName: () => void;
  onFormat: () => void;
  onClose: () => void;
  loadValues?: () => Promise<ColumnValueSuggestions>;
  filterDisabledReason?: string;
  locale?: Locale;
}

/** Anchors and focus belong to the document that owns the grid, including popouts. */
export function ColumnHeaderPopup({ ownerDocument, anchor, column, filters, sortDirection, onApply, onSort,
  onCopyName, onFormat, onClose, loadValues, filterDisabledReason, locale: selectedLocale }: ColumnHeaderPopupProps) {
  const currentLocale = useLocale(), locale = selectedLocale ?? currentLocale;
  const text = (pt: string, en: string) => locale === "en-US" ? en : pt;
  const popup = useRef<HTMLDivElement>(null), initialControl = useRef<HTMLElement | null>(null);
  const closeHandler = useRef(onClose); closeHandler.current = onClose;
  const restoreFocus = useRef(true), dirty = useRef(false), closed = useRef(false), refocusControl = useRef(false);
  const [draft, setDraft] = useState(() => columnFilterDraft(column, filters));
  const [error, setError] = useState(""), [valuesError, setValuesError] = useState("");
  const [suggestions, setSuggestions] = useState<ColumnValueSuggestions>();
  const [valuesLoading, setValuesLoading] = useState(false);
  const [position, setPosition] = useState({ left: -10_000, top: -10_000 });
  const inputId = useId(), valuesId = useId(), errorId = useId();
  const close = (restore = true) => {
    if (closed.current) return;
    closed.current = true; restoreFocus.current = restore; closeHandler.current();
  };

  useEffect(() => {
    let active = true;
    setValuesError(""); setSuggestions(undefined); setValuesLoading(Boolean(loadValues && !filterDisabledReason));
    if (loadValues && !filterDisabledReason) Promise.resolve().then(loadValues).then(values => {
      if (!active || closed.current) return;
      // A bounded server response supplies suggestions; the browser never scans a frame.
      setSuggestions({ ...values, values: values.values.slice(0, 50) });
      if (!dirty.current) {
        refocusControl.current = ownerDocument.activeElement === initialControl.current;
        setDraft(columnFilterDraft(column, filters, values.kind));
      }
    }).catch(failure => { if (active && !closed.current) setValuesError(errorText(failure)); })
      .finally(() => { if (active && !closed.current) setValuesLoading(false); });
    return () => { active = false; };
    // Root keys the popup by result/column and supplies a stable request callback.
  }, [loadValues, column.name, column.dtype, filterDisabledReason]);

  useLayoutEffect(() => {
    const previous = ownerDocument.activeElement as HTMLElement | null;
    restoreFocus.current = true; closed.current = false;
    const control = initialControl.current?.matches(":disabled")
      ? popup.current?.querySelector<HTMLElement>("button:not(:disabled)") : initialControl.current;
    control?.focus({ preventScroll: true });
    return () => {
      if (restoreFocus.current && previous?.isConnected && typeof previous.focus === "function") previous.focus({ preventScroll: true });
    };
  }, [ownerDocument]);

  useLayoutEffect(() => {
    if (!refocusControl.current) return;
    refocusControl.current = false;
    if (!closed.current) initialControl.current?.focus({ preventScroll: true });
  }, [draft.kind]);

  useLayoutEffect(() => {
    const host = ownerDocument.defaultView;
    const update = () => {
      const bounds = popup.current?.getBoundingClientRect();
      if (!bounds) return;
      const next = headerPopupPosition(anchor, bounds, {
        width: host?.innerWidth ?? ownerDocument.documentElement.clientWidth,
        height: host?.innerHeight ?? ownerDocument.documentElement.clientHeight,
      });
      setPosition(previous => previous.left === next.left && previous.top === next.top ? previous : next);
    };
    update();
    const Resize = (host as (Window & typeof globalThis) | null)?.ResizeObserver;
    const observer = Resize ? new Resize(update) : undefined;
    if (popup.current) observer?.observe(popup.current);
    host?.addEventListener("resize", update);
    return () => { observer?.disconnect(); host?.removeEventListener("resize", update); };
  }, [ownerDocument, anchor.x, anchor.y, anchor.width, anchor.height]);

  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!popup.current?.contains(event.target as Node)) close(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault(); event.stopPropagation(); close();
    };
    ownerDocument.addEventListener("pointerdown", outside, true);
    ownerDocument.addEventListener("keydown", escape, true);
    return () => {
      ownerDocument.removeEventListener("pointerdown", outside, true);
      ownerDocument.removeEventListener("keydown", escape, true);
    };
  }, [ownerDocument]);

  const change = (patch: Partial<ColumnFilterDraft>) => {
    dirty.current = true; setError(""); setDraft(previous => ({ ...previous, ...patch, original: undefined }));
  };
  const apply = (event: FormEvent) => {
    event.preventDefault();
    if (filterDisabledReason) return;
    const incomplete = Array.from(popup.current?.querySelectorAll<HTMLInputElement>('input[type="date"]') ?? []).find(input => input.validity.badInput);
    if (incomplete) {
      setError(text("Complete uma data válida ou use o calendário.", "Complete a valid date or use the calendar.")); incomplete.focus(); return;
    }
    const result = draftToColumnFilters(column.name, draft, locale);
    if (!result.ok) {
      setError(result.error);
      popup.current?.querySelector<HTMLElement>(`[data-filter-field="${result.field}"]`)?.focus();
      return;
    }
    onApply(replaceColumnFilters(filters, column.name, result.filters)); close();
  };
  const range = draft.operator === "between";
  const literalText = ["contains", "starts_with", "ends_with"].includes(draft.operator);
  const dates = draft.kind === "date" && !literalText;
  const options: Array<[ColumnFilterOperator, string]> = [
    ["contains", text("Contém", "Contains")], ["equals", text("Igual a", "Equals")],
    ["starts_with", text("Começa com", "Starts with")], ["ends_with", text("Termina com", "Ends with")],
    ["between", text("Intervalo inclusivo", "Inclusive range")],
    ["gt", text("Maior que", "Greater than")], ["gte", text("Maior ou igual", "Greater than or equal")],
    ["lt", text("Menor que", "Less than")], ["lte", text("Menor ou igual", "Less than or equal")],
  ];
  const orderedOptions = draft.kind === "number" || draft.kind === "date"
    ? [...options.slice(4, 5), options[1], ...options.slice(5), options[0], ...options.slice(2, 4)] : options;
  const candidates = suggestions?.values.filter((value): value is string => typeof value === "string" && value.length <= 1000) ?? [];
  const controlRef = (element: HTMLElement | null) => { initialControl.current = element; };
  const amount = (value: number) => value.toLocaleString(locale);

  return createPortal(<div ref={popup} className="column-header-popup" role="dialog" aria-modal="false"
    aria-label={text(`Coluna ${column.name}`, `Column ${column.name}`)} style={position}>
    <header><strong title={column.name}>{column.name}</strong><span title={column.dtype}>{column.dtype}</span>
      <button type="button" className="column-header-close" onClick={() => close()} aria-label={text("Fechar", "Close")}><X size={13}/></button></header>
    <div className="column-header-actions">
      <button type="button" disabled={Boolean(filterDisabledReason)} aria-pressed={sortDirection === "asc"} onClick={() => { onSort("asc"); close(); }}><ArrowDownAZ size={14}/>{text("Ordem crescente", "Sort ascending")}{sortDirection === "asc" && <Check size={12}/>}</button>
      <button type="button" disabled={Boolean(filterDisabledReason)} aria-pressed={sortDirection === "desc"} onClick={() => { onSort("desc"); close(); }}><ArrowUpAZ size={14}/>{text("Ordem decrescente", "Sort descending")}{sortDirection === "desc" && <Check size={12}/>}</button>
      <button type="button" disabled={!sortDirection || Boolean(filterDisabledReason)} onClick={() => { onSort(null); close(); }}><X size={14}/>{text("Limpar ordenação", "Clear sorting")}</button>
    </div>
    <form onSubmit={apply} noValidate>
      <div className="column-header-filter-title"><strong>{text("Filtro da coluna", "Column filter")}</strong>
        <select disabled={Boolean(filterDisabledReason)} value={draft.presence} aria-label={text("Valores ou nulos", "Values or nulls")}
          ref={draft.presence !== "value" ? controlRef : undefined} onChange={event => change({ presence: event.target.value as ColumnFilterDraft["presence"] })}>
          <option value="value">{text("Valores", "Values")}</option><option value="is_null">{text("Apenas nulos", "Null only")}</option><option value="not_null">{text("Não nulos", "Not null")}</option>
        </select></div>
      {draft.presence === "value" && (draft.kind === "bool" ? <label className="column-header-field">{text("Valor", "Value")}
        <select disabled={Boolean(filterDisabledReason)} value={draft.booleanValue} ref={controlRef} onChange={event => change({ booleanValue: event.target.value as ColumnFilterDraft["booleanValue"] })}>
          <option value="any">{text("Qualquer", "Any")}</option><option value="true">{text("Verdadeiro", "True")}</option><option value="false">{text("Falso", "False")}</option>
        </select></label> : <>
        <select disabled={Boolean(filterDisabledReason)} className="column-header-operator" value={draft.operator} aria-label={text("Condição do filtro", "Filter condition")}
          onChange={event => change({ operator: event.target.value as ColumnFilterOperator })}>
          {orderedOptions.map(([operator, label]) => <option key={operator} value={operator}>{label}</option>)}
        </select>
        <div className={range ? "column-header-range" : "column-header-single"}>
          <label className="column-header-field" htmlFor={inputId}>{range ? dates ? text("Data inicial", "Start date") : text("Mínimo", "Minimum") : text("Valor", "Value")}
            <input disabled={Boolean(filterDisabledReason)} id={inputId} data-filter-field="value" type={dates && (!draft.value || /^\d{4}-\d{2}-\d{2}$/.test(draft.value)) ? "date" : "text"} ref={controlRef} value={draft.value}
              inputMode={draft.kind === "number" && !literalText ? "decimal" : undefined} maxLength={draft.kind === "number" ? 1024 : 1000}
              list={!dates && draft.kind === "text" ? valuesId : undefined} placeholder={dates ? "AAAA-MM-DD" : range ? text("Sem limite", "No limit") : text("Digite um valor", "Enter a value")}
              aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} onChange={event => change({ value: event.target.value })}/></label>
          {range && <label className="column-header-field">{dates ? text("Data final", "End date") : text("Máximo", "Maximum")}
            <input disabled={Boolean(filterDisabledReason)} data-filter-field="valueTo" type={dates && (!draft.valueTo || /^\d{4}-\d{2}-\d{2}$/.test(draft.valueTo)) ? "date" : "text"} value={draft.valueTo} maxLength={draft.kind === "number" ? 1024 : 1000}
              inputMode={draft.kind === "number" ? "decimal" : undefined} placeholder={dates ? "AAAA-MM-DD" : text("Sem limite", "No limit")}
              aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} onChange={event => change({ valueTo: event.target.value })}/></label>}
        </div>
        {candidates.length > 0 && <datalist id={valuesId}>{candidates.map((value, index) => <option key={index} value={value}/>)}</datalist>}
        {range && <small className="column-header-hint">{dates ? text("Datas inclusivas; a data final inclui o dia inteiro.", "Inclusive dates; the end date includes the entire day.") : text("Limites inclusivos. Deixe em branco para não limitar.", "Inclusive bounds. Leave blank for no limit.")}</small>}
      </>)}
      {valuesLoading && <small className="column-header-hint">{text("Carregando sugestões…", "Loading suggestions…")}</small>}
      {suggestions?.sampled && <small className="column-header-hint">{text(`Sugestões de ${amount(suggestions.scanned_rows)} de ${amount(suggestions.total_rows)} linhas; o filtro vale para todas.`, `Suggestions from ${amount(suggestions.scanned_rows)} of ${amount(suggestions.total_rows)} rows; the filter applies to all.`)}</small>}
      {valuesError && <small className="column-header-hint" title={valuesError}>{text("Sugestões indisponíveis. Você pode digitar o filtro.", "Suggestions unavailable. You can enter the filter.")}</small>}
      {filterDisabledReason && <p className="column-header-error" role="alert">{filterDisabledReason}</p>}
      {error && <p id={errorId} className="column-header-error" role="alert">{error}</p>}
      <div className="column-header-filter-actions"><button type="button" onClick={() => { onApply(replaceColumnFilters(filters, column.name, [])); close(); }}>{text("Limpar filtro", "Clear filter")}</button>
        <button type="submit" disabled={Boolean(filterDisabledReason)} className="column-header-apply">{text("Aplicar", "Apply")}</button></div>
    </form>
    <div className="column-header-actions column-header-utilities">
      <button type="button" onClick={() => { onCopyName(); close(); }}><Copy size={14}/>{text("Copiar nome da coluna", "Copy column name")}</button>
      <button type="button" onClick={() => { close(false); onFormat(); }}><SlidersHorizontal size={14}/>{text("Formatar coluna…", "Format column…")}</button>
    </div>
  </div>, ownerDocument.body);
}
