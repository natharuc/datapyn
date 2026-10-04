# Gráficos configuráveis no desktop Tauri

O painel usa Plotly em JavaScript na WebView do Tauri. O módulo `plotly.js-basic-dist-min` é carregado quando um gráfico precisa ser desenhado; a fonte inteira permanece no kernel Python. O frontend recebe uma figura com pontos limitados, configuração e métricas de agregação.

## Configuração e fontes

São mantidos os cinco tipos do PyQt6: barras, linhas, área, dispersão e pizza. As cinco agregações legadas são soma, média, contagem, mínimo e máximo; mediana é uma extensão do Tauri. Pizza utiliza a primeira série Y e somente valores positivos. O agrupamento por outra coluna cria séries quando existe uma única Y, como no legado; com várias Y o painel informa essa restrição.

O padrão para X é a primeira coluna não numérica, ou o índice quando todas são numéricas. Y começa pela primeira coluna numérica diferente de X, com fallback para outra coluna disponível. Colunas salvas que desapareceram não são substituídas silenciosamente: o painel pede revisão da configuração. Nomes duplicados são rejeitados porque o contrato identifica colunas pelo nome.

O seletor de DataFrame define a variável de origem. A busca de séries mostra até 200 colunas por vez e permite localizar outras sem montar milhares de controles simultaneamente. Até 50 séries Y podem ser selecionadas.

| Fonte | Comportamento |
|---|---|
| Dados filtrados | Aplica filtros e ordem da grade da variável de origem; não inclui seleção de células automaticamente |
| Todos os dados | Usa a fonte completa, sem filtros, ordem ou seleção da grade |
| Somente seleção | Captura o `DataView` com filtros, ordem e faixas/retângulos selecionados; sua configuração acompanha o gráfico |

A seleção usa as mesmas regras de células disjuntas da grade e das exportações. O backend projeta X, Y e a coluna de agrupamento antes de materializar as linhas escolhidas ou converter uma fonte Polars para Pandas. As outras colunas da tabela não são copiadas para preparar o gráfico.

Os controles preservam nulos como zero, ignoram linhas com nulos nos campos necessários ou mantêm valores ausentes; permitem normalização percentual, barras agrupadas/empilhadas/percentuais, barras horizontais, ordem X crescente e ordem pela primeira Y decrescente. A opção Original conserva a política de ordenação da agregação legada; não promete manter a ordem bruta das linhas após agrupá-las.

As cinco paletas (`default`, `categorical`, `teal`, `warm`, `ocean`) e cores personalizadas continuam disponíveis. Títulos, nomes dos eixos, fundo, texto, rótulos, grade, eixos, legenda, linhas, marcadores, estilo do traço, espessura, opacidade e casas decimais são configuráveis. Cores explícitas prevalecem sobre o tema claro/escuro; **Usar cores do tema** remove esses overrides.

O Tauri acrescenta família e tamanho da fonte, tamanho do título e dos ticks, modo de inspeção e dimensões/escala da imagem exportada. Os defaults tipográficos continuam sendo a família Segoe UI/Roboto/Helvetica/Arial com fallback Ubuntu local, texto 12 px, título 16 px e ticks 11 px. O backend limita texto a 8–24 px, título a 10–32 px e ticks a 8–20 px. A escolha de uma família depende das fontes disponíveis no sistema; não instala fontes.

## Atualização e ciclo de vida

O painel oferece configuração lateral recolhível, seções expansíveis, atualização manual, prévia automática, restauração de zoom, duplicação, reordenação das abas e ordem explícita das séries Y. **Reverter alterações** recupera a configuração do início da edição; **Aplicar** encerra o painel de configuração. As edições são persistidas na configuração da análise. A prévia automática espera 420 ms e mantém uma requisição ativa e somente a última alteração pendente. Respostas e erros obsoletos são invalidados quando a configuração, fonte, versão do resultado ou disponibilidade do painel muda.

Alterar apenas a aparência pode reutilizar o snapshot já mostrado, sem reler o DataFrame nem repetir a agregação. Alterações de fonte, eixos, agrupamento, agregação, nulos, ordem ou normalização preparam uma nova figura. A tela informa quando a configuração mudou e desabilita exportação até existir uma prévia correspondente.

`ChartCanvas` serializa desenho, resize, reset de zoom e exportação. O controlador usa o `ownerDocument` e a janela do dock para observar dimensões e agendar pintura; passa largura e altura medidas explicitamente ao Plotly, inclusive em janelas destacadas. Ao destacar/acoplar o dock, recria o nó Plotly no documento atual; ignora callbacks da janela anterior. Ao fechar, espera o desenho/exportação em andamento antes de purgar o nó, rejeita operações pendentes e remove observers/listeners. O `uirevision` mantém zoom para alterações de estilo e o reinicia quando a fonte ou os eixos mudam; o botão de restauração também redefine o zoom.

Em um canvas abaixo de 260 px de altura, a apresentação reduz as margens superior/inferior e posiciona a legenda dentro do gráfico. Ao expandir, restaura as margens e a legenda originais sem redefinir os eixos. Esse ajuste não modifica o snapshot. A exportação gera uma figura independente nas dimensões pedidas, conserva o zoom atual e usa as margens/legenda completas quando a imagem tem altura suficiente. A captura aceita até 40 milhões de pixels, considerando a escala, em acordo com o backend.

## Agregação, precisão e limites

Os limites de cardinalidade são verificados antes do agrupamento/pivot. Eles são orçamentos de preparação, não uma amostra silenciosa da fonte:

| Limite | Valor |
|---|---:|
| Séries Y ou valores distintos da coluna de agrupamento | 50 |
| Categorias X antes de limitar a figura | 100.000 |
| Categorias X × séries de um pivot | 1.000.000 células |
| Pontos exibidos em barras | 120 |
| Pontos exibidos em linhas, área ou dispersão | 500 |
| Pontos exibidos em pizza | 24 |
| Snapshots retidos por kernel/sessão | Até 8 |
| Bytes JSON de snapshots retidos por kernel/sessão | 16 MiB no total |

Não existe limite de 1.000 pontos nesta implementação: 1.000 caracteres é o limite de categoria original enviada ao hover e de nome de série. Valores numéricos exatos enviados ao hover aceitam até 1.024 caracteres e devem caber em geometria numérica finita. Uma figura individual que excede o orçamento de 16 MiB é rejeitada; snapshots mais antigos são removidos para manter o orçamento total.

A fonte escolhida é agregada antes do limite de pontos. `source_rows`, `aggregated_point_count`, `point_count`, `series_count`, `max_points` e `truncated_points` explicam a quantidade de dados; `bounded` só é verdadeiro quando houve truncamento. Ter exatamente o limite de pontos não é informado como truncamento.

Pandas e Polars conservam inteiros grandes e Decimal durante a agregação, usando aritmética exata quando necessária. Divisões em média/normalização usam precisão Decimal de 80 dígitos; frações recorrentes continuam sendo aproximações. Plotly desenha coordenadas em ponto flutuante; valores agregados são enviados como strings separadas em `customdata` e aparecem no hover sem a conversão geométrica para float. `geometry_approximate` indica Decimal ou inteiros além da precisão segura de JavaScript; o rodapé informa quando a geometria é aproximada. O desenho não substitui os valores originais da tabela nem oferece precisão geométrica arbitrária.

## Exportação da prévia exibida

Cada resposta de `result.chart` inclui um `chart_id` opaco, pertencente ao kernel da sessão. O snapshot serializado contém figura, configuração e métricas imutáveis. Exportar esse ID não relê a variável: mudar/remover a fonte Python depois da prévia não altera o arquivo exportado.

| Formato | Saída |
|---|---|
| HTML | Plotly interativo autocontido, com assets locais embutidos, sem CDN |
| JSON | Figura, configuração e métricas do snapshot |
| PNG | Imagem gerada pelo renderer JavaScript da figura exibida |
| JPG/JPEG | Imagem PNG do renderer JavaScript convertida para RGB sobre o fundo configurado |

O painel captura os bytes da figura antes de abrir o diálogo nativo de destino e envia `chart_id` e, para imagens, esses bytes. Mudanças na fonte enquanto o diálogo está aberto não combinam uma imagem nova com uma configuração antiga. As gravações são atômicas. Operações MCP sem canvas podem usar o renderer Agg Qt-free, cujo nome aparece em `renderer`; ele produz uma representação estática e não é o renderer JavaScript. O RPC ainda aceita exportar diretamente uma variável/configuração quando não foi fornecido um ID, preparando nesse caso uma nova figura.

Título e legenda ocupam bandas separadas no topo da figura completa, inclusive nas imagens exportadas. Em docks baixos a legenda é interna.

Os snapshots são temporários. Reabrir o aplicativo, reiniciar/fechar o kernel ou exceder os oito snapshots/16 MiB pode invalidar um ID; a resposta pede gerar a prévia novamente. Eles não são gravados no `.dpw` nem no cache Parquet. IDs de outra sessão são rejeitados.

## Persistência e compatibilidade PyQt6

Configurações e fontes pertencem à análise; a seleção Tauri é `extras.desktop_chart_id`, com `null` para Dados. O codec conserva IDs modernos, configurações e extensões desconhecidas ao salvar/reabrir. Uma importação Qt cria IDs para os configs legados e converte `result_view_state.charts.active_index` em seleção moderna.

O índice Qt é zero-based na lista de gráficos, sem offset pelas abas de dados. O legado guarda o último gráfico selecionado e não representa Dados ativo; o campo moderno explícito conserva essa distinção. Ao exportar, o ID selecionado é convertido de volta para `active_index`. `title` e `source_label` seguem o título e a variável salvos; `grouped` é projetado como `none` para o leitor Qt, sem alterar o config moderno.

Os 33 campos legados são conservados: `type`, `title`, `horizontal`, `x_column`, `x_label`, `y_columns`, `y_label`, `aggregation`, `group_by`, `stacking`, `normalize`, `nulls`, `sort`, `palette`, `custom_colors`, `text_color`, `label_color`, `background_color`, `grid_color`, `axis_color`, `show_grid`, `show_axis_line`, `show_line`, `show_markers`, `line_style`, `line_width`, `marker_size`, `bar_opacity`, `area_opacity`, `show_legend`, `show_data_labels`, `label_decimals` e `source_label`.

Mediana, escolha de fonte completa/filtrada/seleção, tipografia configurável e parâmetros de imagem são extensões Tauri. O normalizador PyQt6 não implementa mediana e usa soma se receber esse valor. As extensões permanecem no documento moderno, mas abrir e regravar pelo PyQt6 não garante aplicá-las nem retê-las. O painel resolve a variável canônica uma vez por revisão do namespace, com consultas coalescidas e metadata em cache. Isso também cobre uma redefinição de DataFrame cujo último valor do bloco é escalar e não cria uma nova aba de resultados. A preparação usa `variable_name`; liberar/expirar o handle da inspeção não impede atualizar o gráfico. Trocas de fonte descartam respostas antigas após outra escolha ou desmontagem.

A configuração não contém o DataFrame: para renderizar após reabrir, sua variável precisa ser executada ou restaurada pelo cache Parquet opt-in. A inspeção aguarda `ensureSession` concluir a criação/restauração do kernel, inclusive ao alternar análises; apresenta o estado de restauração durante essa espera.

## Contratos e verificação

- `result.chart`: `session_id`, `result_id` ou `variable_name`, `config` e `DataView` opcional; responde com figura, métricas e `chart_id`. Com ID e configuração de dados compatível, reaplica estilo sobre o snapshot.
- `result.chart_export`: `session_id`, `chart_id`, `path`, `format` e `image_data` opcional; responde com caminho, bytes, renderer, ID e métricas. Sem ID, aceita fonte/configuração para preparar a figura.
- `datapyn_chart`: list/create/edit/get/delete/export integra configurações salvas ao contexto da análise; o ID do gráfico salvo é distinto do ID temporário da prévia.

Os testes de `chartModel`, `plotlyLoader` e `plotlyCanvasController` cobrem defaults, identidade por sessão, fontes, coalescimento, respostas obsoletas, lazy loading, desenho/exportação serializados, limites de imagem, zoom e troca de documento. `workspace.test.ts` cobre índices Qt, seleção Dados, IDs obsoletos, extensões e save/reopen JSON. Os testes runtime `test_chart_runtime.py` e `test_chart_artifacts.py` cobrem Pandas/Polars, precisão, limites antes do pivot, fonte larga de um milhão de linhas, exportação após mutação, cache de snapshots, HTML offline, imagens e atomicidade.

Verificação da integração em 04/10/2026:

- 581 testes de frontend, TypeScript e Ruff passaram. A suíte runtime completa passou com 672 testes, incluindo cinco regressões para separar título e legenda.
- O smoke fonte passou com exportação HTML/JSON/PNG/JPEG, mutação da fonte após a prévia, restyle do snapshot e consulta de 10 milhões de linhas.
- O smoke congelado também passou: um gráfico de 10 milhões de linhas gerou 10 pontos em ~433 ms e uma resposta de 9.572 bytes; restyle levou ~13 ms. A regressão adicional confirmou redefinição de DataFrame com saída escalar e atualização por variável após liberar o handle da inspeção. São medições locais sintéticas, sem baseline Qt controlado.
- No desktop foi verificada restauração de uma fonte Polars de 10 milhões de linhas, cinco tipos, duas séries, sua reordenação, fonte Consolas 18 px e isolamento entre duas análises. O dock baixo apresentou os pontos com legenda interna; a janela destacada maximizada passou a preencher a área disponível, e o gráfico voltou ao dock ao fechar a janela. Um PNG de 1.400×850 foi gravado a partir do dock compacto, usando o canvas JavaScript e conservando margens completas, separação título/legenda e tipografia.
- O pacote passou pelos três smokes de execução, paridade e persistência, e o Tauri compilou em modo release. Um ensaio congelado anterior apresentou `ValueError: Single '}' encountered in format string` ao exportar. Ensaios posteriores fonte/congelado e mais dez processos separados, totalizando 50 exportações, passaram; a causa ainda não foi confirmada. Não existe retry silencioso nem uma correção atribuída a essa falha.
