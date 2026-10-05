# Autocomplete SQL e Python no Tauri

O editor retorna sugestões locais imediatamente. Jedi e metadados de bancos são enriquecidos em segundo plano, com caches limitados, debounce e cancelamento por requisição.

## Seleção de banco/schema e preparação do editor

O cabeçalho de cada bloco SQL mostra conexão, banco (catálogo no Databricks) e schema quando a plataforma possui esse contexto. Banco/schema abrem uma lista pesquisável com navegação por teclado, pesquisa local e renderização virtualizada. SQLite mostra o arquivo atual: trocar arquivos usa conexões; aliases `main`/`temp` não representam outra conexão.

A seleção é específica do bloco, inclusive do primeiro. Trocar banco limpa o schema específico anterior e deixa o driver resolver o padrão do novo banco. Execução, diagnósticos, Explorer, exportações e autocomplete usam a mesma precedência. Novos blocos gerados pelo Explorer recebem o contexto de origem; trocar a conexão por arraste limpa banco/schema antigos.

`language.prepare` agenda o catálogo do bloco focado antes da primeira solicitação de sugestões. Os pedidos usam a conexão e os defaults reais da configuração; o dialeto já está disponível no frontend antes de chegar o catálogo. O preparo acompanha mudanças de foco/contexto, agrupa pedidos equivalentes e mantém caches limitados, sem consultar o banco a cada tecla. Atualizar metadados força a recarga mesmo dentro do TTL. Alterações na configuração da conexão descartam os índices do servidor anterior.

Eventos de metadados incluem `requested_scope` e o contexto resolvido pelo driver. O frontend relaciona esses dois endereços por identidade do snapshot, incluindo conexões implícitas (`transient`), e remove todos os aliases na invalidação. Eventos somente de variáveis preservam esse catálogo. Uma falha de acesso publica `metadata_state: error`, limpa o snapshot anterior e apresenta o erro na barra de status, evitando um catálogo silenciosamente vazio ou de outro schema.

SQL Server, MySQL e MariaDB deixam de receber o schema artificial `default`. PostgreSQL descobre os bancos acessíveis e prioriza o schema focado quando existe o mesmo nome de tabela em outro schema. O preparo reconhece fontes separadas por vírgula e subqueries. Listas de nomes já obtidas do driver não são truncadas em 10 mil objetos; colunas continuam carregadas sob demanda e armazenadas em caches limitados.

### Contexto alterado pela execução SQL

Comandos de contexto executados pelo bloco também atualizam banco, catálogo e schema na interface, no Explorer, nos diagnósticos e no autocomplete. A detecção considera somente o código enviado à execução, incluindo uma seleção parcial, e ignora comandos presentes em comentários ou literais. Após `USE` ou alterações de `search_path`, o driver consulta o contexto real na mesma conexão física, antes de devolvê-la ao pool. Queries comuns não recebem essa consulta adicional.

Um comando de troca que falha mantém o contexto anterior. Se o `USE` funcionar e uma instrução posterior falhar, a interface acompanha a troca efetivamente realizada. PostgreSQL observa o contexto após commit/rollback, respeita a duração de `SET LOCAL` e preserva caminhos de busca completos e schema vazio conforme o resultado real da transação ([SET no PostgreSQL](https://www.postgresql.org/docs/18/sql-set.html)). Databricks distingue catálogo de schema; `USE DATABASE` altera schema, como `USE SCHEMA` ([USE SCHEMA no Databricks](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-use-schema)).

Um bloco que herda o contexto da aba atualiza também os demais blocos herdados; blocos com contexto próprio mantêm sua seleção. A fila resolve o contexto atualizado antes de cada execução. A conexão física e suas tabelas temporárias são preservadas mesmo quando já existe outra conexão no banco de destino. O runtime recebe `block_id` e `scope_inherited` explícito nos pedidos modernos; snapshots distinguem o bloco e a origem herdada ou própria. Invalidações de contexto alcançam o bloco ou sua família herdada, enquanto DDL invalida metadados da conexão. Respostas atrasadas não associam um catálogo novo à seleção antiga.

Regressões: `runtime_tests/test_sql_execution_context.py`, `runtime_tests/test_block_language_context.py` e `desktop/src/workspaceSqlContext.test.ts`. Os cenários de plataformas remotas usam DBAPI simulado; os contratos stdio existentes continuam exercitando SQLite real.

Teste do editor real, sem operar o desktop: `npm --prefix desktop run test:autocomplete`. Em uma máquina sem Chromium de teste, instalar com `npm --prefix desktop exec playwright install chromium`. O runner usa Monaco e os componentes de produção em Chromium headless, com a fronteira IPC controlada. Esse teste comprova interação e isolamento dos seis dialetos; integração com banco real usa SQLite. Bancos externos devem ser conferidos no ambiente configurado.

## Aceite desta correção de contexto

Esse aceite anterior não exercitou a lista de métodos permitidos pela ponte Rust para `language.prepare`. O relato seguinte do aplicativo revelou essa lacuna; a correção e o teste da fronteira nativa estão descritos no aceite final abaixo.

Em 04/10/2026, passaram 699 testes frontend, 768 testes do runtime, TypeScript, Ruff, 24 cenários com Monaco/seletores reais em Chromium headless e os três smokes do runtime congelado. O executável Tauri de produção foi recompilado após a última alteração do frontend. Não houve operação do desktop nem conexão a servidores externos neste aceite.

O ensaio local com 100 mil tabelas passou de aproximadamente 111 ms para 0,019 ms na busca aquecida de prefixos por namespace. Resolução de alias aquecida: 0,022 ms; busca após FROM: 0,015 ms. O índice usa a identidade do snapshot, buscas por nomes pré-normalizados, geração posterior à filtragem e caches limitados por dialeto/banco/schema. Mudanças apenas de variáveis preservam o índice SQL. A criação inicial dos índices desse catálogo sintético ainda custa aproximadamente 41–53 ms por snapshot; esses números medem helpers, sem pintura do Monaco nem acesso ao banco.

No runtime congelado atualizado, 40 chamadas aquecidas com SQLite apresentaram SQL p50 0,318 ms/p95 0,443 ms e Python p50 0,241 ms/p95 0,661 ms. O carregamento inicial do schema levou 37,162 ms. Esses valores não representam latência de bancos externos.

O build com o Python 3.12.3 instalado apresentou duas falhas nativas durante a análise do PyInstaller. O pacote final foi gerado com Python 3.12.10 em ambiente de build isolado, reutilizando as mesmas dependências CPython 3.12, e passou todos os smokes. A causa dessas falhas não foi estabelecida; não foram adicionados retries automáticos ou monkeypatches ao produto. O script de build já permite escolher outro ambiente completo de build por `DATAPYN_RUNTIME_PYTHON`, com caminho absoluto para seu Python. A `.venv` original não foi substituída.

## Correções de contexto em 04/10/2026

O índice local SQL agora considera o statement e o escopo da query no cursor. Colunas carregadas são sugeridas em SELECT, WHERE, ON e ORDER BY sem depender de um novo RPC. JOINs usam qualificadores; aliases de CTEs e tabelas derivadas ficam reservados à inferência do runtime e não recebem colunas de tabelas físicas homônimas.

O lexer preserva pontos com espaços, aliases Unicode, identificadores entre aspas e seus escapes. Ponto e ponto-e-vírgula dentro de strings/comentários não alteram o statement. PostgreSQL distingue aliases quoted por caixa e strings comuns de `E'...'`; MySQL/MariaDB mantêm escapes e comentários com `#`. O guard do Monaco e o runtime aplicam as mesmas regras.

Blocos com outra conexão não herdam database/schema da conexão principal. Diagnóstico, execução, Explorer e ferramentas da Pynia seguem essa resolução. Eventos somente de namespace preservam o catálogo já carregado da mesma conexão.

As regressões usam metadados de vários dialetos e integração real SQLite. Bancos externos não foram usados neste aceite. O índice local continua limitado à janela de texto do editor; nesting extremo de 1.500 subqueries levou 43,16 ms em um probe de fonte e não representa a latência usual. Um bloco de 58 KB com 1.700 statements levou 2,93 ms nesse mesmo probe.

## Funcionalidades

- SQL: keywords, tabelas, colunas, aliases, JOINs, CTEs, schemas e rotinas. Nomes especiais/reservados recebem quoting por dialeto. Catálogos explícitos SQL Server/Databricks carregam sob demanda; DDL invalida os metadados.
- Python: builtins, imports/aliases de outros blocos, funções, variáveis e métodos/propriedades pandas/Polars. Pandas oferece colunas por atributo válido ou chave de string; Polars oferece colunas por indexação, sem inventar atributos.
- Snippets de outros blocos da mesma linguagem preservam texto literal, incluindo `$`, chaves e quebras de linha.
- Ctrl+Space solicita sugestões normais, mesmo com autocomplete automático desligado. Ctrl+. mantém sugestões normais ou Pynia inline conforme a preferência de IA. Tab/Enter aceitam; Escape descarta a intenção pendente.
- Completar no meio de uma palavra substitui o sufixo. Strings Python e identificadores SQL reconhecem escapes e aspas existentes.
- Trocar bloco, sessão, conexão, posição ou modelo invalida pedidos antigos. Fontes de outras sessões não alimentam as sugestões; `wordBasedSuggestions` está desligado.

## Integração e limites

Imports/preamble antes ignorados são analisados sem executar código. Snapshots vazios são autoritativos, evitando variáveis removidas reaparecerem. Metadados SQL sem mudança nas variáveis não invalidam inferência Python. A leitura de contexto não reagenda o próprio diagnóstico.

## DataFrames SQL nos blocos Python

As consultas SQL materializadas mantêm seus DataFrames reais no namespace Python da sessão. O nome é o do resultado/bloco SQL, ou `df` quando não foi informado; múltiplos resultsets usam o nome base, seguido de `1`, `2` etc. Esses nomes aparecem em qualquer bloco Python dessa sessão, incluindo blocos com outra conexão SQL configurada. Fechar uma aba da grade não exclui a variável Python.

O kernel publica os nomes, tipos, módulos e colunas antes de anunciar `execution.finished`. Assim, ao concluir o SQL, tanto as sugestões locais quanto a inferência remota já conhecem o resultado. A publicação não consulta o banco nem transfere linhas à interface. DataFrames removidos ou substituídos obedecem ao namespace atual; resultados antigos guardados nos blocos não os recriam. Nomes de consultas ainda não executadas podem ser sugeridos como contexto planejado.

Um catálogo único de membros públicos de `pandas.DataFrame`/`polars.DataFrame` alimenta sugestões locais, inclusive em editores acima de 500.000 caracteres. Foi gerado das classes instaladas Pandas 2.3.3 e Polars 1.41.2; mudanças dessas versões devem atualizar o catálogo. Não se inspecionam propriedades de objetos do usuário. No dot, métodos/propriedades como `head`, `query` e `columns` têm precedência sobre colunas homônimas, que continuam disponíveis por string.

Além de `vendas.` e `vendas['valor total']`, há sugestões de colunas em `vendas[['pedido_id', 'valor total']]`, `vendas.loc[:, 'valor total']` e `vendas.sort_values(by='valor total')`, incluindo listas de colunas e aspas/escapes existentes. Em Polars, `sort(by=...)` é reconhecido. Strings arbitrárias e posições de índices de linha não oferecem nomes de colunas. A execução Python usa os mesmos objetos criados pelo SQL, sem reconstruir ou serializar o DataFrame inteiro para completar código.

O menu de sugestões usa um host externo por editor no seu próprio documento. Isso permite abrir a lista além da borda do bloco/dock, incluindo janelas destacadas. O host acompanha o tema e é removido junto com o widget; permanece abaixo dos diálogos da aplicação.

Identificadores SQL usam aspas por dialeto também nas sugestões locais. Isso evita depender de uma lista parcial de palavras reservadas, como `AUTHORIZATION` no [PostgreSQL](https://www.postgresql.org/docs/current/sql-keywords-appendix.html).

No Monaco 0.57, `editor.action.triggerSuggest` exige que a lista esteja fechada. Usá-lo para atualizar uma lista aberta, inclusive “No suggestions”, não invocava novamente o provider. A atualização usa o controller da versão instalada, com fallback aos comandos públicos e proteções de foco/posição/versão. O problema foi reproduzido no executável nativo e ganhou regressão.

Debounce normal: 120 ms; manual: imediato. Pynia automático: 350 ms, com um pedido ativo e uma intenção posterior por editor. A resposta da IA depende do serviço configurado. O cache frontend guarda oito consultas; Python guarda até 64 consultas/4 MiB; o índice SQL guarda quatro snapshots. Metadados de conexão têm 32 escopos por sessão, TTL de 60 s e invalidação após DDL.

O contexto entre blocos mantém o orçamento legado: 2.500 caracteres por peer e 200.000 no conjunto. Prefixos são cortados em limites lexicais seguros, sem deixar strings/argumentos abertos. Imports multiline permanecem declarações completas. A consulta local examina uma janela limitada; modelos acima de 500.000 caracteres mantêm sugestões locais, mas não solicitam inferência remota do documento inteiro. O namespace mantém até 1.000 nomes/colunas por DataFrame. Esses limites são explícitos para manter edição responsiva.

## Medições

Protocolo real, runtime empacotado, conexão SQLite salva e 40 consultas aquecidas nesta máquina:

| Medida | Tempo |
| --- | ---: |
| Primeira consulta de módulo Python após sessão pronta | 51,94 ms |
| Primeira inferência de método DataFrame | 182,53 ms |
| Coluna de DataFrame por chave string | 0,73 ms |
| Carregamento de schema SQLite/colunas referenciadas | 37,06 ms |
| Python aquecido, p95 do RPC | 0,49 ms |
| SQL aquecido, p95 do RPC | 0,60 ms |

Esses números não incluem pintura da interface nem latência de bancos remotos. Jedi inicializa e infere fora da thread da UI. No benchmark de helpers com 120 blocos de 80 KB, remover a varredura de todos os snippets por consulta reduziu uma consulta aquecida de aproximadamente 39,6 ms para 0,015 ms.

No gerador SQL em processo, um catálogo sintético com 10.001 colunas e 402 sugestões em JOIN passou de mediana 46,07 ms/p95 47,14 ms para mediana 1,00 ms/p95 1,25 ms. Um índice de sufixos literais é construído uma vez por schema, em vez de varrer todos os nomes para cada sugestão. Esse ensaio não inclui RPC ou acesso a banco.

Reprodução isolada: `.venv/Scripts/python.exe scripts/tauri/benchmark_autocomplete.py --executable desktop/src-tauri/target/release/datapyn-runtime.exe`. O script cria diretórios/SQLite próprios, verifica as sugestões e encerra o runtime antes da limpeza.

## Validação

Regressões cobrem cancelamento exato, digitação rápida, cache/backoff, sessões isoladas, namespaces vazios, imports multiline, docstrings longas, DDL, UTF-16, quoting, escape de colunas, substituição parcial, snippets literais, lista aberta e grandes catálogos. Incluem `Id`/`id` distintos no PostgreSQL, nomes SQL com ponto literal e keywords Python válidas somente por indexação. Contratos stdio exercitam o supervisor real; os smokes verificam o binário congelado sem depender do Python instalado.

Verificação em 03/10/2026: 281 testes frontend, 322 testes runtime e 16 testes Rust passaram, assim como TypeScript, Ruff, build Tauri de produção e os três smokes do runtime empacotado. No aplicativo nativo foram conferidos Ctrl+Space, Tab/Enter, atualização de lista aberta, pandas/Polars, imports e funções entre blocos, snippets com `$`/chaves literais, substituição no meio da palavra, colunas com espaço/apóstrofo, keywords Python por chave sem gerar atributos inválidos, alias SQL, aspas existentes, tabela com ponto literal, alias de tabela com aspas no nome e isolamento entre sessões.

O aceite nativo usa análise/base sintéticas em `.tooling/autocomplete-acceptance`. Bancos externos e provedores de IA autenticados precisam ser validados no ambiente configurado pelo usuário.

## Diagnóstico de falha do worker congelado

Em 04/10/2026, duas execuções do smoke de paridade do pacote congelado falharam na primeira conclusão Python de `df.`, com `operation_failed: EOFError`. SQL, os RPCs de filtro/ordenação/exportação e o smoke básico de execução funcionavam. Um probe do pacote anterior também apresentou uma vez `TypeError: 'Stack' object is not iterable`. Esses erros não vieram acompanhados do código de saída nem de um traceback do worker original.

Os probes posteriores passaram tanto em source quanto no pacote novo, com e sem os RPCs de cabeçalho/exportação antes do autocomplete. O prefixo exato do smoke, incluindo Explorer e autocomplete SQL antes da primeira/segunda conclusão Python, também passou sem instrumentação adicional. Traces temporários isolados com `faulthandler` registraram inferências bem-sucedidas, sem capturar a falha original. Portanto, esses resultados não comprovam que os filtros causaram o problema nem estabelecem a causa da saída do worker. Não foi feita uma alteração especulativa nas dependências ou nas fontes coletadas pelo PyInstaller.

O transporte agora devolve `editor_unavailable` quando encontra EOF inesperado ou um pipe de escrita rompido. A mensagem identifica a etapa (`initialization` ou `inference`) e o código de saída observado, inclusive códigos nativos em hexadecimal. A espera de diagnóstico é limitada a 100 ms; se o código ainda não estiver disponível, a mensagem informa `unknown`. Exceções Python durante o bootstrap também são capturadas antes dos imports/inicialização do serviço. Stdout/stderr nativos continuam descartados para preservar o protocolo; stderr vazio do supervisor não exclui uma falha no filho.

A requisição que falhou não é repetida nem convertida em uma lista vazia de sugestões. O worker e seu grupo são descartados; outro pedido explícito pode criar um novo processo. Isso melhora o diagnóstico e a recuperação posterior, mas não constitui correção comprovada da causa de um crash nativo. O kernel de execução e seus DataFrames pertencem a processos separados.

Validação focada: 44 testes de `test_editor_process.py` e `test_autocomplete.py` passaram. As novas regressões verificam EOF na inicialização/inferência, preservação de `0xC0000005`, pipe rompido, encerramento com código zero sem resposta, ausência de retry da requisição, novo pedido após falha e erro no bootstrap anterior à captura de stdio. O aceite final deve continuar executando os smokes originais contra o sidecar reconstruído, sem retries que ocultem uma falha.

O sidecar final reconstruído em 04/10/2026 passou pelos três smokes originais, sem retry das requisições Python. A primeira conclusão de `df.` levou 248,94 ms e a segunda 0,96 ms nessa amostra. A suíte completa do runtime passou por 602 testes. Isso valida o pacote entregue e os novos diagnósticos; não estabelece a causa das falhas intermitentes anteriores.

Verificação dos DataFrames SQL em 04/10/2026: 437 testes frontend e 496 testes runtime passaram, além de TypeScript, Ruff, build Tauri de produção e os três smokes do runtime congelado. As regressões stdio verificam múltiplos resultsets, ordem contexto/finalização, conexões por bloco, isolamento entre sessões, exclusão/substituição de variáveis, mutações parciais após erro e restauração Parquet com nomes Unicode. Testes locais cobrem métodos/propriedades, colisões com colunas e contextos de listas/loc/sort, incluindo documentos grandes.

No executável Windows final, com SQLite/perfil isolados em `.tooling/sql-frames-acceptance`, dois SELECTs produziram `vendas` e `vendas1`. Ctrl+Space ofereceu ambos no Python; `head` foi completado com Tab e executado sobre o DataFrame real. A sugestão `valor total` também foi aceita e executada em `vendas[['valor total']]`, retornando 125,5. O menu exibiu ambas as colunas além da borda inferior do dock, aceitou a segunda com o mouse e conservou o foco. No dock destacado, sugestões de métodos e `head` com Tab/F5 funcionaram; ao fechar a janela, o dock retornou com código e resultado preservados. A validação SQL com a conexão SQLite mostrou "Sintaxe válida"; o smoke congelado cobre SQL válido/inválido nos cinco dialetos suportados, após incluir seus módulos carregados sob demanda.

## Ponte nativa e aceite final

O erro `Unsupported runtime method: language.prepare` do aplicativo veio de `allowed_method` em `desktop/src-tauri/src/runtime.rs`. O runtime Python já implementava o método, mas a ponte Tauri recusava a chamada antes de enviá-la ao processo. A lista explícita agora inclui `language.prepare`; métodos arbitrários continuam recusados.

O novo teste `native_boundary_prepares_and_publishes_sql_metadata` usa a mesma validação e o mesmo roteamento de `Backend::request`, trocando apenas o destino dos eventos por um canal de teste. Ele conecta um SQLite real, cria uma tabela, prepara o contexto através da ponte e verifica o evento com catálogo e colunas. Foi executado em debug com Python de desenvolvimento e em release com o runtime congelado distribuído, sem abrir uma WebView. O teste anterior de stdio direto não atravessava essa validação nativa.

No aceite desta revisão passaram 732 testes frontend, 36 testes Rust, TypeScript, 51 cenários com Monaco real e 12 cenários de tema em Chromium headless. O teste da ponte também passou separadamente em release com o sidecar congelado. Não houve controle do desktop ou conexão a servidores externos. O runtime Python não foi alterado nesta revisão.

O build Tauri de produção foi concluído com os assets finais e entregue localmente em `build/tauri-preview-current/`, contendo `datapyn-desktop.exe` e `datapyn-runtime.exe`. Foi usado um target separado porque a instância anterior continua aberta e o Windows bloqueia seu executável. É necessário fechar essa instância antes de abrir o pacote novo; a configuração e o perfil padrão seguem os caminhos já usados pelo aplicativo.

Com 100.001 tabelas sintéticas, construir o primeiro índice local levou 72,81 ms; buscas de prefixo aquecidas tiveram mediana de 0,0081 ms/p95 de 0,1363 ms. A primeira busca interna levou 2,84 ms; em cache, mediana de 0,0079 ms/p95 de 0,012 ms. Essas medições são dos helpers locais, sem pintura do Monaco ou latência de servidores, e não eliminam o custo inicial de indexação.

## Sugestões durante a digitação e nomes focados

O comportamento de referência segue os editores de dados: o [Databricks SQL editor](https://docs.databricks.com/aws/en/sql/user/sql-editor/write-queries) oferece sugestões durante a digitação, reconhece aliases de tabelas e permite nomes simples com catálogo/schema selecionados; o [MySQL Workbench](https://dev.mysql.com/doc/workbench/en/wb-preferences-sql-editor.html) habilita o início automático por padrão; o [SSMS](https://learn.microsoft.com/en-us/ssms/scripting/intellisense-sql-server-management-studio) combina listas contextuais com conclusão explícita.

Foi avaliado o [monaco-sql-languages](https://github.com/DTStack/monaco-sql-languages). A lista documentada de dialetos não cobre SQL Server e SQLite, a compatibilidade garantida declarada é com Monaco 0.37.1, e os metadados de tabelas/colunas continuam dependendo de um completion service fornecido pela aplicação. A integração mantém Monaco 0.57, o catálogo local compartilhado e a inferência SQL do runtime, preservando os seis dialetos sem adicionar outro parser no caminho de cada tecla.

Palavras comuns em `FROM`, `WHERE` e `SELECT` abrem a lista automaticamente, além dos triggers de espaço, ponto e aspas. O atraso local explícito é 35 ms; o debounce de inferência remota continua separado. O popup não espera RPCs de inferência. SQL aceita palavras internas a nomes, como `movimento` em `gecon_ft_movimentos_premio`, depois das correspondências de prefixo. Uma única letra permanece restrita ao prefixo para evitar listas excessivas. Resultados de busca são limitados a 500 nomes e 64 consultas por índice imutável; respostas locais reutilizam as mesmas entradas mesmo após alterações do namespace Python.

Uma tabela do banco/schema focado aparece pelo nome simples e insere apenas esse identificador quando sua resolução é inequívoca. Tabelas em outros schemas conservam `schema.nome`; outros catálogos conservam a qualificação necessária. Um objeto permanente ocultado por tabela temporária conserva seu schema. O caminho completo permanece nos detalhes da sugestão. Aspas de identificador continuam apropriadas ao dialeto e nomes com ponto literal continuam sendo um único identificador. No PostgreSQL, `"Analytics".` preserva o schema com maiúscula, enquanto `ANALYTICS.` resolve para `analytics`; o índice e a remoção do prefixo respeitam essa identidade também no enriquecimento remoto. O enriquecimento remoto recebe a mesma normalização e não restaura um banco redundante na lista.

Em JOINs, uma coluna presente em uma única origem usa o nome simples quando os campos de todas as origens são conhecidos. Uma coluna presente em mais de uma origem usa `alias.coluna`, inclusive se uma resposta remota atrasada oferecer o nome ambíguo sem alias. CTEs, tabelas derivadas e tabelas com colunas ainda não carregadas mantêm a qualificação das colunas conhecidas até a inferência resolver suas saídas. Assim, Tab insere uma referência válida e conserva a escolha da origem. Completar `alias.` continua restrito aos campos daquela relação.

Validação isolada e repetível: `npm --prefix desktop run test:autocomplete`. O runner executa o componente de produção, providers e Monaco reais em Chromium headless, com metadados sintéticos e sem controlar janelas do usuário. Os 51 cenários cobrem letras comuns e Tab nos seis dialetos, JOINs ambíguos e origens ainda desconhecidas, pesquisa interna e sua ordem/aceitação no widget, schemas PostgreSQL que diferem somente em maiúsculas, contexto tardio, objetos além das primeiras 500 sugestões, inferência atrasada, mudança de banco/schema, Escape, Python e widgets fora dos docks. Os testes com fixtures não equivalem a conexão validada contra seis servidores externos.

## Nomes simples e resolução do SQL Server em 05/10/2026

O encurtamento agora também cobre nomes de fallback em `context.tables`, antes das colunas chegarem, e respostas RPC que ainda não possuem entrada no catálogo local. Em `ESIM`/`dbo`, `ESIM.dbo.Item` aparece como `Item` e Tab insere `Item`. A coluna direita do popup mostra apenas `table`; o caminho completo fica no painel de documentação, preservando o texto remoto existente. A normalização extrai schema/catalog do fallback, compara o banco selecionado e conserva os namespaces de objetos externos ou ambíguos. Uma referência explícita como `dbo.` pesquisa também as chaves `ESIM.dbo.*`, sem inserir o prefixo novamente nem misturar o schema focado com o schema escrito.

Identificadores ordinários usam texto simples no SQL Server, MySQL, MariaDB, Databricks e SQLite. Palavras reservadas e nomes com espaços, pontos literais ou delimitadores continuam escapados. PostgreSQL conserva aspas para preservar a identidade física de letras maiúsculas/minúsculas. Digitar `[` ou aspas/backticks explicitamente mantém o delimitador escolhido pelo usuário; a substituição possui apenas o identificador corrente. O enriquecimento remoto de campos, schemas e bancos aplica a mesma regra. Funções com expressões e snippets permanecem literais.

As listas estáticas de palavras vêm das referências primárias do [SQL Server](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/reserved-keywords-transact-sql?view=sql-server-ver17), [SQLite](https://www.sqlite.org/lang_keywords.html), [MySQL 8.4](https://github.com/mysql/mysql-server/blob/8.4/sql/lex.h), [MariaDB](https://mariadb.com/docs/server/reference/sql-structure/sql-language-structure/reserved-words) e [parser do Apache Spark](https://github.com/apache/spark/blob/master/sql/api/src/main/antlr4/org/apache/spark/sql/catalyst/parser/SqlBaseParser.g4). No MySQL, a gramática separa os tokens não reservados; no Spark, são considerados os reservados ANSI e os tokens restritos para aliases. Os identificadores especiais seguem os [delimitadores documentados do Databricks](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-names). A verificação é local por `Set`, sem RPC, parser adicional ou busca de palavras por tecla.

O runtime publica `schema_snapshot.default_schema` com o padrão físico do login SQL Server, separado de `current_schema`, que representa o foco do seletor. Selecionar `reports` quando o padrão físico é `dbo` mostra `Item` do schema focado, mas Tab insere `reports.Item`; isso conserva a tabela escolhida e evita executar `dbo.Item`. Se o padrão físico for `reports`, a inserção pode ser simples. Um prefixo já escrito pelo usuário possui a qualificação. O campo também participa da chave do cache de sugestões.

O aceite headless passou por 65 cenários com Monaco de produção, incluindo ESIM/dbo com catálogo carregado, fallback e RPC anterior aos metadados, schemas SQL Server diferentes do padrão físico, prefixos explícitos, delimitadores já digitados e reservados aceitos com Tab. As regressões unitárias também conservam as regras de JOIN, catálogos de 100 mil objetos e identidade PostgreSQL. Não foram usados servidores privados nem controle de janelas do desktop.
