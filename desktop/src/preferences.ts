export interface Preferences {
  locale:"pt-BR"|"en-US";
  theme: "dark" | "light" | "system"; uiFont: string; uiFontSize: number;
  editorFont: string; editorFontSize: number; tabSize: number; wordWrap: boolean;
  gridFont:string;gridFontSize:number;
  lineNumbers: boolean; minimap: boolean; autocomplete: boolean; maximizeFirstBlock: boolean;
  aiAutocomplete: boolean;
  connectionIdleSeconds: number;
  leftWidth: number; rightWidth: number; resultHeight: number; leftVisible: boolean; rightVisible: boolean;
  displayRowLimit: number; notifications: boolean; notificationSound: boolean; sharedDelimiter: string;
}
export const DEFAULT_PREFERENCES: Preferences = {
  locale:"pt-BR",
  theme: "dark", uiFont: "Ubuntu", uiFontSize: 12,
  editorFont: "JetBrains Mono, Cascadia Code, Fira Code, Consolas, Ubuntu Mono, monospace", editorFontSize: 13,
  gridFont:"Consolas, Ubuntu Mono, monospace",gridFontSize:12,
  tabSize: 4, wordWrap: false, lineNumbers: true, minimap: false, autocomplete: true,
  aiAutocomplete: false, connectionIdleSeconds: 300, maximizeFirstBlock: false, leftWidth: 260, rightWidth: 260, resultHeight: 310,
  leftVisible: true, rightVisible: true, displayRowLimit: 100, notifications: true, notificationSound: true,
  sharedDelimiter: "{{name}}",
};
export const PREFERENCES_KEY = "datapyn.desktop.preferences.v1";
export function normalizePreferences(raw: Partial<Preferences>): Preferences {
  const p = { ...DEFAULT_PREFERENCES, ...raw };
  const bound = (value: number, min: number, max: number, fallback: number) => Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback;
  return { ...p, locale:p.locale === "en-US" ? "en-US" : "pt-BR", theme: ["dark", "light", "system"].includes(p.theme) ? p.theme : "dark",
    uiFontSize: bound(p.uiFontSize, 9, 24, 12), editorFontSize: bound(p.editorFontSize, 8, 32, 13),
    gridFontSize:bound(p.gridFontSize,7,32,12),
    tabSize: bound(p.tabSize, 1, 8, 4), leftWidth: bound(p.leftWidth, 180, 600, 260),
    rightWidth: bound(p.rightWidth, 180, 600, 260), resultHeight: bound(p.resultHeight, 80, 900, 310),
    displayRowLimit: bound(p.displayRowLimit, 10, 1_000_000, 100),
    connectionIdleSeconds: bound(p.connectionIdleSeconds, 0, 86400, 300),
    sharedDelimiter: typeof p.sharedDelimiter === "string" && p.sharedDelimiter.split("name").length === 2 && p.sharedDelimiter.split("name").every(Boolean) ? p.sharedDelimiter : "{{name}}",
  };
}
export function loadPreferences(): Preferences {
  try { return normalizePreferences(JSON.parse(localStorage.getItem(PREFERENCES_KEY) ?? "{}")); }
  catch { return { ...DEFAULT_PREFERENCES }; }
}
export function savePreferences(p: Preferences) { localStorage.setItem(PREFERENCES_KEY, JSON.stringify(p)); }
