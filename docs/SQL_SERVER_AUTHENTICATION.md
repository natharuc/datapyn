# Autenticação SQL Server

O DataPyn oferece métodos separados de autenticação. Trocar de método nunca
faz o programa tentar outro protocolo silenciosamente.

| Método | Sistema | Credenciais |
| --- | --- | --- |
| SQL Server | Windows, Linux, macOS | Login e senha cadastrados no SQL Server |
| Windows integrada | Windows | Identidade da sessão Windows; sem usuário/senha adicionais |
| NTLM | Windows, Linux, macOS | `DOMÍNIO\usuário` e senha de rede |
| Kerberos | Windows, Linux, macOS | `usuário@REALM` e senha de rede |
| Microsoft Entra MFA | Windows, Linux, macOS | Autenticação no navegador, conforme o servidor |

Windows integrada aparece somente no Windows. Conexões antigas com esse método
são preservadas; ao abri-las em outro sistema, selecione NTLM ou Kerberos. A
opção não é convertida automaticamente para login SQL.

NTLM/Kerberos usam TDS com um contexto de autenticação criado para cada conexão
física. Credenciais são enviadas ao provedor de rede somente após o handshake
TLS, com vínculo ao certificado TLS para servidores que exigem Extended
Protection. O cache de conexões não compartilha identidades entre abas. Senhas
salvas continuam no cofre do sistema, sem aparecer no arquivo de conexões.

## Rede, domínio e certificados

Informe o endereço TCP e a porta do SQL Server. Para instâncias nomeadas,
descubra a porta TCP com o administrador e use o host sem `\INSTÂNCIA`.
LocalDB continua exclusivo do Windows e da autenticação integrada.

NTLM depende de o servidor/domínio aceitar NTLM. Ele pode ser bloqueado pelas
políticas da empresa. Kerberos depende de realm, DNS, relógios sincronizados,
acesso ao KDC e SPN `MSSQLSvc/host:porta` registrado para a conta do serviço.
Use o principal de rede completo e o nome DNS correspondente ao SPN. Essas
condições também valem quando o banco é acessado por SSH; o KDC precisa ser
alcançável no computador que executa DataPyn.

NTLM/Kerberos exigem TLS para toda a sessão. O arquivo CA PEM é opcional quando
o certificado é reconhecido pelas raízes públicas incluídas no aplicativo.
Para CA corporativa, informe o PEM no cadastro da conexão. Nomes DNS, múltiplos
SANs e endereços IP em SAN são validados; CN não sobrepõe um SAN diferente.
“Confiar no certificado” mantém a criptografia e dispensa a validação do
certificado por escolha explícita do usuário. `Encrypt=no` e TDS 8.0
`Encrypt=strict` não estão disponíveis nos modos de rede.

Um túnel SSH preserva o host/porta originais para TLS e SPN. Um redirecionamento
TDS informado pelo SQL Server é recusado antes de abrir outra conexão: cadastre
o endpoint final indicado pelo administrador. Nenhum redirecionamento sai do
túnel selecionado. A troca de banco com `USE` não muda a identidade da rede.

## Distribuição e manutenção

Login SQL, Windows integrada e Entra continuam usando Microsoft ODBC. NTLM e
Kerberos usam `python-tds`, `sqlalchemy-pytds`, `pyspnego` e `pyOpenSSL`, incluídos
no runtime. Windows inclui SSPI. Linux/macOS incluem os módulos Python GSSAPI e
Kerberos, mas continuam dependendo das bibliotecas Kerberos do sistema e da
configuração de domínio feita pela organização. O aplicativo não instala um
domínio, escreve `krb5.conf` nem executa `kinit` com senhas.

O adaptador de rede fixa `python-tds==1.17.1` porque usa as interfaces internas
de login/socket para bloquear redirecionamentos e manter TLS por conexão. Não
atualize essa dependência sem repetir os testes de protocolo, autenticação,
TLS, SSH, parâmetros, múltiplos resultados, tabelas temporárias e cancelamento.
`fast_executemany` é uma opção de ODBC; o driver TDS usa inserção SQLAlchemy
parametrizada em lotes. Conexões temporárias mantêm a mesma sessão física.

```powershell
uv run pytest -c runtime_tests/pytest.ini runtime_tests/test_sqlserver_network_auth.py runtime_tests/test_sqlserver_network_wire.py -q
```

Os testes usam endpoints locais sem SQL Server ou domínio reais. Kerberos foi
validado no adaptador/provedor; a autenticação com um domínio corporativo exige
validação no ambiente do usuário. Não há fallback para NTLM ou login SQL.

Referências: [autenticação integrada Microsoft ODBC](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/using-integrated-authentication),
[python-tds](https://python-tds.readthedocs.io/en/stable/),
[pyspnego: plataformas e Kerberos](https://github.com/jborean93/pyspnego#kerberos-authentication).
