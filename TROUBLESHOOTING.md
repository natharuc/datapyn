# Solução de Problemas - DataPyn IDE

## 🐛 Problemas Comuns

### 1. Erro ao Importar PyQt6

**Erro:**
```
ModuleNotFoundError: No module named 'PyQt6'
```

**Solução:**
```bash
pip install PyQt6 PyQt6-QScintilla
```

Se o erro persistir:
```bash
pip uninstall PyQt6 PyQt6-QScintilla
pip install --force-reinstall PyQt6 PyQt6-QScintilla
```

### 2. Erro ao Importar QScintilla

**Erro:**
```
ModuleNotFoundError: No module named 'PyQt6.Qsci'
```

**Solução:**
```bash
pip install PyQt6-QScintilla
```

### 3. Interface Não Aparece / Janela em Branco

**Possíveis Causas:**

1. **Driver de vídeo desatualizado**
   - Atualize os drivers da sua placa de vídeo

2. **Problema com Qt Platform Plugin**
   
   Tente definir a variável de ambiente:
   ```bash
   set QT_QPA_PLATFORM_PLUGIN_PATH=%VIRTUAL_ENV%\Lib\site-packages\PyQt6\Qt6\plugins\platforms
   ```

3. **Antivírus bloqueando**
   - Adicione exceção para o Python e para a pasta do DataPyn

### 4. Erro ao Conectar SQL Server

**Erro:**
```
Can't open lib 'ODBC Driver 17 for SQL Server'
```

**Solução:**

1. Instale o ODBC Driver 17 for SQL Server:
   https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

2. Ou use pymssql (não precisa de ODBC):
   - Edite `database_connector.py`
   - Mude a connection string para: `mssql+pymssql://...`

### 5. Erro ao Conectar MySQL

**Erro:**
```
Can't connect to MySQL server
```

**Soluções:**

1. **Verifique se o MySQL está rodando**
   ```bash
   # Windows
   net start MySQL
   
   # Linux
   sudo systemctl start mysql
   ```

2. **Verifique host e porta**
   - Host padrão: `localhost` ou `127.0.0.1`
   - Porta padrão: `3306`

3. **Verifique permissões do usuário**
   ```sql
   GRANT ALL PRIVILEGES ON *.* TO 'usuario'@'localhost';
   FLUSH PRIVILEGES;
   ```

### 6. Erro ao Conectar PostgreSQL

**Erro:**
```
could not connect to server: Connection refused
```

**Soluções:**

1. **Verifique se PostgreSQL está rodando**
   ```bash
   # Windows
   net start postgresql-x64-14
   
   # Linux
   sudo systemctl start postgresql
   ```

2. **Verifique pg_hba.conf**
   - Localize o arquivo (geralmente em `/etc/postgresql/*/main/pg_hba.conf`)
   - Adicione linha: `host all all 127.0.0.1/32 md5`
   - Reinicie PostgreSQL

### 7. Query Executada Mas Sem Resultados

**Possíveis Causas:**

1. **Query não retorna dados**
   - Verifique se a query está correta
   - Teste a query diretamente no banco

2. **Timeout**
   - Para queries longas, aumente o timeout em `database_connector.py`

### 8. Erro ao Executar Python

**Erro:**
```
NameError: name 'df' is not defined
```

**Solução:**
- Execute uma query SQL primeiro (F5)
- O DataFrame `df` só existe após executar uma query
- Verifique a aba "Variáveis em Memória" para ver o que está disponível

### 9. Caracteres Especiais Aparecem Incorretamente

**Solução:**

Para SQL Server:
```python
# Na connection string, adicione:
?charset=utf8mb4
```

Para MySQL:
```python
# Já está configurado com utf8mb4
```

Para exports CSV:
```python
# Use encoding utf-8-sig
df.to_csv('arquivo.csv', encoding='utf-8-sig')
```

### 10. Memória Insuficiente

**Erro:**
```
MemoryError
```

**Soluções:**

1. **Limite o número de registros**
   ```sql
   SELECT TOP 10000 * FROM tabela
   ```

2. **Use chunks no Pandas**
   ```python
   # Edite database_connector.py para usar:
   chunks = pd.read_sql(query, engine, chunksize=1000)
   df = pd.concat(chunks)
   ```

3. **Limpe resultados antigos**
   - Use o botão "Limpar Resultados"
   - Ou no Python: `results_manager.clear_all()`

### 11. Aplicação Trava ao Executar Query Longa

**Solução:**

Isso é esperado pois a execução é síncrona. Para queries longas:

1. Execute em horários de menor uso
2. Use LIMIT/TOP para testar primeiro
3. Considere criar índices no banco

### 12. Erro ao Salvar Conexão

**Erro:**
```
PermissionError: [Errno 13] Permission denied
```

**Solução:**

1. Execute como Administrador
2. Ou mude o caminho em `connection_manager.py`:
   ```python
   config_path = Path('C:/Temp/.datapyn/connections.json')
   ```

### 13. Matplotlib Não Funciona

**Erro:**
```
No module named 'matplotlib'
```

**Solução:**
```bash
pip install matplotlib
```

Para gráficos aparecerem corretamente:
```python
import matplotlib
matplotlib.use('Qt5Agg')  # Use Qt backend
import matplotlib.pyplot as plt
```

### 14. Exportação Excel Falha

**Erro:**
```
No module named 'openpyxl'
```

**Solução:**
```bash
pip install openpyxl
```

### 15. Programa Não Inicia

**Checklist:**

1. **Python instalado?**
   ```bash
   python --version
   ```
   Deve ser 3.8 ou superior

2. **Ambiente virtual ativado?**
   ```bash
   venv\Scripts\activate
   ```

3. **Dependências instaladas?**
   ```bash
   pip install -r requirements.txt
   ```

4. **Verifique logs:**
   - Abra `datapyn.log`
   - Procure por mensagens de erro

5. **Teste importações:**
   ```bash
   python -c "import PyQt6; print('PyQt6 OK')"
   python -c "from PyQt6.Qsci import QsciScintilla; print('QScintilla OK')"
   python -c "import pandas; print('Pandas OK')"
   ```

## 🔍 Modo Debug

Para ver mais detalhes de erros, edite `main.py`:

```python
logging.basicConfig(
    level=logging.DEBUG,  # Mude para DEBUG
    # ...
)
```

## 📝 Reportar Bug

Se o problema persistir, reporte com:

1. **Versão do Python**: `python --version`
2. **Sistema Operacional**: Windows/Linux/macOS
3. **Mensagem de erro completa**
4. **Conteúdo do datapyn.log**
5. **Passos para reproduzir**

## 💡 Dicas de Performance

1. **Use índices no banco de dados**
2. **Limite resultados com TOP/LIMIT**
3. **Feche conexões não utilizadas**
4. **Limpe resultados periodicamente**
5. **Use filtros WHERE em vez de processar tudo em Python**

## 🆘 Suporte

Para mais ajuda:

1. Consulte a [documentação oficial do PyQt6](https://www.riverbankcomputing.com/static/Docs/PyQt6/)
2. Consulte a [documentação do Pandas](https://pandas.pydata.org/docs/)
3. Consulte a [documentação do SQLAlchemy](https://docs.sqlalchemy.org/)
