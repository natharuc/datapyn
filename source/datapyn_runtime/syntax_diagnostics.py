"""Bounded, Qt-free syntax diagnostics over source and immutable snapshots.

Nothing in this module executes user code, resolves imports, or accesses a DB.
All marker columns use Monaco's UTF-16 coordinates, including non-BMP text.
"""

from __future__ import annotations

import ast
import builtins
from bisect import bisect_right
from functools import lru_cache
import re
import symtable
import time

MAX_SYNTAX_BYTES = 1024 * 1024
MAX_SQL_BATCH_CHARACTERS = 256 * 1024
MAX_SQL_STATEMENTS = 500
MAX_SQL_NESTING = 100
MAX_SQL_TOKENS = 30_000
MAX_AST_NODES = 100_000
MAX_DIAGNOSTICS = 100
SYNTAX_BUDGET_SECONDS = 0.2

_DIALECTS = {
    "mssql": "tsql", "sqlserver": "tsql", "tsql": "tsql",
    "postgresql": "postgres", "postgres": "postgres", "redshift": "redshift",
    "mysql": "mysql", "mariadb": "mysql", "sqlite": "sqlite", "oracle": "oracle",
    "databricks": "databricks", "spark": "spark", "snowflake": "snowflake", "bigquery": "bigquery",
}
_GO = re.compile(r"(?im)^[ \t]*GO(?:[ \t]+\d+)?[ \t]*(?:--[^\n]*)?\r?$")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PYTHON_GLOBALS = set(dir(builtins)) | {"pd", "np", "pl", "plt", "sns", "df", "db", "db_engine"}


def _localized(locale, english, portuguese):
    return portuguese if locale == "pt-BR" else english


class _Document:
    def __init__(self, code):
        self.code = code
        self.lines = code.split("\n")
        self.starts = [0]
        self.starts.extend(match.end() for match in re.finditer("\n", code))

    def position(self, offset):
        offset = max(0, min(len(self.code), offset))
        line = bisect_right(self.starts, offset) - 1
        column = len(self.code[self.starts[line]:offset].encode("utf-16-le")) // 2 + 1
        return line + 1, column

    def offset(self, line, column, *, byte_column=False):
        index = max(0, min(len(self.lines) - 1, int(line or 1) - 1))
        text = self.lines[index]
        column = max(0, int(column or 1) - 1)
        if byte_column:
            column = len(text.encode("utf-8")[:column].decode("utf-8", errors="ignore"))
        return self.starts[index] + min(len(text), column)

    def marker(self, start, end, message, severity="error"):
        start = max(0, min(len(self.code), start))
        end = max(start, min(len(self.code), end))
        start_line, start_column = self.position(start)
        end_line, end_column = self.position(end)
        if start == end:
            end_column += 1
        return {"start_line": start_line, "start_column": start_column,
                "end_line": end_line, "end_column": end_column,
                "message": message, "severity": severity}


def _mask_shared_parameters(code):
    # This uses the same delimiter and matching rules as execution, but never
    # substitutes values. Width stays identical for accurate original spans.
    from src.utils.sql_parameter_service import _scan_shared_parameters
    _, result = _scan_shared_parameters(code, lambda _name, token, _start, _end: "0" + " " * (len(token) - 1))
    return result


def _python_message(exc, locale):
    message = str(exc.msg or exc)
    if locale != "pt-BR":
        return f"{type(exc).__name__}: {message}"
    translations = {
        "invalid syntax": "sintaxe inválida",
        "expected ':'": "esperado ':' ao final da instrução",
        "unexpected indent": "indentação inesperada",
        "unindent does not match any outer indentation level": "a indentação não corresponde ao bloco anterior",
        "inconsistent use of tabs and spaces in indentation": "a indentação mistura tabulações e espaços",
        "'return' outside function": "'return' só pode ser usado dentro de uma função",
        "'break' outside loop": "'break' só pode ser usado dentro de um laço",
        "'continue' not properly in loop": "'continue' só pode ser usado dentro de um laço",
        "too many levels of indentation": "há níveis de indentação demais",
        "too many nested parentheses": "há parênteses aninhados demais",
        "unexpected EOF while parsing": "o código terminou antes de completar a instrução",
    }
    if message in translations:
        message = translations[message]
    elif message.startswith("expected an indented block"):
        message = "esperado um bloco indentado após a instrução"
    elif match := re.match(r"(.+) was never closed", message):
        message = f"{match.group(1)} não foi fechado"
    elif message.startswith("unterminated string literal"):
        message = "a string não foi fechada"
    elif message.startswith("unterminated triple-quoted string literal"):
        message = "a string com aspas triplas não foi fechada"
    elif match := re.match(r"closing parenthesis (.+) does not match opening parenthesis (.+)", message):
        message = f"o fechamento {match.group(1)} não corresponde à abertura {match.group(2)}"
    elif message.startswith("cannot assign to"):
        message = "o lado esquerdo da atribuição não aceita esse valor; verifique se deveria usar '=='"
    return f"Python: {message}"


def _python_error(exc, document, locale):
    # Parser errors expose character columns; compiler scope errors with no
    # source text expose the AST's UTF-8 byte columns instead.
    byte_column = exc.text is None
    start = document.offset(exc.lineno, exc.offset, byte_column=byte_column)
    end = document.offset(getattr(exc, "end_lineno", None) or exc.lineno,
                          getattr(exc, "end_offset", None) or (int(exc.offset or 1) + 1),
                          byte_column=byte_column)
    return document.marker(start, end, _python_message(exc, locale))


@lru_cache(maxsize=8)
def _context_symbols(code):
    # An unfinished peer must not invalidate names in all earlier blocks.
    # Parsing context is advisory and cached separately from active syntax.
    for _attempt in range(3):
        try:
            table = symtable.symtable(code, "<context>", "exec")
            return frozenset(symbol.get_name() for symbol in table.get_symbols()
                             if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace())
        except SyntaxError as exc:
            code = "\n".join(code.splitlines()[:max(0, int(exc.lineno or 1) - 1)])
        except (ValueError, RecursionError, MemoryError):
            break
    return frozenset()


def _context_names(params, variables):
    known = _PYTHON_GLOBALS | set(variables)
    for code in (params.get("global_imports") or "", params.get("preamble") or ""):
        if not isinstance(code, str) or len(code) > MAX_SYNTAX_BYTES:
            continue
        known.update(_context_symbols(_mask_shared_parameters(code)))
    return known


class _ModuleBindings(ast.NodeVisitor):
    """Module bindings excluding function scopes and inlined comprehensions."""

    def __init__(self, tree):
        self.names = set()
        self.visit(tree)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Import(self, node):
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node):
        self.names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node):
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)

    def visit_ListComp(self, node):
        self.visit(node.generators[0].iter)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Lambda(self, node):
        pass


class _PythonNames(ast.NodeVisitor):
    """Use compiler scopes so arguments, closures and comprehensions are local."""

    def __init__(self, tree, table, known, document, locale, expired):
        self.table = table
        self.known = known | _ModuleBindings(tree).names
        self.document, self.locale, self.expired = document, locale, expired
        self.markers = []
        self.visited = 0
        self.partial = False
        self.children = {}
        self.used = set()
        self.comprehension_locals = []
        self.visit(tree)

    def visit(self, node):
        self.visited += 1
        if self.visited > MAX_AST_NODES or len(self.markers) >= MAX_DIAGNOSTICS:
            self.partial = True
            return None
        if self.visited % 256 == 0 and self.expired():
            self.partial = True
            return None
        return super().visit(node)

    def _scope(self, node, name, body):
        children = self.children.setdefault(id(self.table), self.table.get_children())
        child = next((item for item in children if id(item) not in self.used and
                      item.get_name() == name and item.get_lineno() == node.lineno), None)
        previous = self.table
        # Python 3.12 inlines list/set/dict comprehensions in the parent symbol
        # table (PEP 709); generator expressions still have their own scope.
        if child is not None:
            self.used.add(id(child))
            self.table = child
        try:
            for value in body:
                self.visit(value)
        finally:
            self.table = previous

    def visit_Name(self, node):
        if (not isinstance(node.ctx, ast.Load) or node.id in self.known or node.id.startswith("__")
                or any(node.id in names for names in self.comprehension_locals)):
            return
        try:
            symbol = self.table.lookup(node.id)
        except KeyError:
            return
        if not symbol.is_global():
            return
        start = self.document.offset(node.lineno, node.col_offset + 1, byte_column=True)
        end = self.document.offset(node.end_lineno, node.end_col_offset + 1, byte_column=True)
        message = _localized(self.locale, f"Undefined name: {node.id}",
                             f"Nome não definido no bloco ou na sessão: {node.id}")
        self.markers.append(self.document.marker(start, end, message, "warning"))

    def visit_FunctionDef(self, node):
        for value in [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults, node.returns]:
            if value is not None:
                self.visit(value)
        self._scope(node, node.name, node.body)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        for value in [*node.decorator_list, *node.bases, *node.keywords]:
            self.visit(value)
        self._scope(node, node.name, node.body)

    def visit_Lambda(self, node):
        for value in [*node.args.defaults, *node.args.kw_defaults]:
            if value is not None:
                self.visit(value)
        self._scope(node, "lambda", [node.body])

    def _comprehension(self, node, name):
        self.visit(node.generators[0].iter)
        body = []
        for index, generator in enumerate(node.generators):
            if index:
                body.append(generator.iter)
            body.extend(generator.ifs)
        body.extend([node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt])
        local_names = {value.id for generator in node.generators for value in ast.walk(generator.target)
                       if isinstance(value, ast.Name)}
        self.comprehension_locals.append(local_names)
        try:
            self._scope(node, name, body)
        finally:
            self.comprehension_locals.pop()

    def visit_ListComp(self, node):
        self._comprehension(node, "listcomp")

    def visit_SetComp(self, node):
        self._comprehension(node, "setcomp")

    def visit_DictComp(self, node):
        self._comprehension(node, "dictcomp")

    def visit_GeneratorExp(self, node):
        self._comprehension(node, "genexpr")


def _python(code, document, params, context, expired):
    locale = params.get("locale")
    if "\x00" in code:
        offset = code.index("\x00")
        return [document.marker(offset, offset + 1,
            _localized(locale, "Python: source contains a null character.",
                       "Python: o código contém um caractere nulo."))], False, None
    try:
        tree = ast.parse(code, filename="<block>")
        # AST parsing accepts return/break/await outside their legal scope.
        # Compilation catches these syntax errors without running any bytecode.
        compile(tree, "<block>", "exec")
    except SyntaxError as exc:
        return [_python_error(exc, document, locale)], False, None
    except (RecursionError, MemoryError, ValueError):
        return [], True, _localized(locale, "Validation paused: this Python block is too complex to parse safely.",
                                   "Validação pausada: este bloco Python é complexo demais para analisar com segurança.")
    if expired():
        return [], True, None
    known = _context_names(params, context.get("variables") or {})
    try:
        table = symtable.symtable(code, "<block>", "exec")
        if expired():
            return [], True, None
        names = _PythonNames(tree, table, known, document, locale, expired)
    except (SyntaxError, RecursionError, MemoryError):
        return [], True, None
    return names.markers, names.partial, None


def _sql_code_mask(code, db_type):
    """Blank quoted text/comments, including nested T-SQL/PostgreSQL comments."""
    opening = re.compile(r"--|/\*|'|\"|`|\[|\$(?:[A-Za-z_]\w*)?\$")
    comments = re.compile(r"/\*|\*/")
    backslash_escape = db_type in {"postgresql", "postgres", "mysql", "mariadb", "databricks", "spark"}
    output, index, copied = [], 0, 0
    while match := opening.search(code, index):
        start, token = match.start(), match.group(0)
        if token == "--":
            end = code.find("\n", match.end())
            end = len(code) if end < 0 else end
        elif token == "/*":
            depth, end = 1, match.end()
            while depth:
                delimiter = comments.search(code, end)
                if delimiter is None:
                    end = len(code)
                    break
                depth += 1 if delimiter.group(0) == "/*" else -1
                end = delimiter.end()
        elif token.startswith("$"):
            closing = code.find(token, match.end())
            end = len(code) if closing < 0 else closing + len(token)
        else:
            closing = "]" if token == "[" else token
            end = match.end()
            while end < len(code):
                if backslash_escape and code[end] == "\\":
                    end += 2
                    continue
                if code[end] == closing:
                    end += 1
                    if end < len(code) and code[end] == closing:
                        end += 1
                        continue
                    break
                end += 1
        output.append(code[copied:start])
        output.append(re.sub(r"[^\n\r]", " ", code[start:end]))
        copied = index = end
    output.append(code[copied:])
    return "".join(output)


def _sql_message(description, locale):
    description = _ANSI.sub("", str(description)).strip()
    if locale != "pt-BR":
        # Internal Token representations are not actionable editor messages.
        return "SQL: " + re.sub(r" but got <Token[^>]*>", "", description)
    if description.startswith("Expected table name"):
        description = "esperado um nome de tabela após FROM/JOIN"
    elif description.startswith("Expected CTE to have alias"):
        description = "a expressão WITH precisa de um nome para a CTE"
    elif description.startswith("Required keyword: 'this'"):
        description = "falta uma expressão ou valor nesta instrução"
    elif description.startswith("Required keyword: 'expression'"):
        description = "falta uma expressão após o operador"
    elif description.startswith("Invalid expression / Unexpected token"):
        description = "token inesperado; verifique a palavra-chave, a vírgula ou o operador neste ponto"
    elif match := re.match(r"Expecting (.+)", description):
        description = f"esperado {match.group(1)} neste ponto"
    elif description.startswith("Expected"):
        description = description.replace("Expected", "Esperado", 1)
    return "SQL: " + re.sub(r" but got <Token[^>]*>", "", description)


def _sql(code, document, params, context, expired):
    from sqlglot import exp
    from sqlglot.dialects import Dialect
    from sqlglot.errors import ParseError, TokenError
    from src.services.syntax_validator import _silence_sqlglot_warnings
    from .sql_schema_diagnostics import SchemaWarnings

    locale = params.get("locale")
    db_type = str(params.get("db_type") or (context.get("schema") or {}).get("db_type") or "tsql").lower()
    dialect = Dialect.get_or_raise(_DIALECTS.get(db_type, "tsql"))
    # GO is a batch separator only outside strings, identifiers and comments.
    protected = _sql_code_mask(code, db_type)
    boundaries = list(_GO.finditer(protected)) if _DIALECTS.get(db_type, "tsql") == "tsql" else []
    spans, start = [], 0
    for match in boundaries:
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(code)))
    markers, partial, message, statements = [], False, None, 0
    semantic_batches = []
    for start, end in spans:
        if expired():
            partial = True
            break
        batch = code[start:end]
        if not batch.strip():
            continue
        if len(batch) > MAX_SQL_BATCH_CHARACTERS:
            partial = True
            message = _localized(locale, "Validation paused: a SQL batch exceeds 256 KiB. Split the batch to validate it fully.",
                                 "Validação parcial: um lote SQL ultrapassa 256 KiB. Divida o lote para validar todo o conteúdo.")
            continue
        try:
            tokens = dialect.tokenize(batch)
            if len(tokens) > MAX_SQL_TOKENS:
                partial = True
                message = _localized(locale, "Validation partial: a SQL batch exceeds 30,000 tokens. Split the batch to validate it fully.",
                                     "Validação parcial: um lote SQL ultrapassa 30.000 tokens. Divida o lote para validar todo o conteúdo.")
                break
            count, in_statement = 0, False
            for token in tokens:
                if token.token_type.name == "SEMICOLON":
                    in_statement = False
                elif not in_statement:
                    count += 1
                    in_statement = True
            if statements + count > MAX_SQL_STATEMENTS:
                partial = True
                message = _localized(locale, "Validation partial: this block exceeds the 500-statement limit.",
                                     "Validação parcial: este bloco ultrapassa o limite de 500 instruções.")
                break
            statements += count
            depth = 0
            too_deep = False
            for token in tokens:
                if token.token_type.name in {"L_PAREN", "L_BRACE", "L_BRACKET"}:
                    depth += 1
                elif token.token_type.name in {"R_PAREN", "R_BRACE", "R_BRACKET"}:
                    depth -= 1
                if depth > MAX_SQL_NESTING:
                    partial = True
                    too_deep = True
                    message = _localized(locale, "Validation paused: SQL nesting exceeds 100 levels.",
                                         "Validação pausada: o SQL ultrapassa 100 níveis de aninhamento.")
                    break
            if too_deep or expired():
                partial = True
                break
            with _silence_sqlglot_warnings():
                expressions = dialect.parser(max_errors=MAX_DIAGNOSTICS).parse(tokens, batch)
            # sqlglot accepts an empty Select AST for `SELECT`/`SELECT FROM t`;
            # those are incomplete executable statements in supported engines.
            empty_selects = sum(not select.expressions for node in expressions if node is not None
                                for select in node.find_all(exp.Select))
            for index, token in enumerate(tokens):
                if empty_selects <= 0 or len(markers) >= MAX_DIAGNOSTICS:
                    break
                if token.token_type.name != "SELECT":
                    continue
                following = index + 1
                while following < len(tokens) and tokens[following].token_type.name in {"DISTINCT", "ALL"}:
                    following += 1
                if following < len(tokens) and tokens[following].token_type.name not in {"FROM", "SEMICOLON", "INTO"}:
                    continue
                markers.append(document.marker(start + token.start, start + token.end + 1,
                    _localized(locale, "SQL: SELECT requires a column, expression or '*'.",
                               "SQL: SELECT precisa de uma coluna, expressão ou '*'.")))
                empty_selects -= 1
            if any(isinstance(node, exp.Command) for node in expressions if node is not None):
                partial = True
                message = _localized(locale, "Validation partial: some dialect-specific commands are not recognized by the local parser.",
                                     "Validação parcial: o analisador local não reconhece alguns comandos específicos deste dialeto.")
            semantic_batches.append((expressions, start))
        except ParseError as exc:
            local = _Document(batch)
            for error in (exc.errors or [])[:MAX_DIAGNOSTICS - len(markers)]:
                error_end = local.offset(error.get("line"), int(error.get("col") or 1) + 1)
                error_start = max(0, error_end - len(error.get("highlight") or ""))
                markers.append(document.marker(start + error_start, start + error_end,
                                               _sql_message(error.get("description") or str(exc), locale)))
        except TokenError as exc:
            cause = str(exc.__cause__ or exc)
            located = re.search(r"from (\d+):(\d+)", cause)
            local = _Document(batch)
            position = local.offset(int(located[1]), int(located[2]) + 1) if located else 0
            quote = re.search(r"Missing (.+?) from", cause)
            text = _localized(locale, f"SQL: unclosed string or identifier{': ' + quote[1] if quote else ''}",
                              f"SQL: string ou identificador não fechado{': ' + quote[1] if quote else ''}")
            if quote and quote[1] == "*/":
                text = _localized(locale, "SQL: block comment is not closed with '*/'.",
                                  "SQL: o comentário de bloco não foi fechado com '*/'.")
            markers.append(document.marker(start + position, start + position + 1, text))
        except (RecursionError, MemoryError):
            partial = True
            break
        if len(markers) >= MAX_DIAGNOSTICS:
            partial = True
            break
    # Advisory metadata checks run after syntax, so a large schema snapshot
    # cannot consume the budget before a genuine parser error is reported.
    schema_warnings = SchemaWarnings(context, document, locale, expired, MAX_DIAGNOSTICS)
    for expressions, start in semantic_batches:
        schema_warnings.add(expressions, start)
    available = MAX_DIAGNOSTICS - len(markers)
    markers.extend(schema_warnings.markers[:available])
    partial = partial or schema_warnings.partial or len(schema_warnings.markers) > available
    return markers, partial, message


def diagnose(params, context=None, *, should_abort=None):
    started = time.perf_counter()
    code, locale = params["code"], params.get("locale")
    partial_message = _localized(locale, "Validation partial: the analysis budget was reached. Simplify or split this block.",
                                 "Validação parcial: o limite de análise foi atingido. Simplifique ou divida este bloco.")
    if len(code) > MAX_SYNTAX_BYTES or len(code.encode("utf-8")) > MAX_SYNTAX_BYTES:
        return {"markers": [], "status": "partial", "duration_ms": 0,
                "message": _localized(locale, "Validation paused: this block exceeds the 1 MiB limit.",
                                      "Validação pausada: este bloco ultrapassa o limite de 1 MiB.")}
    def expired():
        return bool(should_abort and should_abort()) or time.perf_counter() - started >= SYNTAX_BUDGET_SECONDS
    if expired():
        return {"markers": [], "status": "partial", "duration_ms": 0, "message": partial_message}
    document = _Document(code)
    prepared = _mask_shared_parameters(code)
    if not prepared.strip():
        markers, partial, message = [], False, None
    elif params["language"] == "python":
        markers, partial, message = _python(prepared, document, params, context or {}, expired)
    else:
        markers, partial, message = _sql(prepared, document, params, context or {}, expired)
    result = {"markers": markers[:MAX_DIAGNOSTICS], "status": "partial" if partial else "complete",
              "duration_ms": round((time.perf_counter() - started) * 1000, 3)}
    if partial:
        result["message"] = message or partial_message
    return result
