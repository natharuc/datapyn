import { useCallback, useSyncExternalStore } from "react";
import portuguese from "../../source/src/language/pt-BR.json";
import english from "../../source/src/language/en-US.json";
import additions from "./i18nEnglish.json";

export type Locale = "pt-BR" | "en-US";
type Variables = Record<string, string | number>;
const listeners = new Set<() => void>();
let locale: Locale = "pt-BR";
const ptKeys: Record<string,string> = {}, enKeys: Record<string,string> = {}, enText: Record<string,string> = {}, ptText:Record<string,string>={};
const newEnglish:Record<string,string> = additions;
const normal = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[&:.…]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
function flatten(value: unknown, target: Record<string,string>, prefix = "") {
  if (!value || typeof value !== "object") return;
  Object.entries(value).forEach(([key,item]) => { const path = prefix ? `${prefix}.${key}` : key; if(typeof item === "string") target[path] = item.replace(/&(?=\w)/g, ""); else flatten(item,target,path); });
}
flatten(portuguese,ptKeys); flatten(english,enKeys);
Object.entries(ptKeys).forEach(([key,text]) => { if(enKeys[key]) {enText[normal(text)] = enKeys[key];ptText[normal(enKeys[key])]=text;} });
Object.entries(additions).forEach(([text,translated]) => { enText[normal(text)] = translated;ptText[normal(translated)]=text; });
export function getLocale(): Locale { return locale; }
export function setLocale(value: Locale) {
  const next: Locale = value === "en-US" ? "en-US" : "pt-BR";
  if(next === locale) return;
  locale = next;
  if(typeof document !== "undefined") document.documentElement.lang = next;
  listeners.forEach(listener=>listener());
}
export function subscribeLocale(listener:()=>void) { listeners.add(listener); return ()=>{listeners.delete(listener);}; }
export function useLocale(): Locale { return useSyncExternalStore(subscribeLocale,getLocale,getLocale); }
export function translate(keyOrPortuguese:string, variables:Variables = {}, selected:Locale = locale):string {
  const source = selected === "en-US" ? enKeys[keyOrPortuguese] ?? newEnglish[keyOrPortuguese] ?? enText[normal(keyOrPortuguese)] ?? keyOrPortuguese : ptKeys[keyOrPortuguese] ?? ptText[normal(keyOrPortuguese)] ?? keyOrPortuguese;
  return source.replace(/\{(\w+)\}/g,(match,key)=>key in variables ? String(variables[key]) : match);
}
export function useTranslation() { const current = useLocale(); const t = useCallback((source:string,vars?:Variables)=>translate(source,vars,current),[current]); return {t,locale:current}; }
/** Used by settings search to match labels in either supported language. */
export function localizedSearch(query:string,...labels:string[]):boolean {
  const needle=normal(query); return !needle||labels.some(label=>normal(translate(label,{},"pt-BR")).includes(needle)||normal(translate(label,{},"en-US")).includes(needle));
}
