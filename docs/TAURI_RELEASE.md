# Release independente do DataPyn Tauri

O workflow `.github/workflows/tauri-release.yml` compila nativamente as mesmas
plataformas e arquiteturas de `.github/workflows/release.yml` do PyQt6. Não chama
o instalador antigo, não altera `pyproject.toml`, não usa os tags `vX.Y.Z` do
semantic-release e nunca promove uma release Tauri para `releases/latest`.

| Plataforma | PyQt6 publicado atualmente | Distribuição Tauri |
| --- | --- | --- |
| Windows x86_64 | Setup `.exe`, ZIP | NSIS `.exe` assinado para updater, ZIP com aplicativo e sidecar |
| Linux x86_64, base Ubuntu 22.04 | DEB, tar.gz | DEB com launcher AppImage por usuário, AppImage assinada, tar.gz portátil com o mesmo launcher |
| macOS arm64, macOS 14 | DMG | DMG, `.app.tar.gz` assinada para updater |

Todos os nomes de download começam com `DataPyn-Tauri-<versão>-<plataforma>`.
Os executáveis dos agentes, servidores de banco e configurações externas de
autenticação seguem os requisitos descritos em [TAURI_RUNTIME_DISTRIBUTION.md](TAURI_RUNTIME_DISTRIBUTION.md).

## Canal e versões

As versões Tauri começam em `1.0.0`, independentemente da versão PyQt6. Antes
de criar `tauri-v1.0.1`, alinhe `desktop/package.json`,
`desktop/src-tauri/Cargo.toml` e `desktop/src-tauri/tauri.conf.json` em `1.0.1`.
Atualize também os respectivos lockfiles. O workflow recusa tags antigos,
pré-releases, versões divergentes e a identidade antiga de preview.

O feed fixo é
`https://github.com/natharuc/datapyn/releases/download/tauri-stable/latest.json`.
O manifesto contém `channel: "tauri-stable"`, a versão, os três targets Tauri
(`windows-x86_64`, `linux-x86_64`, `darwin-aarch64`) e as assinaturas reais.
Cada URL aponta para um artefato de `tauri-vX.Y.Z`, nunca para um arquivo PyQt6.

As releases de versão e do feed usam `make_latest: false`. O feed também é
marcado como prerelease para que permaneça fora do mecanismo `releases/latest`
usado pelo instalador/atualizador PyQt6. O tag `tauri-stable` e seu único asset
`latest.json` são intencionalmente mutáveis; os instaladores publicados em cada
tag de versão não são substituídos. A imutabilidade automática de releases do
GitHub deve permitir a atualização desse feed; o publicador recusa um feed
que já tenha sido marcado como imutável.

## Configuração do GitHub

Configure apenas segredos dedicados ao aplicativo novo:

- `DATAPYN_TAURI_SIGNING_PRIVATE_KEY`: a chave privada do updater.
- `DATAPYN_TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: sua senha, quando houver.
- `DATAPYN_TAURI_UPDATER_PUBLIC_KEY`: variável opcional. Quando omitida, usa a
  chave pública já embutida no config; quando definida, precisa ser idêntica.
- `DATAPYN_TAURI_RELEASE_TOKEN`: token opcional para publicação em uma branch
  que altera workflows em relação à branch padrão. Nesse caso, o GitHub exige
  permissões de repositório `Contents: write` e `Workflows: write`; o
  `GITHUB_TOKEN` não recebe esta última permissão. Em outros casos, o workflow
  usa seu `GITHUB_TOKEN` com `Contents: write`.

A chave privada não entra no config, no manifesto ou nos artifacts. A assinatura
do updater verifica a origem do download e é diferente do certificado
Authenticode Windows e do Developer ID Apple.
[Assinaturas obrigatórias do updater Tauri](https://v2.tauri.app/plugin/updater/),
[permissões da API GitHub para criar releases](https://docs.github.com/en/rest/releases/releases#create-a-release).

Para uma assinatura Developer ID e notarização macOS, use os secrets dedicados
`DATAPYN_TAURI_APPLE_CERTIFICATE`, `DATAPYN_TAURI_APPLE_CERTIFICATE_PASSWORD`,
`DATAPYN_TAURI_APPLE_ID`, `DATAPYN_TAURI_APPLE_PASSWORD` e as variáveis
`DATAPYN_TAURI_APPLE_SIGNING_IDENTITY`, `DATAPYN_TAURI_APPLE_TEAM_ID`.
Sem eles, o build arm64 usa assinatura ad hoc `-`; a instalação pode exigir a
liberação do aplicativo em Privacidade e Segurança. Variáveis Apple vazias são
removidas antes do build para não tentar importar um certificado vazio.
[Assinatura e notarização macOS](https://v2.tauri.app/distribute/sign/macos/).

## Compilar e publicar

Um push na branch `codex/tauri-migration` faz um **dry run** com assinatura e
build nas três plataformas, conservando os arquivos como artifacts. Ele não
cria tags ou releases nem muda o feed, mesmo que um flag de publicação seja
injetado no ambiente. O primeiro teste da distribuição pode usar esse fluxo.

Também existe `workflow_dispatch`: informe um tag Tauri existente e mantenha
`publish: false` para gerar os mesmos artifacts sem publicar.

Quando a distribuição estiver validada, crie e envie o tag da versão:

```bash
git tag tauri-v1.0.0 <commit-validado-da-branch-tauri>
git push origin tauri-v1.0.0
```

Um push de tag Tauri ou execução manual com `publish: true` habilita publicação.
O commit precisa pertencer à branch isolada de migração ou a `main`; não exige
misturar o código Tauri com o pipeline PSR. O guard do workflow legado também
recusa execução manual em refs `tauri-*` e na branch `codex/tauri-migration`.

O build verifica frontend, Python e contratos Rust, empacota o Python com os
drivers e executa os quatro smokes do sidecar congelado. No macOS, repete os
smokes após assinatura da aplicação, com os entitlements de carregamento das
bibliotecas Python. Cada arquivo `.sig` é verificado contra a chave pública
embutida por `minisign_verify`, antes de poder ser publicado.

A etapa final exige os três manifests da mesma versão e os downloads
correspondentes, monta `latest.json` e `SHA256SUMS.txt`, e preserva o pacote
completo para revisão. Primeiro envia os arquivos para um rascunho da release;
somente após o upload publica a versão e promove `tauri-stable/latest.json`.
Falhas de build/upload mantêm o feed anterior. Uma versão publicada não pode
ser sobrescrita; uma promoção antiga não pode diminuir a versão do feed.
Se a versão foi publicada e a promoção do feed falhou por rede, use **Re-run
failed jobs** para reutilizar os artifacts já compilados. O manifesto e os
checksums são determinísticos para esses artifacts. O publicador só retoma o
feed depois de conferir os nomes, tamanhos e digests SHA-256 de todos os assets
da release já publicada, inclusive manifest e assinaturas. Não reenvia nem
edita a versão. Uma promoção já completa retorna sem fazer novas escritas.

O ZIP Windows deve ser extraído em uma pasta gravável pelo usuário. A primeira
atualização usa o NSIS assinado nessa mesma pasta e passa a registrar a
desinstalação do aplicativo; preserva o caminho e não usa o instalador PyQt6.

## Linux: atualização em todos os formatos

O updater oficial atualiza AppImages no Linux. Para manter isso funcional
também no DEB, o pacote `datapyn-tauri` instala somente o seed em
`/usr/lib/datapyn-tauri`, o launcher `/usr/bin/datapyn-tauri`, ícone e associação
`.dpw` com nomes próprios. Na primeira abertura, o launcher copia atomicamente
a AppImage para `${XDG_DATA_HOME:-$HOME/.local/share}/datapyn-tauri/installation/`.
Execuções simultâneas não expõem uma cópia parcial nem substituem a aplicação.

O aplicativo executa e atualiza essa cópia gravável pelo usuário. Uma abertura
posterior ou `apt upgrade` preserva uma AppImage já atualizada. O tar.gz portátil
usa o mesmo launcher, inclusive quando a pasta de extração é somente leitura.
`APPIMAGE_EXTRACT_AND_RUN=1` evita exigir FUSE. Não são gravados dados do Tauri
no diretório do PyQt6.

Desinstalar o DEB remove os arquivos do pacote. Configurações, documentos e a
cópia de atualização do usuário permanecem no perfil Tauri, como os dados de
outros aplicativos; não são excluídos automaticamente pelo desinstalador.
Para verificar o launcher offline, os testes usam uma AppImage simulada, abrem
oito processos concorrentes e confirmam que uma atualização posterior não é
sobrescrita pelo seed.

## Comandos de verificação local

```bash
node --test scripts/tauri/release.test.mjs scripts/tauri/linux-package.test.mjs scripts/tauri/publish.test.mjs
node scripts/tauri/release.mjs verify-version tauri-v1.0.0
```

O teste que realmente monta e inspeciona um DEB roda no Linux. Os testes do
launcher também podem rodar no Git Bash no Windows. As publicações dos testes
são simuladas, sem requisições para contas ou servidores externos. Aceite real
da instalação em macOS/Linux e das autenticações depende de executar os builds
nativos e de testes nos respectivos sistemas.
