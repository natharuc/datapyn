# Recuperar abas fechadas

Use **Ctrl+Shift+T** (ou **Cmd+Shift+T** no macOS), **Mais → Reabrir aba
fechada** ou a mesma opção no menu das abas. Cada acionamento recupera a última
aba fechada, ativa-a e devolve o foco ao editor. O atalho pode ser alterado nas
configurações. Atualizar o schema passa a usar **Ctrl+Alt+R**; a configuração
antiga com o atalho padrão é migrada automaticamente.

O histórico inclui fechamentos pelo X, atalho, menu e fechamento múltiplo. A
confirmação de salvar alterações continua funcionando: cancelar não fecha a aba
nem cria uma entrada no histórico. Escolher descartar mantém uma cópia temporária
do texto fechado para permitir sua recuperação durante a mesma execução do app.

São recuperados código e parâmetros dos blocos, título, arquivo associado,
alterações ainda não salvas, banco/schema, conexão salva, configurações de
gráficos, alturas, blocos recolhidos/maximizados, foco, seleção e rolagem do
editor. O conteúdo vem do momento do fechamento, mesmo que o arquivo original
tenha sido alterado ou removido depois. A preferência de maximizar o primeiro
bloco de abas novas não sobrescreve o layout recuperado.

A sessão recebe identificadores novos e reconecta a conexão cadastrada pelo
fluxo normal de autenticação. Conexões avulsas precisam ser reconectadas; o
histórico não retém suas senhas. Código SQL/Python nunca é repetido para
reconstituir a aba. Resultados, DataFrames, imagens, saída, transações e tabelas
temporárias da conexão anterior não são restaurados. A execução periódica fica
desligada. Fechar uma aba continua encerrando seu kernel e liberando seus dados.

Esse histórico existe somente em memória: não faz parte do `.dpw`, dos arquivos
de recuperação, da exportação de configurações nem da restauração ao iniciar o
aplicativo. Ele é apagado ao encerrar o app ou trocar/restaurar o workspace,
mantendo os contextos separados. A restauração de abas que continuaram abertas
ao sair permanece independente.

Para limitar o consumo de memória, são mantidas até **50 abas**, com orçamento de
**32 MiB** de texto/configurações serializados em UTF-16. Entradas antigas são
removidas primeiro; a mais recente sempre é mantida, mesmo quando um único
script ultrapassa esse orçamento. Dados de grids e kernels não entram nesse
cálculo porque não são guardados no histórico.
