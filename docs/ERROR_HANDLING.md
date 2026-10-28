# Exibição dos erros

A execução e as respostas do runtime usam `error_info` para separar categoria,
título, mensagem e detalhes técnicos. O campo `error` continua disponível como
resumo em texto para consumidores anteriores do protocolo.

O painel Saída mostra uma entrada por falha de execução, com o motivo principal.
O cadastro de conexão, o aviso da aba e os resultados de comandos usam a mesma
apresentação. Detalhes técnicos ficam recolhidos e podem ser expandidos ou
copiados. Mensagens de execuções diferentes não são concatenadas; a saída
produzida pelo código Python continua disponível.

## Categorias

- Permissão e autenticação: falta de acesso ao banco/objeto ou falha de login.
- Objeto inexistente e sintaxe: erro na consulta, sem substituir a conexão.
- Tempo limite e rede: distinguem uma operação lenta de transporte perdido.
- Restrição e dados: integridade, duplicidade, conversão e valores inválidos.
- Arquivo e Python: falhas locais, com tipo da exceção e linha quando disponível.
- Interno: causa ainda não reconhecida, preservando uma mensagem útil.

As mensagens do provedor são extraídas da exceção original. Prefixos de driver,
wrappers e repetições são removidos. Acesso negado do SQL Server, incluindo
`08004/4060`, não é tratado como perda de transporte. Erros antigos guardados em
`__context__` não substituem a causa atual.

## Diagnóstico e privacidade

Os detalhes locais incluem tipo da exceção, mensagem do provedor e frames com
arquivo, linha e função. Não incluem linhas-fonte, variáveis locais nem os
anexos de SQL e parâmetros do SQLAlchemy. Credenciais identificáveis e URLs de
conexão são removidas. Mensagem e detalhes têm limites de tamanho.

Logs internos de bibliotecas não são repetidos na saída de uma execução quando
já existe o erro estruturado. O código do usuário pode continuar escrevendo em
stdout, stderr e seus próprios loggers. Handlers de arquivo e monitoramento não
são desativados por essa apresentação.

`error_info` não é salvo em documentos exportados, duplicações ou recuperação de
workspaces. Os detalhes não são enviados ao coletor de telemetria; continua
valendo a lista de campos permitidos em [TELEMETRY.md](TELEMETRY.md).

## Validação

Os testes cobrem exceções dos provedores, a passagem pelo host Rust, isolamento
entre execuções, o pool e o kernel com SQLAlchemy real e transporte ODBC
controlado. A interface é exercitada em português e inglês, nos temas claro e
escuro, incluindo expansão e cópia dos detalhes.
