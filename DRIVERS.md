# Instalação de Drivers de Banco de Dados

Este guia ajuda você a instalar os drivers necessários para conectar aos diferentes bancos de dados.

## 🔧 SQL Server

### Windows

**Opção 1: ODBC Driver (Recomendado)**

1. Baixe e instale o **ODBC Driver 17 for SQL Server**:
   - https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

2. Ou use o instalador do Windows:
   ```powershell
   # Baixar automaticamente
   winget install Microsoft.ODBCDriver.17
   ```

**Opção 2: PyMSSQL**

Já está no requirements.txt. Não precisa de instalação adicional.

### Linux

```bash
# Ubuntu/Debian
curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql17
```

### macOS

```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew update
brew install msodbcsql17
```

## 🐬 MySQL

### Windows

**Opção 1: MySQL Connector/ODBC**

1. Baixe em: https://dev.mysql.com/downloads/connector/odbc/
2. Instale o MSI

**Opção 2: Usar PyMySQL**

Já está no requirements.txt. Funciona sem drivers adicionais! ✅

### Linux

```bash
# Ubuntu/Debian
sudo apt-get install libmysqlclient-dev

# RedHat/CentOS
sudo yum install mysql-devel
```

### macOS

```bash
brew install mysql
```

## 🦭 MariaDB

### Windows

1. Baixe o MariaDB Connector/C em:
   https://mariadb.com/downloads/connectors/

2. Ou instale via pip (já no requirements.txt):
   ```bash
   pip install mariadb
   ```

### Linux

```bash
# Ubuntu/Debian
sudo apt-get install libmariadb-dev

# RedHat/CentOS
sudo yum install mariadb-devel
```

### macOS

```bash
brew install mariadb-connector-c
```

## 🐘 PostgreSQL

### Windows

**Opção 1: PostgreSQL ODBC Driver**

1. Baixe em: https://www.postgresql.org/ftp/odbc/versions/msi/
2. Instale o MSI

**Opção 2: Usar psycopg2-binary**

Já está no requirements.txt. Funciona sem drivers adicionais! ✅

### Linux

```bash
# Ubuntu/Debian
sudo apt-get install libpq-dev

# RedHat/CentOS
sudo yum install postgresql-devel
```

### macOS

```bash
brew install postgresql
```

## 🧪 Testando a Instalação

Após instalar os drivers, teste com Python:

```python
# Testar PyMySQL (MySQL)
import pymysql
print("PyMySQL OK!")

# Testar psycopg2 (PostgreSQL)
import psycopg2
print("psycopg2 OK!")

# Testar mariadb
import mariadb
print("MariaDB OK!")

# Testar pyodbc (SQL Server)
import pyodbc
drivers = pyodbc.drivers()
print("ODBC Drivers disponíveis:")
for driver in drivers:
    print(f"  - {driver}")
```

## ⚠️ Problemas Comuns

### SQL Server: "No module named 'pyodbc'"

```bash
pip install pyodbc
```

Se der erro ao instalar pyodbc:

**Windows:**
- Instale o Visual C++ Build Tools
- Ou use: `pip install pyodbc --only-binary :all:`

**Linux:**
```bash
sudo apt-get install unixodbc-dev
pip install pyodbc
```

### MySQL: "Library not loaded: libmysqlclient"

**macOS:**
```bash
brew install mysql-client
export PATH="/usr/local/opt/mysql-client/bin:$PATH"
```

**Linux:**
```bash
sudo apt-get install libmysqlclient-dev
```

### PostgreSQL: "Error loading psycopg2 module"

Use `psycopg2-binary` em vez de `psycopg2`:

```bash
pip uninstall psycopg2
pip install psycopg2-binary
```

### MariaDB: "Failed to import _mariadb"

**Windows:**
- Baixe e instale MariaDB Connector/C
- Ou use pymysql como alternativa (compatível com MariaDB)

**Linux/macOS:**
```bash
# Certifique-se de ter o mariadb-connector-c instalado
pip install --upgrade mariadb
```

## 🎯 Recomendações

Para começar rapidamente, use estas combinações que **não precisam de drivers adicionais**:

- ✅ **MySQL**: PyMySQL (já no requirements.txt)
- ✅ **PostgreSQL**: psycopg2-binary (já no requirements.txt)
- ✅ **SQL Server**: pymssql (funciona sem ODBC)

Apenas instale:

```bash
pip install -r requirements.txt
```

E está pronto para usar! 🚀

## 📚 Mais Informações

- **SQL Server**: https://learn.microsoft.com/en-us/sql/connect/python/
- **MySQL**: https://dev.mysql.com/doc/connector-python/
- **PostgreSQL**: https://www.psycopg.org/
- **MariaDB**: https://mariadb.com/docs/connect/programming-languages/python/
