# Integrações do runtime distribuído

O DataPyn Tauri embute seu interpretador Python, bibliotecas e ferramentas `uv`
e `ruff` no sidecar. Não requer uma instalação do DataPyn PyQt6, Python ou Node
para executar consultas, blocos Python, exportações ou gráficos. Instalação,
configurações, credenciais, sessões e atualizações do Tauri têm identidade própria.
A importação explícita de configurações do PyQt6 continua disponível.

## Plataformas e arquitetura

A referência de compatibilidade é a distribuição publicada por
`.github/workflows/release.yml` do PyQt6:

| Plataforma | Arquitetura publicada pelo PyQt6 | Formatos publicados pelo PyQt6 |
| --- | --- | --- |
| Windows | x64 | Setup `.exe`, ZIP portátil |
| Linux | x64, build Ubuntu 22.04 | `.deb`, `.tar.gz` portátil |
| macOS | Apple Silicon arm64, build macOS 14 | `.dmg` |

O runtime precisa ser compilado nativamente para cada arquitetura; PyInstaller
não permite gerar o sidecar macOS/Linux em uma máquina Windows. `build_runtime.py`
recusa um target Rust diferente do host. No Linux, construir o Python e o binário
Rust em Ubuntu 22.04 preserva a base glibc do artefato anterior; compilar em 24.04
e simplesmente nomear o arquivo como compatível com 22.04 não preserva essa base.

## Bancos e autenticação

O Tauri reutiliza `source/src/database/database_connector.py`, o mesmo conector
de produção do PyQt6. Não há um driver alternativo específico para a interface.

| Plataforma de dados | Driver distribuído | Autenticação/recursos preservados | Requisito externo |
| --- | --- | --- | --- |
| SQL Server, Azure SQL, Synapse/Fabric com endpoint SQL | SQLAlchemy + `pyodbc` | SQL, autenticação integrada, Microsoft Entra com MFA no navegador, parâmetros, múltiplos resultados | Microsoft ODBC Driver compatível com o sistema/arquitetura; permissões, rede e certificados do servidor |
| SQL Server LocalDB | SQLAlchemy + `pyodbc` | Instância local/named pipe, autenticação integrada | Windows, instância LocalDB já instalada e ODBC |
| MySQL | SQLAlchemy + PyMySQL | Usuário/senha, Unicode, parâmetros | Rede e permissões do servidor |
| MariaDB | SQLAlchemy + PyMySQL | Mesmo fluxo MySQL, sem dependência do conector C MariaDB | Rede e permissões do servidor |
| PostgreSQL | SQLAlchemy + `psycopg2-binary` | Usuário/senha, banco e schema, search path, cancelamento | Rede, permissões e política de autenticação do servidor |
| Databricks SQL Warehouse | `databricks-sql-connector` + `databricks-sqlalchemy` | PAT e OAuth no navegador, catálogo/schema, persistência de token, parâmetros | Warehouse/endereço/http path, navegador e acesso à conta/workspace |
| SQLite | SQLite nativo + SQLAlchemy | Arquivo local ou memória | Permissão no arquivo |

`pymssql` e `mysql.connector` também são distribuídos para compatibilidade com
blocos Python que importavam esses módulos. A conexão principal SQL Server usa
`pyodbc`; `pymssql` não substitui silenciosamente ODBC ou o fluxo MFA.

Autenticação integrada exige a identidade e a configuração de domínio do SO.
Em Linux/macOS, uma configuração Kerberos apropriada pode ser necessária.
O instalador não provisiona servidores, instâncias LocalDB, contas de domínio,
certificados privados ou permissões nos bancos.

## Dependências nativas

### Windows x64

Microsoft ODBC Driver 18 é o requisito para novas instalações de SQL Server.
O instalador NSIS Tauri inclui o MSI oficial 18.7.1.1 x64, baixado no build e
validado por SHA256 fixado e assinatura Microsoft. Um driver 17/18 x64 existente
é preservado. Se estiver ausente, a instalação inicial pede consentimento para
instalar o driver e aceitar seus termos; somente o processo Microsoft solicita
elevação. O aplicativo continua instalado apenas para o usuário. O MSI está
embutido, assim como o instalador offline WebView2: não há download de pré-requisito
no computador do usuário durante a instalação.

Atualizações/passivo não exibem perguntas quando o driver já existe. Uma instalação
desassistida em máquina sem driver é interrompida: provisione ODBC 18 antes dela ou
use o instalador interativo. Cancelar ou falhar na instalação do driver interrompe
o setup com erro claro. O desinstalador Tauri não remove o ODBC compartilhado e
nunca chama o instalador/desinstalador PyQt6.

A documentação Microsoft consultada em 05/10/2026 informa que o ODBC 18.7.1.1
não exige instalar previamente o Visual C++ Redistributable. Versões 18.6 e
anteriores exigem esse componente. Uma instalação existente com driver antigo
pode continuar a funcionar, mas um artefato novo deve usar o redistribuível
oficial da arquitetura correta.
[Download e requisitos oficiais](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server).

### Linux x64

O gerenciador unixODBC (`libodbc2`/`unixodbc`) permite carregar `pyodbc` e deve
estar incluído nos requisitos do pacote. Para SQL Server, instale também
`msodbcsql18` pelo repositório Microsoft correspondente à distribuição; unixODBC
sozinho não é o driver de SQL Server. Os requisitos de WebKitGTK/GTK do Tauri
são independentes dos antigos requisitos de Qt.
[Instalação oficial no Linux](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server).

Para salvar senhas no cofre do SO, a sessão desktop precisa de um provedor
Secret Service (por exemplo `gnome-keyring`) e D-Bus do usuário. As bibliotecas
Python SecretStorage e jeepney são distribuídas; importar o backend não exige
acesso a um cofre real durante a CI. Sem serviço de cofre ativo, o usuário pode
conectar informando a senha, mas o runtime deve recusar persistência insegura.

### macOS arm64

Para SQL Server, instale o ODBC arm64 e unixODBC pelo Homebrew nativo. Evite
misturar um terminal Intel/Rosetta e um aplicativo arm64. O driver Microsoft
suporta Apple Silicon desde 17.8 e usa unixODBC, não iODBC.

```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew trust microsoft/mssql-release # necessário no Homebrew 6.0+
brew update
HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql18
```

O comando `brew trust` não existe em versões antigas; nesses casos, omita-o.
[Instalação e diagnóstico oficiais no macOS](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/install-microsoft-odbc-driver-sql-server-macos).

## Pynia e ferramentas opcionais

Os módulos ACP, ferramentas de dados e MCP interno fazem parte do runtime.
Executáveis dos agentes Claude, Cursor, Copilot e Codex, suas contas e login
continuam sendo instalações externas do usuário, como no PyQt6. O gerenciador de
agentes oferece instalação/login; a distribuição não embute essas contas ou CLIs.
Os pacotes adicionais instalados para blocos Python ficam no perfil do Tauri,
sem modificar o Python ou a instalação PyQt6.

## Verificação do artefato

`source/datapyn_runtime/distribution.py` define um contrato único de módulos,
metadados, dialetos e ferramentas. A especificação PyInstaller copia os metadados
das distribuições e dependências, além de seus módulos: isso preserva os entry
points usados pelo SQLAlchemy/Databricks e as consultas de versão feitas por
bibliotecas de autenticação. Qt permanece excluído.

Antes de empacotar, `build_runtime.py` verifica os drivers, os DBAPIs e a criação
de engines/pools sem abrir conexão. `--smoke` verifica o executável congelado,
sem `PYTHONPATH`, Python externo ou módulos do checkout, através de:

- `smoke_runtime.py`: SQL/Python, cancelamento e recuperação.
- `smoke_parity.py`: autocomplete, filtros, exportações, gráficos e integrações.
- `smoke_persistence.py`: sessões, documentos e restauração.
- `smoke_distribution.py`: todos os drivers, metadados, entry points, DBAPIs e
  executáveis `uv`/`ruff` realmente embutidos, além do arquivo CA usado em TLS/OAuth.

```powershell
# Source, sem conectar a serviços externos
.\.venv\Scripts\python.exe scripts/tauri/smoke_distribution.py

# Artefato congelado já produzido
.\.venv\Scripts\python.exe scripts/tauri/smoke_distribution.py --executable desktop/src-tauri/binaries/datapyn-runtime-x86_64-pc-windows-msvc.exe
```

A falta de módulo, metadado, dialect ou ferramenta embutida reprova o build.
A presença do ODBC nativo é informada separadamente: o smoke da CI pode não ter
SQL Server instalado, enquanto o requisito deve ser provido no computador do
usuário. A verificação offline valida empacotamento e caminhos de inicialização;
autenticação e execução contra servidores reais exigem credenciais e aceite em
cada ambiente. Nenhum teste offline afirma ter autenticado em servidores reais.
