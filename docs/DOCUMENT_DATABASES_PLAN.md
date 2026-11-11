# Elasticsearch, Azure Cosmos DB e MongoDB

Plano da demanda, elaborado antes da implementação em 11/11/2026.
Branch: `codex/document-database-connectors`, na pasta original do projeto.
Base analisada: `847d356` (Tauri 1.0.15). Nenhum banco real foi acessado.

## Escopo confirmado

- Elasticsearch: consultas SQL pelo endpoint SQL REST do próprio servidor.
- MongoDB: Atlas e instalações próprias, inclusive Community.
- Azure Cosmos DB: API for NoSQL e API compatível com MongoDB.
- Para MongoDB/Cosmos Mongo, o usuário escolheu SQL básico, ampliado por etapas.
  A tradução acontece para operações no servidor; não se baixa a coleção para
  executar SQL localmente. SQL não implementado deve falhar explicitamente.
- Nesta entrega, os novos adaptadores são de consulta. Escrita documental,
  DDL, transações manuais e tabelas temporárias não serão anunciadas como
  suportadas. Os bancos relacionais mantêm seus recursos atuais.
- Publicação não fazia parte do escopo inicial. Depois da implementação e dos
  testes, o usuário autorizou commit, integração direta na main e a versão 1.1.0.
  A identidade, a chave e o endereço do feed do aplicativo permanecem os mesmos.

## Evidências e decisões

O runtime atual usa `database.connect` e `ConnectorPool`; a maioria dos
consumidores pressupõe SQLAlchemy. `kernel.activate` publica `db_engine`, o
explorer reflete engines, a exportação para tabela usa `to_sql`, e distribuição
e smoke tests exigem dialect/DBAPI para todos os tipos. Acrescentar nomes ao
combobox não resolve esses contratos.

Usar adaptadores pequenos no runtime Tauri, sem modificar o conector relacional
legado para fingir compatibilidade documental. Separar o contrato de capacidades
da presença opcional de uma Engine SQLAlchemy. A ponte Rust continua genérica;
clientes e execução ficam no kernel Python. Segredos do cadastro transitam
somente no estado temporário necessário à conexão e no cofre do SO, nunca nos
documentos persistidos da interface.

| Tipo | Transporte | Contexto | SQL inicial |
| --- | --- | --- | --- |
| Elasticsearch | REST SQL + sessão HTTP reutilizada | índices/aliases e mappings | Dialeto do servidor; paginação por cursor |
| Cosmos NoSQL | SDK oficial `azure-cosmos` | database + container + partition key opcional | Dialeto nativo Cosmos, consulta por container |
| MongoDB | SDK oficial `pymongo` | database + collection | Subconjunto DataPyn convertido de AST para pipeline |
| Cosmos Mongo | `pymongo`, perfil de compatibilidade explícito | database + collection | Mesmo subconjunto, limitado aos operadores compatíveis |

O SQL Interface oficial MongoDB não cobre Community. Não exigir um proxy SQL,
ODBC proprietário, instalação manual ou serviço pago para a consulta básica.
O compilador oficial `mongodb/mongosql` é candidato para evolução avançada,
mas exige catálogo/bridge/builds nativos próprios e não será tratado como um
pacote Python pronto. ES|QL, OpenSearch, MQL livre e SQL avançado Mongo ficam
fora deste incremento; não fazer fallback silencioso entre linguagens.

## Contratos antes dos adaptadores

1. Identificadores estáveis: `elasticsearch`, `cosmosdb`, `mongodb`; Cosmos
   informa a modalidade `nosql` ou `mongodb` explicitamente.
2. Capacidades pequenas e explícitas: linguagem/dialeto, níveis e nomes do
   contexto, metadados, consulta/paginação, Engine opcional, escrita, temporárias,
   transações manuais e SSH. Runtime é autoridade; esconder botões não basta.
3. Contexto Cosmos distingue container de schema. O campo precisa participar
   dos pedidos, identidade de pool/cache, snapshots, duplicação e restauração.
   Resultados atrasados de outro contexto não podem sobrescrever o atual.
4. `sql()` continua devolvendo DataFrames nos blocos Python. `db_engine` só é
   publicado quando existe Engine real; remover valores antigos ao alternar
   para um adaptador sem Engine. Não transformar um SDK em engine fictícia.
5. Testar e conectar usam a mesma normalização/autenticação e o mesmo adaptador.

## SQL básico MongoDB e Cosmos Mongo

- Um `SELECT` sobre uma collection; `*` ou projeção explícita, aliases de
  tabela/campos, filtros escalares, `AND`/`OR`/`NOT`, comparações, `IS NULL`,
  `IS NOT NULL`, `IN`, ordenação e `LIMIT`/`OFFSET`.
- Construção por AST do SQLGlot já distribuído, com allowlist da árvore inteira;
  nenhum `eval`, JavaScript ou substituição textual de SQL por regex.
- Rejeitar JOIN, CTE, subquery, UNION, window, funções/agregações e escrita até
  que uma etapa própria implemente e teste sua semântica. Nenhuma cláusula pode
  ser ignorada ou executada aproximadamente.
- Semântica explícita para NULL/campo ausente, negação e `NOT IN` com NULL,
  campos aninhados, tipos heterogêneos, nomes reservados e `LIMIT 0`.
  Arrays não são expandidos implicitamente. Operadores não compatíveis com o
  perfil Cosmos Mongo devem ser rejeitados antes de enviar a consulta.
- Valores de parâmetros permanecem dados, nunca nomes de operador ou código.
  O servidor executa filtros, projeções e ordenação; o cliente consome lotes.

## Cadastro, autenticação e sigilo

- Elastic: endpoint HTTP(S), usuário/senha ou API key, CA/TLS conforme cadastro.
- Cosmos NoSQL: endpoint, chave da conta ou identidade Microsoft Entra explícita,
  database e container; nunca selecionar credencial de outra conta por fallback.
- Mongo/Cosmos Mongo: URI `mongodb://` ou `mongodb+srv://`, autenticação,
  authSource e TLS; manter o perfil Cosmos distinto de MongoDB completo.
- Decompor URIs de entrada. Senhas, chaves e opções secretas vão ao cofre do SO;
  só endpoint/opções públicas vão ao catálogo, DPW, rascunho e histórico de abas.
  A edição deve permitir reutilizar segredos salvos sem revelá-los.
- Identidade de credencial inclui provedor, endpoint, conta e modalidade de
  autenticação. Testar troca de endpoint, edição, importação e reconexão.
- Importar/exportar strings reais por provedor. Não gerar SQLAlchemy/MySQL
  ou connection string .NET fictícia para um SDK que não usa esses formatos.
- Não ampliar SSH automaticamente: HTTP, SRV e descoberta de replica sets
  exigem uma solução própria para preservar TLS/topologia. Motivo claro na UI.

## Explorer, editor e usabilidade

- Índices/aliases no Elastic; databases/containers no Cosmos NoSQL;
  databases/collections no Mongo. Templates de consulta gerados pelo adaptador.
- Metadados preguiçosos e limitados. Usar mappings/validators quando existentes;
  inferência amostral documental deve ser identificada como parcial.
- Autocomplete local sobre snapshots, com caminhos aninhados, aliases e quoting
  correto, sem consulta de rede a cada tecla. Invalidar ao mudar contexto.
- Validação conforme dialeto: não deixar novos tipos caírem no fallback T-SQL,
  nem marcar campo ausente na amostra como definitivamente inexistente.
- Preservar execução apenas da seleção, atalhos, multiblocos, foco, loading,
  timer, notificações e confirmação destrutiva existentes.
- Adicionar logos SVG e cor da conexão/grupo, labels simples e temas atuais.
- Destinos de exportação para tabela/temporária são filtrados por capacidade.
  Um resultado documental pode ser enviado a um destino relacional compatível.
  Recursos indisponíveis devem explicar o motivo e nunca ficar em loading.

## Resultados, exportação e desempenho

- DataFrames ficam no kernel e a UI recebe handles/páginas, como hoje.
  Paginação remota não autoriza enviar o conjunto inteiro ao WebView.
- Consumir cursores/páginas em lotes; evitar listas gigantes intermediárias e
  concatenação quadrática. A consulta pode carregar milhões de linhas na memória
  do kernel, respeitando RAM disponível, sem bloquear o loop da interface.
- Preservar números/decimais, datas, strings, booleanos e valores BSON no frame.
  Distinguir representação de preview e valor original; objetos/arrays no grid
  recebem serialização JSON estável, nunca `[object Object]` ou `repr` ambíguo.
- Sem explosão automática de arrays ou flatten que multiplique linhas.
  Exportação JSON deve preservar estrutura; CSV/Excel aplicam representação
  explícita para valores compostos e preservam tipos escalares suportados.
- Integrar stream de exportação com staging e cleanup. Não substituir arquivo
  existente por exportação parcial em erro ou cancelamento.
- Cosmos: contabilizar RU quando fornecida e respeitar throttling/Retry-After
  dentro do orçamento total; não executar COUNT/amostragem ampla no background.

## Erros, recuperação e cancelamento

- Reutilizar `error_info` e detalhes técnicos recolhidos, com limpeza de URI,
  cabeçalhos e documentos. Auth/permissão, recurso inexistente, SQL inválido,
  timeout, throttling e transporte são categorias distintas.
- 401/403/404 não disparam reconexão por suposta queda. Cosmos Mongo 16500 é
  throttling. Limitar tentativas e tempo total; não empilhar retries do SDK/pool.
- Após envio/interrupção da consulta ou falha de `getMore`, não reexecutar a
  query para reconstruir cursor silenciosamente. Manter código e frames prévios,
  informar interrupção sem apresentar resultados incompletos como completos.
- Cancelamento atual reinicia o kernel. Não prometer cancelamento cooperativo
  que o sistema ainda não possui. Fechar cursor/client no caminho normal e em
  `finally`; limitar validade remota porque um kill pode impedir o cleanup.
- Desconexão de uma aba/bloco não deve bloquear ou trocar o contexto de outro.

## Execução e gates, na ordem

1. **Fundação:** capacidades, configuração pública/segredos, contexto e Engine
   opcional. Gate: seis bancos atuais e seus contratos continuam válidos.
2. **Compilador e adaptadores:** SQL básico Mongo, REST SQL Elastic, SDK Cosmos,
   perfil Cosmos Mongo. Gate: contratos/protocolos simulados, parâmetros,
   paginação, NULL/tipos, erros e nenhum replay depois do envio.
3. **Fluxo completo:** catálogo→teste→salvar→conectar→explorer→editor→DataFrame→
   Python→exportação, com troca/restauração de contexto. Gate: UI não oferece
   operações sem suporte e credenciais não saem nos documentos/diagnósticos.
4. **Robustez:** falhas entre páginas, cursor expirado, autenticação/permissão,
   throttling, timeout e cancelamento. Gate: próxima consulta funciona e outras
   abas continuam independentes; seleção e confirmação existentes preservadas.
5. **Distribuição:** lock, imports dinâmicos/metadados, licenças, diagnóstico e
   smoke próprios para SDKs, sem inventar dialects SQLAlchemy. Gate: source e
   sidecar congelado em Windows x64, Linux x64 (base Ubuntu 22.04) e macOS arm64.
6. **Regressão e documentação:** runtime pytest, frontend test/build, Rust
   fmt/check/test e distribuição. Acrescentar integração isolada/sintética para
   os provedores e documentar separadamente o que exige serviço autenticado.
   Não declarar acesso real Cosmos/Atlas validado apenas com mocks.

Telemetria mantém opt-in e campos enumerados: atualizar em conjunto allowlists
do runtime, coletor e painel antes de emitir tipos novos. Nunca adicionar URI,
nome de banco/container/collection, query, documento, usuário ou credencial.

## Matriz mínima de aceite

| Tema | Casos obrigatórios |
| --- | --- |
| Conexão | Testar/salvar/abrir; senha/chave; TLS; SRV; sem permissão; credencial expirada |
| Contexto | Troca rápida; container/collection corretos; aba nova/duplicada/restaurada; cache atrasado |
| SQL Mongo | AST integral; filtros/aliases/NULL/ausentes/tipos mistos; LIMIT 0; unsupported sem I/O |
| Paginação | Vazio; página vazia com continuação; múltiplas páginas; cursor expirado; queda parcial |
| Tipos | Decimal128/Decimal/int64/ObjectId/datetime/timezone/bytes; objetos e arrays; exportação |
| Desempenho | Lotes grandes/milhões sintéticos; memória do kernel; IPC limitado; UI responsiva |
| Recuperação | 401/403/404/429/16500; timeout/transporte; sem replay; próxima consulta; cancelamento |
| Sigilo | URI com senha; key/token; DPW/drafts/abas fechadas; import/export; logs/diagnóstico/telemetria |
| Distribuição | Imports/metadata/CA/DNS e smoke no congelado; instalação nas três plataformas |
| Legado | SQL Server/MFA/SSH, PostgreSQL, MySQL/MariaDB, SQLite, Databricks e configurações PyQt |

## Referências consultadas

- [Elasticsearch SQL REST](https://www.elastic.co/docs/explore-analyze/query-filter/languages/sql-rest-overview)
- [Consulta/paginação SQL e tratamento de arrays Elastic](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-sql-query)
- [Limitações do dialeto Elastic](https://www.elastic.co/docs/reference/query-languages/sql/sql-limitations)
- [SDK Cosmos Python e limitações](https://learn.microsoft.com/en-us/python/api/overview/azure/cosmos-readme)
- [SQL Interface MongoDB e modalidades suportadas](https://www.mongodb.com/docs/sql-interface/)
- [Compilador MongoSQL oficial](https://github.com/mongodb/mongosql)
- [Mapeamento SQL/MongoDB](https://www.mongodb.com/docs/manual/reference/sql-comparison/)
- [Agregações Cosmos Mongo](https://learn.microsoft.com/en-us/azure/cosmos-db/mongodb/tutorial-aggregation)
- [Retries PyMongo](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/configure/)
- [Retryable reads e getMore](https://www.mongodb.com/docs/manual/core/retryable-reads/)

## Acompanhamento

Plano fechado com as três decisões de escopo confirmadas pelo usuário.
Implementação iniciada somente depois desse fechamento, na mesma branch.

### Implementado

- Capacidades, adaptadores, cadastro/autenticação, cofre e strings de conexão.
- Explorer, container Cosmos, isolamento de contexto, autocomplete e logos.
- SQL básico Mongo com validação integral da AST e execução no servidor.
- DataFrames/Python sem Engine fictícia, representação JSON/BSON, filtros e
  ordenação da grade, CSV/Excel/JSON/Parquet e exportação para destino SQL.
- Erros, throttling, timeouts, fechamento de cursores e recuperação sem replay.
- Distribuição/diagnóstico para nove tipos e allowlists de telemetria aditivas.
- Correções de compatibilidade encontradas na regressão: adaptadores SQL antigos
  que expõem somente Engine e credenciais SSH embutidas nos perfis históricos.

### Verificado

- Runtime completo: **1.903 passaram, 34 pulados**; os pulados incluem os 33
  testes que exigem servidor Mongo opcional e uma condição de plataforma.
- MongoDB Community 8.0.38 local, temporário, somente loopback: **33 passaram**
  com PyMongo real; servidor e dados sintéticos encerrados/removidos ao terminar.
- SDK Cosmos real com transporte HTTP simulado: **9 passaram**, incluindo
  parâmetros, SELECT VALUE, página vazia com continuação, RUs e ausência de
  retries ocultos nas falhas testadas. Isso não é autenticação contra Azure.
- Elasticsearch: protocolo supervisor/kernel e HTTP reais contra API local
  sintética; paginação/cursor, tipos, Python, exportação e erro 403 sem reconexão.
- Frontend: **1.260 passaram**; TypeScript e build Vite passaram.
- Monaco real em browser headless: **73 cenários passaram**; explorer e cadastro
  isolados passaram em português/inglês e claro/escuro, sem usar a janela do usuário.
- Rust: fmt/check e **47 testes passaram, 1 ignorado**.
- Runtime congelado Windows x64: build e os quatro smokes passaram depois das
  correções de compatibilidade (execução, paridade/grade com 10 milhões de linhas,
  persistência e distribuição). As 278 fontes permaneceram idênticas durante esse build e a
  cópia do sidecar confere com o artefato gerado.
- Coletor/painel de telemetria: **16 + 18 testes** e typechecks passaram.
- Lock consistente; auditoria Python sem vulnerabilidades conhecidas.
  Foram acrescentados três pacotes (Cosmos/PyMongo/DNS) e aplicado o patch
  OAuthLib 4.0.1 necessário para corrigir vulnerabilidade preexistente no lock.

### Limites e preparação para publicação

- Cosmos NoSQL recebe validação lexical local parcial; o serviço valida seu
  dialeto nativo. Não há fallback para um validador T-SQL incorreto.
- Snapshot opcional de variáveis pode pular frames com tipos BSON/heterogêneos
  que seu mecanismo Parquet não aceita; consultar o guia de uso.
- Acesso autenticado a Atlas/Cosmos/Elasticsearch reais precisa de ambientes
  de teste apropriados; as suítes simuladas não comprovam login nesses serviços.
- Linux/macOS precisam dos builds/smokes nativos da esteira; wheels e integração
  de empacotamento foram preparados, sem declarar execução nativa neste Windows.
- Publicar as allowlists do coletor/painel antes de uma versão que emita os novos
  tipos. Nenhuma configuração ou autenticação Cloudflare foi alterada nesta demanda.
- A publicação autorizada prepara os cinco manifests/lockfiles para Tauri 1.1.0,
  preservando identidade, chave/endereço do feed e versão histórica PyQt.
  O guia funcional é [DOCUMENT_DATABASES.md](DOCUMENT_DATABASES.md).
