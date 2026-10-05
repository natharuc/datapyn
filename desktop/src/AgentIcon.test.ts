import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AgentIcon, agentIconAssets } from "./AgentIcon";

describe("Pynia agent marks", () => {
  it.each(["claude", "cursor", "copilot", "codex"])("renders the bundled %s mark instead of a generic bot", (agentId) => {
    const html = renderToStaticMarkup(createElement(AgentIcon, { agentId, size: 23 }));
    expect(html).toContain("<img");
    expect(html).not.toContain("lucide-bot");
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('alt=""');
    const assets = agentIconAssets[agentId as keyof typeof agentIconAssets];
    const sources = [...html.matchAll(/src="([^"]+)"/g)].map((match) => match[1].replaceAll("&#x27;", "'").replaceAll("&amp;", "&"));
    expect(sources).toContain(assets.dark);
    expect(sources).toContain(assets.light);
  });

  it("provides one accessible name when used without a visible label", () => {
    const html = renderToStaticMarkup(createElement(AgentIcon, { agentId: "copilot", label: "GitHub Copilot" }));
    expect(html).toContain('role="img" aria-label="GitHub Copilot"');
    expect(html.match(/aria-label=/g)).toHaveLength(1);
    expect(html.match(/alt=""/g)).toHaveLength(2);
  });

  it.each([undefined, null, "unknown", "constructor", "__proto__"])("uses a neutral fallback for %s", (agentId) => {
    const html = renderToStaticMarkup(createElement(AgentIcon, { agentId }));
    expect(html).toContain("lucide-bot");
    expect(html).not.toContain("<img");
  });

  it("ships only inert local SVGs with proportions preserved", () => {
    for (const file of ["claude.svg", "cursor-dark.svg", "cursor-light.svg", "copilot-dark.svg", "copilot-light.svg", "codex-dark.svg", "codex-light.svg"]) {
      const svg = readFileSync(new URL(`./assets/agents/${file}`, import.meta.url), "utf8");
      expect(svg).toMatch(/viewBox="0 0 [\d.]+ [\d.]+"/);
      expect(svg).toContain("<path");
      expect(svg).not.toMatch(/<script|<foreignObject|<image|\bhref=|\bon\w+=/i);
      expect(svg.length).toBeLessThan(4000);
    }
  });

  it("preserves the official Codex product symbol rather than using the company Blossom", () => {
    const original = readFileSync(new URL("./assets/agents/codex-light.svg", import.meta.url));
    expect(createHash("sha256").update(original).digest("hex")).toBe("0b490f33f9c5b62c7db578f5101497efb87b774720f91b9e878243e761952c52");
    const dark = readFileSync(new URL("./assets/agents/codex-dark.svg", import.meta.url), "utf8");
    expect(dark).toBe(original.toString("utf8").replaceAll("#0D0D0D", "#FFFFFF"));
  });
});
