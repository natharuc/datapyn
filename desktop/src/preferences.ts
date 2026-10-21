export interface Preferences {
  locale:"pt-BR"|"en-US";
  theme: "dark" | "light" | "system"; uiFont: string; uiFontSize: number;
  editorFont: string; editorFontSize: number; tabSize: number; wordWrap: boolean;
  gridFont:string;gridFontSize:number;
  lineNumbers: boolean; minimap: boolean; autocomplete: boolean; maximizeFirstBlock: boolean;
  aiAutocomplete: boolean;
  connectionIdleSeconds: number;
  automaticTransactions: boolean;
  confirmDestructiveSql: boolean;
  leftWidth: number; rightWidth: number; resultHeight: number; leftVisible: boolean; rightVisible: boolean;
  displayRowLimit: number; notifications: boolean; notificationSound: boolean; sharedDelimiter: string;
}
export const DEFAULT_PREFERENCES: Preferences = {
  locale:"pt-BR",
  theme: "dark", uiFont: "Ubuntu", uiFontSize: 12,
  editorFont: "JetBrains Mono, Cascadia Code, Fira Code, Consolas, Ubuntu Mono, monospace", editorFontSize: 13,
  gridFont:"Consolas, Ubuntu Mono, monospace",gridFontSize:12,
  tabSize: 4, wordWrap: false, lineNumbers: true, minimap: false, autocomplete: true,
  aiAutocomplete: false, connectionIdleSeconds: 300, automaticTransactions: true, confirmDestructiveSql: true, maximizeFirstBlock: false, leftWidth: 260, rightWidth: 260, resultHeight: 310,
  leftVisible: true, rightVisible: true, displayRowLimit: 100, notifications: true, notificationSound: true,
  sharedDelimiter: "{{name}}",
};
export const PREFERENCES_KEY = "datapyn.desktop.preferences.v1";
/** Accept settings typed with either decimal separator without guessing from text. */
export function preferenceNumber(value: unknown): number | undefined {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value !== "string" || !/^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$/.test(value.trim())) return undefined;
  const parsed = Number(value.trim().replace(",", "."));
  return Number.isFinite(parsed) ? parsed : undefined;
}
function boundNumber(value: unknown, min: number, max: number, fallback: number): number {
  return Math.max(min, Math.min(max, preferenceNumber(value) ?? fallback));
}
/** Share one bounded pixel value between the saved preference and editor zoom. */
export function normalizeEditorFontSize(value: unknown, fallback = DEFAULT_PREFERENCES.editorFontSize): number {
  return Math.round(boundNumber(value, 8, 32, boundNumber(fallback, 8, 32, DEFAULT_PREFERENCES.editorFontSize)) * 10) / 10;
}
export function normalizePreferences(raw: Partial<Preferences>): Preferences {
  const p = { ...DEFAULT_PREFERENCES, ...raw };
  const bound = boundNumber;
  return { ...p, locale:p.locale === "en-US" ? "en-US" : "pt-BR", theme: ["dark", "light", "system"].includes(p.theme) ? p.theme : "dark",
    uiFontSize: Math.round(bound(p.uiFontSize, 9, 24, 12) * 10) / 10, editorFontSize: normalizeEditorFontSize(p.editorFontSize),
    gridFontSize:Math.round(bound(p.gridFontSize,7,32,12) * 10) / 10,
    tabSize: Math.round(bound(p.tabSize, 1, 8, 4)), leftWidth: bound(p.leftWidth, 180, 600, 260),
    rightWidth: bound(p.rightWidth, 180, 600, 260), resultHeight: bound(p.resultHeight, 80, 900, 310),
    displayRowLimit: Math.round(bound(p.displayRowLimit, 10, 1_000_000, 100)),
    connectionIdleSeconds: Math.round(bound(p.connectionIdleSeconds, 0, 86400, 300)),
    automaticTransactions: p.automaticTransactions !== false,
    confirmDestructiveSql: p.confirmDestructiveSql !== false,
    sharedDelimiter: typeof p.sharedDelimiter === "string" && p.sharedDelimiter.split("name").length === 2 && p.sharedDelimiter.split("name").every(Boolean) ? p.sharedDelimiter : "{{name}}",
  };
}
export function loadPreferences(): Preferences {
  try { return normalizePreferences(JSON.parse(localStorage.getItem(PREFERENCES_KEY) ?? "{}")); }
  catch { return { ...DEFAULT_PREFERENCES }; }
}
export function savePreferences(p: Preferences) { localStorage.setItem(PREFERENCES_KEY, JSON.stringify(p)); }
