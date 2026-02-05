# Importação Automática de Arquivos

## Descrição

O DataPyn agora suporta importação automática de arquivos de dados através de arrastar e soltar (drag-and-drop). Quando você arrasta arquivos CSV, JSON ou Excel (XLSX/XLS) para a área de blocos, o sistema gera automaticamente o código Python necessário para importar esses dados usando pandas.

## Formatos Suportados

- **CSV** (`.csv`) - Arquivos de valores separados por vírgula
- **JSON** (`.json`) - Arquivos JavaScript Object Notation
- **Excel** (`.xlsx`, `.xls`) - Planilhas do Microsoft Excel

## Como Usar

### Método 1: Arrastar e Soltar

1. Abra o DataPyn
2. Localize o arquivo que deseja importar no seu explorador de arquivos
3. Arraste o arquivo para a área de blocos de código
4. Um novo bloco Python será criado automaticamente com o código de importação
5. Execute o bloco (F5 ou Shift+F5) para carregar os dados

### Método 2: Múltiplos Arquivos

Você pode arrastar múltiplos arquivos simultaneamente:
1. Selecione vários arquivos no explorador de arquivos
2. Arraste todos de uma vez para a área de blocos
3. Um bloco Python será criado para cada arquivo

## Código Gerado

### Para arquivos CSV:
```python
import pandas as pd
df = pd.read_csv('/caminho/para/arquivo.csv')
```

### Para arquivos JSON:
```python
import pandas as pd
df = pd.read_json('/caminho/para/arquivo.json')
```

### Para arquivos Excel:
```python
import pandas as pd
df = pd.read_excel('/caminho/para/arquivo.xlsx')
```

## Características

- ✅ **Detecção automática de tipo**: O sistema identifica automaticamente a extensão do arquivo
- ✅ **Caminhos normalizados**: Funciona tanto em Windows quanto em Linux/Mac
- ✅ **Case-insensitive**: Reconhece extensões em maiúsculas e minúsculas (`.CSV`, `.csv`)
- ✅ **Caracteres especiais**: Suporta nomes de arquivo com espaços e caracteres especiais
- ✅ **Múltiplos arquivos**: Importe vários arquivos de uma só vez
- ✅ **Preserva blocos existentes**: Novos blocos são adicionados sem afetar o código existente

## Exemplos de Uso

### Exemplo 1: Importar CSV de vendas
```
Arquivo: vendas_2024.csv
Resultado: Bloco Python criado com código pronto para importar os dados
```

### Exemplo 2: Importar múltiplos arquivos
```
Arquivos: vendas.csv, clientes.json, produtos.xlsx
Resultado: 3 blocos Python criados, um para cada arquivo
```

### Exemplo 3: Análise rápida
```python
# Após arrastar o arquivo, você pode continuar editando:
import pandas as pd
df = pd.read_csv('/dados/vendas.csv')

# Adicione suas análises:
print(df.head())
print(df.describe())
df.plot(x='data', y='valor')
```

## Notas Técnicas

- O código gerado usa a biblioteca **pandas** que já está incluída no DataPyn
- A variável `df` é criada automaticamente para armazenar o DataFrame
- Você pode editar o código gerado conforme necessário (adicionar parâmetros, mudar nome da variável, etc.)
- Os blocos criados são do tipo Python e podem ser executados com F5 ou Shift+F5

## Troubleshooting

**Arquivo não é aceito ao arrastar:**
- Verifique se a extensão do arquivo é `.csv`, `.json`, `.xlsx` ou `.xls`
- Extensões em maiúsculas também são suportadas (`.CSV`, `.JSON`, etc.)

**Erro ao executar o código:**
- Verifique se o caminho do arquivo está correto
- Verifique se o arquivo existe e você tem permissão de leitura
- Para arquivos Excel, pode ser necessário instalar `openpyxl`: `pip install openpyxl`

## Implementação

Esta funcionalidade foi implementada em:
- **Arquivo**: `source/src/editors/block_editor.py`
- **Métodos principais**:
  - `dragEnterEvent()` - Aceita arquivos arrastados
  - `dropEvent()` - Processa arquivos soltos
  - `_generate_import_code()` - Gera o código de importação

## Testes

Testes automatizados estão disponíveis em:
- `tests/test_block_editor.py::TestFileDragAndDrop`

Para executar os testes:
```bash
pytest tests/test_block_editor.py::TestFileDragAndDrop -v
```
