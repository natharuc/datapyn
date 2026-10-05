# DataPyn Desktop

Frontend React/TypeScript em Tauri 2, com Monaco e grade de resultados. A execução SQL/Python fica em um runtime Python local e em kernels separados por sessão. Esta é a aplicação desktop da branch `main`; o código PyQt6 permanece para compatibilidade e manutenção do legado.

Consulte [arquitetura, contrato e fases](../docs/TAURI_MIGRATION.md) e o [diagnóstico inicial](../docs/DATAPYN_DIAGNOSTIC_AND_MIGRATION_BASELINE.md).

## Desenvolvimento

Pré-requisitos: Python 3.12+, `uv`, Node.js 22.12+ e Rust estável. Windows precisa das ferramentas C++/Windows SDK e WebView2; Linux precisa de WebKitGTK e bibliotecas de desenvolvimento; macOS precisa de Xcode Command Line Tools. Veja os [pré-requisitos oficiais do Tauri](https://v2.tauri.app/start/prerequisites/).

Na raiz do repositório:

```powershell
uv sync --dev --frozen
cd desktop
npm ci
npm run desktop:dev
```

O comando inicia o Vite na porta 1420 e o shell Tauri. O shell inicia o Python da `.venv` com `-u -m datapyn_runtime` e `PYTHONPATH=source`. Não é preciso gerar o sidecar para desenvolver.

Os runners usam Rust em `.tooling/cargo` e `.tooling/rustup`, se disponível; também reconhecem um SDK Windows local em `.tooling/windows-sdk/{cpp,x64}` e ferramentas MSVC instaladas. A configuração só se aplica aos subprocessos. Um terminal configurado pelas ferramentas C++ também funciona.

Para escolher outro interpretador, configure `DATAPYN_RUNTIME_PYTHON` com o caminho absoluto de um Python com as dependências do projeto. `npm run dev` inicia apenas a interface no navegador; o transporte de execução depende do shell desktop.

## Validação

```powershell
# Dentro de desktop
npm test
npm run build

# Na raiz, sem abrir uma janela
uv run pytest -c runtime_tests/pytest.ini runtime_tests -q
uv run python scripts/tauri/smoke_runtime.py
node scripts/tauri/check.mjs
```

O smoke percorre SQLite → DataFrame nomeado → Python, executa outra sessão durante um loop infinito, cancela o loop, verifica encerramento de um subprocesso criado pelo código e confirma recuperação do kernel. Os testes não precisam de bancos externos ou autenticação Copilot.

`check.mjs` roda Cargo fmt/check/test usando o mesmo ambiente dos runners desktop, incluindo ferramentas locais em `.tooling`, quando disponíveis.

## Sidecar e build nativo

```powershell
# Dentro de desktop
npm run runtime:bundle -- --smoke
npm run desktop:build -- --no-bundle

# Gerar os instaladores definidos no overlay Tauri
npm run desktop:build
```

`runtime:bundle` usa PyInstaller onefile e grava `src-tauri/binaries/datapyn-runtime-<host-triple>[.exe]`. `desktop:build` verifica o runtime congelado antes de chamar Tauri com `src-tauri/tauri.bundle.conf.json`. O projeto-base não declara `externalBin`; o overlay adiciona o sidecar apenas no build distribuível.

O runtime deve ser construído no mesmo sistema e arquitetura do destino. `--target` aceita o host Rust nativo; o script rejeita cross-compilation do runtime Python. Artefatos gerados ficam em `build/tauri-runtime`, `desktop/src-tauri/binaries` e no target Cargo.

O workflow de distribuição testa os instaladores Windows, Linux e macOS em runners descartáveis, incluindo o runtime congelado e as assinaturas do updater. Consulte [a publicação de versões](../docs/TAURI_RELEASE.md) e [a matriz de funcionalidades e validações](../docs/TAURI_FEATURE_PARITY.md).

## Dados e versão PyQt6

O Tauri mantém configurações, credenciais, workspaces e resultados em armazenamento próprio. Importação de um arquivo escolhido e migração de formatos são ações explícitas. Para executar a interface PyQt6 preservada, use `uv run python source/main.py` na raiz. Os instaladores e canais de atualização são independentes.
