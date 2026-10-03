export type Command = "run" | "runAdvance" | "runAll" | "addBlock" | "newSession" | "closeSession" | "save" | "open" | "cancel" | "settings" | "copyHeaders" | "clearResults";
export const DEFAULT_SHORTCUTS: Record<Command, string> = {
  run: "Ctrl+Enter", runAdvance: "Shift+Enter", runAll: "Ctrl+F5", addBlock: "Ctrl+Shift+B",
  newSession: "Ctrl+N", closeSession: "Ctrl+W", save: "Ctrl+S", open: "Ctrl+O", cancel: "Escape",
  settings: "Ctrl+,", copyHeaders: "Ctrl+Shift+C", clearResults: "Ctrl+Shift+L",
};

export function keySequence(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey">): string {
  const modifiers = [event.ctrlKey || event.metaKey ? "Ctrl" : "", event.altKey ? "Alt" : "", event.shiftKey ? "Shift" : ""].filter(Boolean);
  let key = event.key;
  if (key === "Return") key = "Enter";
  if (key.length === 1) key = key.toUpperCase();
  return [...modifiers, key].join("+");
}
export function commandForEvent(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey" | "repeat">, shortcuts = DEFAULT_SHORTCUTS): Command | undefined {
  if (event.repeat) return undefined;
  const key = keySequence(event);
  if (key === "F5") return "run";
  if (key === "Ctrl+T") return "newSession";
  return (Object.entries(shortcuts) as [Command, string][]).find(([, binding]) => key.toUpperCase() === binding.trim().toUpperCase())?.[0];
}
export function shortcutConflicts(shortcuts: Record<Command, string>): string[] {
  const seen = new Map<string, string>(); const conflicts: string[] = [];
  for (const [command, binding] of Object.entries(shortcuts)) {
    const key = binding.trim().toUpperCase(); if (!key) continue;
    if (seen.has(key)) conflicts.push(`${binding}: ${seen.get(key)} e ${command}`);
    seen.set(key, command);
    if (["F5", "CTRL+T"].includes(key) && !((key === "F5" && command === "run") || (key === "CTRL+T" && command === "newSession"))) conflicts.push(`${binding}: atalho reservado`);
  }
  return conflicts;
}
