# DataPyn v2 — fork do VS Code (o produto)

**Isto é a “tela nova”.** O usuário abre o executável **DataPyn** (fork Code-OSS), não instala extensão no VS Code da Microsoft.

```
DataPyn (fork)  =  checkout/scripts/code.sh
    └── extensions/datapyn  →  ../extension/ (built-in)
    └── ../runtime/         →  motor Python
```

## Requisitos (Linux)

- **git**, **nvm**, **Node 24.x** (lido de `checkout/.nvmrc`)
- **npm** (não use `yarn` no checkout — upstream bloqueia)
- Pacotes de sistema: `./scripts/install-linux-deps.sh` (Ubuntu/Debian)

## Primeira vez

```bash
cd nac/datapyn/v2/runtime && uv sync --dev

cd ../vscode
chmod +x scripts/*.sh
./scripts/bootstrap.sh      # clone + symlink extensão + branding
./scripts/install-linux-deps.sh   # opcional se o build falhar por libs
./scripts/build.sh            # npm install + compile (~5–15 min)

./scripts/start.sh            # inicia DataPyn em background (PID em /tmp/datapyn-app.pid)
./scripts/run.sh              # mesmo app, terminal em foreground
```

No app: Command Palette → **DataPyn: PoC Ping Runtime** ou **DataPyn: PoC Run SQL**.

## Problemas comuns

| Erro | Solução |
|------|---------|
| `Cannot find module .../out/vs/nls.js` | Build incompleto — rode `./scripts/build.sh` até o fim (~5–15 min) |
| `ENOENT .../out/nls.messages.json` | Rode `./scripts/build.sh` de novo (precisa `transpile --nls`) |
| `renderer launch-failed code 1002` | GPU/display na VM — `run.sh` já usa `--disable-gpu`; confira `DISPLAY=:1` |
| Linhas `dbus/bus.cc` vermelhas | Normal em VM sem D-Bus; pode ignorar se a janela abrir |
| Node 22 / `/exec-daemon/node` | Use `./scripts/run.sh` (não `code.sh` direto) — força Node 24 via nvm |
| `please use npm i instead` | Não rode `yarn` no `checkout/`; use `./scripts/build.sh` |
| `Please use Node.js v24…` | `nvm install 24.15.0` |
| Build falta lib GTK/X11 | `./scripts/install-linux-deps.sh` |
| Diagnóstico | `./scripts/verify.sh` |

## Variáveis

- `VSCODE_CHECKOUT` — pasta do clone (padrão: `vscode/checkout`)
- `DATAPYN_USER_DATA` — perfil do app (padrão: `/tmp/datapyn-fork-data`)
- `DISPLAY` — ex.: `:1` em VMs com GUI

## Desenvolvimento

- Edite `../extension/` (built-in) e `../runtime/`
- Recompile extensão: `cd ../extension && npm run compile`
- Recompile fork: `cd checkout && npm run compile` (ou `./scripts/build.sh`)
