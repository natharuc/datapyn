# DataPyn v2 — Python runtime

Motor de execução desacoplado do PyQt6. Comunicação via **JSON-RPC 2.0** (uma linha JSON por mensagem em stdin/stdout).

## Comandos

```bash
cd nac/datapyn/v2/runtime
uv sync --dev
uv run pytest -q
```

## Servidor stdio

```bash
uv run python -m datapyn_runtime
```

### Métodos (PoC)

| Método | Params | Resultado |
|--------|--------|-----------|
| `ping` | `{}` | `{ "ok": true, "version": "0.1.0" }` |
| `execute_sql` | `{ "sql": "SELECT 1" }` | `{ columns, rows, row_count, truncated }` |
| `shutdown` | `{}` | `{ "ok": true }` |

PoC usa **SQLite em memória** (`sqlite:///:memory:`). Próximo passo: conectar `ConnectionManager` do v1.

## Exemplo

```bash
echo '{"jsonrpc":"2.0","method":"execute_sql","params":{"sql":"SELECT 42 AS x"},"id":1}' \
  | uv run python -m datapyn_runtime
```
