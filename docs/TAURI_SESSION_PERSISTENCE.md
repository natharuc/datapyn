# Armazenamento e restauração das sessões internas

O Tauri grava sessões internas em `workspace_sessions.sqlite3` dentro de cada perfil. Uma mudança no código atualiza somente aquele documento; foco, título e estado de visualização ficam separados do código. A restauração carrega documentos e metadados, sem executar SQL/Python automaticamente.

Os formatos públicos `.dpw`, `.sql`, `.py` e `.ipynb` continuam usando os leitores/escritores existentes. O banco é privado do aplicativo, separado da exportação de arquivos e do cache Parquet opt-in. Não serializa DataFrames, engines, objetos Python ou pickle.

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

## Evidências e medições

- `runtime_tests/test_session_store.py`: migração/reopen, identidade estável, preservação do JSON, updates parciais, headers sem payload, rollback após escrita, limites, conflito de revisão, corrupção/checksum, kill no meio da transação, duas conexões e guard WAL.
- `runtime_tests/test_profiles.py`: isolamento/clone/archive/select, IDs de conexões, snapshots e configuração privada preservados.
- `runtime_tests/test_session_store_runtime.py`: processo NDJSON real, ACK de patch, kill/restart e documento com código marcador que nunca é executado.
- `desktop/src/nativeDrafts.test.ts` e `workspace.test.ts`: patches, header-only, fila/retry, proteção durante transição, foco/view privados e payload memoizado. No executável desktop, um perfil temporário reabriu sem argumento de arquivo, conservando duas abas, quatro blocos, foco no segundo bloco e cursor na linha 2, coluna 22.
- `scripts/tauri/smoke_persistence.py`: 121 documentos, migração JSON, edição de um documento, idempotência, header-only, kill após ACK e segundo processo restaurando código/metadados intactos.

Na execução congelada final medida em 3/10/2026, o smoke NDJSON enviou 11.445.150 bytes no save inicial e 95.471 bytes no patch: redução de 99,17% no payload. Save inicial 639,13 ms, edição incremental 62,43 ms e leitura após novo processo 5.119,30 ms; header-only retornou zero payloads alterados. São dados sintéticos locais, e a leitura após restart inclui boot/import e extração do broker onefile. A rodada source final teve save inicial de 235,44 ms, patch de 6,76 ms e restauração de 330,65 ms. Uma rodada congelada anterior teve patch de 6,95 ms: há variação local, sem comparação controlada com o PyQt6.

Uma medição direta separada com 120 documentos (~9,6 MiB) teve save inicial 150,85 ms e mediana de 2,563 ms em 20 patches de foco/header, sem regravar payloads, com journal DELETE. As medições não são um benchmark de hardware remoto nem simulação de corte físico de energia. O smoke congelado passa no build desktop; instaladores e máquina limpa continuam no pipeline de distribuição.
