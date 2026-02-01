# 🚀 Guia Rápido - Novas Funcionalidades

## Instalação

Se você já tinha o DataPyn instalado, apenas instale a nova dependência:

```bash
pip install qtawesome>=1.3.0
```

Ou reinstale tudo:

```bash
install.bat
```

Execute:

```bash
run.bat
```

---

## 1️⃣ Sintaxe Mista (SQL no Python)

### O que mudou?

Antes você precisava:
1. Escrever SQL no Editor SQL
2. Executar (F5)
3. Usar `df` no Editor Python

Agora você pode fazer tudo no Editor Python!

### Como usar?

```python
# Escreva isso no Editor Python e execute (Shift+F5):

# Buscar dados
clientes = query("SELECT * FROM clientes WHERE ativo = 1")
print(f"Total: {len(clientes)}")

# Múltiplas queries
vendas = query("SELECT * FROM vendas WHERE data >= '2024-01-01'")
produtos = query("SELECT * FROM produtos")

# Manipular com Pandas
total = vendas['valor'].sum()
print(f"Total vendido: R$ {total:,.2f}")

# Executar UPDATE/INSERT/DELETE
linhas = execute("UPDATE clientes SET ultimo_acesso = NOW() WHERE id = 123")
print(f"{linhas} linhas atualizadas")
```

### Veja mais exemplos

Abra o arquivo **examples_mixed.py** que tem 10 exemplos práticos!

---

## 2️⃣ Windows Authentication (SQL Server)

### Como usar?

1. Menu **Conexão > Nova Conexão**
2. Selecione **SQL Server** em "Tipo de Banco"
3. Marque a checkbox **"Usar Windows Authentication"**
4. Os campos de usuário e senha ficarão desabilitados
5. Preencha apenas: Host, Port, Database
6. Clique em **Conectar**

Pronto! A IDE vai usar suas credenciais do Windows.

---

## 3️⃣ Configurar Atalhos

### Como acessar?

- Menu **Ferramentas > Configurações de Atalhos**
- Ou pressione **Ctrl+,**

### Como configurar?

1. Na tabela, veja todos os atalhos disponíveis
2. Dê duplo-clique no atalho que quer mudar
3. Pressione a nova combinação de teclas
4. O sistema avisa se houver conflito
5. Clique em **Salvar**

**Exemplo:** Mudar execução Python de `Shift+F5` para `F6`:
- Duplo-clique em "Executar Python"
- Pressione F6
- Salvar

---

## 4️⃣ Interface Sem Emojis

A interface agora usa ícones profissionais (Font Awesome):

- ❌ Antes: `🔌 Nova Conexão`
- ✅ Agora: `⚡ Nova Conexão` (ícone vetorial)

Melhor para:
- Ambientes corporativos
- Acessibilidade
- Consistência visual
- Profissionalismo

---

## 📋 Checklist de Verificação

Após instalar, verifique se está tudo funcionando:

- [ ] A IDE abre sem erros
- [ ] Ícones aparecem nos menus e botões
- [ ] Consegue abrir "Configurações de Atalhos" (Ctrl+,)
- [ ] Consegue conectar com Windows Auth (se usar SQL Server)
- [ ] Consegue usar `query()` no Editor Python

---

## ❓ Problemas Comuns

### "ModuleNotFoundError: No module named 'qtawesome'"

**Solução:** Instale o QtAwesome
```bash
pip install qtawesome>=1.3.0
```

### "Windows Authentication não funciona"

**Verifique:**
- Você está usando SQL Server?
- A checkbox está marcada?
- Seu usuário Windows tem permissão no banco?

### "query() não definido"

**Solução:** 
- A função `query()` só existe no Editor Python
- Precisa ter uma conexão ativa
- Execute com Shift+F5 (não F5)

### Atalhos não salvam

**Solução:**
- Verifique permissões na pasta `~/.datapyn/`
- Confirme que clicou em "Salvar" no diálogo

---

## 🎓 Aprenda Mais

- **README.md** - Documentação geral
- **MIXED_SYNTAX.md** - Guia completo de sintaxe mista
- **examples_mixed.py** - Exemplos práticos
- **CHANGELOG.md** - Lista de mudanças
- **QUICKSTART.md** - Guia de início rápido

---

## 💡 Dicas Profissionais

1. **Desenvolva SQL primeiro:** Teste sua query no Editor SQL, depois copie para `query()`
2. **Use nomes descritivos:** `vendas_2024` é melhor que `df1`
3. **Combine tudo:** Busque com SQL, processe com Pandas, salve com `execute()`
4. **Atalhos personalizados:** Configure os atalhos do jeito que você prefere
5. **Windows Auth:** Use em ambientes corporativos para evitar gerenciar senhas

---

**Divirta-se explorando as novas funcionalidades!** 🎉

Se encontrar bugs, reporte. Se tiver sugestões, compartilhe!
