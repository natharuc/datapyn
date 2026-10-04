# Cabeçalhos interativos da grade Tauri

O cabeçalho mantém dois alvos separados, como no PyQt6: a seta alterna crescente/decrescente e o botão de filtro abre um painel ancorado à coluna. Clicar no nome continua selecionando a coluna; redimensionar sua borda não ordena os dados. Clique direito no cabeçalho/célula e o botão **Coluna** também abrem o painel.

O painel oferece ordenação explícita crescente/decrescente, remoção da ordem, copiar nome e abrir a formatação existente. Filtros de colunas diferentes combinam com AND e com a pesquisa global. Chips mostram a regra ativa, permitem reabri-la ou removê-la; **Limpar todos os filtros** também limpa a pesquisa global.

| Tipo | Filtros |
|---|---|
| Texto | Contém, igual, começa com, termina com; comparação literal sem diferenciar maiúsculas/minúsculas |
| Número | Intervalo inclusivo mínimo/máximo ou comparações individuais; limites abertos |
| Data | Intervalo início/fim, comparações individuais e calendário |
| Booleano | Qualquer, verdadeiro ou falso; aliases legados em colunas textuais |
| Todos | É nulo ou não é nulo |

Datas finais sem horário incluem o dia inteiro. O runtime usa o início do próximo dia como limite exclusivo, conservando fusos/DST e nanosegundos; um datetime explícito conserva seu instante inclusivo. Valores numéricos digitados atravessam o IPC como strings para preservar Decimal e inteiros maiores que o limite seguro de JavaScript.

## Processamento e limites

Ordenação e filtros operam sobre a fonte inteira no kernel Python, antes da paginação. A ordem é estável e mantém nulos no fim nas duas direções. Cópia, arquivos, INSERT, tabelas temporárias, estatísticas e gráficos recebem o mesmo `DataView`; os valores de apresentação não substituem os valores originais.

`result.column_values` consulta somente uma coluna da fonte original. Examina até 10.000 linhas, oferece até 50 valores não nulos distintos em ordem de ocorrência e limita a lista JSON de sugestões a 32 KiB. Valores de texto maiores que 1.000 caracteres são omitidos, sem gerar sugestões truncadas. A UI informa quando as sugestões são uma amostra; nenhum `unique()` de milhões de valores é enviado à WebView. As respostas antigas são descartadas ao fechar/trocar o painel ou trocar de resultado.

O painel usa o `ownerDocument` do dock, inclusive em janelas destacadas. Escape/clique externo fecham o painel, Enter aplica, os limites são validados antes do RPC e o posicionamento respeita o espaço da janela. A grade continua usando tiles/cache/fila limitados descritos em `TAURI_GRID_PERFORMANCE.md`.

## Restauração e compatibilidade

Filtros e ordem ficam em `table_views`, por variável da análise, e são restaurados no workspace interno/`.dpw` Tauri. Quando a variável é reexecutada com outras colunas, regras sem uma coluna válida são removidas; regras ainda válidas e a busca global são conservadas. Nomes duplicados são ambíguos no contrato baseado em nomes e não são restaurados como regras.

O PyQt6 atual grava `column_formats` e `charts` no `result_view_state`; seus filtros e ordem são temporários. A migração conserva esses campos públicos e acrescenta a persistência Tauri sem inventar filtros ausentes no arquivo legado.

Na restauração de variáveis, inteiros com nulos continuam exatos, inclusive acima de `2**53`, e os snapshots Polars usam Parquet nativo. A leitura continua aceitando o formato anterior. A correção e seus limites estão documentados em `TAURI_SESSION_PERSISTENCE.md`.

## Validação

Regressões de helpers cobrem alvos do cabeçalho, posicionamento, validação, precisão e reconciliação de colunas. Testes de runtime usam Pandas e Polars reais para intervalos, textos literais, aliases booleanos, nulos, ordenação estável, precisão, timezone/nanossegundos e sugestões limitadas. O smoke congelado verifica RPC de sugestões, filtro combinado, ordenação e exportação; também mede sugestões e páginas em uma fonte com 10 milhões de linhas.

Aceite Windows em 04/10/2026, com workspace e dados sintéticos separados: um DataFrame de um milhão de linhas retornou 333.334 linhas para o intervalo numérico inclusivo 2–10, e 166.667 ao combinar `false` em outra coluna. A seta alternou a ordem crescente/decrescente, enquanto o nome do cabeçalho selecionou a coluna sem alterar a ordem. Reabrir o aplicativo restaurou o intervalo e a ordem decrescente. Decimal com 18 casas e datas após 250 nulos retornaram as 25 linhas esperadas em cada filtro.

O dock destacado de 900×300 voltou a renderizar linhas; o popup abriu no documento dessa janela e conservou o intervalo. Fechar/acoplar o dock preservou o resultado e suas regras. A pintura invalida callbacks da janela anterior; o patch verificado do Dockview cancela o debounce de resize ao destruir a janela.

A integração passou por 530 testes frontend, 602 testes runtime e 35 testes Rust, TypeScript/Ruff e build Tauri de produção. Os três smokes do sidecar reconstruído passaram, incluindo uma restauração de inteiros nullable pandas e `UInt64` Polars acima do limite seguro de JavaScript.

No executável final, o bloco Python com o rótulo `Tipos após nulos` executou sem exigir um identificador como destino SQL. Fechar e reabrir conservou o filtro de um dia, suas 25 linhas e `9007199254740993` exato na coluna com nulos, sem reexecutar o bloco.
