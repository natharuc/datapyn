"""
MonacoEditor - Editor de código baseado em Monaco (VS Code)

Usa o pacote monaco-qt para integração do Monaco Editor com PyQt6.
Inclui temas customizados, autocomplete e visual otimizado.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QObject, QTimer
from PyQt6.QtWebChannel import QWebChannel
import json

# Importa o MonacoWidget do pacote monaco-qt
try:
    from monaco import MonacoWidget as BaseMonacoWidget
    MONACO_AVAILABLE = True
except ImportError:
    MONACO_AVAILABLE = False
    BaseMonacoWidget = None


# Mapeamento de temas do sistema para temas Monaco
THEME_MAP = {
    'dark': 'vs-dark',
    'light': 'vs',
    'monokai': 'monokai',
    'dracula': 'dracula', 
    'solarized_dark': 'solarized-dark',
    'nord': 'nord',
}


class ExecuteBridge(QObject):
    """Bridge para receber comandos de execução do JavaScript."""
    execute_requested = pyqtSignal()
    
    @pyqtSlot()
    def requestExecute(self):
        self.execute_requested.emit()


class MonacoEditor(QWidget):
    """Editor Monaco integrado via monaco-qt com temas e autocomplete."""
    
    content_changed = pyqtSignal()
    execute_requested = pyqtSignal()
    SCN_FOCUSIN = pyqtSignal()  # Compatibilidade com QScintilla
    SCN_FOCUSOUT = pyqtSignal()  # Compatibilidade com QScintilla
    textChanged = pyqtSignal()  # Compatibilidade com QScintilla
    
    LANGUAGE_MAP = {
        'python': 'python',
        'sql': 'sql', 
        'cross': 'python'
    }
    
    def __init__(self, parent=None, theme_manager=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._language = 'python'
        self._content = ''
        self._selection = ''
        self._is_ready = False
        self._min_height = 60
        self._pending_text = ''
        self._pending_language = 'python'
        self._themes_injected = False
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        if not MONACO_AVAILABLE:
            from PyQt6.QtWidgets import QLabel
            label = QLabel("monaco-qt não está instalado.\nExecute: pip install monaco-qt")
            label.setStyleSheet("color: #ff6b6b; padding: 20px; background: #1e1e1e;")
            layout.addWidget(label)
            return
        
        self.monaco = BaseMonacoWidget()
        self.monaco.setMinimumHeight(self._min_height)
        
        # Bridge para atalhos de execução
        self._exec_bridge = ExecuteBridge(self)
        self._exec_bridge.execute_requested.connect(self.execute_requested.emit)
        
        # Conectar sinais
        self.monaco.textChanged.connect(self._on_text_changed)
        self.monaco.initialized.connect(self._on_initialized)
        
        layout.addWidget(self.monaco)
    
    def _on_initialized(self):
        """Chamado quando o Monaco está pronto."""
        self._is_ready = True
        
        # Injetar temas customizados e configurações
        self._inject_custom_themes()
        self._inject_editor_options()
        self._inject_autocomplete()
        self._inject_keybindings()
        
        # Aplicar texto e linguagem pendentes
        if self._pending_text:
            self.monaco.setText(self._pending_text)
            self._content = self._pending_text
        
        if self._pending_language:
            monaco_lang = self.LANGUAGE_MAP.get(self._pending_language, 'python')
            self.monaco.setLanguage(monaco_lang)
        
        # Aplicar tema do sistema
        self.apply_theme()
    
    def _get_theme_colors(self):
        """Obtém as cores do tema atual do sistema."""
        if not self.theme_manager:
            return None
        
        try:
            theme = self.theme_manager.get_current_theme()
            return {
                'editor': theme.get('editor', {}),
                'python': theme.get('python', {}),
                'sql': theme.get('sql', {}),
                'app': theme.get('app', {}),
                'name': self.theme_manager.current_theme
            }
        except:
            return None
    
    def _inject_custom_themes(self):
        """Injeta temas customizados no Monaco."""
        if not MONACO_AVAILABLE or not self._is_ready or self._themes_injected:
            return
        
        colors = self._get_theme_colors()
        if not colors:
            # Usar tema padrão se não houver theme_manager
            self.monaco.setTheme('vs-dark')
            self._themes_injected = True
            return
        
        editor = colors['editor']
        python = colors['python']
        sql_colors = colors['sql']
        app = colors['app']
        
        js_code = f'''
        (function() {{
            // Tema customizado baseado nas cores do sistema
            monaco.editor.defineTheme('datapyn-theme', {{
                base: '{self._get_base_theme()}',
                inherit: true,
                rules: [
                    // Python
                    {{ token: 'keyword', foreground: '{python.get("keyword", "#569cd6")[1:]}', fontStyle: 'bold' }},
                    {{ token: 'string', foreground: '{python.get("string", "#ce9178")[1:]}' }},
                    {{ token: 'string.escape', foreground: '{python.get("string", "#ce9178")[1:]}' }},
                    {{ token: 'number', foreground: '{python.get("number", "#b5cea8")[1:]}' }},
                    {{ token: 'comment', foreground: '{python.get("comment", "#6a9955")[1:]}', fontStyle: 'italic' }},
                    {{ token: 'type', foreground: '{python.get("classname", "#4ec9b0")[1:]}' }},
                    {{ token: 'class', foreground: '{python.get("classname", "#4ec9b0")[1:]}' }},
                    {{ token: 'function', foreground: '{python.get("function", "#dcdcaa")[1:]}' }},
                    {{ token: 'variable', foreground: '{python.get("identifier", "#9cdcfe")[1:]}' }},
                    {{ token: 'identifier', foreground: '{editor.get("foreground", "#d4d4d4")[1:]}' }},
                    
                    // SQL
                    {{ token: 'keyword.sql', foreground: '{sql_colors.get("keyword", "#569cd6")[1:]}', fontStyle: 'bold' }},
                    {{ token: 'string.sql', foreground: '{sql_colors.get("string", "#ce9178")[1:]}' }},
                    {{ token: 'number.sql', foreground: '{sql_colors.get("number", "#b5cea8")[1:]}' }},
                    {{ token: 'comment.sql', foreground: '{sql_colors.get("comment", "#6a9955")[1:]}', fontStyle: 'italic' }},
                    {{ token: 'operator.sql', foreground: '{sql_colors.get("operator", "#4ec9b0")[1:]}' }},
                    
                    // Operadores e delimitadores
                    {{ token: 'delimiter', foreground: '{editor.get("foreground", "#d4d4d4")[1:]}' }},
                    {{ token: 'delimiter.bracket', foreground: '{editor.get("foreground", "#d4d4d4")[1:]}' }},
                    {{ token: 'operator', foreground: '{editor.get("foreground", "#d4d4d4")[1:]}' }},
                ],
                colors: {{
                    'editor.background': '{editor.get("background", "#1e1e1e")}',
                    'editor.foreground': '{editor.get("foreground", "#d4d4d4")}',
                    'editorCursor.foreground': '{editor.get("caret", "#ffffff")}',
                    'editor.lineHighlightBackground': '{editor.get("caret_line", "#2a2a2a")}',
                    'editor.selectionBackground': '{editor.get("selection", "#264f78")}',
                    'editorLineNumber.foreground': '{editor.get("margin_fg", "#858585")}',
                    'editorLineNumber.activeForeground': '{editor.get("foreground", "#d4d4d4")}',
                    'editorGutter.background': '{editor.get("margin_bg", "#1e1e1e")}',
                    'editorBracketMatch.background': '{editor.get("brace_match", "#3e3e42")}',
                    'editorBracketMatch.border': '{app.get("accent", "#007acc")}',
                    'editorWidget.background': '{app.get("background", "#1e1e1e")}',
                    'editorWidget.border': '{app.get("border", "#3e3e42")}',
                    'editorSuggestWidget.background': '{app.get("background", "#1e1e1e")}',
                    'editorSuggestWidget.border': '{app.get("border", "#3e3e42")}',
                    'editorSuggestWidget.foreground': '{editor.get("foreground", "#d4d4d4")}',
                    'editorSuggestWidget.selectedBackground': '{app.get("accent", "#007acc")}',
                    'editorSuggestWidget.highlightForeground': '{app.get("accent", "#007acc")}',
                    'list.hoverBackground': '{editor.get("caret_line", "#2a2a2a")}',
                    'list.activeSelectionBackground': '{app.get("accent", "#007acc")}',
                    'scrollbar.shadow': '#00000000',
                    'scrollbarSlider.background': '{app.get("border", "#3e3e42")}80',
                    'scrollbarSlider.hoverBackground': '{app.get("border", "#3e3e42")}',
                    'scrollbarSlider.activeBackground': '{app.get("accent", "#007acc")}',
                }}
            }});
            
            // Aplicar tema
            monaco.editor.setTheme('datapyn-theme');
            console.log('Tema datapyn-theme aplicado');
        }})();
        '''
        
        try:
            self.monaco.page().runJavaScript(js_code)
            self._themes_injected = True
        except Exception as e:
            print(f"Erro ao injetar temas: {e}")
    
    def _get_base_theme(self):
        """Retorna o tema base do Monaco (vs ou vs-dark)."""
        if not self.theme_manager:
            return 'vs-dark'
        
        theme_name = self.theme_manager.current_theme
        if theme_name == 'light':
            return 'vs'
        return 'vs-dark'
    
    def _inject_editor_options(self):
        """Injeta opções de configuração do editor."""
        if not MONACO_AVAILABLE or not self._is_ready:
            return
        
        js_code = '''
        (function() {
            if (typeof editor !== 'undefined' && editor) {
                editor.updateOptions({
                    // Visual
                    fontSize: 14,
                    fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace",
                    fontLigatures: true,
                    lineHeight: 22,
                    letterSpacing: 0.5,
                    
                    // Aparência
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    renderLineHighlight: 'all',
                    renderWhitespace: 'selection',
                    cursorBlinking: 'smooth',
                    cursorSmoothCaretAnimation: 'on',
                    smoothScrolling: true,
                    
                    // Números de linha
                    lineNumbers: 'on',
                    lineNumbersMinChars: 3,
                    glyphMargin: false,
                    folding: true,
                    foldingHighlight: true,
                    
                    // Scroll
                    scrollbar: {
                        vertical: 'auto',
                        horizontal: 'auto',
                        verticalScrollbarSize: 10,
                        horizontalScrollbarSize: 10,
                        useShadows: false
                    },
                    
                    // Indentação
                    tabSize: 4,
                    insertSpaces: true,
                    detectIndentation: true,
                    autoIndent: 'full',
                    
                    // Brackets
                    bracketPairColorization: { enabled: true },
                    matchBrackets: 'always',
                    
                    // Seleção
                    selectionHighlight: true,
                    occurrencesHighlight: true,
                    
                    // Autocomplete
                    quickSuggestions: {
                        other: true,
                        comments: false,
                        strings: true
                    },
                    suggestOnTriggerCharacters: true,
                    acceptSuggestionOnEnter: 'on',
                    tabCompletion: 'on',
                    wordBasedSuggestions: 'currentDocument',
                    suggestSelection: 'first',
                    suggest: {
                        showKeywords: true,
                        showSnippets: true,
                        showClasses: true,
                        showFunctions: true,
                        showVariables: true,
                        showConstants: true,
                        showModules: true,
                        preview: true,
                        previewMode: 'subwordSmart',
                        shareSuggestSelections: true,
                        filterGraceful: true
                    },
                    
                    // Hover
                    hover: {
                        enabled: true,
                        delay: 300
                    },
                    
                    // Links
                    links: true,
                    
                    // Formatação
                    formatOnType: true,
                    formatOnPaste: true,
                });
                console.log('Opções do editor atualizadas');
            }
        })();
        '''
        
        try:
            self.monaco.page().runJavaScript(js_code)
        except Exception as e:
            print(f"Erro ao configurar editor: {e}")
    
    def _inject_autocomplete(self):
        """Injeta providers de autocomplete para Python e SQL."""
        if not MONACO_AVAILABLE or not self._is_ready:
            return
        
        js_code = '''
        (function() {
            // Python autocomplete
            var pythonKeywords = [
                'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
                'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
                'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
                'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try',
                'while', 'with', 'yield'
            ];
            
            var pythonBuiltins = [
                'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'breakpoint', 'bytearray',
                'bytes', 'callable', 'chr', 'classmethod', 'compile', 'complex',
                'delattr', 'dict', 'dir', 'divmod', 'enumerate', 'eval', 'exec',
                'filter', 'float', 'format', 'frozenset', 'getattr', 'globals',
                'hasattr', 'hash', 'help', 'hex', 'id', 'input', 'int', 'isinstance',
                'issubclass', 'iter', 'len', 'list', 'locals', 'map', 'max',
                'memoryview', 'min', 'next', 'object', 'oct', 'open', 'ord', 'pow',
                'print', 'property', 'range', 'repr', 'reversed', 'round', 'set',
                'setattr', 'slice', 'sorted', 'staticmethod', 'str', 'sum', 'super',
                'tuple', 'type', 'vars', 'zip', '__import__'
            ];
            
            var pythonModules = [
                'os', 'sys', 'json', 'datetime', 'math', 'random', 're', 'collections',
                'itertools', 'functools', 'pathlib', 'typing', 'dataclasses', 'enum',
                'pandas', 'numpy', 'matplotlib', 'seaborn', 'sklearn', 'scipy',
                'requests', 'urllib', 'asyncio', 'threading', 'multiprocessing'
            ];
            
            var pandasMethods = [
                'DataFrame', 'Series', 'read_csv', 'read_excel', 'read_sql', 'read_json',
                'to_csv', 'to_excel', 'to_sql', 'to_json', 'head', 'tail', 'describe',
                'info', 'shape', 'columns', 'index', 'values', 'dtypes', 'isnull',
                'dropna', 'fillna', 'merge', 'concat', 'groupby', 'pivot_table',
                'sort_values', 'sort_index', 'reset_index', 'set_index', 'loc', 'iloc',
                'apply', 'map', 'transform', 'agg', 'filter', 'query', 'where', 'mask',
                'duplicated', 'drop_duplicates', 'unique', 'value_counts', 'nunique',
                'sum', 'mean', 'median', 'std', 'var', 'min', 'max', 'count', 'corr',
                'plot', 'hist', 'scatter', 'bar', 'line', 'pie', 'box'
            ];
            
            // SQL autocomplete
            var sqlKeywords = [
                'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN',
                'IS', 'NULL', 'AS', 'ON', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER',
                'FULL', 'CROSS', 'NATURAL', 'UNION', 'ALL', 'DISTINCT', 'ORDER', 'BY',
                'ASC', 'DESC', 'NULLS', 'FIRST', 'LAST', 'GROUP', 'HAVING', 'LIMIT',
                'OFFSET', 'FETCH', 'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE',
                'CREATE', 'TABLE', 'DATABASE', 'INDEX', 'VIEW', 'TRIGGER', 'PROCEDURE',
                'FUNCTION', 'DROP', 'ALTER', 'ADD', 'COLUMN', 'CONSTRAINT', 'PRIMARY',
                'KEY', 'FOREIGN', 'REFERENCES', 'UNIQUE', 'CHECK', 'DEFAULT', 'AUTO_INCREMENT',
                'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'CAST', 'CONVERT', 'COALESCE',
                'NULLIF', 'EXISTS', 'ANY', 'SOME', 'WITH', 'RECURSIVE', 'CTE', 'WINDOW',
                'OVER', 'PARTITION', 'ROWS', 'RANGE', 'UNBOUNDED', 'PRECEDING', 'FOLLOWING',
                'CURRENT', 'ROW', 'ROLLUP', 'CUBE', 'GROUPING', 'SETS', 'GRANT', 'REVOKE',
                'BEGIN', 'COMMIT', 'ROLLBACK', 'TRANSACTION', 'SAVEPOINT', 'TRUNCATE'
            ];
            
            var sqlFunctions = [
                'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'ROUND', 'FLOOR', 'CEIL', 'ABS',
                'CONCAT', 'SUBSTRING', 'SUBSTR', 'LENGTH', 'LEN', 'UPPER', 'LOWER',
                'TRIM', 'LTRIM', 'RTRIM', 'REPLACE', 'REVERSE', 'LEFT', 'RIGHT',
                'LPAD', 'RPAD', 'INSTR', 'LOCATE', 'POSITION', 'CHARINDEX',
                'NOW', 'CURRENT_DATE', 'CURRENT_TIME', 'CURRENT_TIMESTAMP', 'GETDATE',
                'DATE', 'TIME', 'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND',
                'DATEADD', 'DATEDIFF', 'DATE_FORMAT', 'STR_TO_DATE', 'TO_DATE', 'TO_CHAR',
                'EXTRACT', 'DATE_PART', 'DATE_TRUNC', 'LAST_DAY', 'ADD_MONTHS',
                'IFNULL', 'ISNULL', 'NVL', 'NVL2', 'NULLIF', 'COALESCE', 'IIF', 'DECODE',
                'ROW_NUMBER', 'RANK', 'DENSE_RANK', 'NTILE', 'LAG', 'LEAD',
                'FIRST_VALUE', 'LAST_VALUE', 'NTH_VALUE', 'LISTAGG', 'STRING_AGG',
                'GROUP_CONCAT', 'JSON_OBJECT', 'JSON_ARRAY', 'JSON_VALUE', 'JSON_QUERY'
            ];
            
            var sqlTypes = [
                'INT', 'INTEGER', 'BIGINT', 'SMALLINT', 'TINYINT', 'DECIMAL', 'NUMERIC',
                'FLOAT', 'REAL', 'DOUBLE', 'MONEY', 'BIT', 'BOOLEAN', 'BOOL',
                'CHAR', 'VARCHAR', 'NCHAR', 'NVARCHAR', 'TEXT', 'NTEXT', 'CLOB',
                'DATE', 'TIME', 'DATETIME', 'TIMESTAMP', 'YEAR', 'INTERVAL',
                'BINARY', 'VARBINARY', 'BLOB', 'IMAGE', 'JSON', 'XML', 'UUID', 'GUID'
            ];
            
            // Registrar provider Python
            monaco.languages.registerCompletionItemProvider('python', {
                provideCompletionItems: function(model, position) {
                    var word = model.getWordUntilPosition(position);
                    var range = {
                        startLineNumber: position.lineNumber,
                        endLineNumber: position.lineNumber,
                        startColumn: word.startColumn,
                        endColumn: word.endColumn
                    };
                    
                    var suggestions = [];
                    
                    // Keywords
                    pythonKeywords.forEach(function(kw) {
                        suggestions.push({
                            label: kw,
                            kind: monaco.languages.CompletionItemKind.Keyword,
                            insertText: kw,
                            range: range,
                            detail: 'keyword'
                        });
                    });
                    
                    // Builtins
                    pythonBuiltins.forEach(function(fn) {
                        suggestions.push({
                            label: fn,
                            kind: monaco.languages.CompletionItemKind.Function,
                            insertText: fn + '($0)',
                            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                            range: range,
                            detail: 'built-in function'
                        });
                    });
                    
                    // Modules
                    pythonModules.forEach(function(mod) {
                        suggestions.push({
                            label: mod,
                            kind: monaco.languages.CompletionItemKind.Module,
                            insertText: mod,
                            range: range,
                            detail: 'module'
                        });
                    });
                    
                    // Pandas methods
                    pandasMethods.forEach(function(m) {
                        suggestions.push({
                            label: m,
                            kind: monaco.languages.CompletionItemKind.Method,
                            insertText: m,
                            range: range,
                            detail: 'pandas'
                        });
                    });
                    
                    // Snippets
                    suggestions.push({
                        label: 'def',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'def ${1:function_name}(${2:args}):\\n\\t${0:pass}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'function definition',
                        documentation: 'Define a new function'
                    });
                    
                    suggestions.push({
                        label: 'class',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'class ${1:ClassName}:\\n\\tdef __init__(self${2:, args}):\\n\\t\\t${0:pass}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'class definition',
                        documentation: 'Define a new class'
                    });
                    
                    suggestions.push({
                        label: 'for',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'for ${1:item} in ${2:items}:\\n\\t${0:pass}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'for loop'
                    });
                    
                    suggestions.push({
                        label: 'if',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'if ${1:condition}:\\n\\t${0:pass}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'if statement'
                    });
                    
                    suggestions.push({
                        label: 'try',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'try:\\n\\t${1:pass}\\nexcept ${2:Exception} as e:\\n\\t${0:pass}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'try/except block'
                    });
                    
                    suggestions.push({
                        label: 'with',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'with ${1:expression} as ${2:var}:\\n\\t${0:pass}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'with statement'
                    });
                    
                    suggestions.push({
                        label: 'import pandas',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'import pandas as pd',
                        range: range,
                        detail: 'import pandas'
                    });
                    
                    suggestions.push({
                        label: 'import numpy',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'import numpy as np',
                        range: range,
                        detail: 'import numpy'
                    });
                    
                    return { suggestions: suggestions };
                }
            });
            
            // Registrar provider SQL
            monaco.languages.registerCompletionItemProvider('sql', {
                provideCompletionItems: function(model, position) {
                    var word = model.getWordUntilPosition(position);
                    var range = {
                        startLineNumber: position.lineNumber,
                        endLineNumber: position.lineNumber,
                        startColumn: word.startColumn,
                        endColumn: word.endColumn
                    };
                    
                    var suggestions = [];
                    
                    // Keywords
                    sqlKeywords.forEach(function(kw) {
                        suggestions.push({
                            label: kw,
                            kind: monaco.languages.CompletionItemKind.Keyword,
                            insertText: kw,
                            range: range,
                            detail: 'keyword'
                        });
                        // Também adicionar lowercase
                        suggestions.push({
                            label: kw.toLowerCase(),
                            kind: monaco.languages.CompletionItemKind.Keyword,
                            insertText: kw.toLowerCase(),
                            range: range,
                            detail: 'keyword'
                        });
                    });
                    
                    // Functions
                    sqlFunctions.forEach(function(fn) {
                        suggestions.push({
                            label: fn,
                            kind: monaco.languages.CompletionItemKind.Function,
                            insertText: fn + '($0)',
                            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                            range: range,
                            detail: 'function'
                        });
                    });
                    
                    // Types
                    sqlTypes.forEach(function(t) {
                        suggestions.push({
                            label: t,
                            kind: monaco.languages.CompletionItemKind.TypeParameter,
                            insertText: t,
                            range: range,
                            detail: 'data type'
                        });
                    });
                    
                    // Snippets
                    suggestions.push({
                        label: 'SELECT',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'SELECT ${1:*}\\nFROM ${2:table}\\nWHERE ${3:condition}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'SELECT statement',
                        documentation: 'Basic SELECT query'
                    });
                    
                    suggestions.push({
                        label: 'INSERT',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'INSERT INTO ${1:table} (${2:columns})\\nVALUES (${3:values})',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'INSERT statement'
                    });
                    
                    suggestions.push({
                        label: 'UPDATE',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'UPDATE ${1:table}\\nSET ${2:column} = ${3:value}\\nWHERE ${4:condition}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'UPDATE statement'
                    });
                    
                    suggestions.push({
                        label: 'DELETE',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'DELETE FROM ${1:table}\\nWHERE ${2:condition}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'DELETE statement'
                    });
                    
                    suggestions.push({
                        label: 'JOIN',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: '${1:LEFT} JOIN ${2:table} ON ${3:condition}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'JOIN clause'
                    });
                    
                    suggestions.push({
                        label: 'CTE',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'WITH ${1:cte_name} AS (\\n\\t${2:SELECT * FROM table}\\n)\\nSELECT * FROM ${1:cte_name}',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'Common Table Expression'
                    });
                    
                    suggestions.push({
                        label: 'CASE',
                        kind: monaco.languages.CompletionItemKind.Snippet,
                        insertText: 'CASE\\n\\tWHEN ${1:condition} THEN ${2:result}\\n\\tELSE ${3:default}\\nEND',
                        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                        range: range,
                        detail: 'CASE expression'
                    });
                    
                    return { suggestions: suggestions };
                }
            });
            
            console.log('Autocomplete providers registrados');
        })();
        '''
        
        try:
            self.monaco.page().runJavaScript(js_code)
        except Exception as e:
            print(f"Erro ao configurar autocomplete: {e}")
    
    def _inject_keybindings(self):
        """Injeta atalhos de teclado no Monaco Editor."""
        if not MONACO_AVAILABLE or not self._is_ready:
            return
        
        try:
            page = self.monaco.page()
            channel = page.webChannel()
            if channel:
                channel.registerObject('execBridge', self._exec_bridge)
            
            js_code = '''
            (function() {
                if (typeof editor !== 'undefined' && editor) {
                    // F5 - Executar
                    editor.addCommand(monaco.KeyCode.F5, function() {
                        if (typeof execBridge !== 'undefined') {
                            execBridge.requestExecute();
                        }
                    });
                    // Shift+Enter - Executar
                    editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, function() {
                        if (typeof execBridge !== 'undefined') {
                            execBridge.requestExecute();
                        }
                    });
                    // Ctrl+Enter - Executar (alternativo)
                    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, function() {
                        if (typeof execBridge !== 'undefined') {
                            execBridge.requestExecute();
                        }
                    });
                    console.log('Keybindings registrados');
                }
            })();
            '''
            page.runJavaScript(js_code)
        except Exception as e:
            print(f"Erro ao injetar keybindings: {e}")
    
    def _on_text_changed(self, text: str):
        """Chamado quando o texto muda no editor."""
        self._content = text
        self.content_changed.emit()
        self.textChanged.emit()
    
    # === API compatível com QScintilla ===
    
    def text(self) -> str:
        """Retorna o texto atual do editor."""
        if MONACO_AVAILABLE and self._is_ready:
            return self.monaco.text()
        return self._content
    
    def setText(self, text: str):
        """Define o texto do editor."""
        self._content = text
        if MONACO_AVAILABLE:
            if self._is_ready:
                self.monaco.setText(text)
            else:
                self._pending_text = text
    
    def selectedText(self) -> str:
        """Retorna o texto selecionado."""
        return self._selection
    
    def hasSelectedText(self) -> bool:
        """Verifica se há texto selecionado."""
        return len(self._selection) > 0
    
    def set_lexer_type(self, lexer_type: str):
        """Define o tipo de linguagem/lexer."""
        self._language = lexer_type
        monaco_lang = self.LANGUAGE_MAP.get(lexer_type, 'python')
        
        if MONACO_AVAILABLE:
            if self._is_ready:
                self.monaco.setLanguage(monaco_lang)
            else:
                self._pending_language = lexer_type
    
    def get_lexer_type(self) -> str:
        """Retorna o tipo de linguagem/lexer atual."""
        return self._language
    
    def setFocus(self):
        """Foca no editor."""
        if MONACO_AVAILABLE and hasattr(self, 'monaco'):
            self.monaco.setFocus()
        super().setFocus()
    
    def apply_theme(self):
        """Aplica o tema atual do sistema no editor."""
        if not MONACO_AVAILABLE or not self._is_ready:
            return
        
        # Re-injetar temas customizados quando o tema mudar
        self._themes_injected = False
        self._inject_custom_themes()
    
    def setMinimumHeight(self, height: int):
        """Define altura mínima."""
        self._min_height = height
        super().setMinimumHeight(height)
        if MONACO_AVAILABLE and hasattr(self, 'monaco'):
            self.monaco.setMinimumHeight(height)
    
    def setFixedHeight(self, height: int):
        """Define altura fixa."""
        super().setFixedHeight(height)
        if MONACO_AVAILABLE and hasattr(self, 'monaco'):
            self.monaco.setFixedHeight(height)

