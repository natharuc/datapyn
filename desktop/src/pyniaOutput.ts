import type { PyniaState, PyniaToolActivity } from "./pynia";

export type OutputToolStatus = "running" | "completed" | "error" | "interrupted" | "unknown";
export interface OutputActivity {
  id: string;
  messageIndex: number;
  live: boolean;
  thinking: string;
  tools: PyniaToolActivity[];
}
export interface OutputCut {
  messageIndex: number;
  conversationId?: string | null;
  current?: { messageIndex: number; thinking: string; tools: Record<string, string> };
}
export interface OutputHistory { activities: OutputActivity[]; hasOlder: boolean }

const text = (value: unknown, maximum: number) => typeof value === "string" ? value.slice(-maximum) : "";
function activity(value: unknown): { thinking: string; tools: PyniaToolActivity[] } {
  const source = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const tools = Array.isArray(source.tools) ? source.tools.slice(-80).flatMap((item, index) => {
    if (!item || typeof item !== "object") return [];
    const tool = item as Record<string, unknown>, id = text(tool.id, 300) || `tool-${index}`;
    return [{ id, ...(typeof tool.title === "string" ? { title: text(tool.title, 300) } : {}),
      ...(typeof tool.status === "string" ? { status: text(tool.status, 60) } : {}),
      ...(typeof tool.error === "string" ? { error: text(tool.error, 4000) } : {}) }];
  }) : [];
  return { thinking: text(source.thinking, 8000), tools };
}
const toolSignature = (tool: PyniaToolActivity) => JSON.stringify([tool.title, tool.status, tool.error]);
function currentMessageIndex(state: PyniaState): number {
  const messages = state.messages ?? [];
  return messages.at(-1)?.role === "assistant" ? messages.length - 1 : messages.length;
}

/** Clear only the displayed output. The transcript and live ACP operation stay intact. */
export function cutPyniaOutput(state?: PyniaState): OutputCut {
  if (!state) return { messageIndex: 0 };
  const live = activity(state), currentIndex = currentMessageIndex(state), messageIndex = state.busy ? currentIndex : state.messages.length;
  return { messageIndex, conversationId: state.acp_session_id,
    ...((state.busy || live.thinking || live.tools.length) ? { current: { messageIndex: currentIndex, thinking: live.thinking,
    tools: Object.fromEntries(live.tools.map(tool => [tool.id, toolSignature(tool)])) } } : {}) };
}

function afterCut(source: ReturnType<typeof activity>, messageIndex: number, cut?: OutputCut): ReturnType<typeof activity> {
  if (!cut?.current || cut.current.messageIndex !== messageIndex) return source;
  const before = cut.current;
  const thinking = source.thinking.startsWith(before.thinking) ? source.thinking.slice(before.thinking.length) : source.thinking;
  return { thinking, tools: source.tools.filter(tool => before.tools[tool.id] !== toolSignature(tool)) };
}

/** Read the newest bounded activity snapshots, without rendering the chat or scanning its whole history. */
export function pyniaOutputHistory(state?: PyniaState, limit = 40, cut?: OutputCut): OutputHistory {
  if (!state) return { activities: [], hasOlder: false };
  const messages = state.messages ?? [], count = Math.max(1, Math.min(200, Math.trunc(limit) || 40));
  // A cleared/new chat starts a new history even when the output panel remains mounted.
  const effectiveCut = cut && cut.messageIndex <= messages.length && cut.conversationId === state.acp_session_id ? cut : undefined;
  const floor = effectiveCut?.messageIndex ?? 0;
  const historical: OutputActivity[] = [];
  let hasOlder = false;
  for (let index = messages.length - 1; index >= floor; index--) {
    const source = afterCut(activity(messages[index]?.activity), index, effectiveCut);
    if (!source.thinking && !source.tools.length) continue;
    if (historical.length === count) { hasOlder = true; break; }
    historical.push({ id: `message-${index}`, messageIndex: index, live: false, ...source });
  }
  historical.reverse();
  const messageIndex = currentMessageIndex(state), current = afterCut(activity(state), messageIndex, effectiveCut);
  const latest = historical.at(-1);
  const duplicate = !state.busy && latest?.messageIndex === messageIndex && latest.thinking === current.thinking &&
    latest.tools.length === current.tools.length && latest.tools.every((tool, index) => tool.id === current.tools[index].id && toolSignature(tool) === toolSignature(current.tools[index]));
  if ((state.busy || current.thinking || current.tools.length) && !duplicate) {
    historical.push({ id: `current-${messageIndex}`, messageIndex, live: true, ...current });
  }
  return { activities: historical, hasOlder };
}

export function outputToolStatus(tool: PyniaToolActivity, busy: boolean): OutputToolStatus {
  const status = tool.status?.trim().toLowerCase() ?? "";
  if (tool.error || ["failed", "error", "cancelled", "canceled", "timed_out", "timeout"].includes(status)) return "error";
  if (["completed", "complete", "success", "ok", "done", "succeeded"].includes(status)) return "completed";
  if (["pending", "in_progress", "running", "inprogress", "queued"].includes(status)) return busy ? "running" : "interrupted";
  return "unknown";
}
