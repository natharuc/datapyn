# Transações nas execuções SQL

## Comportamento confirmado

O executor SQL Server anterior usava o padrão `autocommit=False` do pyodbc,
obtinha uma conexão bruta do pool e chamava `commit()` após os lotes, inclusive
na exportação direta da consulta para arquivo. O SQLAlchemy também pode fazer
`rollback()` ao devolver uma conexão ao pool. O adaptador TDS de NTLM/Kerberos
usava o mesmo modo transacional.

Esse caminho pode explicar a proteção `IF @@TRANCOUNT <> 0` falhar antes do
corpo de um script que gerencia suas próprias transações. A mensagem, sozinha,
não distingue esse caminho de SQL anterior ou `SET IMPLICIT_TRANSACTIONS ON`
naquela sessão. Nenhum script de criação/backfill do MDE foi executado para a
investigação.

## Opções

- **Configurações → Geral → Transações automáticas:** habilitada por padrão.
  Desmarcar aplica a desativação a todas as execuções gerenciadas pelo DataPyn,
  inclusive em outros perfis. A opção fica no arquivo de estado global
  `transaction_settings.json`, separado dos documentos.
- **Ações do bloco → Desativar transações automáticas neste bloco:** desmarcada
  por padrão; permite desativar apenas um bloco quando a opção global continua
  habilitada. É salva em DPW e na restauração de sessões. Duplicar copia a opção,
  mas cria outra conexão física: não copia uma transação aberta.

A desativação global prevalece. Configurações e blocos antigos que não possuem
as opções continuam com o comportamento anterior. A transferência de
configurações mantém os formatos Tauri/PyQt e acrescenta a opção geral; a versão
PyQt histórica não executa esta nova política.

## Quando as transações automáticas estão desativadas

O driver recebe autocommit antes da primeira instrução. O DataPyn não envia
`BEGIN`, `COMMIT` ou `ROLLBACK` para envolver a execução, nem devolve a conexão
do bloco ao pool ao terminar a consulta. O próprio SQL pode controlar uma
transação entre instruções, lotes `GO` e execuções sucessivas do mesmo bloco:

```sql
BEGIN TRANSACTION;
-- comandos SQL do usuário
COMMIT;
```

Sem um `BEGIN` explícito, os comandos seguem o autocommit nativo do banco;
desativar a opção não elimina as transações internas usadas pelo servidor.
SQL Server também permite conferir `SELECT @@TRANCOUNT, XACT_STATE()` no
mesmo bloco. O cabeçalho indica uma transação aberta ou estado desconhecido.

Cada bloco nesse modo usa uma conexão própria. Metadados e outros blocos não
podem confirmar ou desfazer seu trabalho. Tabelas temporárias e transações
pertencem a essa conexão: use o mesmo bloco para acessá-las. **Para tabela** e
a exportação direta para arquivo mantêm a conexão do bloco correspondente.
O autocomplete separa os metadados por modo de transação e recarrega ao mudar
a opção, evitando sugerir temporárias de outra conexão física.

Alterar a configuração só grava a opção para próximas execuções. Se uma
transação estiver pendente, a próxima tentativa de trocar o modo ou a conexão
do bloco é recusada, sem confirmar, desfazer ou fechar a conexão existente.
Mantenha o modo desativado e execute `COMMIT` ou `ROLLBACK` no mesmo bloco antes
de trocar. Estado desconhecido também impede descartar automaticamente a
conexão. O fechamento por ociosidade e a expulsão do cache preservam essas
conexões; se não houver espaço seguro no cache, a nova conexão é recusada.
Finalize transações antes de editar o cadastro da conexão ou seu túnel SSH.
O sistema não substitui credenciais ou transportes de uma sessão pendente
pelos novos dados do cadastro.

Fechar/desconectar uma sessão, encerrar o aplicativo, perder a rede ou cancelar
forçadamente um kernel continua sujeito às regras de desconexão do banco. A
restauração de sessões recupera código e opções, não conexões físicas ou
transações pendentes.

## Bancos e código Python

SQL Server ODBC/TDS, PostgreSQL, MySQL/MariaDB e SQLite recebem o modo do
driver antes de executar. Comandos que mudam contexto não fazem rollback
automático nesse modo. Uma transação PostgreSQL em erro permanece nesse estado
até o SQL do usuário resolver com `ROLLBACK`.

MySQL/MariaDB podem confirmar DDL implicitamente por regra do servidor.
Databricks continua executando normalmente, mas o warehouse/SDK gerencia suas
transações: esta opção não acrescenta suporte a `BEGIN`/`ROLLBACK` nem oferece
estado transacional manual onde o serviço não o fornece.

O `db_engine` disponibilizado ao Python também é criado com autocommit quando
a opção está desativada. Bibliotecas usadas pelo próprio código, ou conexões
que o usuário cria independentemente, continuam com suas próprias regras de
transação. Os efeitos de contextos como `engine.begin()` e `pandas.to_sql()` não
equivalem automaticamente a um `BEGIN` SQL nesse modo. Para controlar o SQL
pela conexão retida do bloco, use o executor SQL do DataPyn ou o helper
`sql(query, parameters=None)` dentro do bloco Python. SELECTs retornam
dataframes; comandos sem resultado retornam `None` e informam linhas afetadas.
O helper usa o modo capturado da execução e rejeita aliases guardados de uma
execução que já terminou. Uma variável ou função do usuário já chamada `sql`
continua preservada; o helper só é instalado quando esse nome está disponível.

## Validação isolada

Os testes cobrem opções antigas/novas, persistência e transferência, precedência
global, filas, isolamento entre blocos, metadados, transações explícitas,
temporárias, streaming, erros e cancelamento. SQLite usa arquivos temporários;
SQL Server usa fixtures ODBC, o ODBC Driver 18 real quando instalado e um
endpoint TDS/TLS local de teste. Esse endpoint não é uma instância SQL Server.
Não há acesso a bancos de aplicação nem publicação automática de release nesta
mudança.

Referências: [transações ODBC e troca de autocommit](https://learn.microsoft.com/en-us/sql/relational-databases/native-client/odbc/performing-transactions-in-odbc),
[padrão pyodbc](https://github.com/mkleehammer/pyodbc/blob/master/src/pyodbc.pyi),
[rollback ao devolver conexões SQLAlchemy](https://docs.sqlalchemy.org/en/20/core/pooling.html#reset-on-return).
