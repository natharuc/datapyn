# DataPyn v2 — fork do VS Code (o produto)

**Isto é a “tela nova”.** O DataPyn v2 não é uma extensão para instalar no VS Code da Microsoft.

É um **executável próprio** (fork do [Code-OSS](https://github.com/microsoft/vscode)), com:

- janela / workbench do VS Code (Electron);
- **GitHub Copilot** como extensão oficial embutida no produto (fase posterior);
- funcionalidades DataPyn via **extensão built-in** (código em [`../extension/`](../extension/README.md));
- motor Python em [`../runtime/`](../runtime/README.md).

O usuário abre o app **DataPyn**, não “VS Code + plugin”.

```
┌─────────────────────────────────────────────┐
│  DataPyn.app  (= fork VS Code + built-ins)  │
│  ┌─────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Editor  │ │ Copilot  │ │ Painéis DPyn │  │
│  └─────────┘ └──────────┘ └──────────────┘  │
└──────────────────┬──────────────────────────┘
                   │ JSON-RPC
            ../runtime/ (Python)
```

## Pastas

| Item | Descrição |
|------|-----------|
| `product.json` | Branding DataPyn (merge no `product.json` do Code-OSS) |
| `scripts/bootstrap.sh` | Clona VS Code + symlink `extensions/datapyn` |
| `scripts/build.sh` | Compila extensão built-in + `yarn compile` do fork |
| `checkout/` | Clone do vscode (gitignored) |

## Primeira vez (Linux)

Requisitos: **git**, **Node 18+**, **yarn**, **Python 3.12+**, **uv**.

```bash
cd nac/datapyn/v2/runtime && uv sync --dev

cd ../vscode
chmod +x scripts/*.sh
./scripts/bootstrap.sh    # clone ~2GB — demora
./scripts/build.sh        # compile — demora muito na 1ª vez

./checkout/scripts/code.sh   # abre a janela DataPyn (fork dev)
```

Variáveis opcionais:

- `VSCODE_CHECKOUT` — caminho do clone (padrão: `vscode/checkout`)
- `VSCODE_REF` — branch/tag do upstream (padrão: `main`)

## O que NÃO é o produto

| Errado | Certo |
|--------|--------|
| Publicar só `.vsix` na Marketplace | Build do fork com extensão **embutida** |
| F5 “Run Extension” no VS Code stock como entrega | F5 só para **desenvolver** o built-in antes do merge no fork |
| Substituir PyQt por “extensão qualquer” | Substituir PyQt pelo **binário fork** |

## PoC atual

- `runtime/` — JSON-RPC + `SELECT 1` (ok)
- `extension/` — lógica built-in (comandos PoC); entra no fork via `extensions/datapyn`
- `checkout/` — ainda não versionado; gerado pelo `bootstrap.sh`

Próximo passo: primeiro build do fork + ícone + Copilot no `product.json` / `builtInExtensions`.
