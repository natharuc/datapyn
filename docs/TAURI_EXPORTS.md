# Exportações na migração Tauri

A referência é o comportamento dos exportadores PyQt6, incluindo a escolha do dialeto pelo bloco em foco. A conversão dos dados permanece no kernel Python: React recebe páginas da grade, progresso ou o texto final de uma cópia, sem receber o DataFrame inteiro.

## Destinos e formatos

| Origem / destino | Recursos |
|---|---|
| Resultado ou variável → arquivo | CSV, TSV, TXT, XLSX, JSON, Parquet e SQL. Filtros, ordenação e seleção descontínua são aplicados antes da exportação; o limite visual da grade não limita o arquivo. |
| Resultado ou variável → clipboard | CSV com separador/decimal/cabeçalho, TSV/TXT, Excel como texto tabulado, JSON e SQL. Parquet exige arquivo. Texto limitado a 16 MiB, com erro explícito sugerindo arquivo. |
| Resultado ou variável → tabela | Perfil de conexão e banco de destino, schema/nome, modos falhar/acrescentar/substituir, tamanho dos lotes, progresso e cancelamento. O destino não troca a conexão padrão da análise. |
| Resultado ou variável → SQL | INSERT, CREATE TABLE e CREATE + INSERT; seis dialetos, agrupamento dos INSERTs, transação e GO para SQL Server. Prévia, clipboard, arquivo ou novo bloco SQL; gerar/inserir não executa o script. |
| Consulta SQL → arquivo | Executar o bloco ou seleção e baixar CSV/Parquet em lotes, incluindo múltiplos resultados. Diálogo CSV, última pasta, extensão correspondente ao formato e abertura da pasta após sucesso. Cancelamento pelo bloco. |
| Variáveis → Parquet público | Arquivo individual ou pasta de variáveis com `manifest.json` versão 2 compatível com o leitor PyQt6. Importação valida todos os arquivos antes de mudar o namespace. |
| Análise → script | Python, SQL e notebook; parâmetros locais e compartilhados no script Python, SQL via SQLAlchemy e URL de conexão externa. Atalho Ctrl+Shift+E mantido. |
| Gráfico / resultado rico → arquivo | Gráficos PNG/JPG/HTML/JSON; imagens Python PNG/JPG; HTML e JSON preservados pelos exportadores de artefatos existentes. |

CSV mantém os defaults importados do PyQt6, incluindo UTF-8 com BOM, Windows-1252/Latin-1, decimal e separador. XLSX usa escrita sequencial, mantém valores de precisão elevada como texto e impede que dados de texto sejam interpretados como fórmulas. JSON oferece orientação, indentação e registros por linha. Parquet oferece compressão configurável.

## Temporárias e contexto de conexão

SQL Server reconhece `#nome` e `##nome`; os demais dialetos usam a opção de tabela temporária. A temporária pertence à conexão física do kernel da análise. A conexão deve permanecer disponível para os próximos blocos que utilizem o mesmo perfil/banco/schema. Desconectar ou reiniciar o kernel encerra essa conexão e suas temporárias locais. Tabelas globais SQL Server seguem o ciclo de vida definido pelo servidor.

No Databricks, tabelas temporárias requerem Databricks SQL compatível ou Runtime 18.1+. A geração de transações também depende das capacidades do destino; conferir as restrições para DDL/temporárias antes de executar um script com transação. Referências oficiais: [temporárias](https://docs.databricks.com/aws/en/tables/temporary-tables), [BEGIN TRANSACTION](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-txn-begin).

Nomes de objetos são escapados por dialeto. Campos de tabela aceitam nomes qualificados e identificadores entre aspas; aspas permitem um ponto literal no nome. O Object Explorer oferece SELECT limitado, todas as colunas, COUNT, CREATE e DROP protegido + CREATE, além de copiar `tabela.coluna` e inserir WHERE/GROUP BY/ORDER BY.

## Gravação, progresso e limites

Arquivos são escritos em staging na mesma unidade e publicados após sucesso. Falha ou cancelamento preserva o arquivo anterior e limpa o arquivo incompleto. Pacotes Parquet publicam o manifest por último e recuperam os arquivos anteriores se a publicação falhar ou for cancelada cooperativamente. Encerramento forçado durante a publicação de uma pasta ainda não tem recuperação por journal. Exportações comuns usam identificador próprio e cancelamento cooperativo, preservando o kernel e suas variáveis; progresso é limitado para não saturar a interface.

A exportação para tabela usa transação quando suportada pelo driver. DDL e rollback dependem do banco, especialmente MySQL/MariaDB e Databricks: não há promessa de atomicidade universal de DROP/CREATE. A interface descreve explicitamente o modo substituir.

Conexões com temporárias ficam protegidas contra expiração por ociosidade e remoção automática do pool. O limite continua em oito conexões por análise; se todas estiverem retidas por temporárias, abrir outra exige desconectar uma delas. Metadados marcam temporárias para que autocomplete respeite o shadowing de nomes sem schema explícito.

Prévia SQL mostra até 64 mil caracteres, mas copiar/inserir utiliza o texto completo dentro do limite de 16 MiB. Para scripts maiores, salvar arquivo usa o escritor sequencial. XLSX respeita os limites de linhas e colunas do formato. Texto/Excel/JSON copiados diretamente pela grade têm teto de 200 mil células; SQL pela grade usa o kernel e limite de 16 MiB sem teto de células. Exportar por arquivo atende resultados maiores.

## Aceite

Testes cobrem formatos/dialetos, tipos especiais, nomes escapados, filtros/seleção, progresso/cancelamento e preservação de destino. SQLite permite verificar de ponta a ponta a consulta de uma temporária em execução seguinte e o isolamento entre conexões. Os drivers de SQL Server, PostgreSQL, MySQL/MariaDB e Databricks exigem aceite em servidores reais; testes de contratos e geração SQL não substituem esse aceite.

As configurações públicas PyQt6 continuam com o contrato de importação/exportação existente. Pacotes de variáveis públicos são separados dos snapshots privados usados na restauração automática de sessões.

Rodada de validação: 303 testes de frontend, 380 de runtime e 16 de Rust aprovados; TypeScript, Ruff e verificação de diff aprovados. Build release com sidecar congelado passou nos três smokes de execução, paridade e persistência. O smoke de paridade também executa o SQL gerado, consulta a temporária no bloco seguinte, verifica JPEG real e faz round-trip de pacote público.

No executável Windows final, em workspace isolado, foram verificados CREATE + INSERT com prévia e inserção/foco sem execução automática, tabela temporária consultada em outro bloco, download SQL para CSV e exportação de quatro variáveis pandas/Polars. Os arquivos foram lidos novamente para confirmar manifest v2, dimensões, Unicode e os defaults CSV importados (Windows-1252, decimal vírgula e sem cabeçalho). A cópia CSV para clipboard também passou na interface em desenvolvimento.

## Medição local

Amostra pontual de 100 mil linhas × três colunas (int64, texto Unicode e float64), runtime fonte em Windows e pasta temporária local, nesta rodada. Os números não incluem diálogo, IPC Tauri ou servidor remoto e não representam percentis de produção.

| Destino | Tempo | Tamanho |
|---|---:|---:|
| CSV | 68 ms | 1,89 MB |
| JSON | 553 ms | 4,69 MB |
| Parquet | 32 ms | 606 KB |
| SQL INSERT, lotes de 1000, SQLite | 182 ms | 2,49 MB |
| XLSX | 2688 ms | 1,42 MB |
| Tabela temporária SQLite, lotes de 1000 | 147 ms | — |
