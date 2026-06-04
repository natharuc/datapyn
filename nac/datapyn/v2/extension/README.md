# DataPyn built-in extension (código-fonte)

**Não é o produto final.** Este diretório contém o código TypeScript da extensão que será **embutida no fork do VS Code** (`../vscode/`), em `extensions/datapyn`.

O usuário final abre o aplicativo **DataPyn** (fork), não instala esta pasta no VS Code.

## Papel na arquitetura

```
vscode/checkout/          ← fork Code-OSS (a “tela nova”)
  extensions/datapyn/     ← symlink para este diretório (bootstrap.sh)
  product.json            ← nome DataPyn, ícones, built-ins

extension/                ← você edita aqui
runtime/                  ← motor Python (subprocess)
```

## Desenvolvimento

### 1) Dentro do fork (caminho real)

Após `../vscode/scripts/bootstrap.sh` e `build.sh`, use `checkout/scripts/code.sh` — a extensão já está no app.

### 2) Modo rápido (só para debug da extensão)

Opcional: F5 com `launch.example.json` no VS Code **stock** — apenas para testar RPC antes do fork compilar. Não confundir com o produto v2.

```bash
cd nac/datapyn/v2/runtime && uv sync --dev
cd ../extension && npm install && npm run compile
# cp launch.example.json .vscode/launch.json
```

## Configuração (no fork)

| Setting | Descrição |
|---------|-----------|
| `datapyn.runtime.directory` | Pasta `../runtime` |
| `datapyn.runtime.useUv` | `uv run python -m datapyn_runtime` |
