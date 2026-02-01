# Changelog - DataPyn IDE v1.1.0

## 🎉 Novas Funcionalidades

### 1. ✨ Sintaxe Mista SQL + Python

**A maior novidade!** Agora você pode escrever SQL diretamente no editor Python:

```python
# Antes (2 passos):
# 1. Executar no Editor SQL: SELECT * FROM clientes
# 2. Usar no Python: df

# Agora (1 passo):
clientes = query("SELECT * FROM clientes WHERE ativo = 1")
print(len(clientes))
```

**Novos comandos disponíveis:**
- `query(sql)` - Executa SELECT e retorna DataFrame
- `execute(sql)` - Executa INSERT/UPDATE/DELETE e retorna nº de linhas

**Veja exemplos completos em:**
- [examples_mixed.py](examples_mixed.py) - 10 exemplos práticos
- [MIXED_SYNTAX.md](MIXED_SYNTAX.md) - Documentação completa

### 2. 🔐 Windows Authentication (SQL Server)

Conecte ao SQL Server sem precisar de senha!

- Nova checkbox "Usar Windows Authentication" no diálogo de conexão
- Campos de usuário/senha são desabilitados automaticamente
- Usa as credenciais do Windows (Trusted_Connection)
- Funciona apenas para SQL Server

### 3. ⌨️ Atalhos Configuráveis

- Novo menu: **Ferramentas > Configurações de Atalhos** (Ctrl+,)
- Personalize todos os atalhos de teclado da IDE
- Sistema detecta e alerta sobre conflitos
- Configurações salvas em JSON (~/.datapyn/shortcuts.json)

### 4. 🎨 Interface Profissional (Sem Emojis)

- Removidos todos os emojis da interface
- Adicionado pacote **QtAwesome** (Font Awesome icons)
- Ícones profissionais em:
  - Menus
  - Toolbar
  - Botões
  - Labels
  - Status

## 🔧 Melhorias

### Interface
- Labels mais limpos sem emojis
- Ícones vetoriais escaláveis (Font Awesome)
- Visual mais profissional e corporativo
- Melhor acessibilidade

### Conexões
- Suporte completo a Windows Authentication
- Toggle automático de campos username/password
- Visibilidade condicional da opção Windows Auth (apenas SQL Server)

### Editores
- Sintaxe mista funciona no Editor Python
- Auto-detecção de uso de query() e execute()
- Validação de sintaxe antes da execução
- Mensagens de erro mais claras

### Atalhos
- Todos os atalhos agora são configuráveis
- Tabela visual para edição
- Validação de conflitos em tempo real
- Atalhos salvos persistem entre sessões

## 📦 Dependências Adicionadas

- **QtAwesome >= 1.3.0** - Ícones Font Awesome para PyQt6

## 📝 Arquivos Modificados

### Novos Arquivos
- `src/core/mixed_executor.py` - Executor de sintaxe mista
- `src/ui/settings_dialog.py` - Diálogo de configuração de atalhos
- `examples_mixed.py` - Exemplos de sintaxe mista
- `MIXED_SYNTAX.md` - Documentação da sintaxe mista
- `CHANGELOG.md` - Este arquivo

### Arquivos Atualizados
- `src/ui/main_window.py`:
  - Removidos emojis de todos os componentes UI
  - Adicionado método `_setup_icons()` para criar ícones
  - Integrado MixedLanguageExecutor
  - Adicionado menu de configurações
  - Método `_execute_python()` agora suporta sintaxe mista
  - Método `_show_settings()` para abrir diálogo de atalhos

- `src/database/database_connector.py`:
  - Parâmetros `username` e `password` agora são opcionais
  - Novo parâmetro `use_windows_auth` em kwargs
  - Método `_build_connection_string()` suporta Windows Authentication
  - Connection string com `Trusted_Connection=yes` para SQL Server

- `src/ui/connection_dialog.py`:
  - Nova checkbox "Usar Windows Authentication"
  - Método `_toggle_windows_auth()` desabilita campos
  - Método `_toggle_windows_auth_visibility()` mostra apenas para SQL Server
  - `_connect()` passa flag `use_windows_auth` para connector

- `requirements.txt`:
  - Adicionado `QtAwesome>=1.3.0`

- `README.md`:
  - Atualizada seção de características
  - Adicionada documentação de sintaxe mista
  - Adicionada seção sobre Windows Authentication
  - Atualizada lista de atalhos
  - Referências aos novos documentos

## 🐛 Correções

- Corrigido warning "Ambiguous shortcut overload: F5"
- Removidos emojis que causavam problemas de encoding em alguns terminais
- Melhorada validação de conexão antes de executar código

## 📚 Documentação

### Novos Documentos
- **MIXED_SYNTAX.md** - Guia completo de sintaxe mista com casos de uso avançados
- **examples_mixed.py** - 10 exemplos práticos de sintaxe mista

### Documentos Atualizados
- **README.md** - Incluídas novas funcionalidades
- **CHANGELOG.md** - Este arquivo

## 🚀 Como Atualizar

Se você já tem o DataPyn instalado:

1. **Baixe as atualizações**
   ```bash
   cd c:\nac\datapyn
   # (atualize os arquivos)
   ```

2. **Instale nova dependência**
   ```bash
   pip install qtawesome>=1.3.0
   ```
   
   Ou execute:
   ```bash
   install.bat
   ```

3. **Execute**
   ```bash
   run.bat
   ```

## ⚠️ Breaking Changes

**Nenhum!** Esta versão é 100% retrocompatível.

- Todas as funcionalidades antigas continuam funcionando
- Sintaxe mista é opcional (se não usar query(), funciona como antes)
- Windows Authentication é opcional (campos de usuário/senha continuam disponíveis)
- Atalhos padrão continuam os mesmos (configuração é opcional)

## 🎯 Próximos Passos (Roadmap)

Possíveis melhorias futuras:

- [ ] Autocompletar SQL (IntelliSense)
- [ ] Histórico de queries executadas
- [ ] Suporte a schemas/databases múltiplos
- [ ] Export para mais formatos (JSON, Parquet, etc)
- [ ] Visualizações gráficas (charts) integradas
- [ ] Themes customizáveis
- [ ] Snippets de código
- [ ] Comparação de resultados (diff)
- [ ] Execution plan visualizer
- [ ] Plugin system

## 🙏 Agradecimentos

Obrigado por usar o DataPyn! 

Para reportar bugs ou sugerir melhorias, abra uma issue no repositório.

---

**Versão:** 1.1.0  
**Data:** 2025-01-24  
**Python:** 3.8+  
**Plataforma:** Windows (testado)
