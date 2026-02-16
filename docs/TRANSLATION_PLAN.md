# English (en-US) Translation Plan

This document tracks the progress of translating all Portuguese UI text to English (en-US).

## Status: IN PROGRESS

## Files to translate (user-visible strings, comments, docstrings)

### UI Components (`source/src/ui/components/`)
- [ ] toolbar.py - "Nova Aba" -> "New Tab", "Conexao" -> "Connection", "Executar (F5)" -> "Run (F5)"
- [ ] statusbar.py - "Pronto" -> "Ready", "Desconectado" -> "Disconnected"
- [ ] session_tabs.py - "Abrir Local do Arquivo" -> "Open File Location", "Fechar Tudo" -> "Close All", "Fechar" -> "Close"
- [ ] output_panel.py - "Limpar" -> "Clear", "Copiar" -> "Copy", "[AVISO]" -> "[WARNING]", "[ERRO]" -> "[ERROR]"
- [ ] connection_panel.py - "CONEXAO ATIVA" -> "ACTIVE CONNECTION", "Nenhuma" -> "None", "Desconectar" -> "Disconnect", "Gerenciar" -> "Manage"
- [ ] variables_panel.py - "Nenhuma variavel" -> "No variables", "Atualizar" -> "Refresh", "Copiar nome/valor/tipo" -> "Copy name/value/type", "Remover variavel" -> "Remove variable"
- [ ] object_explorer_panel.py - "Nenhuma conexao" -> "No connection", "Buscar tabelas e colunas..." -> "Search tables and columns...", "Copiar nome" -> "Copy name"
- [ ] bottom_tabs.py - "Resultados" -> "Results", "Variaveis" -> "Variables"
- [ ] results_viewer.py - "Exportar CSV" -> "Export CSV", "Copiar Tudo" -> "Copy All", "Nenhum resultado" -> "No results", "Salvar Imagem" -> "Save Image"
- [ ] session_widget.py - "[ERRO] Nenhuma conexao ativa" -> "[ERROR] No active connection", "Erro SQL/Python" -> "SQL/Python Error"
- [ ] buttons.py - docstrings only
- [ ] inputs.py - "Buscar..." -> "Search..."
- [ ] editor_header.py - docstrings only

### Main Window (`source/src/ui/`)
- [ ] main_window.py - menus ("&Arquivo"->"&File", "&Conexao"->"&Connection", "&Executar"->"&Run"), status messages, about dialog, empty state, error messages

### Dialogs (`source/src/ui/dialogs/`)
- [ ] settings_dialog.py - "Configuracoes - Atalhos" -> "Settings - Shortcuts", action names, buttons
- [ ] connections_manager_dialog.py - "Gerenciar Conexoes" -> "Manage Connections", buttons, messages
- [ ] connection_edit_dialog.py - "Nova Conexao" -> "New Connection", form labels, buttons
- [ ] connection_picker_dialog.py - "Selecionar Conexao" -> "Select Connection"
- [ ] update_dialog.py - "Atualizacao Disponivel" -> "Update Available", buttons
- [ ] package_manager_dialog.py - "Gerenciador de Pacotes" -> "Package Manager", buttons, status
- [ ] file_import_dialog.py - "Importar Arquivo" -> "Import File"
- [ ] export_to_table_dialog.py - "Exportar para Tabela" -> "Export to Table"

### Docking (`source/src/ui/docking/`)
- [ ] dockable_widget.py - "Fechar painel" -> "Close panel"
- [ ] docking_manager.py - debug messages
- [ ] example_integration.py - print messages

### Editors (`source/src/editors/`)
- [ ] code_editor.py - "Buscar..." -> "Search...", "Substituir..." -> "Replace...", tooltips
- [ ] code_block.py - "Arraste para reposicionar" -> "Drag to reposition", "Executar (F5)" -> "Run (F5)", status labels
- [ ] block_editor.py - "Adicionar bloco" -> "Add block", "Bloco" -> "Block"
- [ ] python_editor.py - snippet text

### Services (`source/src/services/`)
- [ ] query_service.py - "Nenhuma conexao ativa disponivel" -> "No active connection available"
- [ ] connection_service.py - "Conexao bem-sucedida!" -> "Connection successful!"
- [ ] package_manager_service.py - error messages
- [ ] auto_update_service.py - error messages
- [ ] schema_service.py - error messages
- [ ] python_execution_service.py - "Erro de sintaxe" -> "Syntax error"
- [ ] code_formatter_service.py - error messages
- [ ] file_import_service.py - error messages

### Database (`source/src/database/`)
- [ ] database_connector.py - error/log messages, "Resultado" -> "Result"
- [ ] connection_manager.py - docstrings

### Tests (`tests/`)
- [ ] test_object_explorer.py - "Nenhuma conexao" -> "No connection"
- [ ] test_usability.py - "Erro" assertions
- [ ] test_export_script.py - "Nenhuma sessao ativa" assertion, menu name checks
- [ ] test_block_editor.py - "Executando" assertion, "conexao" assertion
- [ ] test_background_workers.py - "Erro de conexao", "Falha ao conectar" assertions
- [ ] test_ui_integration.py - "Erro", "conexao" assertions
- [ ] test_python_output_e2e.py - "Resultado", "Pronto" assertions
- [ ] test_block_connection.py - "Nenhuma", "ERRO" assertions
- [ ] test_database_connector.py - "nao suportado" assertion
