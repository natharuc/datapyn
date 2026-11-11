# Bancos documentais

O DataPyn consulta Elasticsearch, Azure Cosmos DB e MongoDB por adaptadores no
kernel Python. O editor, os atalhos, os blocos SQL/Python e o grid usam os mesmos
fluxos dos demais bancos; a conexão informa quais operações o provedor aceita.

## Escolher a conexão

| Tipo | Contexto | Consulta |
| --- | --- | --- |
| Elasticsearch | Índices/aliases | SQL REST do Elasticsearch |
| Cosmos DB — NoSQL | Database e container | SQL nativo da API for NoSQL |
| MongoDB | Database e collection | SELECT básico do DataPyn |
| Cosmos DB — MongoDB | Database e collection | SELECT básico com perfil de compatibilidade Cosmos |

Cosmos NoSQL e Cosmos Mongo são APIs distintas. Selecione a modalidade da conta;
um endpoint NoSQL não pode ser usado com PyMongo. MongoDB admite Atlas e
instalações próprias, inclusive Community. OpenSearch, ES|QL e comandos livres
do mongosh não pertencem a este incremento.

Elasticsearch usa endpoint HTTP(S), usuário/senha ou API key. Cosmos NoSQL usa
endpoint HTTPS e chave da conta ou Microsoft Entra. Mongo/Cosmos Mongo usam
`mongodb://` ou `mongodb+srv://`, com credenciais separadas e opções de
authSource/TLS. O catálogo público não deve armazenar senha ou chave dentro da
URI; a edição reutiliza o segredo no cofre do sistema operacional.

Certificados privados e permissões são requisitos do ambiente. Um túnel SSH
genérico não preserva automaticamente a topologia/SRV Mongo ou a identidade TLS
dos endpoints HTTP; esses adaptadores não oferecem SSH nesta entrega.

## SQL MongoDB

O SQL básico é compilado de uma AST para um pipeline executado no servidor.
Não é MongoSQL/SQL-92 completo e não baixa uma collection para executar SQL
localmente. A mesma conexão aceita o subconjunto no Atlas e no Mongo Community,
sem exigir SQL Interface, proxy SQL ou ODBC/JDBC adicional.

Exemplo:

```sql
SELECT p.nome, p.status AS situacao
FROM pessoas AS p
WHERE p.ativo = TRUE AND p.status IS NOT NULL
ORDER BY p.nome
LIMIT 100
```

O escopo inicial inclui um SELECT de uma collection, projeção ou `*`, aliases,
campos aninhados, filtros escalares com `AND`, `OR`, `NOT`, comparações,
`IS NULL`/`IS NOT NULL`, `IN`, ordenação, `LIMIT` e `OFFSET`. Parâmetros são
valores, nunca operadores ou código executável. `LIMIT 0` retorna zero linhas.

JOIN, CTE, subqueries, UNION, funções/agregações, janelas e escrita são recusados
antes da execução. Uma cláusula desconhecida não pode ser ignorada. Comparações
consideram NULL/campo ausente e tipos escalares; arrays não são expandidos nem
comparados como se fossem escalares. Os caminhos BSON e identificadores precisam
respeitar o conjunto suportado pelo compilador.

O servidor decide SQL completo no Elastic e o dialeto Cosmos NoSQL. Por exemplo,
no Cosmos, selecione o container e consulte `SELECT * FROM c`; no Elastic,
índices com hífen precisam do quoting do dialeto, como `FROM "meu-indice"`.

## Resultados e operações

O kernel consome cursores/páginas em lotes e publica handles/páginas para o grid.
DataFrames gerados ficam disponíveis nos blocos Python e nas exportações. A
interface não recebe todos os documentos por IPC de uma vez. Objetos/arrays não
são automaticamente explodidos em linhas; o valor de preview não deve substituir
o tipo original usado pelo Python e pela exportação.

JSON mantém objetos/arrays estruturados e usa Extended JSON para tipos BSON ou
números que precisam preservar precisão. CSV/Excel representam células compostas
como JSON; os escalares continuam com seus tipos suportados pelo formato. Em
Parquet, colunas com documentos, ObjectId ou tipos heterogêneos usam Extended
JSON com metadados `datapyn.encoding=extended-json`, enquanto colunas escalares
homogêneas mantêm tipos Arrow nativos. Essa codificação não modifica o DataFrame
mantido no kernel.

O snapshot opcional de variáveis usa Parquet e pode pular um DataFrame que
contenha tipos BSON/heterogêneos não serializáveis pelo mecanismo de snapshots,
com aviso `unsupported_parquet_type`. Código e contexto da aba continuam no
workspace; isso não equivale a persistir sessões ou cursores remotos.

Os novos adaptadores são de consulta. DDL, importação/escrita no provedor,
transações manuais e tabelas temporárias ficam indisponíveis. É possível exportar
um resultado para arquivo ou escolher um destino relacional com suporte a
escrita. Os seis bancos já existentes mantêm suas capacidades.

No Cosmos, consultas e amostras consomem RUs. O autocomplete trabalha sobre
metadados limitados/cacheados; a amostra documental é parcial, sem garantir que
todos os campos da collection/container foram encontrados. Não há leitura de
collection inteira ou COUNT de fundo para gerar sugestões.

## Erros e recuperação

Falhas de autenticação/permissão, recurso ausente, sintaxe, timeout, throttling e
transporte precisam permanecer distintas. Um erro de acesso não solicita
reconexão por suposta queda da rede. Cosmos Mongo pode retornar 16500 por limite
de capacidade; não se habilita Server Side Retry da conta automaticamente.

Depois que uma consulta foi enviada, uma falha de cursor/página não autoriza
reexecutá-la silenciosamente. O DataPyn preserva código e DataFrames anteriores
e informa a interrupção. SDK, adaptador e pool não devem multiplicar retries.
Cancelamento usa o mecanismo atual de interrupção/reinício do kernel.

## Distribuição e validação

Os clientes são distribuídos no sidecar: `requests` para REST SQL,
`azure-cosmos` (MIT), `pymongo` (Apache-2.0) e `dnspython` (ISC). O lock registra
as versões exatas. Não adicionar o pacote independente `bson`: o codec usado é
o fornecido pelo PyMongo. Cosmos/DNS têm wheels Python puras; o lock também
contém wheels PyMongo CPython 3.12 para Windows x64, Linux x64 e macOS arm64.

O verificador de distribuição e o smoke no executável congelado validam módulos,
metadados, TLS, DNS e BSON sem acessar serviços ou credenciais do usuário.
Autenticação, permissões, versão de API e comportamento de um serviço real
exigem um teste de integração isolado. Passar no teste offline não comprova
login real no Atlas, Azure ou Elasticsearch.

Há uma suíte opcional contra MongoDB local descartável. Ela só aceita URI
loopback sem credenciais, cria um database com UUID próprio e remove apenas
esse database. Não instala nem inicia o servidor:

```powershell
$env:DATAPYN_TEST_MONGO_URI = 'mongodb://127.0.0.1:27018'
uv run pytest -c runtime_tests/pytest.ini runtime_tests/test_mongo_sql_live.py -q
Remove-Item Env:DATAPYN_TEST_MONGO_URI
```

Sem a variável, esses casos são pulados. A suíte verifica os pipelines no
servidor real, sem interpretar MongoDB com um mock Python; o ambiente deve ser
de teste e pertencer à pessoa que executa a verificação.

Telemetria permanece opcional, sem URI, conta, nome de banco/container/collection,
query, documento ou credencial. O coletor/painel precisam receber as categorias
novas antes da publicação do desktop; consulte [Telemetria](TELEMETRY.md).

## Referências

- [Elasticsearch SQL REST](https://www.elastic.co/docs/explore-analyze/query-filter/languages/sql-rest-overview)
- [SDK Cosmos Python](https://learn.microsoft.com/en-us/python/api/overview/azure/cosmos-readme)
- [MongoDB SQL Interface e modalidades](https://www.mongodb.com/docs/sql-interface/)
- [Mapeamento SQL/MongoDB](https://www.mongodb.com/docs/manual/reference/sql-comparison/)
- [Agregações e limites Cosmos Mongo](https://learn.microsoft.com/en-us/azure/cosmos-db/mongodb/tutorial-aggregation)
- [Retries e limitações de cursor MongoDB](https://www.mongodb.com/docs/manual/core/retryable-reads/)
