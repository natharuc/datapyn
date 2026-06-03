# DataPyn v2 — Python runtime

Pacote Python desacoplado do PyQt6, reutilizando módulos do v1:

- `source/src/database/`
- Execução SQL/Python e namespace (hoje em `main_window/_workers.py`, services)

API alvo: `execute`, `connect`, `list_variables`, `load_schema` (JSON-RPC).

**Não iniciado** — scaffold para Fase 1 do plano de migração.
