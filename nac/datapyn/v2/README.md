# DataPyn v2 (monorepo)

**Produto = fork do VS Code** em [`vscode/`](vscode/README.md) — aplicativo **DataPyn**, não extensão Marketplace.

| Decisão | Escolha |
|---------|---------|
| Formato | **`.dpw`** (igual v1) |
| Blocos | SQL, Python ou mistos no mesmo arquivo |
| Código v2 | `nac/datapyn/v2/` |

## Quick start (Linux)

```bash
cd nac/datapyn/v2/runtime && uv sync --dev
cd ../vscode && chmod +x scripts/*.sh
./scripts/bootstrap.sh
./scripts/build.sh          # corrigido: Node 24 + npm
./scripts/run.sh            # abre o fork
```

## Estrutura

| Pasta | Papel |
|-------|--------|
| **`vscode/`** | Fork Code-OSS — **a tela nova** |
| `extension/` | Código built-in (`extensions/datapyn` no fork) |
| `runtime/` | Motor Python JSON-RPC |
| `cli/` | migrate / headless (futuro) |

Plano: [`docs/DATAPYN_V2_MIGRATION_PLAN.md`](../../../docs/DATAPYN_V2_MIGRATION_PLAN.md)

## Status

| Componente | Estado |
|------------|--------|
| `vscode/` | bootstrap + **build OK** + `run.sh` |
| `runtime/` | PoC `execute_sql` + testes |
| `extension/` | PoC built-in no fork |
| `cli/` | scaffold |

v1 PyQt: `source/`
