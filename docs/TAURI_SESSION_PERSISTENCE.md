# Armazenamento e restauração das sessões internas

O Tauri grava sessões internas em `workspace_sessions.sqlite3` dentro de cada perfil. Uma mudança no código atualiza somente aquele documento; foco, título e estado de visualização ficam separados do código. A restauração carrega documentos e metadados, sem executar SQL/Python automaticamente.

Os formatos públicos `.dpw`, `.sql`, `.py` e `.ipynb` continuam usando os leitores/escritores existentes. O banco é privado do aplicativo, separado da exportação de arquivos e do cache Parquet opt-in. Não serializa DataFrames, engines, objetos Python ou pickle.

Ao abrir uma análise restaurada, o frontend prepara sua sessão e autentica a conexão salva antes de liberar o contexto SQL. Banco/schema focados no documento são enviados ao runtime antes de autenticar, inclusive na nova tentativa, mesmo quando diferem dos valores configurados na conexão. A resposta resolvida pelo driver determina o contexto da UI e do namespace Python. As outras análises são preparadas quando ativadas; nenhum código é executado por essa etapa. O indicador de abertura, o erro e o estado de autenticação são transitórios: não entram no `.dpw` nem provocam regravação do documento ou header a cada mudança de status. Senhas também não entram no objeto de conexão mantido pelo controller.

## Estrutura

| Tabela | Conteúdo |
|---|---|
| `documents` | Payload público de cada análise, identificado pelo `sessionId` estável |
| `document_headers` | Título, arquivo, modified, foco, blockIds, editorViewState e extras privados |
| `document_order` | Ordem das análises abertas |
| `workspace_metadata` | Aba selecionada, preferências, atalhos, layout e extras desconhecidos |
| `store_control` | Revisão, horário confirmado, contagens, versão lógica e fingerprint da migração |

Payloads, headers e valores de metadados têm hashes SHA-256. Conteúdo idêntico não é regravado; `updated_revision` muda somente nas linhas alteradas. Campos pequenos precedem o JSON grande nas tabelas para consultas de hashes/tamanhos evitarem ler os payloads extensos.

`BEGIN IMMEDIATE` torna upserts, exclusões, ordem e metadados uma operação única. Leituras usam uma transação consistente, incluindo a revisão retornada. Há limite de 1000 análises abertas, 16 MiB de estado e validação de IDs, ordem, tipos, JSON finito e campos reservados. Uma falha ou erro de validação desfaz a transação completa.

## Migração do JSON interno

Na primeira abertura, se o banco não existe, `workspace_state.json` é validado e importado. IDs ausentes recebem valores determinísticos; IDs existentes, conteúdo, extras, foco, parâmetros, layout, preferências e atalhos são preservados. A migração publica um banco completo após o commit, sob lock de inicialização liberado pelo sistema operacional.

O arquivo JSON original permanece intacto. O ID legado `document.desktop.session_id` é herdado quando o header não tem `sessionId`, conservando a associação com snapshots Parquet e conversas privadas. Depois da migração o SQLite é autoritativo: abrir novamente não reaplica o JSON nem substitui edições novas por uma cópia antiga. JSON inválido, banco incompleto, schema desconhecido, checksum inconsistente ou corrupção geram erro explícito. Não há fallback silencioso para um workspace vazio ou para o JSON antigo.

Criar, selecionar, arquivar/restaurar e duplicar perfis continua funcionando. Selecionar valida o alvo antes de mudar `active_id`. Duplicar cria outro banco, preserva IDs de sessões e remapeia referências de conexões/grupos. O diretório `.pyqt-configuration` de importação explícita também é copiado com a allowlist e os limites próprios; credenciais continuam com a política opt-in existente.

## Journal e durabilidade

WAL é habilitado nas versões corrigidas 3.51.3 ou posteriores, 3.50.7+ da série 3.50 e 3.44.6+ da série 3.44. Séries intermediárias sem o patch usam `journal_mode=DELETE`, conservando atualizações incrementais e transações. O guard segue a descrição oficial do [WAL-reset bug e seus backports](https://www.sqlite.org/wal.html#walreset).

Em WAL, o store usa `synchronous=FULL`. Em DELETE, usa `synchronous=EXTRA`, que acrescenta sincronização da remoção do journal; essa é a recomendação documentada para durabilidade em rollback journal. [PRAGMA synchronous oficial](https://www.sqlite.org/pragma.html#pragma_synchronous).

WAL mantém autocheckpoint em 1000 páginas. Troca de perfil, fechamento de stores/evicção e shutdown tentam checkpoint TRUNCATE e fecham as conexões. Journals de recuperação são administrados pelo SQLite. A referência de comportamento está em [checkpointing do SQLite](https://www.sqlite.org/wal.html#ckpt).

## Contrato RPC

`workspace.profiles.state` preserva o DTO existente:

```json
{
  "active_id": "default",
  "profile": {"id": "default", "name": "Padrão", "path": "..."},
  "state": {"documents": [], "activeIndex": 0, "preferences": {}, "shortcuts": {}, "layout": {}},
  "revision": 1,
  "storage": "sqlite",
  "journal_mode": "delete"
}
```

Um perfil sem estado confirmado retorna `state: null`. `workspace.profiles.save` continua aceitando `{profile_id,state}` completo e conserva campos desconhecidos. O novo `workspace.profiles.patch` aceita:

```json
{
  "profile_id": "default",
  "upserts": [{"sessionId": "analysis-1", "title": "Novo título", "editorViewState": {"cursor": 9}, "remove_header": ["filePath"]}],
  "removes": ["analysis-2"],
  "order": ["analysis-1"],
  "metadata": {"activeIndex": 0},
  "remove_metadata": ["extra_antigo"]
}
```

Todos os campos de operação são opcionais. `upserts` com `document` substituem payload e header desse registro; sem `document`, mesclam somente o header de uma sessão existente. `remove_header` é controle da operação e não é persistido. `order`, quando enviado, precisa listar exatamente os IDs finais; quando ausente, conserva a ordem anterior e acrescenta sessões novas. `metadata` mescla campos top-level, sem `documents` ou `saved_at`. `expected_revision` opcional permite rejeitar um escritor desatualizado; a fila serial do frontend não depende dele.

A resposta inclui `saved_at`, `revision`, `changed_documents`, `changed_payloads`, `changed_headers`, `removed_documents`, `changed_metadata` e `order_changed`. Reenviar o mesmo patch já confirmado é idempotente: não regrava linhas nem aumenta a revisão. `activeIndex` pode ser atualizado, mas não excluído. Uma tentativa com `expected_revision` antigo é rejeitada; a fila serial do frontend não envia essa opção. `NativeDrafts` captura perfil/estado no agendamento, envia apenas diferenças, serializa gravações e mantém alterações para retry em caso de erro. O estado privado memoizado evita reenviar código quando só foco/view/título mudaram. Durante troca de perfil e fechamento, o controller protege o estado capturado e os editores ficam somente leitura, inclusive em painéis destacados.

## Layout dos docks e janela principal

O mesmo store guarda `layout.docking`, o grafo serializado Dockview, e `layout.mainWindow`, a geometria nativa. Mover, redimensionar, agrupar ou ocultar painéis atualiza apenas `metadata.layout`; os documentos, headers, ordem das análises e extensões do workspace não são reenviados. Campos desconhecidos no objeto `layout` são conservados pelo snapshot completo desse metadado. O patch substitui o valor de `layout` inteiro, não faz merge recursivo de suas propriedades.

Há nove painéis: Análise, Conexões, Object Explorer, Resultados, Resumo, Saída, Pynia Output, Variáveis e Pynia. O grafo registra divisões, tamanhos, ordem/aba selecionada dos grupos, maximização e grupos flutuantes ou em outra janela. O campo privado `datapyn.hiddenPanels` lembra a posição dos painéis ocultos, seus pares de abas e referências às divisões vizinhas. Reabrir um painel tenta essa posição antes do agrupamento padrão e não reabre seus vizinhos fechados.

Resultados ocupa a altura disponível de seu dock, na janela principal e nas janelas destacadas. A regra específica `.dock-results > .results-panel` remove o antigo `max-height: calc(100vh - 280px)`: em um pop-out de 900×300, essa reserva de 280 pixels podia deixar apenas 20 pixels ou menos para o painel, exibindo controles sem espaço para as linhas. O ajuste fica restrito aos resultados do Dockview; a rolagem da grade continua dentro de seu canvas, sem criar rolagem no documento da janela.

Fechar ou reacoplar uma janela cancela o debounce de resize de 100 ms e invalida seus callbacks de geometria. O patch local de Dockview 8.4.0 é aplicado no postinstall aos dois entry points publicados, após validar versão, definição e hashes completos. Isso evita que um resize pendente consulte uma janela já fechada; os testes executam o helper real publicado e cobrem cancelamento, debounce normal, fechamento reentrante e instalação idempotente.

A abertura de um perfil estabelece um baseline silencioso das saídas restauradas. Resultados e Saída só são revelados por novos resultados/artefatos ou novas falhas da análise ativa; uma saída recebida em segundo plano é observada sem reabrir seu painel na troca posterior de abas. Editar um bloco que já falhou não altera a visibilidade. O Resumo usa a visibilidade real de seu painel, independente do grupo que está com foco.

Eventos Dockview são coalescidos em 150 ms; o autosave de sessão continua com debounce de 500 ms. Antes de fechar ou trocar de perfil, o frontend captura o layout vivo e a geometria atual e faz flush da fila. **Exibir → Painéis e layout** oferece mostrar/ocultar individualmente, mover por direção, agrupar, flutuar, destacar, acoplar todas as janelas, restaurar o padrão e salvar imediatamente. `Ctrl+Shift+R` restaura a disposição; `Ctrl+Shift+Alt+R` também redefine as dimensões padrão.

O grafo salvo é validado antes de substituir a disposição atual: IDs conhecidos e únicos, referências válidas, estruturas/dimensões limitadas e URL de pop-out local. Layout inválido aplica o padrão e gera uma mensagem. A restauração inicial termina após a recuperação dos pop-outs; a splash aguarda esse marco, a geometria nativa e o editor necessário antes de mostrar a janela principal.

`mainWindow` tem versão 1, posição externa e tamanho interno em pixels físicos, `scaleFactor` e `maximized`. A restauração escolhe um monitor disponível, usa sua área útil, adapta o tamanho à escala DPI e mantém a janela acessível caso o monitor anterior tenha sido removido. Os bounds normais são preservados ao maximizar ou minimizar, evitando gravar tamanho maximizado como tamanho restaurado ou coordenadas de minimização. Leituras/mutações nativas são serializadas; eventos de movimento/tamanho/DPI são coalescidos em 250 ms. A geometria é aplicada uma vez na abertura do aplicativo; mudar de workspace conserva a janela atual e passa a gravá-la no perfil selecionado.

O layout Qt de `MainWindow.ini`/`DockingLayout.ini` conserva sua representação binária original para retornar ao PyQt6. Esses bytes não são interpretados como grafo Dockview nem sobrescritos pela persistência privada Tauri. Consulte [TAURI_CONFIGURATION_COMPATIBILITY.md](TAURI_CONFIGURATION_COMPATIBILITY.md).

## Cache opcional de variáveis Parquet

Os snapshots de variáveis permanecem opt-in e isolados por perfil e ID da sessão. Quando habilitados com restauração na abertura, recuperam DataFrames e Series sem executar seus blocos. A publicação continua usando uma geração completa e um ponteiro atômico; a alteração abaixo não modifica os formatos públicos de configuração.

A restauração pandas preserva inteiros com nulos sem passar por `float64`. Na fixture de aceitação, uma coluna `object` com 250 nulos iniciais guardava `9007199254740993` como `int64` exato no Parquet, mas a leitura pandas padrão produzia `9007199254740992.0`. A leitura Arrow agora mantém o inteiro original; paginação e sugestões retornam `"9007199254740993"`, conforme o contrato JSON para inteiros acima do limite seguro do JavaScript. Índices inteiros com nulos recebem o mesmo cuidado: os níveis são reconstruídos diretamente do Arrow com o dtype original, conservando nomes, duplicações e valores exatos. Os demais índices e dtypes continuam seguindo os metadados pandas do arquivo.

DataFrames e Series Polars são escritos e lidos em Parquet nativo, sem converter o frame inteiro para pandas. Isso preserva `UInt64` com nulos, a precisão declarada de `Decimal` e timestamps com nanossegundos e timezone. O manifesto privado usa versão 2 e identifica o armazenamento de cada variável. Snapshots versão 1 continuam aceitos, incluindo os arquivos Polars antigos que foram escritos por pandas; nessa conversão, tipos Arrow evitam transformar inteiros nullable em floats.

A correção conserva os valores exatos presentes nos arquivos existentes. Um arquivo que já tenha sido regravado com um número arredondado não contém informação suficiente para recuperar o valor anterior. Tipos que o escritor Parquet não suporta continuam sendo informados como variáveis ignoradas.

O aceite Windows final executou uma coluna sintética com 250 nulos e inteiros `9007199254740993`, fechou o aplicativo e o reabriu. A grade restaurou o inteiro exato e o filtro de datas com 25 linhas sem executar código na abertura.

## Evidências e medições

- `runtime_tests/test_session_store.py`: migração/reopen, identidade estável, preservação do JSON, updates parciais, headers sem payload, rollback após escrita, limites, conflito de revisão, corrupção/checksum, kill no meio da transação, duas conexões e guard WAL.
- `runtime_tests/test_profiles.py`: isolamento/clone/archive/select, IDs de conexões, snapshots e configuração privada preservados.
- `runtime_tests/test_session_store_runtime.py`: processo NDJSON real, ACK de patch, kill/restart e documento com código marcador que nunca é executado.
- `runtime_tests/test_snapshot_precision.py`: Parquet exato antes/depois da restauração e regravação, DataFrame/Series pandas, índices inteiros nullable simples/MultiIndex, `UInt64`, `Decimal` e timestamps Polars nativos, leitura de snapshots versão 1 e reinício NDJSON com coluna de 250 nulos iniciais. Após o reinício, a grade e o filtro numérico recuperam as 25 ocorrências de `9007199254740993` sem arredondamento.
- `desktop/src/nativeDrafts.test.ts` e `workspace.test.ts`: patches, header-only, mudanças/coalescing de layout sem inspecionar documentos inalterados, preservação de extensões, fila/retry, proteção durante transição, foco/view privados e payload memoizado. `dockingLayout.test.ts` e `windowLayout.test.ts` verificam os contratos de grafo/posições ocultas e geometria nativa. No executável desktop, um perfil temporário reabriu sem argumento de arquivo, conservando duas abas, quatro blocos, foco no segundo bloco e cursor na linha 2, coluna 22.
- `desktop/src/outputReveal.test.ts`: baseline de abertura/troca de perfil, saídas em segundo plano, reutilização de IDs em nova execução, dedupe de artefatos/falhas e fila real de execução. `dockPanelVisibility.test.ts` verifica Resumo visível ao lado de Resultados, abas inativas e cleanup. `shortcutModalGuard.test.ts` cobre modais visíveis/ocultas e o find widget não modal do Monaco.
- `scripts/tauri/smoke_persistence.py`: 121 documentos, migração JSON, edição de um documento, idempotência, header-only, kill após ACK e segundo processo restaurando código/metadados intactos.

Na execução congelada final medida em 3/10/2026, o smoke NDJSON enviou 11.445.150 bytes no save inicial e 95.471 bytes no patch: redução de 99,17% no payload. Save inicial 639,13 ms, edição incremental 62,43 ms e leitura após novo processo 5.119,30 ms; header-only retornou zero payloads alterados. São dados sintéticos locais, e a leitura após restart inclui boot/import e extração do broker onefile. A rodada source final teve save inicial de 235,44 ms, patch de 6,76 ms e restauração de 330,65 ms. Uma rodada congelada anterior teve patch de 6,95 ms: há variação local, sem comparação controlada com o PyQt6.

Uma medição direta separada com 120 documentos (~9,6 MiB) teve save inicial 150,85 ms e mediana de 2,563 ms em 20 patches de foco/header, sem regravar payloads, com journal DELETE. As medições não são um benchmark de hardware remoto nem simulação de corte físico de energia. O smoke congelado passa no build desktop; instaladores e máquina limpa continuam no pipeline de distribuição.
