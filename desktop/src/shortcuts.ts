export const COMMAND_LABELS = {
  run: "Executar bloco ou seleção", runAdvance: "Executar e avançar", runAll: "Executar todos", addBlock: "Novo bloco",
  newSession: "Nova sessão", newTab: "Nova aba", closeSession: "Fechar aba", save: "Salvar .dpw", saveAs: "Salvar como",
  open: "Abrir arquivo", exportScript: "Exportar script", cancel: "Cancelar execução", settings: "Configurações",
  copyHeaders: "Copiar com cabeçalhos", clearResults: "Limpar resultados", find: "Localizar", replace: "Substituir",
  formatCode: "Formatar código", entityInfo: "Informações da entidade", autocomplete: "Forçar autocomplete",
  manageConnections: "Gerenciar conexões", newConnection: "Nova conexão", reloadSchema: "Atualizar schema",
  exit: "Sair", restoreView: "Restaurar visualização", resetLayout: "Restaurar disposição",
  editorNewline: "Editor: nova linha", editorDuplicateLine: "Editor: duplicar linha", editorCutLine: "Editor: recortar linha",
  editorTransposeLine: "Editor: trocar linhas", editorLowercase: "Editor: minúsculas", editorUppercase: "Editor: maiúsculas",
  editorDeleteLine: "Editor: excluir linha",
} as const;
export type Command = keyof typeof COMMAND_LABELS;
export const DEFAULT_SHORTCUTS: Record<Command, string> = {
  run: "F5", runAdvance: "Shift+Enter", runAll: "Ctrl+F5", addBlock: "Ctrl+Shift+B", newSession: "Ctrl+N", newTab: "Ctrl+T",
  closeSession: "Ctrl+W", save: "Ctrl+S", saveAs: "Ctrl+Shift+S", open: "Ctrl+O", exportScript: "Ctrl+Shift+E", cancel: "Escape",
  settings: "Ctrl+,", copyHeaders: "Ctrl+Shift+C", clearResults: "Ctrl+Shift+L", find: "Ctrl+F", replace: "Ctrl+H",
  formatCode: "Ctrl+Shift+F", entityInfo: "Alt+F1", autocomplete: "Ctrl+.", manageConnections: "Ctrl+Shift+M",
  newConnection: "Ctrl+Shift+D", reloadSchema: "Ctrl+Shift+T", exit: "Ctrl+Q", restoreView: "Ctrl+Shift+R", resetLayout: "Ctrl+Shift+Alt+R",
  editorNewline: "", editorDuplicateLine: "Ctrl+D", editorCutLine: "Ctrl+L", editorTransposeLine: "",
  editorLowercase: "Ctrl+U", editorUppercase: "Ctrl+Shift+U", editorDeleteLine: "Ctrl+Shift+K",
};
export const EDITOR_COMMANDS = new Set<Command>(["find", "replace", "formatCode", "autocomplete", "entityInfo", "editorNewline", "editorDuplicateLine", "editorCutLine", "editorTransposeLine", "editorLowercase", "editorUppercase", "editorDeleteLine"]);
export function normalizeBinding(binding: string): string {
  const parts = binding.trim().split("+").map(p => p.trim().toUpperCase());
  const key = parts.pop()?.replace(/^RETURN$/, "ENTER") ?? "";
  const modifiers = [parts.includes("CTRL") || parts.includes("CMD") ? "CTRL" : "", parts.includes("ALT") ? "ALT" : "", parts.includes("SHIFT") ? "SHIFT" : ""].filter(Boolean);
  return [...modifiers, key].join("+");
}
export function keySequence(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey">): string {
  const modifiers = [event.ctrlKey || event.metaKey ? "Ctrl" : "", event.altKey ? "Alt" : "", event.shiftKey ? "Shift" : ""].filter(Boolean);
  const key = event.key === "Return" ? "Enter" : event.key.length === 1 ? event.key.toUpperCase() : event.key;
  return [...modifiers, key].join("+");
}
export function commandForEvent(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey" | "repeat">, shortcuts = DEFAULT_SHORTCUTS): Command | undefined {
  if (event.repeat) return undefined;
  const key = normalizeBinding(keySequence(event));
  if (key === "CTRL+ENTER" && normalizeBinding(shortcuts.run) === "F5") return "run";
  return (Object.entries(shortcuts) as [Command, string][]).find(([, binding]) => binding.trim() && key === normalizeBinding(binding))?.[0];
}
export function shortcutConflicts(shortcuts: Record<Command, string>): string[] {
  const seen = new Map<string, string>(); const conflicts: string[] = [];
  for (const [command, binding] of Object.entries(shortcuts)) {
    const key = normalizeBinding(binding); if (!key) continue;
    if (seen.has(key)) conflicts.push(`${binding}: ${seen.get(key)} e ${command}`);
    seen.set(key, command);
  }
  return conflicts;
}
