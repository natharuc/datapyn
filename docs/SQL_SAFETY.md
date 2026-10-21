# Confirmação de comandos SQL destrutivos

**Configurações → Geral → Confirmar comandos SQL destrutivos** fica habilitada
por padrão. A opção vale para todas as sessões e perfis. Para executar essas
ações sem confirmação, desmarque-a e salve as configurações.

Antes da execução, o DataPyn mostra o bloco, a conexão, o banco/schema e os
comandos identificados. `DELETE` e `UPDATE` pedem confirmação mesmo com `WHERE`;
quando não há filtro no próprio comando, o aviso destaca **todas as linhas**.
`TRUNCATE`, remoção/substituição de objetos, `MERGE`, alterações de estrutura e
chamadas de código SQL que não podem ser inspecionadas também exigem revisão.
Consultas de leitura, inserções comuns e criação de objetos novos não abrem
esse aviso.

- Havendo seleção no editor, somente o trecho selecionado é revisado e executado.
- Executar todos revisa cada bloco antes de executá-lo. Cancelar interrompe a fila.
- Execuções periódicas e exportação direta da consulta para arquivo usam a mesma
  proteção. Não existe aprovação permanente para um bloco.
- Em **Para tabela**, escolher **Substituir** também exige confirmação antes de
  remover a tabela existente. Acrescentar dados mantém o fluxo normal.
- Fechar o aviso, pressionar Escape, cancelar a execução ou trocar de perfil não
  autoriza a operação. Os resultados anteriores são preservados ao cancelar.

A confirmação corresponde ao código, aos parâmetros e ao destino apresentados.
Ela é de uso único e expira em cinco minutos. Se o contexto mudar enquanto o
aviso estiver aberto, execute novamente para revisar o destino atual. O runtime
recusa comandos destrutivos sem essa autorização; a proteção não depende apenas
do botão da interface. A Pynia não pode aprovar seus próprios comandos destrutivos.

Em Python, chamadas SQL literais aos executores gerenciados e substituições via
`to_sql` são revisadas. Consultas dinâmicas podem exigir confirmação por não ser
possível determinar seu conteúdo antecipadamente. SQL destrutivo indireto pelo
helper `sql()` ou por engines SQLAlchemy é bloqueado quando não foi autorizado.
Python continua sendo código com acesso local: esta opção não cria um sandbox
para drivers externos, processos ou conexões criadas fora do DataPyn, nem prevê
efeitos de triggers no servidor.

A opção é persistida no estado global `sql_safety_settings.json` e acompanha a
transferência de configurações. Configurações antigas sem esse campo preservam
a opção atual; uma instalação nova inicia com a confirmação habilitada. O canal
PyQt6 histórico não executa esta política.

Os testes usam SQL estático, bancos SQLite temporários e fixtures de protocolo;
não precisam de credenciais nem de acesso a bancos de aplicação.
