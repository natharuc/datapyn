# Autocomplete SQL e Python no Tauri

O editor retorna sugestões locais imediatamente. Jedi e metadados de bancos são enriquecidos em segundo plano, com caches limitados, debounce e cancelamento por requisição.

## Funcionalidades

- SQL: keywords, tabelas, colunas, aliases, JOINs, CTEs, schemas e rotinas. Nomes especiais/reservados recebem quoting por dialeto. Catálogos explícitos SQL Server/Databricks carregam sob demanda; DDL invalida os metadados.
- Python: builtins, imports/aliases de outros blocos, funções, variáveis, métodos pandas/Polars e colunas de DataFrames por atributo ou chave de string.
- Snippets de outros blocos da mesma linguagem preservam texto literal, incluindo `$`, chaves e quebras de linha.
- Ctrl+Space solicita sugestões normais, mesmo com autocomplete automático desligado. Ctrl+. mantém sugestões normais ou Pynia inline conforme a preferência de IA. Tab/Enter aceitam; Escape descarta a intenção pendente.
- Completar no meio de uma palavra substitui o sufixo. Strings Python e identificadores SQL reconhecem escapes e aspas existentes.
- Trocar bloco, sessão, conexão, posição ou modelo invalida pedidos antigos. Fontes de outras sessões não alimentam as sugestões; `wordBasedSuggestions` está desligado.

## Integração e limites

Imports/preamble antes ignorados são analisados sem executar código. Snapshots vazios são autoritativos, evitando variáveis removidas reaparecerem. Metadados SQL sem mudança nas variáveis não invalidam inferência Python. A leitura de contexto não reagenda o próprio diagnóstico.

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
