# Distribuição DataPyn Tauri

O Tauri tem instalação, armazenamento, assinatura e canal de atualização próprios.
A migração permanece em `codex/tauri-migration`. O instalador e updater do PyQt6
não instalam esta versão.

## Plataformas preservadas

A matriz foi conferida no workflow de releases do PyQt6, incluindo a arquitetura
real dos runners. O runtime Python é gerado nativamente em cada plataforma.

| Plataforma | PyQt6 | Tauri |
| --- | --- | --- |
| Windows x64 | Setup.exe e ZIP | NSIS Setup.exe e ZIP |
| Linux x64, Ubuntu 22.04+ | DEB e tar.gz | DEB, tar.gz e AppImage |
| macOS 14+, Apple Silicon | DMG | DMG e app.tar.gz para updater |

Python, bibliotecas de análise/exportação e drivers SQL Server, PostgreSQL, MySQL,
MariaDB e Databricks são embutidos, com as autenticações existentes. SQLite também
está disponível. O usuário não precisa instalar Python ou Node.js.
Veja [o contrato dos drivers e pré-requisitos nativos](TAURI_RUNTIME_DISTRIBUTION.md).

O Setup Windows inclui WebView2 offline e o MSI Microsoft ODBC 18 x64, verificado
por hash fixado e assinatura Microsoft. O instalador verifica ODBC 17/18 x64 antes
de pedir consentimento e permissão de administrador apenas para esse driver.
Atualizações com o driver presente não repetem a instalação. O uninstall não
remove drivers compartilhados nem dados do usuário.

No ZIP, mantenha os dois executáveis juntos. WebView2 e ODBC são pré-requisitos do
portátil; o Setup os prepara. Atualizar o ZIP usa o NSIS na mesma pasta, preservando
o caminho e registrando a instalação no Windows.

No Linux, DEB e tar.gz iniciam um AppImage gerenciado em
`$XDG_DATA_HOME/datapyn-tauri/installation` (padrão `~/.local/share`). Essa cópia
gravável recebe updates assinados. Upgrade do DEB não substitui uma versão já
atualizada. `APPIMAGE_EXTRACT_AND_RUN=1` dispensa FUSE. SQL Server exige o driver
Microsoft nativo; os demais pré-requisitos estão no documento de runtime.

O macOS recebe `.dpw` pelo Finder, inclusive durante startup. App e sidecar são
assinados pelo bundler; o entitlement permite carregar extensões Python e pacotes
do usuário. O pipeline verifica o sidecar novamente depois da assinatura.

## Identidade e armazenamento

- Nome: `DataPyn Tauri`; identificador: `app.datapyn.tauri`.
- Versão independente: `1.0.0`, sem alterar a numeração do PyQt6.
- Windows: `%LOCALAPPDATA%/app.datapyn.tauri`.
- macOS: `~/Library/Application Support/app.datapyn.tauri`.
- Linux: `$XDG_DATA_HOME/app.datapyn.tauri` ou `~/.local/share/app.datapyn.tauri`.
- Credenciais: `DataPyn.Tauri.Connections` no cofre do sistema; notificações usam
  um namespace Tauri por workspace.
- Snapshots: cache Tauri próprio do sistema.

O host fixa esses caminhos e não herda um workspace PyQt6 do shell. Configurações
continuam compatíveis com o formato PyQt6 por importação explícita. A desinstalação
não apaga workspaces.

## Atualização automática

Feed único:
`https://github.com/natharuc/datapyn/releases/download/tauri-stable/latest.json`.
Instaladores usam tags imutáveis `tauri-vX.Y.Z`. O feed valida canal, versão,
plataforma e URLs da mesma release; o plugin verifica a assinatura com a chave
pública embutida.

O app verifica após iniciar e a cada seis horas; falhas têm retry após quinze
minutos. O download fica em segundo plano no recurso nativo mesmo com o diálogo
fechado. Ao terminar aparece `Atualização pronta`. A instalação exige ação do
usuário e salva o workspace. Operações em andamento e falha ao salvar impedem a
instalação. Sair antes de instalar descarta o download e exige baixá-lo novamente.

As releases Tauri usam `make_latest=false`; o feed `tauri-stable` é prerelease para
não substituir o `latest` consultado pelo PyQt6. A promoção exige as três
plataformas e rejeita downgrade, mistura de versões e publicação parcial.

## Build e publicação

```powershell
uv sync --dev --frozen
npm --prefix desktop ci
npm --prefix desktop run desktop:build -- --signed --ci --bundles nsis
```

Linux: `--bundles appimage`. macOS: `--bundles app,dmg`. O build executa quatro
smokes no sidecar congelado. O staging produz DEB e portáteis conforme
[TAURI_RELEASE.md](TAURI_RELEASE.md).

Build assinado exige `TAURI_SIGNING_PRIVATE_KEY` e, se aplicável,
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`. A chave pública embutida é o padrão;
`DATAPYN_TAURI_UPDATER_PUBLIC_KEY` divergente é rejeitada. O endpoint é fixo.
Build sem `--signed` serve apenas para validação.

Os secrets exclusivos `DATAPYN_TAURI_SIGNING_PRIVATE_KEY` e
`DATAPYN_TAURI_SIGNING_PRIVATE_KEY_PASSWORD` foram configurados no repositório.
A cópia local está fora do Git em `%LOCALAPPDATA%/DataPyn-Tauri/signing`, restrita
ao usuário e SYSTEM. `password.dpapi` só abre no mesmo usuário Windows. Guarde
chave e senha em backup seguro antes de distribuir: perder a chave impede assinar
updates aceitos pelos clientes instalados.

Push na branch de migração gera artefatos para revisão e não publica releases.
Publicação exige tag própria ou despacho explícito, conforme TAURI_RELEASE.md.
A assinatura do updater é diferente do certificado de editor Windows e da
notarização Apple. Configure essas credenciais para distribuição com editor
reconhecido/Gatekeeper; assinatura ad hoc não substitui notarização.

Referências: [updater Tauri](https://v2.tauri.app/plugin/updater/),
[instalador Windows](https://v2.tauri.app/distribute/windows-installer/),
[releases GitHub](https://docs.github.com/en/rest/releases/releases#create-a-release).
