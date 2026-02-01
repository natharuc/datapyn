# DataPyn IDE - Guia Rápido

## Instalação Rápida

```bash
# 1. Criar ambiente virtual
python -m venv venv
venv\Scripts\activate

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Executar
python main.py
```

## Funcionalidades

✅ Conexão com SQL Server, MySQL, MariaDB, PostgreSQL
✅ Editor SQL com syntax highlighting (estilo Monaco)
✅ Editor Python integrado
✅ Resultados persistem em memória (df1, df2, df3...)
✅ Manipule resultados com pandas
✅ Exportar para CSV/Excel
✅ Tema escuro moderno
✅ Atalhos customizáveis

## Atalhos Principais

- **F5**: Executar SQL
- **Shift+F5**: Executar Python
- **Ctrl+/**: Comentar linha
- **Ctrl+Shift+C**: Limpar resultados

## Exemplo de Uso

1. **Conecte ao banco**: Botão "Nova Conexão"
2. **Execute SQL** (F5):
   ```sql
   SELECT * FROM clientes WHERE ativo = 1
   ```
3. **Manipule em Python** (Shift+F5):
   ```python
   # 'df' sempre aponta para o último resultado
   print(f"Total: {len(df)}")
   
   # Filtrar
   clientes_sp = df[df['estado'] == 'SP']
   print(f"SP: {len(clientes_sp)}")
   ```

## Diferencial

O grande diferencial é que **os resultados das queries ficam em memória** como DataFrames do pandas (df1, df2, df3...), permitindo que você execute múltiplas queries e depois manipule todos os resultados juntos com código Python!

Exemplo:
```sql
-- Query 1
SELECT * FROM vendas_2024
```
```sql
-- Query 2  
SELECT * FROM vendas_2025
```
```python
# Agora você tem df1 (2024) e df2 (2025) em memória!
crescimento = ((df2['total'].sum() / df1['total'].sum()) - 1) * 100
print(f"Crescimento: {crescimento:.2f}%")
```
