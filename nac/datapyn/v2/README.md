# DataPyn v2 (monorepo)

Implementação do **DataPyn v2** dentro do repositório principal do DataPyn v1.

| Decisão | Escolha |
|---------|---------|
| Formato de análise | **`.dpw`** (mesmo JSON do v1, sem substituto) |
| Documento | **Um arquivo `.dpw` = múltiplos blocos** SQL, Python ou mistos (comportamento atual) |
| Layout do repo | **`nac/datapyn/v2/`** — todo código novo do v2 fica aqui |

Plano completo: [`docs/DATAPYN_V2_MIGRATION_PLAN.md`](../../../docs/DATAPYN_V2_MIGRATION_PLAN.md)

## Estrutura

```
nac/datapyn/v2/
├── README.md           # este arquivo
├── extension/          # extensão VS Code (TypeScript) — PoC
├── runtime/            # motor Python JSON-RPC — PoC
├── vscode/             # fork Code-OSS + product.json
└── cli/                # ferramentas CLI (migrate, run headless)
```

## PoC Fase 0 (implementado)

1. **Runtime** (`runtime/`): `ping`, `execute_sql` via SQLite em memória.
2. **Extension** (`extension/`): comandos PoC que falam com o runtime via subprocess + stdio.

### Quick start

```bash
# Runtime
cd nac/datapyn/v2/runtime && uv sync --dev && uv run pytest -q

# Extension
cd ../extension && npm install && npm run compile
# F5 → Run Extension no VS Code/Cursor
```

## v1 (referência)

- App PyQt6: `source/`
- Formato `.dpw`: `source/src/ui/main_window/_file_io.py`
- Dependências compartilháveis: `source/src/database/`, workers, services

## Status

| Componente | Estado |
|------------|--------|
| `runtime/` | PoC — JSON-RPC + `execute_sql` (SQLite) |
| `extension/` | PoC — ping + run SQL |
| `vscode/` | scaffold |
| `cli/` | scaffold |

Próximo passo: language support `.dpw`, conexões reais (v1 `ConnectionManager`), painel de resultados.
