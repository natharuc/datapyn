# DataPyn v2 — VS Code extension (PoC)

Extensão mínima que inicia o runtime Python e executa SQL.

## Build

```bash
cd nac/datapyn/v2/extension
npm install
npm run compile
```

Requisitos: **Node.js 18+**, **uv** (para `datapyn.runtime.useUv`, padrão `true`).

## Testar no VS Code / Cursor

1. Abra a pasta `nac/datapyn/v2/extension` no editor.
2. Copie `launch.example.json` → `.vscode/launch.json` (a pasta `.vscode` é ignorada pelo git do repo).
3. **Run and Debug** → **Run Extension** (abre Extension Development Host).
3. No host, Command Palette:
   - **DataPyn: PoC Ping Runtime**
   - **DataPyn: PoC Run SQL (SELECT 1)** — usa seleção ou texto do editor, senão `SELECT 1 AS n`
4. Resultado em **Output → DataPyn**.

## Configuração

| Setting | Descrição |
|---------|-----------|
| `datapyn.runtime.directory` | Caminho para `nac/datapyn/v2/runtime` (vazio = `../runtime` relativo à extensão) |
| `datapyn.runtime.useUv` | `true` → `uv run python -m datapyn_runtime` |

Antes do primeiro uso, rode `uv sync` em `../runtime`.
