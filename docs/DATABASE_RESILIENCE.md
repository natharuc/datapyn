# Recuperação das conexões

A versão Tauri 1.0.13 recupera conexões na própria aba/bloco, mantendo o kernel
Python, códigos, parâmetros, DataFrames e resultados que já estavam carregados.
São cobertos SQL Server (ODBC/TDS e métodos de autenticação existentes),
PostgreSQL, MySQL, MariaDB, Databricks, SQLite e conexões com túnel SSH.

## Comportamento

- Flags locais do driver identificam sockets encerrados. Após 15 segundos sem
  validar a conexão, um probe leve é realizado antes do próximo comando, quando
  o estado transacional permite. Autocomplete não faz ping a cada tecla.
- Uma conexão comprovadamente perdida é substituída preservando seu destino,
  banco/catalog, schema, `search_path`, modo transacional e proprietário. Blocos
  com conexões físicas independentes continuam separados, mesmo quando usam o
  mesmo cadastro e banco.
- São feitas até duas tentativas de conexão para falhas classificadas de
  transporte, com intervalo de 200 ms e cooldown de 3 segundos na recuperação.
  O cadastro inicial pode receber novas tentativas limitadas pela interface.
  Erros SQL, cancelamento, autenticação, certificado e confirmação de identidade
  SSH não provocam repetição automática de autenticação.
- `Reconectando…` aparece no bloco afetado. Em caso de falha persistente, há um
  botão para tentar novamente na mesma aba. Os demais blocos e abas continuam
  disponíveis conforme suas próprias conexões e execuções.
- O Object Explorer e os metadados do autocomplete são invalidados quando a
  conexão física muda. As sugestões Python continuam refletindo os DataFrames,
  inclusive após um bloco Python alterar colunas e terminar com erro.
- Python que trabalha localmente não precisa reconectar o banco. O helper
  gerenciado `sql()` e engines gerenciadas recebem a política de recuperação
  quando acessam o banco.

## Comandos já enviados e estado de sessão

Reconectar **não repete SQL ou Python submetido**. Uma queda durante execução,
leitura de resultados ou commit pode impedir que o cliente saiba o resultado
no servidor. A execução continua marcada como falha e a repetição periódica é
interrompida; o usuário deve conferir o resultado antes de reenviar o comando.

Transações manuais pendentes/desconhecidas, commit de resultado indeterminado,
temporárias conhecidas e SQLite em memória exigem confirmação antes de abrir
uma conexão física nova. A confirmação é vinculada ao contexto apresentado.
Mudar bloco, destino ou recuperação exige uma nova revisão.

Transações, tabelas temporárias, variáveis SQL e outros objetos exclusivos da
sessão física anterior não podem ser reconstruídos automaticamente. A interface
informa a perda desse estado; código e DataFrames Python permanecem disponíveis.
Em SQLite em memória, a confirmação também reconhece a perda do banco em memória.

## Implementação e validação

`ConnectionLostError` leva uma classificação estruturada entre driver, kernel,
supervisor e interface. `ConnectorPool` recupera a conexão física afetada;
`connection.recover` permite a revisão e recuperação explícita. O evento
`connection.recovery` identifica bloco, escopo, modo e geração da recuperação.
Eventos antigos, respostas após fechamento e confirmações de contexto antigo
são recusados.

Os testes usam sockets/servidores de protocolo locais, SSH local, SQLite e
drivers simulados. Cobrem falhas em execute/fetch/nextset/commit, cancelamento,
autenticação, aliases de engines Python, contexto após `USE`, separação entre
blocos, preservação do namespace e ausência de repetição de comandos. O teste
de interface com App/Monaco reais está em `npm --prefix desktop run
test:connection-recovery`.
