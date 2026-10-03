# DataPyn Tauri Preview: distribuição e atualizações

O aplicativo usa `app.datapyn.desktop.preview` e um canal próprio. Builds normais
não têm chave nem endpoint de atualização e informam que o atualizador está
indisponível. O servidor e os instaladores do PyQt não são consultados.

O diálogo permite verificar, baixar e instalar explicitamente. O download mantém
os bytes no Rust e envia apenas progresso à interface. Antes da instalação, o
frontend salva os documentos e o estado do workspace; uma falha no salvamento
impede a instalação. No Windows, o plugin encerra o aplicativo para executar o
NSIS. No Linux, o usuário reinicia depois da instalação.

O plugin oficial exige assinatura do artefato e verifica a chave pública embutida.
Endpoints usam HTTPS; nenhum modo de transporte ou certificado inseguro é
habilitado. Essa assinatura do updater é diferente do certificado Authenticode do
Windows. [Documentação do updater](https://v2.tauri.app/plugin/updater/),
[assinatura Windows](https://v2.tauri.app/distribute/sign/windows/).

## Gerar artefatos para revisão

`npm run desktop:build` continua gerando o build de migração com updater
desabilitado. Para um build assinado, mantenha uma chave exclusiva deste canal e
configure no ambiente do processo:

- `DATAPYN_TAURI_UPDATER_PUBLIC_KEY`: conteúdo da chave pública do Tauri, nunca um caminho.
- `DATAPYN_TAURI_UPDATER_ENDPOINT`: URL HTTPS pública do manifesto deste canal.
- `TAURI_SIGNING_PRIVATE_KEY`: chave privada ou caminho aceito pelo CLI Tauri.
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: senha da chave, quando houver.

Execute `npm run desktop:build -- --signed --ci --bundles nsis` no Windows, ou
`--bundles appimage` no Linux. A chave privada fica apenas no ambiente do processo;
o config adicional contém somente a chave pública e o endpoint. Configuração
incompleta falha antes do build; não há fallback silencioso para um release sem
assinatura. O runtime Python congelado é incluído e testado antes do empacotamento.

O workflow manual `.github/workflows/tauri-signed.yml` usa as variáveis de repositório
com os dois nomes `DATAPYN_TAURI_UPDATER_*` acima e os secrets exclusivos
`DATAPYN_TAURI_SIGNING_PRIVATE_KEY` / `DATAPYN_TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.
Ele gera os instaladores assinados e um `latest.json` com os artefatos e suas
assinaturas por plataforma. O diretório HTTPS dos artefatos é informado na execução.
Todos os arquivos ficam como artifacts do workflow para revisão; o workflow não
publica, instala nem cria uma release.

Depois da revisão, disponibilize os instaladores e o manifesto nos endereços
configurados. Preserve a chave do canal e incremente a versão Tauri antes de uma
nova release. O updater mantém a comparação padrão de versões; downgrade não é
habilitado. Não foi criada chave, configurado endpoint de produção, assinado ou
publicado instalador nesta migração.

## Janelas destacadas

O bridge nativo aceita `window.open` somente para `/popout.html` do domínio de
assets Tauri ou da origem exata do servidor de desenvolvimento configurado. URLs
externas, outros arquivos, credenciais na URL e outras portas são recusados. Cada
janela recebe um identificador próprio e preserva o contexto relacionado do
WebView para o portal React do Dockview. Fechar a janela principal destrói as
janelas destacadas. O gesto e o comportamento entre monitores exigem aceite
visual no desktop de cada plataforma.
