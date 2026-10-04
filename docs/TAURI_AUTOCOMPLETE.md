# Autocomplete SQL e Python no Tauri

O editor retorna sugestões locais imediatamente. Jedi e metadados de bancos são enriquecidos em segundo plano, com caches limitados, debounce e cancelamento por requisição.

## Seleção de banco/schema e preparação do editor

O cabeçalho de cada bloco SQL mostra conexão, banco (catálogo no Databricks) e schema quando a plataforma possui esse contexto. Banco/schema abrem uma lista pesquisável com navegação por teclado, pesquisa local e renderização virtualizada. SQLite mostra o arquivo atual: trocar arquivos usa conexões; aliases `main`/`temp` não representam outra conexão.

A seleção é específica do bloco, inclusive do primeiro. Trocar banco limpa o schema específico anterior e deixa o driver resolver o padrão do novo banco. Execução, diagnósticos, Explorer, exportações e autocomplete usam a mesma precedência. Novos blocos gerados pelo Explorer recebem o contexto de origem; trocar a conexão por arraste limpa banco/schema antigos.

`language.prepare` agenda o catálogo do bloco focado antes da primeira solicitação de sugestões. Os pedidos usam a conexão e os defaults reais da configuração; o dialeto já está disponível no frontend antes de chegar o catálogo. O preparo acompanha mudanças de foco/contexto, agrupa pedidos equivalentes e mantém caches limitados, sem consultar o banco a cada tecla. Atualizar metadados força a recarga mesmo dentro do TTL. Alterações na configuração da conexão descartam os índices do servidor anterior.

Eventos de metadados incluem `requested_scope` e o contexto resolvido pelo driver. O frontend relaciona esses dois endereços por identidade do snapshot, incluindo conexões implícitas (`transient`), e remove todos os aliases na invalidação. Eventos somente de variáveis preservam esse catálogo. Uma falha de acesso publica `metadata_state: error`, limpa o snapshot anterior e apresenta o erro na barra de status, evitando um catálogo silenciosamente vazio ou de outro schema.

SQL Server, MySQL e MariaDB deixam de receber o schema artificial `default`. PostgreSQL descobre os bancos acessíveis e prioriza o schema focado quando existe o mesmo nome de tabela em outro schema. O preparo reconhece fontes separadas por vírgula e subqueries. Listas de nomes já obtidas do driver não são truncadas em 10 mil objetos; colunas continuam carregadas sob demanda e armazenadas em caches limitados.

Teste do editor real, sem operar o desktop: `npm --prefix desktop run test:autocomplete`. Em uma máquina sem Chromium de teste, instalar com `npm --prefix desktop exec playwright install chromium`. O runner usa Monaco e os componentes de produção em Chromium headless, com a fronteira IPC controlada. Esse teste comprova interação e isolamento dos seis dialetos; integração com banco real usa SQLite. Bancos externos devem ser conferidos no ambiente configurado.

## Aceite desta correção de contexto

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
