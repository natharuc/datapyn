# Guia de Otimizacao de Testes

## Visao Geral

Este documento descreve as otimizacoes implementadas nos testes do DataPyn para reduzir o tempo de execucao mantendo a cobertura e confiabilidade.

## Otimizacoes Implementadas

### 1. Execucao Paralela com pytest-xdist

Os testes agora executam em paralelo automaticamente usando todos os nucleos da CPU disponiveis.

**Antes**: Execucao sequencial (~15-20 minutos)
**Depois**: Execucao paralela (~5-8 minutos, 60-70% mais rapido)

#### Configuracao
```ini
# pytest.ini
addopts = -v --tb=short -n auto
```

O parametro `-n auto` detecta automaticamente o numero de nucleos e distribui os testes.

#### Controle Manual
```bash
# Usar todos os nucleos (padrao)
pytest

# Usar 4 processos paralelos
pytest -n 4

# Executar sequencialmente (sem paralelizacao)
pytest -n 0
```

### 2. Marcadores de Teste

Testes agora podem ser categorizados e filtrados para execucao seletiva.

#### Marcadores Disponiveis
- `@pytest.mark.unit` - Testes unitarios rapidos
- `@pytest.mark.integration` - Testes de integracao
- `@pytest.mark.slow` - Testes lentos (>5 segundos)
- `@pytest.mark.gui` - Testes que usam interface grafica

#### Uso
```python
import pytest

@pytest.mark.unit
def test_rapido():
    assert 1 + 1 == 2

@pytest.mark.slow
@pytest.mark.integration
def test_lento_integracao():
    # teste que demora varios segundos
    pass
```

#### Execucao Seletiva
```bash
# Apenas testes unitarios
pytest -m unit

# Apenas testes de integracao
pytest -m integration

# Pular testes lentos
pytest -m "not slow"

# Combinacao: unitarios OU integracao
pytest -m "unit or integration"

# Combinacao: integracao MAS nao lentos
pytest -m "integration and not slow"
```

### 3. Otimizacoes de Configuracao

#### Limite de Falhas
```ini
addopts = ... --maxfail=5
```
Para apos 5 falhas para economizar tempo quando ha erros criticos.

#### Strict Markers
```ini
addopts = ... --strict-markers
```
Garante que apenas marcadores definidos sejam usados, evitando erros de digitacao.

#### Traceback Resumido
```ini
addopts = ... --tb=short
```
Mostra apenas o essencial nos tracebacks, reduzindo output e melhorando legibilidade.

### 4. Fixtures Otimizadas

#### Scope de Fixtures
Fixtures caras sao configuradas uma vez por sessao:

```python
@pytest.fixture(scope="session", autouse=True)
def configure_matplotlib():
    """Configura matplotlib uma vez para toda a sessao"""
    import matplotlib
    matplotlib.use("Agg")
    yield
```

#### Fixtures Condicionais
Fixtures pesadas sao aplicadas apenas quando necessario:

```python
@pytest.fixture
def auto_close_dialogs(qtbot, monkeypatch):
    """Auto-fecha dialogos apenas em testes GUI"""
    # Aplicado automaticamente a todos os testes
    # mas pode ser desabilitado com markers
```

## Estrategias de Teste

### Desenvolvimento Local

Durante desenvolvimento, execute apenas os testes relevantes:

```bash
# Teste especifico
pytest tests/test_mixed_executor.py

# Todos os testes de um modulo
pytest tests/test_mixed_executor.py -v

# Teste especifico por nome
pytest tests/test_mixed_executor.py::test_sql_execution

# Apenas testes unitarios (rapidos)
pytest -m unit
```

### CI/CD

No CI/CD, execute todos os testes com paralelizacao:

```bash
# Todos os testes em paralelo
pytest

# Com cobertura
pytest --cov=source/src --cov-report=html
```

### Pre-Commit

Antes de commit, execute testes rapidos:

```bash
# Apenas unitarios (1-2 minutos)
pytest -m unit

# Ou testes especificos da area modificada
pytest tests/test_workspace_manager.py
```

## Metricas de Performance

### Antes das Otimizacoes
- Tempo total: ~15-20 minutos
- Execucao: Sequencial
- Feedback: Lento

### Depois das Otimizacoes
- Tempo total: ~5-8 minutos (60-70% reducao)
- Execucao: Paralela (4-8 processos)
- Feedback: Rapido

### Por Categoria (estimado)
- Testes unitarios: ~2-3 minutos
- Testes de integracao: ~4-6 minutos
- Testes lentos: ~8-12 minutos

## Boas Praticas

### 1. Marcar Testes Apropriadamente

```python
# BOM: Teste rapido sem marca especifica
def test_simple_addition():
    assert 1 + 1 == 2

# BOM: Teste lento marcado adequadamente
@pytest.mark.slow
def test_database_migration():
    # teste que demora muito
    pass

# RUIM: Teste lento sem marca
def test_expensive_operation():
    # teste que demora mas nao esta marcado
    pass
```

### 2. Usar Fixtures Apropriadas

```python
# BOM: Reutilizar fixtures
def test_with_temp_dir(temp_dir):
    file = temp_dir / "test.txt"
    file.write_text("test")
    assert file.exists()

# RUIM: Criar recursos manualmente
def test_without_fixture():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        # codigo duplicado
        pass
```

### 3. Isolar Testes

```python
# BOM: Teste isolado
def test_isolated(mock_db_connector):
    result = function_under_test(mock_db_connector)
    assert result is not None

# RUIM: Teste com efeitos colaterais
def test_with_side_effects():
    global_variable = "modified"  # Pode afetar outros testes
    assert True
```

### 4. Evitar Sleep Desnecessarios

```python
# BOM: Usar qtbot.waitUntil
def test_async_operation(qtbot):
    widget = MyWidget()
    qtbot.waitUntil(lambda: widget.isReady(), timeout=5000)

# RUIM: Usar time.sleep
def test_with_sleep():
    widget = MyWidget()
    time.sleep(5)  # Sempre espera 5s mesmo se pronto antes
```

## Troubleshooting

### Testes Falhando em Paralelo

**Problema**: Testes passam sequencialmente mas falham em paralelo.

**Causas Comuns**:
- Recursos compartilhados (arquivos, banco de dados)
- Variáveis globais
- Singletons não isolados

**Solucao**:
```bash
# Executar sequencialmente para debug
pytest -n 0 tests/test_problematico.py -v
```

### Fixtures Não Encontradas

**Problema**: `fixture 'nome' not found`

**Solucao**: Verifique se a fixture esta em `conftest.py` ou importada corretamente.

### Marcadores Desconhecidos

**Problema**: `Unknown pytest.mark.meu_marker`

**Solucao**: Adicione o marcador em `pytest.ini`:
```ini
markers =
    meu_marker: descricao do marcador
```

### Performance Inconsistente

**Problema**: Testes as vezes rapidos, as vezes lentos.

**Causas**:
- Cache do pytest
- Estado residual de testes anteriores
- Recursos do sistema

**Solucao**:
```bash
# Limpar cache
pytest --cache-clear

# Executar em ordem especifica
pytest --collect-only  # Ver ordem de coleta
```

## Monitoramento de Performance

### Ver Testes Mais Lentos

```bash
# Mostrar os 10 testes mais lentos
pytest --durations=10

# Mostrar todos os testes com duracao
pytest --durations=0
```

### Gerar Relatorio de Cobertura

```bash
# HTML (recomendado)
pytest --cov=source/src --cov-report=html
# Abrir htmlcov/index.html no navegador

# Terminal
pytest --cov=source/src --cov-report=term-missing

# XML (para CI)
pytest --cov=source/src --cov-report=xml
```

## Proximos Passos

### Otimizacoes Futuras
1. Categorizar todos os testes com marcadores apropriados
2. Separar testes E2E em suite separada
3. Implementar cache de fixtures caras
4. Adicionar testes de smoke (minimos para validacao rapida)
5. Configurar execucao distribuida em multiplas maquinas (opcional)

### Melhorias Sugeridas
- Adicionar `pytest-benchmark` para testes de performance
- Configurar `pytest-timeout` para evitar testes travados
- Implementar `pytest-randomly` para detectar dependencias entre testes
- Adicionar `pytest-sugar` para output mais legivel

## Referencias

- [pytest-xdist Documentation](https://pytest-xdist.readthedocs.io/)
- [pytest Markers](https://docs.pytest.org/en/stable/how-to/mark.html)
- [pytest Fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [pytest Best Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
