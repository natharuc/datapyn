# Testes do DataPyn

## Estrutura dos Testes

```
tests/
├── __init__.py             # Inicializador do pacote
├── conftest.py             # Fixtures compartilhadas (pytest)
├── test_connection_manager.py   # Testes do gerenciador de conexões
├── test_database_connector.py   # Testes do conector de banco
├── test_integration.py          # Testes de integração
├── test_mixed_executor.py       # Testes do executor cross-syntax
├── test_results_manager.py      # Testes do gerenciador de resultados
├── test_shortcut_manager.py     # Testes do gerenciador de atalhos
└── test_workspace_manager.py    # Testes do gerenciador de workspace
```

## Executando os Testes

### Todos os testes
```bash
pytest
```

### Com cobertura
```bash
pytest --cov=src --cov-report=html
```

### Testes específicos
```bash
# Um arquivo
pytest tests/test_mixed_executor.py

# Uma classe
pytest tests/test_mixed_executor.py::TestMixedExecutorSyntaxParsing

# Um teste
pytest tests/test_mixed_executor.py::TestMixedExecutorSyntaxParsing::test_extract_double_brace_simple
```

### Modo verboso
```bash
pytest -v
```

## Princípios de Design (SOLID / Clean Code)

### Single Responsibility
- Cada classe de teste foca em uma única responsabilidade
- `TestConnectionManager` testa apenas operações CRUD de conexões
- `TestConnectionManagerGroups` testa apenas operações de grupos

### Open/Closed
- Fixtures são extensíveis sem modificar código existente
- Novos testes podem ser adicionados sem alterar infraestrutura

### Dependency Inversion
- Testes dependem de abstrações (fixtures) não implementações
- Mocks são injetados via fixtures do conftest.py

### Arrange-Act-Assert
- Cada teste segue padrão AAA claro
- Setup → Ação → Verificação

## Fixtures Disponíveis (conftest.py)

| Fixture | Descrição |
|---------|-----------|
| `temp_dir` | Diretório temporário para testes |
| `shortcut_manager` | ShortcutManager com config em temp |
| `workspace_manager` | WorkspaceManager com config em temp |
| `results_manager` | ResultsManager limpo |
| `connection_manager` | ConnectionManager com config em temp |
| `mock_db_connector` | Conector de BD mockado |
| `sample_dataframe` | DataFrame de exemplo |
| `mixed_executor` | MixedLanguageExecutor configurado |

## Cobertura de Código

| Módulo | Cobertura |
|--------|-----------|
| `mixed_executor.py` | 86% |
| `workspace_manager.py` | 93% |
| `shortcut_manager.py` | 84% |
| `results_manager.py` | 75% |
| `connection_manager.py` | 71% |
| `database_connector.py` | 57% |

## Adicionando Novos Testes

1. Crie o arquivo `tests/test_novo_modulo.py`
2. Importe fixtures do `conftest.py`
3. Use classes para agrupar testes relacionados
4. Siga o padrão de nomenclatura: `test_descricao_do_teste`

```python
class TestNovoModulo:
    """Descrição do grupo de testes"""
    
    def test_funcionalidade_especifica(self, fixture_necessaria):
        """Descrição do que está sendo testado"""
        # Arrange
        setup_data = fixture_necessaria
        
        # Act
        resultado = funcao_testada(setup_data)
        
        # Assert
        assert resultado == esperado
```
