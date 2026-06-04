# DataPyn v2 (monorepo)

**Produto:** aplicativo desktop = **fork do VS Code** (nova janela, workbench Electron), não extensão para VS Code.

| Decisão | Escolha |
|---------|---------|
| Formato de análise | **`.dpw`** (mesmo JSON do v1) |
| Documento | **Um `.dpw` = vários blocos** SQL, Python ou mistos |
| Layout do repo | **`nac/datapyn/v2/`** |

Plano: [`docs/DATAPYN_V2_MIGRATION_PLAN.md`](../../../docs/DATAPYN_V2_MIGRATION_PLAN.md)

## Estrutura

```
nac/datapyn/v2/
├── vscode/       ← FORK Code-OSS = a “tela nova” (produto)
├── extension/    ← extensão built-in (embutida no fork, não Marketplace)
├── runtime/      ← motor Python
└── cli/          ← migrate / headless
```

## O que confundir

| Você pediu | O que o PoC inicial parecia |
|------------|----------------------------|
| Fork VS Code → app **DataPyn** | Extensão `.vsix` no VS Code normal |

O código em `extension/` continua válido: é o módulo **interno** do fork (`extensions/datapyn`), ligado pelo [`vscode/scripts/bootstrap.sh`](vscode/scripts/bootstrap.sh).

## Começar (fork)

```bash
cd nac/datapyn/v2/runtime && uv sync --dev
cd ../vscode && chmod +x scripts/*.sh && ./scripts/bootstrap.sh
# depois: ./scripts/build.sh  (longo)
# ./checkout/scripts/code.sh
```

Ver [`vscode/README.md`](vscode/README.md).

## Status

| Componente | Estado |
|------------|--------|
| `vscode/` | bootstrap + product.json + scripts de build |
| `runtime/` | PoC JSON-RPC + `execute_sql` |
| `extension/` | PoC built-in (comandos); entra no fork via symlink |
| `cli/` | scaffold |

v1 PyQt permanece em `source/` até EOL.
