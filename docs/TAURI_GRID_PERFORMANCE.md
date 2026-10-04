# Grade de resultados com milhões de linhas

A grade conserva o DataFrame no kernel Python e envia ao frontend somente blocos da região visível. O número total de linhas não aumenta o DOM, a fila de pedidos nem o cache do canvas. Os dados originais permanecem disponíveis para Python, filtros, resumo e exportações.

## Implementação

- Canvas Glide virtualiza linhas e colunas. `getCellContent` consulta o cache e formata a célula; não dispara IPC nem atualiza estado React durante a pintura.
- Páginas visuais têm até 200 linhas × 32 colunas. A fila usa dois pedidos simultâneos, debounce de 35 ms, prioridade para a região atual e descarte das respostas de uma visualização antiga. Uma troca de filtro não libera artificialmente slots ainda ocupados por IPC antigo.
- Cache LRU tem três limites: 40 blocos, 250 mil células e 16 MiB de memória JavaScript estimada. Cabeçalhos vêm do descritor original. Chegadas de páginas atualizam somente as células visíveis, agrupadas em `requestAnimationFrame`, por `DataEditorRef.updateCells`.
- Filtros e ordenações conservam posições `uint32`/`uint64`, em vez de cópias completas de DataFrames. Cache LRU de posições: 64 visualizações e 256 MiB por kernel; execução, restauração e liberação de resultados invalidam os índices. Ordenação continua estável, com nulos ao final e seleção após filtro/ordenação.
- Paging Pandas extrai apenas os elementos das colunas solicitadas antes de construir o pequeno DataFrame da página. Isso evita copiar colunas inteiras em DataFrames fragmentados. Polars permanece nativo; a conversão de timestamps com precisão de nanossegundos é restrita à página. A conversão completa para Pandas ocorre somente em ações explícitas que precisem dela.
- Seleções de linhas/colunas usam faixas compactas. Selecionar 10 milhões de linhas consecutivas não cria 10 milhões de números em JavaScript. Retângulos descontínuos conservam exatamente as células selecionadas.
- Texto/Excel/JSON são formatados em Web Worker local, com transferência em lotes e acknowledgement, limite incremental de 16 MiB e cancelamento. A cópia continua limitada a 200 mil células; seleções maiores orientam a usar exportação. SQL é gerado no kernel, com cancelamento cooperativo. Decimal, bigint, Unicode, nulos e cabeçalhos continuam preservados.

## Contrato de paginação

`result.page` mantém `offset`, `limit`, `filter` e `sort`. Acrescenta `column_offset`, `column_limit` (1–256) e `include_columns`. Quando `include_columns=false`, retorna `columns: []`; a projeção inclui `column_offset` e `total_columns`. Chamadas antigas conservam seus metadados e colunas completos.

Uma página maior que 8 MiB gera erro explícito, sem truncar o DataFrame. Uma visualização cujo índice exceda 256 MiB orienta a refinar o filtro e memoriza esse erro até a próxima geração, evitando repetir uma ordenação impossível de armazenar. Esses limites dizem respeito ao transporte/cache; o DataFrame original continua sujeito à RAM disponível no kernel.

## Medições locais

Windows, mesma instalação Python/Pandas/NumPy/Polars, dados sintéticos locais. Benchmark direto de `ResultStore`, sem banco remoto, IPC ou pintura. Cada execução usa 10 milhões de linhas × 8 colunas `int64` (640.000.132 bytes), ordenação descendente de `id` e cinco páginas de 200 linhas. A implementação anterior (`8ebcf14`, classe e contrato de views daquela revisão) transferia as oito colunas; a atual projeta duas. Os quatro tempos após a primeira página compõem a mediana.

| Medida | Antes | Atual |
|---|---:|---:|
| Primeira página com ordenação | 358,69 ms | 379,22 ms |
| Mediana das páginas seguintes | 367,11 ms | 0,79 ms |
| Cache de posições | nenhum: view completa excedia orçamento | 40.000.000 bytes |
| Células por página | 1.600 | 400 |
| JSON da última página medida | 13.971 bytes | 2.908 bytes |

A primeira ordenação ainda percorre o conjunto; o ganho principal está na reutilização e na extração das páginas seguintes. Registrar um Polars de 10 milhões de linhas levou 0,056 ms, conservando o mesmo objeto; uma página final de uma coluna levou 2,19 ms. Tempos são amostras desta máquina, sem promessa de latência universal.

Validação visual do componente real no navegador com transporte sintético de 12 ms: 10 milhões de linhas × 256 colunas, salto à última linha/coluna, seleção de 2,56 bilhões de células e recusa da cópia acima do limite. Rolagem vertical/horizontal rápida manteve no máximo dois pedidos simultâneos; a amostra observada não registrou tarefas da UI acima de 50 ms. Um heartbeat React a cada 100 ms continuou avançando. O worker formatou 200 mil células em 89 ms, gerando 1.294.039 caracteres de texto e 13.334.490 de HTML, sem tarefa observada acima de 50 ms na UI. Esse teste exercita o canvas, scheduler, seleção e worker; a aceitação congelada verifica separadamente o transporte real e os frames Pandas/Polars.

O executável Tauri recompilado passou pelos três smokes congelados. No smoke com Pandas de 10 milhões de linhas e filtro que seleciona um milhão, o RPC inicial com filtro/ordenação levou 46,23 ms e as páginas seguintes tiveram mediana de 0,68 ms (100 linhas/página). O aceite nativo abriu um DataFrame de 10 milhões × 8 colunas, mostrou todas as linhas virtualizadas, navegou à última linha/coluna, copiou uma célula com cabeçalho pelo worker e selecionou as 80 milhões de células. Todas essas verificações usaram perfil e dados sintéticos separados do usuário.

## Reprodução e regressões

```powershell
.venv/Scripts/python.exe scripts/tauri/benchmark_grid.py --baseline 8ebcf14
.venv/Scripts/python.exe scripts/tauri/benchmark_grid.py
.venv/Scripts/python.exe -m pytest runtime_tests/test_result_paging.py -q
npm --prefix desktop test
npm --prefix desktop run desktop:build -- --no-bundle
```

`benchmark_grid.py` usa dados novos e não toca conexões nem perfis do usuário. O smoke de paridade do build verifica páginas finais projetadas, filtro/ordenação de Pandas com 10 milhões de linhas e página Polars do mesmo tamanho em um perfil temporário.

Regressões cobrem fila de mil saltos, dois pedidos em voo, cache por bytes/células/LRU, damage recortado, reset e abort, seleções de 1M/10M sem iteração dos índices, worker/Unicode/precisão/limites, DataFrames consolidados e fragmentados sem materialização de colunas completas, ordenação estável, índices repetidos, Polars nativo, timestamps ns e exports de UInt64 nullable/Decimal.

Os 350 testes frontend e 407 testes runtime passaram na integração. Após o último ajuste de extração, 152 testes relacionados passaram, incluindo as 25 regressões de paginação. Banco remoto, pico total de RAM de cada carga do usuário e todas as combinações possíveis de dtype ainda dependem do cenário real.
