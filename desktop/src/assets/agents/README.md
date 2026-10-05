# Pynia agent marks

These local SVGs identify the four supported integrations. They are bundled by Vite, work offline, and are displayed with the agent name. Their trademarks belong to their respective owners; their presence identifies the integration and does not imply endorsement.

| Files | Source |
| --- | --- |
| `claude.svg` | Claude asterisk path and terracotta fill extracted from the official [Claude website](https://claude.com/) wordmark SVG, preserving its original `0 0 125 125` symbol coordinates. |
| `cursor-light.svg`, `cursor-dark.svg` | Unmodified `General Logos/Cube/SVG/CUBE_2D_LIGHT.svg` and `CUBE_2D_DARK.svg` from the [official Cursor brand assets](https://cursor.com/brand). [Source archive](https://ptht05hbb1ssoooe.public.blob.vercel-storage.com/assets/brand/cursor-brand-assets.zip). |
| `copilot-light.svg`, `copilot-dark.svg` | Exact paths from GitHub's official [Copilot 24 Octicon](https://github.com/primer/octicons/blob/main/icons/copilot-24.svg), with black/white fill for background contrast. The accompanying `OCTICONS_LICENSE` is the repository's MIT license. The [Copilot identity guidelines](https://brand.github.com/brand-identity/copilot) permit the Octicon for product navigation; this is an integration icon, not a standalone marketing logo. |
| `codex-light.svg`, `codex-dark.svg` | Actual Codex product symbol (flower outline with a terminal prompt), extracted from `webview/assets/codex_new-f14177b03534.svg` in the installed, official `OpenAI.Codex_26.930.3930.0_x64__2p2nqsd0c76g0` Windows package. The light file preserves the source bytes; the dark variant only changes the three path fills from `#0D0D0D` to white for contrast. Product: [Codex by OpenAI](https://openai.com/codex/). Trademark reference: [OpenAI design guidelines](https://openai.com/brand/). This replaces the generic OpenAI Blossom previously used in the PyQt assets. |

Verified on 2026-10-04. Light and dark variants retain the mark's proportions and are selected by the application's `data-theme` setting. Unknown integrations use a neutral fallback icon.

Codex original SVG SHA-256: `0b490f33f9c5b62c7db578f5101497efb87b774720f91b9e878243e761952c52`.
