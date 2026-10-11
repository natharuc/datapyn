# Conexões por túnel SSH

O DataPyn Tauri abre o túnel dentro do runtime com Paramiko, sem executar SSH no
terminal ou depender de um cliente instalado. A opção **Usar túnel SSH** começa
desativada. As conexões existentes continuam com o mesmo funcionamento.

## Cadastro

Os campos de servidor, porta, usuário, banco e TLS continuam sendo os **dados do
banco**. Ative o túnel e informe separadamente o servidor SSH, a porta (22 por
padrão), o usuário e a autenticação:

- **Senha:** a senha da conta SSH.
- **Chave privada:** selecione o arquivo local da chave. Informe a passphrase se
  a chave estiver criptografada. Chaves OpenSSH/PEM suportadas pelo Paramiko são
  carregadas diretamente; o DataPyn não usa `ssh-agent` nem procura outras chaves.

Ao salvar, a senha SSH e a passphrase ficam no armazenamento seguro do sistema,
em um registro separado da senha do banco. Elas não entram no catálogo JSON,
nos rascunhos, nos arquivos DPW, nos logs ou na exportação de configurações.
Editar deixando o segredo em branco mantém o valor salvo somente quando a
identidade SSH continua a mesma. Trocar servidor, porta, usuário, autenticação
ou caminho da chave exige informar novamente o segredo correspondente.
Desativar o SSH remove as credenciais SSH salvas. Se o armazenamento seguro não
estiver disponível, o cadastro falha em vez de gravar os segredos em texto aberto.

O arquivo da chave permanece no local selecionado. Somente seu caminho faz
parte da configuração; o conteúdo da chave não é copiado para o catálogo nem
para as exportações. Após importar em outra máquina, selecione uma chave local
e informe os segredos novamente. Uma duplicação no mesmo perfil preserva as
credenciais no armazenamento seguro. Clonar um perfil só leva as credenciais
quando a opção existente de incluir credenciais estiver marcada.

## PostgreSQL em containers na mesma VPS

O destino do banco é resolvido **a partir do servidor SSH**. `127.0.0.1` significa
a VPS, não o computador do usuário. Um nome Docker, como `postgres-stg`, só
funciona se o servidor SSH conseguir resolvê-lo e alcançá-lo; os nomes de serviço
de uma rede Docker normalmente não são resolvidos pelo sistema da VPS.

Para STG e PRD separados, cadastre duas conexões com os mesmos dados SSH e os
dados de banco de cada ambiente. Por exemplo, se os containers estiverem
publicados na interface de loopback da VPS:

| Campo | STG (exemplo) | PRD (exemplo) |
| --- | --- | --- |
| Tipo do banco | PostgreSQL | PostgreSQL |
| Servidor do banco | `127.0.0.1` | `127.0.0.1` |
| Porta do banco | `5433` | `5434` |
| Banco/usuário/senha | Dados de STG | Dados de PRD |
| Servidor SSH | Endereço da VPS | Mesmo endereço da VPS |
| Porta SSH | `22` | `22` |

As portas acima são ilustrativas. Use as portas realmente publicadas na VPS;
o DataPyn não altera containers, firewall ou configuração do servidor. A conta
SSH precisa permitir encaminhamento TCP até o destino configurado.

## Confiança no servidor

No primeiro teste ou conexão, o aplicativo apresenta servidor, porta, algoritmo
e fingerprint SHA-256 da chave pública. Compare a fingerprint com uma referência
confiável do administrador antes de confirmar. O DataPyn verifica a chave **antes
de enviar a autenticação SSH**. Confirmar salva o vínculo e repete a conexão;
cancelar encerra a tentativa.

A confiança é específica do perfil/workspace e fica em `ssh_known_hosts.json`,
com gravação atômica. Esse arquivo contém somente chaves públicas. Ele não entra
na exportação/importação nem é copiado ao clonar um perfil. Na mesma VPS, as
conexões STG e PRD podem compartilhar o vínculo de confiança do mesmo servidor
SSH e porta dentro do perfil.

Uma chave diferente de uma já conhecida bloqueia a conexão. O diálogo não
oferece sobrescrever essa chave. Uma troca legítima exige verificar a nova
fingerprint com o administrador e revisar o registro de confiança local antes
de tentar novamente. Falha SSH nunca provoca uma tentativa direta ao banco.

## Teste, TLS e encerramento

**Testar conexão** verifica a chave do servidor, autentica no SSH, abre o
encaminhamento e autentica no banco. O teste só informa sucesso se as duas
conexões funcionarem. O trabalho roda fora da interface, com cancelamento e
limite de tempo. Fechar o formulário cancela o teste que estiver ativo.

Cada conector usa uma porta local automática, reservada pelo sistema e
restrita a `127.0.0.1`. É possível abrir várias abas, STG e PRD simultaneamente
sem escolher portas locais nem compartilhar o contexto do banco. Desconectar,
fechar a sessão, cancelar o teste ou falhar fecha o encaminhamento. Uma queda
SSH também fecha o listener e os streams ativos.

O túnel não substitui nem enfraquece o TLS do banco:

- PostgreSQL conserva `sslmode`, CA e certificados do cliente. Usa `hostaddr`
  para transportar por loopback e conserva o hostname original para
  `verify-full`. Se esse hostname não corresponder ao certificado, a conexão
  falha. O formulário disponibiliza modo TLS e arquivo de CA.
- MySQL/MariaDB conservam o hostname original na validação TLS mesmo usando
  o socket local do túnel.
- SQL Server conserva a validação do nome com `HostNameInCertificate` no
  ODBC Driver 18. Combinações de driver que não conseguem preservar essa
  validação são recusadas.

SQLite é um arquivo local, e Databricks usa seu próprio fluxo HTTP/OAuth; essas
duas integrações não oferecem a opção de túnel SSH. O suporte TCP se aplica a
PostgreSQL, MySQL, MariaDB e SQL Server.

Copiar uma connection string gera os dados e as opções TLS do banco. Formatos
URI, Python, C# e ODBC não criam o túnel do DataPyn por conta própria e não
incluem credenciais SSH.

## Validação técnica

Os testes usam um servidor SSH Paramiko real e destinos locais controlados,
sem acesso a STG/PRD. Cobrem autenticação por senha/chave/passphrase, verificação
da chave antes da autenticação, mudança inesperada da chave, portas distintas,
destino resolvido pelo servidor, quedas, cancelamento e fechamento dos recursos.
Os drivers reais PostgreSQL e MySQL estabelecem TLS através do túnel e rejeitam
um hostname que não corresponde ao certificado. Um endpoint PostgreSQL local
controlado também valida autenticação, `SELECT 1` e limpeza após senha incorreta.
Os testes de catálogo, perfil e IPC verificam a separação dos segredos, edição,
duplicação, importação/exportação e confirmação/cancelamento no frontend.

Execute `uv run --frozen pytest -c runtime_tests/pytest.ini runtime_tests -q`
para os testes do runtime, `npm --prefix desktop test` para a lógica do frontend
e `npm --prefix desktop run test:ssh` para o formulário e a confirmação em
browser headless nos temas claro e escuro.

As referências do transporte e de TLS são a [documentação do Paramiko](https://docs.paramiko.org/en/stable/api/transport.html)
e a [documentação de conexão do PostgreSQL](https://www.postgresql.org/docs/current/libpq-connect.html).
