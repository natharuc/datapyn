import { useEffect, useMemo,useRef, useState } from "react";
import {translate as t,useLocale} from "./i18n";
import { runtime, errorText } from "./runtime";

export interface ParameterDefinition {
  id: string; name: string; label?: string; order?: number; sql_type?: string; input_kind?: string;
  value?: unknown; default_value?: unknown; required?: boolean; options?: unknown[]; multi_select?: boolean;
  [key: string]: unknown;
}
export function useParameterScan(codes: string[], definitions: ParameterDefinition[], shared: boolean, delimiter: string,
  onChange: (parameters: ParameterDefinition[]) => void) {
  const latest = useRef({ definitions, onChange }); latest.current = { definitions, onChange };
  const [error, setError] = useState("");
  const generation = useRef(0), text = useMemo(()=>codes.join("\u0000"),[codes]);
  useEffect(() => {
    const version = ++generation.current;
    const timer = setTimeout(() => {
      void runtime.request<{ sql_parameters: ParameterDefinition[]; shared_parameters: ParameterDefinition[] }>("parameters.scan", { codes: text.split("\u0000"),
        sql_parameters: shared ? [] : latest.current.definitions, shared_parameters: shared ? latest.current.definitions : [], shared_delimiter: delimiter }).then(response => {
          if (version !== generation.current) return;
          setError("");
          const parameters = shared ? response.shared_parameters : response.sql_parameters;
          if (JSON.stringify(parameters) !== JSON.stringify(latest.current.definitions)) latest.current.onChange(parameters);
        }).catch(failure => { if (version === generation.current) setError(errorText(failure)); });
    }, 350);
    return () => { clearTimeout(timer); ++generation.current; };
  }, [text, shared, delimiter]);
  return error;
}
export function ParameterPanel({ parameters, enabled = true, onChange, onEnabled, title, disabled }: {
  parameters: ParameterDefinition[]; enabled?: boolean; onChange: (parameters: ParameterDefinition[]) => void;
  onEnabled?: (enabled: boolean) => void; title: string; disabled?: boolean;
}) {
  useLocale();
  const [configure, setConfigure] = useState(false);
  if (!parameters.length) return null;
  const update = (id: string, patch: Partial<ParameterDefinition>) => onChange(parameters.map(p => p.id === id ? { ...p, ...patch } : p));
  return <section className={`parameter-panel ${!enabled ? "disabled" : ""}`} aria-label={title}>
    <header><strong>{title}</strong>{onEnabled && <label><input type="checkbox" checked={enabled} disabled={disabled} onChange={e => onEnabled(e.target.checked)} />{t("Usar parâmetros")}</label>}<button className="text-button" onClick={() => setConfigure(!configure)}>{configure ? t("Valores") : t("Configurar")}</button></header>
    {enabled && <div className="parameter-fields">{parameters.map(p => {
      const options = (p.options ?? []).map(raw => typeof raw === "object" && raw ? { label: String((raw as {label?: unknown}).label ?? (raw as {value?: unknown}).value ?? ""), value: String((raw as {value?: unknown}).value ?? "") } : { label: String(raw), value: String(raw) });
      return <div className="parameter-field" key={p.id}><label title={p.name}>{p.label || p.name}{p.required && " *"}
        {p.input_kind === "multi_choice" || p.multi_select ? <select multiple disabled={disabled} value={Array.isArray(p.value) ? p.value.map(String) : []} onChange={e => update(p.id, { value: Array.from(e.target.selectedOptions).map(o => o.value) })}>{options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
          : p.input_kind === "choice" || p.sql_type === "boolean" ? <select disabled={disabled} value={String(p.value ?? "")} onChange={e => update(p.id, { value: e.target.value })}><option value="">{t("Selecionar…")}</option>{(p.sql_type === "boolean" ? [{label:t("Verdadeiro"), value:"true"}, {label:t("Falso"),value:"false"}] : options).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
          : <input disabled={disabled} type={p.sql_type === "date" ? "date" : p.sql_type === "datetime" ? "datetime-local" : "text"} value={String(p.value ?? "")} placeholder={String(p.default_value ?? "")} onChange={e => update(p.id, { value: e.target.value })} />}</label>
        {configure && <div className="parameter-config"><input aria-label={`Rótulo ${p.name}`} value={p.label ?? ""} placeholder={t("Rótulo")} disabled={disabled} onChange={e => update(p.id,{label:e.target.value})}/><select aria-label={`Tipo ${p.name}`} value={p.sql_type ?? "text"} disabled={disabled} onChange={e => update(p.id, {sql_type:e.target.value})}>{["text","integer","decimal","boolean","date","datetime","uuid"].map(t => <option key={t}>{t}</option>)}</select><select aria-label={`Entrada ${p.name}`} value={p.input_kind ?? "value"} disabled={disabled} onChange={e => update(p.id,{input_kind:e.target.value, multi_select:e.target.value === "multi_choice"})}>{[["value","Valor"],["choice","Escolha"],["multi_choice","Múltipla escolha"]].map(([v,l]) => <option key={v} value={v}>{t(l)}</option>)}</select><input aria-label={`Padrão ${p.name}`} value={String(p.default_value ?? "")} placeholder={t("Valor padrão (hoje, agora, null…)")} disabled={disabled} onChange={e => update(p.id,{default_value:e.target.value})}/><textarea aria-label={`Opções ${p.name}`} value={options.map(o => o.value).join("\n")} placeholder={t("Opções: uma por linha")} disabled={disabled} onChange={e => update(p.id,{options:e.target.value.split("\n")})}/><label><input type="checkbox" checked={p.required !== false} disabled={disabled} onChange={e=>update(p.id,{required:e.target.checked})}/>{t("Obrigatório")}</label></div>}
      </div>;
    })}</div>}
  </section>;
}
