# Validação de sintaxe por bloco

Cada bloco de código SQL/Python mostra o estado da validação e o primeiro problema com linha, coluna e mensagem. O resumo abre uma lista de diagnósticos; clicar em um problema expande o bloco e revela o trecho, mesmo se o editor ainda não foi montado. Erros são separados de avisos. O idioma segue a preferência português/inglês.

O validador analisa o bloco inteiro. Não executa código, não bloqueia a execução de uma seleção e não transforma o restante do bloco em código executável.

## Agendamento e interface

- Pausa de digitação de 450 ms; construção do contexto só depois dessa pausa.
- Dois pedidos simultâneos para o workspace, com prioridade para o bloco focado.
- Uma revisão pendente por bloco; alterações cancelam pedidos antigos por `diagnostic_id`. Respostas obsoletas não reaplicam erros.
- A validação pertence ao bloco, e não ao widget Monaco: também cobre blocos recolhidos e fora da tela.
- SQL usa a conexão/database/schema do bloco. Python compartilha um preâmbulo limitado e cacheado por sessão; alterações de declarações nos irmãos invalidam os diagnósticos dependentes.
- Mudanças de altura, layout, saída e status de execução conservam o contexto. Editar o conteúdo SQL ou Markdown/raw não invalida os irmãos Python; renomear um resultado SQL atualiza o nome disponível. Eventos de outra sessão não revalidam o notebook atual.
- Monaco recebe os mesmos marcadores exibidos no resumo, em posições UTF-16. Recriar o editor/dock conserva os diagnósticos; descartar um modelo limpa seu owner de marcadores.
- A lista renderiza até 20 problemas inicialmente; o usuário pode revelar mais. Falha, timeout ou análise parcial são mostrados explicitamente e não aparecem como "Sintaxe válida".

## Serviço local

`source/datapyn_runtime/diagnostic_jobs.py` mantém uma thread de diagnóstico independente do autocomplete e dos kernels de execução. A fila guarda no máximo 64 blocos/8 MiB de código pendente, substituindo imediatamente versões antigas. Fechar uma sessão invalida seus pedidos. O serviço usa snapshots disponíveis, sem disparar carregamento de schema ou trabalho no kernel.

Python usa AST, compilação sem execução e tabelas de símbolos. Detecta também erros de escopo de `return`, `break` e `await`; compreensões, parâmetros e variáveis locais não geram falsos avisos de nomes ausentes. Imports e declarações de outros blocos são tratados como contexto estático, sem importar módulos.

SQL usa o dialeto da conexão, preservando as posições do texto original, parâmetros e separadores `GO`. Reutiliza os ASTs para avisos de schema quando o snapshot é completo e as colunas foram carregadas. CTEs, subqueries, aliases e tabelas temporárias são resolvidos de forma conservadora. Não se consulta o banco para confirmar um aviso.

O envelope de código é limitado a 1 MiB. O analisador possui orçamento cooperativo de 200 ms e limites de complexidade: SQL até 500 instruções, 256 KiB por lote, 30 mil tokens e 100 níveis; Python até 100 mil nós AST. Comandos específicos de dialeto que o parser não reconhece e análises que atingem os limites apresentam **Validação parcial**. A consulta pode ser executada normalmente.

## Verificação

- `desktop/src/syntaxDiagnostics.test.ts`: debounce, contexto lazy, prioridade, concorrência, cancelamento, respostas atrasadas, mudança de linguagem/contexto, limites, falha/retry/timeout e descarte.
- `desktop/src/editorRegistry.test.ts`: revelar erro em editor montado/offscreen e limpar marcadores antes de descartar um modelo.
- `desktop/src/sessionCompletion.test.ts`: revisão estática e schema por sessão/conexão, cache/retenção e 300 blocos com mil leitores sem rescan.
- `runtime_tests/test_syntax_diagnostics.py`: sintaxe, Unicode, escopos, idiomas, parâmetros, dialetos e limites.
- `runtime_tests/test_sql_schema_diagnostics.py`: avisos com snapshots carregados, cache, orçamento e AST parseado uma única vez.
- `runtime_tests/test_diagnostic_jobs.py`: coalescing, cancelamento, isolamento de filas, atividade/flush e validação por stdio durante execução Python longa.

Medições locais, dependentes da máquina: Python com 10 mil linhas ~89 ms; SQL com 500 SELECTs ~11 ms sem schema e ~54 ms com schema; schema pequeno reutilizado ~0,22 ms. Mil substituições de revisões de 100 KB levaram ~2,77 ms no scheduler, mantendo apenas a primeira execução já ativa e a última revisão pendente.

Aceite Windows local em 2026-10-04 no executável recompilado, com perfil isolado e 18 blocos: mensagens claras SQL/Python com linha e coluna; correção de ambos os códigos removendo marcadores e mostrando "Sintaxe válida"; blocos válidos com compreensões/parâmetros sem falsos erros; diagnóstico do último bloco SQL ainda recolhido e fora da tela. Clicar nesse erro expandiu o bloco, montou o editor e selecionou `FROM` na posição correta, conservando os marcadores depois do foco. Na versão final, editar esse SQL manteve os irmãos Python válidos, sem reagendar suas análises.

Validação final: 409 testes frontend, 486 testes runtime, TypeScript e lint aprovados; executável Tauri release atualizado. Os três smokes do sidecar congelado passaram em série (runtime, paridade e persistência), incluindo gráficos, exportações e 10 milhões de linhas. Nas tentativas iniciais houve uma falha nativa intermitente durante PyInstaller (`0xc0000374`) e gráficos; cinco reproduções isoladas e a rodada completa final passaram sem alterações nesses módulos. A causa dessas falhas iniciais não foi localizada.
