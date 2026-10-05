import { Bot } from "lucide-react";
import claude from "./assets/agents/claude.svg";
import cursorDark from "./assets/agents/cursor-dark.svg";
import cursorLight from "./assets/agents/cursor-light.svg";
import copilotDark from "./assets/agents/copilot-dark.svg";
import copilotLight from "./assets/agents/copilot-light.svg";
import codexDark from "./assets/agents/codex-dark.svg";
import codexLight from "./assets/agents/codex-light.svg";
import "./agentIcon.css";

export const agentIconAssets = {
  claude: { dark: claude, light: claude },
  cursor: { dark: cursorDark, light: cursorLight },
  copilot: { dark: copilotDark, light: copilotLight },
  codex: { dark: codexDark, light: codexLight },
} as const;

/** Pass a label for a standalone icon; adjacent agent labels make it decorative. */
export function AgentIcon({ agentId, size = 18, label }: { agentId?: string | null; size?: number; label?: string }) {
  const asset = agentId && Object.hasOwn(agentIconAssets, agentId)
    ? agentIconAssets[agentId as keyof typeof agentIconAssets] : undefined;
  return <span className="agent-icon" style={{ width: size, height: size }} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
    {asset ? asset.dark === asset.light
      ? <img src={asset.dark} alt="" aria-hidden="true" />
      : <><img className="agent-icon-dark" src={asset.dark} alt="" aria-hidden="true" /><img className="agent-icon-light" src={asset.light} alt="" aria-hidden="true" /></>
      : <Bot size={size} aria-hidden="true" />}
  </span>;
}
