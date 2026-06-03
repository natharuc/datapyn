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
├── extension/          # extensão VS Code (TypeScript)
├── runtime/            # motor Python (extraído/adaptado do v1)
├── vscode/             # fork Code-OSS + product.json
└── cli/                # ferramentas CLI (migrate, run headless)
```

## v1 (referência)

- App PyQt6: `source/`
- Formato `.dpw`: `source/src/ui/main_window/_file_io.py`
- Dependências compartilháveis: `source/src/database/`, workers, services

## Status

| Componente | Estado |
|------------|--------|
| `extension/` | scaffold |
| `runtime/` | scaffold |
| `vscode/` | scaffold |
| `cli/` | scaffold |

Próximo passo recomendado (Fase 0): PoC em `extension/` + `runtime/` — executar `SELECT 1` via subprocess a partir do VS Code OSS em `vscode/`.
