# ✅ Clean Code Checklist - DataPyn

Checklist para garantir qualidade de código na refatoração.

---

## 📋 Princípios SOLID

### ✅ **S - Single Responsibility Principle**

**Uma classe = uma responsabilidade**

#### Checklist:
- [ ] Cada classe tem propósito claro e único
- [ ] Nomes de classes descrevem exatamente o que fazem
- [ ] Se precisa de "e", "ou", está fazendo demais
- [ ] Mudanças em regras de negócio afetam apenas uma classe

**Exemplos**:
- ✅ `QueryService` - apenas executa queries
- ✅ `Button` - apenas renderiza botão
- ❌ `MainWindowManager` - gerencia janela E conexões E queries

---

### ✅ **O - Open/Closed Principle**

**Aberto para extensão, fechado para modificação**

#### Checklist:
- [ ] Novos comportamentos via herança, não modificação
- [ ] Componentes base extensíveis
- [ ] Não precisa modificar código existente para adicionar features

**Exemplos**:
```python
# ✅ BOM - Extensível
class Button:
    pass

class PrimaryButton(Button):  # Novo comportamento via herança
    def __init__(self, text, **kwargs):
        super().__init__(text, variant="primary", **kwargs)

# ❌ RUIM - Precisa modificar Button toda vez
class Button:
    def __init__(self, text, is_primary=False, is_danger=False, is_success=False):
        # Adicionar novo tipo = modificar aqui
```

---

### ✅ **L - Liskov Substitution Principle**

**Subclasses devem ser substituíveis por suas bases**

#### Checklist:
- [ ] Subclasses não quebram contrato da classe base
- [ ] Mesmos métodos, mesmas garantias
- [ ] Não adiciona exceções inesperadas

**Exemplos**:
```python
# ✅ BOM
class BaseWorker:
    def run(self):
        raise NotImplementedError

class SqlWorker(BaseWorker):
    def run(self):  # Mesmo contrato
        # executa SQL

# ❌ RUIM
class BaseWorker:
    def run(self):
        return result

class BadWorker(BaseWorker):
    def run(self):
        raise Exception("Não implementado")  # Quebra contrato
```

---

### ✅ **I - Interface Segregation Principle**

**Muitas interfaces pequenas > uma interface grande**

#### Checklist:
- [ ] Classes não implementam métodos que não usam
- [ ] Interfaces focadas e específicas
- [ ] Clientes não dependem de métodos desnecessários

---

### ✅ **D - Dependency Inversion Principle**

**Dependa de abstrações, não implementações**

#### Checklist:
- [ ] UI depende de services (abstração), não DB direto
- [ ] Services usam callbacks, não conhecem UI específica
- [ ] Fácil trocar implementações

**Exemplos**:
```python
# ✅ BOM - UI depende de service (abstração)
class MainWindow:
    def __init__(self):
        self.query_service = QueryService()  # Abstração
    
    def execute(self):
        self.query_service.execute_query(...)  # Não conhece detalhes

# ❌ RUIM - UI conhece implementação
class MainWindow:
    def execute(self):
        conn = pyodbc.connect(...)  # Implementação concreta
        cursor = conn.cursor()
        cursor.execute(...)
```

---

## 🧹 Clean Code

### ✅ **Naming (Nomenclatura)**

#### Checklist:
- [ ] Nomes descritivos e claros
- [ ] Evita abreviações obscuras
- [ ] Classes: Substantivos (`QueryService`, `Button`)
- [ ] Métodos: Verbos (`execute_query`, `set_active`)
- [ ] Booleanos: `is_`, `has_`, `can_`
- [ ] Constantes: UPPER_CASE

**Exemplos**:
```python
# ✅ BOM
is_connected = True
execute_query(query_text)
MAX_RETRY_ATTEMPTS = 3

# ❌ RUIM
flag = True
do(q)
m = 3
```

---

### ✅ **Functions (Funções)**

#### Checklist:
- [ ] Funções pequenas (< 20 linhas idealmente)
- [ ] Fazem UMA coisa
- [ ] Poucos parâmetros (< 4 idealmente)
- [ ] Sem efeitos colaterais ocultos
- [ ] Um nível de abstração por função

**Exemplos**:
```python
# ✅ BOM - Faz uma coisa
def validate_query(query: str) -> tuple[bool, str]:
    if not query.strip():
        return False, "Query vazia"
    return True, ""

# ❌ RUIM - Faz muitas coisas
def process_query(query):
    # valida
    # conecta
    # executa
    # formata resultado
    # atualiza UI
    # salva histórico
    # envia analytics
```

---

### ✅ **Comments (Comentários)**

#### Checklist:
- [ ] Código auto-explicativo (não precisa comentário)
- [ ] Comentários explicam "por que", não "o que"
- [ ] Sem código comentado (use git)
- [ ] Docstrings em classes e funções públicas

**Exemplos**:
```python
# ✅ BOM - Auto-explicativo
def calculate_total_price(items, discount):
    subtotal = sum(item.price for item in items)
    return subtotal * (1 - discount)

# ❌ RUIM - Comentários óbvios
def calc(i, d):
    # soma os preços
    s = 0
    for x in i:
        s += x.p  # adiciona preço
    # aplica desconto
    return s * (1 - d)
```

---

### ✅ **Error Handling**

#### Checklist:
- [ ] Não ignora exceções silenciosamente
- [ ] Exceções específicas, não genéricas
- [ ] Try/catch no nível certo
- [ ] Mensagens de erro úteis

**Exemplos**:
```python
# ✅ BOM
try:
    result = execute_query(query)
except ConnectionError as e:
    logger.error(f"Falha na conexão: {e}")
    raise
except QuerySyntaxError as e:
    return None, f"Erro de sintaxe: {e}"

# ❌ RUIM
try:
    result = execute_query(query)
except:  # Muito genérico
    pass  # Ignora silenciosamente
```

---

### ✅ **DRY - Don't Repeat Yourself**

#### Checklist:
- [ ] Sem código duplicado
- [ ] Lógica comum extraída para funções
- [ ] Estilos extraídos para design system

**Exemplos**:
```python
# ✅ BOM
def create_button(text, variant):
    return Button(text, variant=variant)

btn1 = create_button("OK", "primary")
btn2 = create_button("Cancel", "secondary")

# ❌ RUIM
btn1 = QPushButton("OK")
btn1.setStyleSheet("background: blue; padding: 8px;")
btn1.setFixedHeight(32)

btn2 = QPushButton("Cancel")
btn2.setStyleSheet("background: gray; padding: 8px;")
btn2.setFixedHeight(32)
```

---

## 🎨 UI/UX

### ✅ **Consistência Visual**

#### Checklist:
- [ ] Todos os botões seguem mesmo padrão
- [ ] Espaçamentos consistentes (usar SPACING)
- [ ] Cores semânticas (usar tokens)
- [ ] Fontes padronizadas (usar TYPOGRAPHY)

---

### ✅ **Feedback Visual**

#### Checklist:
- [ ] Loading states para operações longas
- [ ] Mensagens de erro claras
- [ ] Confirmação de sucesso
- [ ] Estados disabled visualmente diferentes

---

### ✅ **Performance**

#### Checklist:
- [ ] Operações pesadas em workers (não trava UI)
- [ ] Queries otimizadas
- [ ] Não renderiza listas enormes sem virtualização
- [ ] Evita re-renders desnecessários

---

## 📝 Code Review Checklist

Antes de commit:

- [ ] Código segue SOLID?
- [ ] Nomes descritivos?
- [ ] Funções pequenas e focadas?
- [ ] Sem duplicação?
- [ ] Comentários úteis (não óbvios)?
- [ ] Testes passam?
- [ ] UI consistente?
- [ ] Sem console.log / print() esquecido?

---

## 🚫 Code Smells (Sinais de Problema)

### ❌ Evite:

1. **God Classes** - Classes que fazem tudo
   ```python
   class MainWindowManagerControllerService:  # ❌
   ```

2. **Long Methods** - Métodos com 100+ linhas
   ```python
   def process_everything(self):  # ❌
       # 200 linhas de código
   ```

3. **Magic Numbers** - Números sem contexto
   ```python
   if age > 18:  # ❌ Por que 18?
   
   # ✅ Melhor:
   LEGAL_AGE = 18
   if age > LEGAL_AGE:
   ```

4. **Deep Nesting** - Muitos ifs aninhados
   ```python
   if x:
       if y:
           if z:
               if w:  # ❌ Muito profundo
   ```

5. **Shotgun Surgery** - Mudança em um lugar afeta muitos arquivos
   - Se mudar cor primária precisa editar 20 arquivos → ❌
   - Se usar design tokens, muda em 1 lugar → ✅

---

## ✅ Refatoração Segura

### Processo:

1. **Testes existem?** Se não, crie antes de refatorar
2. **Pequenas mudanças** - Não refaça tudo de uma vez
3. **Commit frequente** - Cada pequena melhoria
4. **Rode testes** após cada mudança
5. **Revise** antes de merge

### Técnicas:

- **Extract Method** - Extrair bloco para função
- **Extract Class** - Extrair responsabilidade para classe
- **Rename** - Nome melhor
- **Replace Magic Number** - Constante nomeada
- **Simplify Conditional** - Guard clauses

---

## 📚 Recursos

- [Clean Code (Robert C. Martin)](https://www.amazon.com/Clean-Code-Handbook-Software-Craftsmanship/dp/0132350882)
- [Refactoring (Martin Fowler)](https://refactoring.com/)
- [SOLID Principles](https://en.wikipedia.org/wiki/SOLID)

---

**Use este checklist em cada PR/commit!**
