# Diagnóstico do DataPyn e base para a migração desktop

O DataPyn tem um produto consistente: SQL, Python, resultados e assistência de IA se combinam em um fluxo útil, com detalhes de produtividade que precisam continuar na migração. A arquitetura atual, porém, mistura execução do usuário, bibliotecas globais, conexões e interface Qt no mesmo processo. A recomendação preliminar é manter o aplicativo desktop e o backend Python, migrar a interface para React com TypeScript e separar a execução em processos supervisionados. A escolha final do host e da grade depende de uma prova prática de performance e paridade.

Análise realizada em 3 de outubro de 2026 sobre `C:\nac\datapyn`, branch `feat/postgresql-schema-ux`, commit `479b2e82cbe67fd3c007094792e450b0ccdbdab5`, versão `1.57.0` em `pyproject.toml`. O usuário confirmou que deseja manter um aplicativo instalado, com acesso local a arquivos, Python e bancos. Este documento registra diagnóstico e uma direção inicial; o plano completo de implementação ainda será desenvolvido.

A leitura abrangeu código, testes, documentação e distribuição. Foram identificados 195 arquivos Python de aplicação, com 86.489 linhas, e 133 módulos de teste com 2.485 definições de teste. Esses números medem tamanho, não qualidade nem cobertura. Foram executados 90 testes existentes em nove módulos, com resultado `90 passed in 8.77s`. As configurações Qt foram redirecionadas para arquivos INI temporários para preservar o ambiente do usuário. O aplicativo e bancos reais não foram usados nesta análise; os travamentos relatados não foram reproduzidos nem medidos.

**O que já funciona como base para a migração**

O núcleo do produto vai além do editor: cada sessão reúne blocos, namespace Python, identidade de conexão, parâmetros, resultados, chat, notificações e execução periódica. A integração SQL para DataFrame para Python é o contrato principal. A conexão pode variar por bloco, e resultados de múltiplos SELECTs possuem nomes e abas próprios.

Há investimento útil em carregamento lazy de schema, autocomplete contextual, reconexão, exportação de consultas em streaming, persistência Parquet, preparo assíncrono da grade, descarte de respostas obsoletas e gerenciamento de pacotes. A migração deve conservar essas regras e otimizações.

Monaco, chat Pynia e Plotly já utilizam conteúdo web. O editor já é JavaScript; a mudança envolve expandir essa camada e substituir a ponte Qt, além de extrair o backend. Ainda não existe uma API Python pronta e independente de Qt: sessões, schema, configuração e serviços dependem de `QObject`, signals ou `QSettings` em vários pontos.

**Problemas encontrados e limites da evidência**

Os achados abaixo foram confirmados por leitura de código. Suas consequências são hipóteses técnicas bem fundamentadas, mas ainda precisam de reprodução e medição no fluxo real.

| Problema | Evidência no código | Implicação para a migração |
|---|---|---|
| Python executa no processo que hospeda a interface | `source/src/ui/main_window/_workers.py:74`, `:198`; `source/src/ui/components/session_widget.py:2656` | Separar execução em processos persistentes por sessão. Uma biblioteca JS não corrige sozinha consumo de CPU, memória ou falha do kernel. |
| Captura de saída e Matplotlib são globais | `_workers.py:85` altera `sys.stdout` e `sys.stderr`; `:139` fecha figuras e altera `plt.show` e `rcParams` | Namespaces por aba não isolam bibliotecas globais. Duas execuções podem interferir em saída e gráficos. |
| Cancelamento Python apenas solicita interrupção | `session_widget.py:1770`; worker em `_workers.py:85` e `:198` não consulta a flag | Loops e chamadas bloqueadas podem continuar após cancelar. Definir interrupção cooperativa e reinício forçado do processo. |
| Cancelamento SQL depende da fila do thread ocupado | `session_widget.py:136`, `:1798`, `:2312` | O slot de interrupção pode esperar a consulta síncrona terminar. O canal de cancelamento precisa funcionar enquanto o driver está bloqueado. |
| Há espera e encerramento forçado de threads na interface | `source/src/utils/qt_threading.py:103`; `_sessions.py:564`; `session_widget.py:1730` | O helper espera até 300 ms, usa `terminate()` e espera mais 500 ms. Encerramento e limpeza precisam sair do caminho da UI. |
| Ferramentas silenciosas da Pynia podem executar SQL e Python na thread da interface | `source/src/services/pynia/acp/mcp_host.py:75`, `:350`; `source/src/services/copilot/mcp_tools.py:3036`, `:3153` | IA e usuário devem usar a mesma API de execução e as mesmas filas. O timeout do socket não interrompe o handler. |
| Grandes resultados ainda são materializados integralmente | `source/src/database/database_connector.py:71`; `results_viewer.py:526` | Fetch em chunks acumula linhas e DataFrames. Limite visual não limita memória do resultado. Definir estratégia para materialização e arquivos temporários. |
| Operações grandes ainda começam na UI | `results_viewer.py:3588`, `:5358`, `:5206`, `:5233`, `:5410` | Cópias de DataFrame e serialização para clipboard precisam ser jobs com progresso e limites. Virtualização da grade não resolve essas cópias. |
| Preparo antigo da grade pode continuar após invalidar a resposta | `results_viewer.py:608`, `:4249` | Descartar resposta antiga não cancela CPU já consumida. Usar jobs canceláveis e controle de concorrência. |
| Snapshots assíncronos compartilham DataFrames e criam threads por chamada | `source/src/core/session_result_storage.py:468` | Coordenar snapshots por sessão e versão; avaliar mutação durante escrita. |
| Há serviços legados que parecem reutilizáveis, mas não são o caminho operacional | `source/src/services/python_execution_service.py:16`; `source/src/workers/__init__.py:135` | `PythonExecutionWorker` lança `NotImplementedError`. Extrair a implementação real de `PythonWorker`, sem portar serviço apenas pelo nome. |
| Credencial salva é escrita em JSON | `source/src/database/connection_manager.py:66`, `:143` | Preservar a funcionalidade de salvar credenciais com armazenamento no cofre do sistema e migração do formato existente. |

O custo de um `QWebEngineView` por bloco e a dependência de CDN do Monaco são outros candidatos a medição. Cada bloco cria seu editor web (`code_block.py:1143`; `monaco_editor.py:223`), e o template carrega Monaco `0.45.0` de CDN (`monaco_template.html:62`, `:154`). Empacotar os assets localmente permitirá funcionamento offline previsível, mas o impacto de memória ainda precisa ser medido.

A documentação do [Qt QThread](https://doc.qt.io/qt-6/qthread.html) confirma que interrupção é uma solicitação que o código precisa observar, que `wait()` bloqueia quem chama e que `terminate()` pode interromper um thread sem limpeza. Esses mecanismos ajudam a interpretar os achados; não substituem uma reprodução do DataPyn.

**Inventário de funcionalidades a preservar**

Esta matriz registra funcionalidades implementadas e seus contratos relevantes. Preservar a capacidade não significa manter limitações ou conflitos existentes. O plano de migração deve transformar cada linha em critérios observáveis de aceitação.

| Área | Paridade necessária | Referências principais |
|---|---|---|
| Sessões | Criar, herdar conexão/contexto, duplicar, renomear, fechar e salvar; namespace, blocos, resultados e chat por aba | `core/session.py:43`; `ui/main_window/_sessions.py:57`, `:342`, `:1178` |
| Blocos | SQL/Python; nome, ordem por drag, duplicação, exclusão, ativação, altura, maximização e cabeçalho durante rolagem | `editors/code_block.py:935`, `:2008`; `editors/block_editor.py:384`, `:598` |
| Execução | Bloco ou seleção; fila sequencial dos blocos ativos; estados, duração, erros, cancelamento e proteção contra tecla repetida | `editors/block_editor.py:454`; `ui/components/session_widget.py:1248`, `:3151` |
| SQL e namespace | `df` ou nome do bloco; múltiplos resultados `nome`, `nome1`, `nome2`; `db_engine` real e demais variáveis `db_*` | `ui/components/session_widget.py:2395`; `core/session.py:121`, `:127` |
| Python | Estado entre blocos; última expressão; saída/logs; pandas/Polars; imagens, Plotly e outros resultados ricos; pacotes importáveis | `ui/main_window/_workers.py:74`; `ui/components/session_widget.py:2590`, `:2680` |
| Bancos | SQL Server, PostgreSQL, MySQL, MariaDB, SQLite e Databricks; identidade de conexão grupo mais nome | `database/connection_manager.py:87`, `:149`; `database/database_connector.py` |
| Gestão de conexões | Grupos/pastas/cores; criar, testar, editar, importar/exportar; conexão por bloco; reconexão e desconexão por inatividade | `database/block_connector_pool.py`; `core/connection_settings.py:7` |
| Contexto de banco | SQL Server/MySQL/MariaDB por database; PostgreSQL com schema e `search_path`; Databricks com catalog/schema; refletir contexto no editor e Explorer | `database/database_connector.py:349`, `:473`, `:630`; `editors/code_block.py:1651` |
| Autenticação local | SQL Server por senha, Windows e Entra MFA; drivers ODBC e bibliotecas nativas | `database/database_connector.py:181`, `:250`, `:646`, `:701` |
| Parâmetros | `@nome` por bloco; compartilhados por `{{nome}}`; tipos/listas/defaults/delimitador; habilitação e validação | `utils/sql_parameter_service.py`; `core/parameter_settings.py` |
| Object Explorer | Schema lazy, pesquisa/expansão, copiar/inserir/arrastar nomes; gerar SELECT, COUNT, WHERE, GROUP BY, ORDER BY e DDL; detalhes de entidade | `ui/components/object_explorer_panel.py:436`, `:1055`, `:1455`; `ui/main_window/_sessions.py:220` |
| Editor | Monaco; seleção/cursor/foco; autocomplete SQL com schema/aliases e Python com namespace; ghost text; formatação e zoom | `editors/monaco`; `services/code_formatter_service.py` |
| Grade | Resultados múltiplos; filtros/chips, ordenação, formatos por coluna, seleção de células/ranges, cópia com/sem cabeçalho, menus e zoom | `ui/components/results_viewer.py:2553`, `:4103`, `:5403`, `:5689` |
| Resumo estatístico | Estatísticas do resultado e da seleção; agregados por coluna e atualização assíncrona | `ui/components/summarize_panel.py`; `ui/components/summarize_stats.py` |
| Gráficos | Plotly por resultado; criar/editar/excluir/exportar; configurações persistidas; matplotlib e rich output | `ui/components/results_viewer.py:3186`, `:3566`, `:4671`; `services/visualization` |
| Exportar resultados | CSV com opções, XLSX, JSON, SQL INSERT; arquivo/clipboard; revelar arquivo; exportar para tabela com progresso/cancelamento | `ui/components/results_viewer.py:5142`, `:5347`, `:6265`; `ui/dialogs/export_to_table_dialog.py` |
| Downloads grandes | Consulta direto para CSV/Parquet em streaming; chunks, múltiplos resultados, progresso, velocidade e cancelamento | `database/query_stream_exporter.py`; `ui/components/session_widget.py:1356`, `:1918` |
| Arquivos e importação | `.sql`, `.py`, `.dpw`, `.ipynb`; CSV/JSON/XLS/XLSX; opções de importação, geração de bloco, encoding, drag/drop e recentes | `services/file_import_service.py`; `ui/main_window/_file_io.py:42`, `:99` |
| Salvamento e script | Salvar inteligente `.sql/.py/.dpw`, Save As, indicação de modificação e exportar análise como Python standalone | `ui/main_window/_file_io.py:416`, `:597`, `:799` |
| Workspaces | Perfis em pastas, configurações, sessões/conexões/atalhos; duplicação e instância por workspace; geometria/docks/painéis | `core/workspace_service.py`; `core/workspace_manager.py`; `ui/dialogs/settings_dialog.py:1408` |
| Persistência de dados | DataFrames do namespace em Parquet, inclusive Polars convertido; opção/limite; inventário, export/import e restauração | `core/session_result_storage.py:73`, `:362`, `:380`; `ui/components/session_widget.py:669` |
| Execução periódica | Timer por aba; execução imediata ao iniciar e novo disparo depois do término; comportamento ao trocar foco | `ui/components/session_widget.py:3641`; `ui/main_window/_execution.py:62`, `:91` |
| Notificações | Templates e referências ao resultado; condições/cor/supressão; toast, Telegram e SMTP; configuração por aba e global | `services/notification_delivery_service.py`; `ui/components/session_widget.py:410`, `:2809` |
| Pynia atual | Claude, Cursor, GitHub Copilot e Codex por ACP local; instalação/login; chat por aba, streaming, cancelamento, modelo/reasoning, permissões e anexos | `services/pynia/acp/catalog.py:13`, `:53`; `ui/components/pynia_chat_panel.py` |
| Ferramentas da IA | APIs snapshot, inspect, query, run, edit, blocks, database, chart e notify; contexto, execução, edição/undo, resultados, schema e seleção | `services/pynia/tools/definitions.py` |
| Pacotes | Listar/pesquisar/instalar/desinstalar/atualizar via uv/pip; venv, fontes e import imediato | `services/package_manager_service.py:69`, `:204`, `:371`, `:542` |
| Plataforma e apresentação | Instância única, arquivos por associação, `--workspace`, clipboard, dialogs/abrir pastas, processos IA, update/instaladores/crash reporting; pt-BR/en-US e claro/escuro | `services/single_instance.py`; `source/main.py`; `services/auto_update_service.py`; `design_system`; `language` |

As referências abreviadas da matriz partem de `source/src/`.

**Atalhos e foco precisam virar um contrato único**

O mapa configurável está em `source/src/core/shortcut_manager.py:18`; os bindings globais são registrados em `source/src/ui/main_window/_ui_setup.py:724`. A migração deve unificar comandos, remapeamento e contexto de foco entre Monaco, grade, chat, diálogos e janela.

| Atalho | Comportamento encontrado |
|---|---|
| F5 | Executar bloco/seleção na linguagem do bloco |
| Ctrl+F5 | Executar todos os blocos ativos com código |
| Shift+Return | Executar e avançar pelo callback Qt; há binding conflitante no Monaco |
| Ctrl+Enter | Executar pelo binding fixo do Monaco |
| Ctrl+N e Ctrl+T | Nova sessão |
| Ctrl+W | Fechar sessão |
| Ctrl+Shift+B | Adicionar bloco |
| Ctrl+O, Ctrl+S, Ctrl+Shift+S | Abrir, salvar, salvar como |
| Ctrl+Shift+E | Exportar script Python |
| Ctrl+Shift+L | Limpar resultados |
| Ctrl+F e Ctrl+H | Buscar e substituir no editor |
| Ctrl+Shift+F | Formatar código |
| Alt+F1 | Informação da entidade selecionada |
| Ctrl+. e Ctrl+Space | Forçar autocomplete inline e sugestões Monaco, respectivamente |
| Ctrl+Shift+M e Ctrl+Shift+D | Gerenciar conexões e nova conexão |
| Ctrl+Shift+T | Recarregar schema |
| Ctrl+, | Configurações |
| Ctrl+Shift+C | Copiar seleção da grade com cabeçalhos |
| Ctrl+Shift+R e Ctrl+Shift+Alt+R | Restaurar view e resetar layout |
| Ctrl+Q | Sair |
| Ctrl+/ | Comentário pelo binding Monaco |
| Ctrl+roda | Zoom conforme painel |
| Ctrl+C e Ctrl+V | Ações contextuais; Pynia aceita também anexos/imagens no clipboard |

Monaco associa F5, Ctrl+Enter e Shift+Enter ao mesmo `triggerExecute()` em `monaco_template.html:1087`. Isso diverge do executar e avançar registrado pelo Qt. Remapear um comando global também pode deixar o binding fixo JS ativo. O comportamento efetivo precisa ser verificado com foco dentro do editor.

O README lista Ctrl+B para bloco, F5 apenas SQL, Shift+F5 para Python e Escape para cancelar. O código atual usa Ctrl+Shift+B, F5 por linguagem e não registra Shift+F5 no mapa. Não foi encontrado cancelamento global por Escape nos caminhos pesquisados. Há ainda defaults legados rotulados QScintilla no manager que não comprovam comandos configuráveis efetivos no Monaco.

**Persistência e documentação exigem cuidado na compatibilidade**

O `.dpw` usado normalmente representa uma aba com múltiplos blocos e formato versionado, enquanto `workspace.json` e `sessions.json` armazenam outros níveis de estado. Existe também um caminho legado de workspace inteiro. O migrador deve detectar os formatos, preservar a origem e validar importação e exportação com amostras reais.

Snapshots de DataFrames ficam em `%LOCALAPPDATA%\DataPyn\session_snapshots` no Windows, fora do workspace, com vínculo ao workspace no manifesto. Copiar somente `~/.datapyn` perde esses snapshots. A serialização da sessão e o `.dpw` não preservam exatamente os mesmos campos; testar chat, parâmetros compartilhados, contexto, formatos e gráficos individualmente.

A Pynia atual usa agentes ACP locais; a tabela de provedores por API key do README está desatualizada. O README também mostra uma versão anterior à `1.57.0`. A implementação e cenários funcionais devem definir a paridade.

Há capacidades com limitações atuais que precisam de uma decisão explícita: importação `.ipynb` trata células retornadas como Python sem consultar `cell_type`; exportação standalone usa um engine da sessão e não reproduz integralmente conexões diferentes por bloco. As ferramentas IA anunciam HTML, mas os despachos de execução de bloco pesquisados cobrem SQL/Python. O viewer renderiza HTML; isso não comprova uma linguagem de bloco HTML plenamente operacional.

**Verificação atual e trabalho necessário antes da migração**

Os 90 testes executados cobrem namespace, parâmetros SQL, limpeza do pool, cancelamento SQL, entrega de erros SQL, múltiplos resultados, afinidade de thread na restauração, gerenciador de atalhos e protocolo ACP. Os módulos foram `test_namespace.py`, `test_sql_parameters.py`, `test_block_connector_pool_reaper.py`, `test_sql_cancel_nonblocking.py`, `test_sql_worker_error_delivery.py`, `test_execution_multi_result.py`, `test_session_restore_signal_threading.py`, `test_shortcut_manager.py` e `test_pynia_acp_protocol.py`.

A CI exclui 22 módulos, incluindo vários de Monaco, atalhos, arquivos, blocos, restauração e Python E2E (`scripts/ci_test_shard.py:8`). Algumas exclusões são justificadas por display ou autenticação, mas deixam lacunas de paridade. Alguns testes de atalhos fazem `assert True` após enviar a tecla; não comprovam a ação realizada. `scripts/ci_pytest.sh:65` aceita certos crashes se a saída contém `passed` sem um número de falhas, podendo mascarar falhas de teardown. `pyproject.toml:95` configura `ruff` com `select = []`, sem regras de lint selecionadas.

Os testes mocked de cancelamento não demonstram que um driver bloqueado é interrompido. O teste de grade grande localizado usa 1.800 linhas, sem metas de tempo ou RAM. A próxima etapa deve medir a aplicação atual e a prova da nova arquitetura com dados e cenários representativos.

**Arquitetura candidata para manter o aplicativo desktop**

React com TypeScript é o candidato principal para a UI. Electron é o candidato principal para o host, por fornecer Chromium uniforme e APIs desktop adequadas aos fluxos existentes. Essa preferência é uma avaliação de risco de paridade, não um benchmark: Electron tem custo de distribuição e memória, e não há garantia de que será mais leve que a versão atual. Seu [modelo de processos](https://www.electronjs.org/docs/latest/tutorial/process-model) permite separar renderização e host; código pesado ainda deve ser encaminhado para processos próprios.

Tauri 2 continua uma alternativa viável. Sua documentação suporta [binários externos, inclusive Python](https://v2.tauri.app/develop/sidecar/). Ele adiciona integração Rust e diferenças entre WebViews por sistema. Comparar o aplicativo completo com Python, drivers e dados, em vez de comparar apenas o tamanho do host.

| Parte | Direção preliminar |
|---|---|
| Interface | React e TypeScript; estado organizado por sessão/bloco e comandos únicos |
| Host | Electron; APIs nativas expostas por ponte restrita e IPC tipado |
| Editor | Monaco empacotado localmente; reaproveitar providers e regras de contexto |
| Layout | Dockview como candidato a docking; validar janelas destacadas e serialização |
| Grade | Glide Data Grid como candidato inicial; testar seleção, clipboard, zoom, tipos e grandes volumes |
| Gráficos | Manter Plotly e saída matplotlib; transportes de resultados ricos |
| Backend | Python local extraído de Qt; preservar drivers, transformações, parâmetros e ferramentas |
| Execução | Processos persistentes por sessão, iniciados sob demanda e supervisionados; fila por sessão |
| Dados | DataFrames permanecem no backend; frontend recebe metadados, páginas e versões de resultado |

[Glide Data Grid](https://github.com/glideapps/glide-data-grid) oferece seleção e copy/paste sob MIT, tornando-o um candidato para a prova de conceito. Filtros, estatísticas e exportações ainda precisarão de integração com o backend. [Dockview](https://github.com/dockview/dockview) é um candidato para painéis e docking; validar a licença de cada recurso e a integração de popouts com o host escolhido. A edição Community do [AG Grid](https://www.ag-grid.com/react-data-grid/community-vs-enterprise/) não oferece nativamente todos os recursos desejados: seleção de ranges, operações avançadas de clipboard e Excel export aparecem como Enterprise. Ele pode ser avaliado, mas não deve ser escolhido supondo paridade completa gratuita.

Os comandos e eventos precisam identificar `session_id`, `block_id`, `execution_id` e `result_id`, além da versão do resultado. O host deve supervisionar kernels e continuar responsivo quando um deles para. O canal de controle não pode depender da mesma execução bloqueada que ele deve cancelar. Saída precisa chegar incrementalmente com limites e controle de fluxo; stdout do usuário deve ficar separado do protocolo.

O kernel deve manter namespace, módulos e objetos como `db_engine` vivos dentro de seu processo. Uma fila serial por sessão preserva a ordem entre SQL e Python, enquanto sessões distintas podem executar em paralelo com limites configuráveis. Exportação, preparo de dados e snapshots precisam de jobs coordenados, sem mandar milhões de linhas em JSON para React.

A transferência precisa preservar inteiros de 64 bits, decimais, valores nulos, datas e timezone, sem conversões silenciosas pelos tipos JavaScript. Arrow é uma opção a avaliar depois de medir páginas tipadas. O runtime estável do serviço deve ser separado do ambiente de pacotes modificável do kernel: instalar uma dependência para a análise não deve substituir bibliotecas das quais o aplicativo depende. A prova de empacotamento precisa funcionar em uma máquina sem Python de desenvolvimento instalado.

Cancelar forçadamente um kernel perde objetos Python vivos e estado intermediário; a recuperação deve ser explícita. Encerrar um processo local também não comprova que uma consulta no servidor parou. Cancelamento SQL precisa de estratégia por driver, estado final e confirmação quando disponível. As ferramentas Pynia devem usar o mesmo caminho de execução que os comandos da UI.

**Sequência proposta para o próximo planejamento**

1. Fechar a matriz de paridade com cenários reais, formatos de arquivo e comandos por contexto de foco. Separar capacidades a preservar de defeitos a corrigir.
2. Medir a aplicação atual: início, memória, digitação, troca de aba, resultado grande, filtros, clipboard, exportação e cancelamento. Fixar metas e datasets reproduzíveis.
3. Extrair regras Python e um contrato de comandos/eventos sem Qt. Priorizar a execução real, conectores, parâmetros, streaming e formatos de persistência.
4. Construir uma prova completa pequena: abrir sessão e conexão, executar SQL, passar o DataFrame ao Python, mostrar grade e gráfico, cancelar e restaurar estado. Validar empacotamento e autenticação local cedo.
5. Migrar gradualmente os demais recursos e manter a versão PyQt disponível enquanto a equivalência é verificada. A migração pode ser completa no destino e incremental na execução.
6. Validar instaladores, atualizações, drivers, pacotes, ACP e compatibilidade de dados em Windows, Linux e macOS. A distribuição atual já contempla os três sistemas.
7. Substituir a interface atual quando critérios de paridade, estabilidade e performance estiverem demonstrados. Estimar esforço depois da prova de arquitetura e das decisões de grade/host.

A prova precisa incluir loop Python infinito, consultas lentas, muitas mensagens de stdout, duas sessões simultâneas, filtros rápidos sobre dados grandes, fechamento durante execução e falha de um kernel. Também precisa de SQL Server com Windows/Entra, PostgreSQL com schemas, Databricks com catalogs, conexões por bloco, Pynia com ferramentas e restauração de workspaces existentes. O critério de sucesso é preservar o fluxo de trabalho e tornar seus limites de execução observáveis e controláveis.
