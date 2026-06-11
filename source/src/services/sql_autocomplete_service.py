"""
Contextual SQL autocomplete service.

Analyzes the SQL text and cursor position to provide context-aware completions:
- After FROM/JOIN: suggests table names
- After SELECT/WHERE/ON/ORDER BY/GROUP BY: suggests columns (with table prefix)
- After "table." or "alias.": suggests columns of that specific table
- After USE/DATABASE: suggests database names
- Default (start of statement): suggests SQL keywords + tables

Uses sqlglot for advanced parsing of:
- CTEs (WITH clauses)
- Subquery aliases
- Complex nested queries
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Try to import sqlglot for advanced parsing
try:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False
    logger.warning("sqlglot not installed - advanced SQL autocomplete disabled")

logger = logging.getLogger(__name__)

# Category constants for completion items
CAT_KEYWORD = "keyword"
CAT_TABLE = "table"
CAT_COLUMN = "column"
CAT_DATABASE = "database"
CAT_FUNCTION = "function"
CAT_VARIABLE = "variable"
CAT_ROUTINE = "routine"

# Context constants
CTX_TABLE = "table"         # Expects table names (FROM, JOIN, INTO, UPDATE, etc.)
CTX_COLUMN = "column"       # Expects column names (SELECT, WHERE, ON, etc.)
CTX_DOT = "dot"             # After "something." - resolve to table/alias columns
CTX_DATABASE = "database"   # Expects database names (USE)
CTX_DEFAULT = "default"     # Keywords + tables
CTX_ROUTINE = "routine"     # After EXEC/EXECUTE/CALL - expects procedure/function names

SQL_KEYWORDS = [
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "BETWEEN",
    "LIKE", "IS", "NULL", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER",
    "FULL", "CROSS", "ON", "AS", "ORDER", "BY", "GROUP", "HAVING",
    "LIMIT", "OFFSET", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
    "DELETE", "CREATE", "TABLE", "ALTER", "DROP", "INDEX", "VIEW",
    "UNION", "ALL", "DISTINCT", "TOP", "CASE", "WHEN", "THEN",
    "ELSE", "END", "EXISTS", "COUNT", "SUM", "AVG", "MIN", "MAX",
    "CAST", "CONVERT", "COALESCE", "ISNULL", "NULLIF",
    "GO", "USE", "EXEC", "DECLARE", "BEGIN", "COMMIT", "ROLLBACK",
    "ASC", "DESC", "WITH", "OVER", "PARTITION", "ROW_NUMBER", "RANK",
    "DENSE_RANK", "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE",
    "STRING_AGG", "STUFF", "CONCAT", "SUBSTRING", "REPLACE", "TRIM",
    "UPPER", "LOWER", "LEN", "CHARINDEX", "GETDATE", "DATEADD",
    "DATEDIFF", "YEAR", "MONTH", "DAY",
]

SQL_FUNCTIONS = [
    "COUNT", "SUM", "AVG", "MIN", "MAX",
    "CAST", "CONVERT", "COALESCE", "ISNULL", "NULLIF",
    "ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD",
    "FIRST_VALUE", "LAST_VALUE",
    "STRING_AGG", "STUFF", "CONCAT", "SUBSTRING", "REPLACE", "TRIM",
    "UPPER", "LOWER", "LEN", "CHARINDEX",
    "GETDATE", "DATEADD", "DATEDIFF", "YEAR", "MONTH", "DAY",
    "ABS", "CEILING", "FLOOR", "ROUND", "POWER", "SQRT",
    "ISNUMERIC", "NEWID", "FORMAT",
]

# Keywords that indicate next token should be a table name
_TABLE_CONTEXT_KW = {
    "FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN",
    "FULL JOIN", "CROSS JOIN", "LEFT OUTER JOIN", "RIGHT OUTER JOIN",
    "FULL OUTER JOIN", "INTO", "UPDATE", "TABLE", "TRUNCATE",
}

# Keywords that indicate next token should be column/expression
_COLUMN_CONTEXT_KW = {
    "SELECT", "WHERE", "AND", "OR", "ON", "SET", "HAVING",
    "ORDER BY", "GROUP BY", "PARTITION BY",
}

# Regex to strip SQL comments and string literals for cleaner parsing
_RE_LINE_COMMENT = re.compile(r"--[^\n]*", re.DOTALL)
_RE_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_STRING_LITERAL = re.compile(r"'[^']*'")
_RE_GO_BATCH = re.compile(r"(?im)^[ \t]*GO(?:[ \t]+--[^\n]*)?[ \t]*$")
_RE_SQL_TOKEN = re.compile(
    r"""
    \[[^\]]+\]
    |`[^`]+`
    |"[^"]+"
    |@@?[A-Za-z_][\w$]*
    |##?[A-Za-z_][\w$]*
    |[A-Za-z_][\w$]*
    |[,().]
    """,
    re.VERBOSE,
)
_RE_DOT_CONTEXT = re.compile(
    r'((?:@@?[A-Za-z_][\w$]*|##?[A-Za-z_][\w$]*|[A-Za-z_][\w$]*|\[[^\]]+\]|`[^`]+`|"[^"]+")'
    r'(?:\.(?:@@?[A-Za-z_][\w$]*|##?[A-Za-z_][\w$]*|[A-Za-z_][\w$]*|\[[^\]]+\]|`[^`]+`|"[^"]+"))*)'
    r'\.\s*(?:[@#A-Za-z_][\w$]*)?$',
    re.IGNORECASE,
)
# T-SQL: database..table (schema omitted → dbo)
_RE_CROSS_DB_TABLE = re.compile(
    r"(?:^|[\s,(])"
    r"((?:\[[^\]]+\]|`[^`]+`|\"[^\"]+\"|[A-Za-z_][\w$]*))"
    r"\s*\.\s*\.\s*"
    r"([\w$]*)$",
    re.IGNORECASE,
)

CURSOR_PLACEHOLDER = "__datapyn_cursor__"
DEFAULT_SCHEMA_PRIORITY = ("dbo", "public")

# Regex for alias detection in FROM/JOIN clauses
# Matches: table_name AS alias, table_name alias (not a keyword)
_RE_FROM_ITEM = re.compile(
    r"(?:FROM|JOIN)\s+"
    r"(?:(\[?\w+\]?)\.)?(\[?\w+\]?)"    # optional schema.table
    r"(?:\s+(?:AS\s+)?(\w+))?"           # optional alias
    r"(?:\s*,\s*"                         # or comma-separated
    r"(?:(\[?\w+\]?)\.)?(\[?\w+\]?)"     # schema.table2
    r"(?:\s+(?:AS\s+)?(\w+))?"           # optional alias2
    r")*",
    re.IGNORECASE,
)

# More flexible alias parsing: each source item individually
# NOTE: alias group uses [ \t] instead of \s to avoid consuming newlines
# which could steal the FROM/JOIN keyword of the next clause.
_RE_TABLE_REF = re.compile(
    r"(?:(?:FROM|JOIN)\s+|,\s*)"         # preceded by FROM/JOIN or comma
    r"(?:(\[?\w+\]?)\.)?(\[?\w+\]?)"     # optional schema.table
    r"(?:[ \t]+(?:AS[ \t]+)?(\w+))?"     # optional alias (same line only)
    ,
    re.IGNORECASE,
)


class SqlContextParser:
    """
    Advanced SQL parser using sqlglot for:
    - CTE extraction (WITH clauses)
    - Subquery alias tracking
    - Complex alias resolution
    """

    def __init__(self):
        self._ctes: Dict[str, List[str]] = {}  # CTE name -> column names
        self._aliases: Dict[str, str] = {}     # alias -> real table name
        self._subquery_aliases: Dict[str, List[str]] = {}  # subquery alias -> column names

    def parse(self, sql: str, schema_columns: Dict[str, List] = None) -> Dict[str, str]:
        """
        Parse SQL and build comprehensive alias mapping.

        Args:
            sql: The SQL query text
            schema_columns: Dict of table_name -> list of columns from schema

        Returns:
            Dict mapping alias/CTE names (lowercase) -> real table name or '__cte__' or '__subquery__'
        """
        self._ctes = {}
        self._aliases = {}
        self._subquery_aliases = {}
        schema_columns = schema_columns or {}

        if not HAS_SQLGLOT:
            return self._fallback_parse(sql)

        try:
            # Parse SQL - try multiple dialects for best coverage
            parsed = None
            for dialect in [None, "tsql", "mysql", "postgres"]:
                try:
                    parsed = sqlglot.parse(sql, dialect=dialect)
                    if parsed:
                        break
                except Exception:
                    continue

            if not parsed:
                return self._fallback_parse(sql)

            for statement in parsed:
                if statement:
                    self._extract_from_statement(statement, schema_columns)

        except Exception as e:
            logger.debug(f"sqlglot parse error: {e}, falling back to regex")
            return self._fallback_parse(sql)

        # Build combined alias map
        result = {}
        for alias, table in self._aliases.items():
            result[alias.lower()] = table
        for cte_name in self._ctes:
            result[cte_name.lower()] = "__cte__"
        for subq_alias in self._subquery_aliases:
            result[subq_alias.lower()] = "__subquery__"

        return result

    def get_cte_columns(self, cte_name: str) -> List[str]:
        """Get columns defined in a CTE."""
        return self._ctes.get(cte_name.lower(), [])

    def get_subquery_columns(self, alias: str) -> List[str]:
        """Get columns from a subquery alias."""
        return self._subquery_aliases.get(alias.lower(), [])

    def _extract_from_statement(self, statement, schema_columns: Dict[str, List]) -> None:
        """Extract CTEs, aliases, and subqueries from a parsed statement."""
        if not HAS_SQLGLOT:
            return

        # Extract CTEs
        for cte in statement.find_all(exp.CTE):
            cte_name = cte.alias
            if cte_name:
                # Get columns from CTE definition
                cte_cols = self._extract_select_columns(cte.this)
                self._ctes[cte_name.lower()] = cte_cols

        # Extract table aliases from FROM and JOIN
        for table in statement.find_all(exp.Table):
            table_name = table.name
            alias = table.alias
            if alias:
                self._aliases[alias.lower()] = table_name
            # Also map table name to itself
            self._aliases[table_name.lower()] = table_name

        # Extract subquery aliases
        for subquery in statement.find_all(exp.Subquery):
            alias = subquery.alias
            if alias:
                # Get columns from subquery SELECT
                inner_cols = self._extract_select_columns(subquery.this)
                self._subquery_aliases[alias.lower()] = inner_cols

    def _extract_select_columns(self, select_node) -> List[str]:
        """Extract column names from a SELECT statement."""
        columns = []
        if not HAS_SQLGLOT or not select_node:
            return columns

        try:
            # Look for SELECT expressions
            if hasattr(select_node, "expressions"):
                for expr in select_node.expressions:
                    col_name = None
                    # Check for alias first
                    if hasattr(expr, "alias") and expr.alias:
                        col_name = expr.alias
                    elif isinstance(expr, exp.Column):
                        col_name = expr.name
                    elif isinstance(expr, exp.Star):
                        # SELECT * - we can't know columns without schema
                        continue
                    elif hasattr(expr, "name"):
                        col_name = expr.name

                    if col_name and col_name not in columns:
                        columns.append(col_name)
        except Exception as e:
            logger.debug(f"Error extracting columns: {e}")

        return columns

    def _fallback_parse(self, sql: str) -> Dict[str, str]:
        """Fallback to regex-based parsing when sqlglot fails."""
        result = {}

        # Use existing regex pattern for basic alias detection
        for match in _RE_TABLE_REF.finditer(sql):
            table = match.group(2)
            alias = match.group(3)

            if table:
                table_clean = table.strip("[]")
                if alias:
                    alias_clean = alias.strip("[]")
                    # Don't treat SQL keywords as aliases
                    if alias_clean.upper() not in {kw.upper() for kw in SQL_KEYWORDS}:
                        result[alias_clean.lower()] = table_clean
                result[table_clean.lower()] = table_clean

        # Basic CTE detection with regex
        cte_pattern = re.compile(
            r"WITH\s+(\w+)\s+(?:\([^)]*\)\s+)?AS\s*\(",
            re.IGNORECASE
        )
        for match in cte_pattern.finditer(sql):
            cte_name = match.group(1)
            result[cte_name.lower()] = "__cte__"
            self._ctes[cte_name.lower()] = []  # Can't extract columns without full parse

        return result


@dataclass
class StatementContext:
    """Current SQL statement slices around the cursor."""

    previous_sql: str
    statement_before_cursor: str
    statement_after_cursor: str

    @property
    def current_statement(self) -> str:
        return f"{self.statement_before_cursor}{self.statement_after_cursor}"

    @property
    def cursor_offset(self) -> int:
        return len(self.statement_before_cursor)


class SqlAutoCompleteService:
    """
    Context-aware SQL autocomplete service.

    Usage:
        service = SqlAutoCompleteService()
        service.set_schema(schema_dict)
        completions = service.get_completions(sql_text, cursor_line, cursor_col)
    """

    def __init__(self):
        self._schema: dict = {}
        self._keywords_lower = {kw.lower() for kw in SQL_KEYWORDS}
        self._schema_db_type = ""
        self._table_entries: List[dict[str, Any]] = []
        self._table_lookup: dict[str, List[dict[str, Any]]] = {}

    def set_schema(self, schema: Optional[dict]) -> None:
        """Update the database schema used for completions."""
        self._schema = schema if schema else {}
        self._schema_db_type = str(self._schema.get("db_type", "") or "").lower()
        self._rebuild_schema_index()

    def get_schema(self) -> dict:
        """Return current schema dict."""
        return self._schema

    def get_completions(self, text: str, cursor_line: int, cursor_col: int) -> List[Tuple[str, str, str]]:
        """Get contextual completions at the cursor position."""
        text_before = self._text_before_cursor(text, cursor_line, cursor_col)
        if not text_before.strip():
            return self._keyword_completions()

        statement_context = self._statement_context(text, cursor_line, cursor_col)
        cleaned_before = self._strip_noise(statement_context.statement_before_cursor)
        context, context_arg = self._detect_context(cleaned_before)
        analysis = self._analyze_context(statement_context, context)
        if context == CTX_DOT:
            analysis["dot_table_prefix"] = self._partial_token_after_final_dot(cleaned_before)
        return self._build_completions(context, context_arg, analysis)

    @staticmethod
    def _text_before_cursor(text: str, line: int, col: int) -> str:
        """Extract text from start up to cursor position."""
        lines = text.split("\n")
        if not lines:
            return ""

        line = max(0, line)
        col = max(0, col)
        if line >= len(lines):
            return text

        result_lines = lines[:line]
        result_lines.append(lines[line][:col])
        return "\n".join(result_lines)

    @staticmethod
    def _text_after_cursor(text: str, line: int, col: int) -> str:
        """Extract text from cursor position to the end."""
        lines = text.split("\n")
        if not lines:
            return ""

        line = max(0, line)
        col = max(0, col)
        if line >= len(lines):
            return ""

        result_lines = [lines[line][col:]]
        result_lines.extend(lines[line + 1 :])
        return "\n".join(result_lines)

    @staticmethod
    def _strip_noise(text: str) -> str:
        """Remove comments and string literals to simplify parsing."""
        text = _RE_BLOCK_COMMENT.sub(" ", text)
        text = _RE_LINE_COMMENT.sub(" ", text)
        text = _RE_STRING_LITERAL.sub("''", text)
        return text

    @staticmethod
    def _normalize_batches(text: str) -> str:
        """Treat T-SQL GO batch separators like semicolons."""
        return _RE_GO_BATCH.sub(";", text)

    def _statement_context(self, text: str, line: int, col: int) -> StatementContext:
        """Get the current statement and all finished statements before it."""
        before_cursor = self._normalize_batches(self._text_before_cursor(text, line, col))
        after_cursor = self._normalize_batches(self._text_after_cursor(text, line, col))

        before_parts = before_cursor.split(";")
        statement_before = before_parts[-1]
        previous_sql = ";".join(before_parts[:-1]).strip()
        statement_after = after_cursor.split(";", 1)[0]

        return StatementContext(
            previous_sql=previous_sql,
            statement_before_cursor=statement_before,
            statement_after_cursor=statement_after,
        )

    @staticmethod
    def _strip_identifier_quotes(value: Any) -> str:
        text = str(value or "").strip()
        for left, right in (("[", "]"), ("`", "`"), ('"', '"')):
            while text.startswith(left) and text.endswith(right) and len(text) >= 2:
                text = text[1:-1].strip()
        return text

    @classmethod
    def _split_identifier_parts(cls, value: Any) -> List[str]:
        text = str(value or "").strip()
        if not text:
            return []

        parts: List[str] = []
        current: List[str] = []
        quote_char = ""
        bracket_depth = 0

        for char in text:
            if quote_char:
                current.append(char)
                if char == quote_char:
                    quote_char = ""
                continue

            if char in {'"', "`"}:
                quote_char = char
                current.append(char)
                continue

            if char == "[":
                bracket_depth += 1
                current.append(char)
                continue

            if char == "]" and bracket_depth:
                bracket_depth -= 1
                current.append(char)
                continue

            if char == "." and bracket_depth == 0:
                part = cls._strip_identifier_quotes("".join(current))
                if part:
                    parts.append(part)
                current = []
                continue

            current.append(char)

        tail = cls._strip_identifier_quotes("".join(current))
        if tail:
            parts.append(tail)
        return parts

    @classmethod
    def _normalize_name(cls, value: Any) -> str:
        return cls._strip_identifier_quotes(value).lower()

    @classmethod
    def _normalize_relation_key(cls, value: Any) -> str:
        parts = cls._split_identifier_parts(value)
        if not parts:
            return cls._normalize_name(value)
        return ".".join(cls._normalize_name(part) for part in parts if part)

    def _clone_columns(self, columns: Any) -> List[dict[str, Any]]:
        cloned: List[dict[str, Any]] = []
        for column in columns or []:
            if isinstance(column, dict):
                cloned.append(dict(column))
            else:
                cloned.append({"name": str(column), "type": ""})
        return cloned

    def _make_relation(
        self,
        display_name: str,
        columns: List[dict[str, Any]],
        source_type: str,
        detail: str,
        preferred_qualifier: str = "",
        lookup_names: Optional[Set[str]] = None,
    ) -> dict[str, Any]:
        names = {self._normalize_relation_key(display_name)}
        if preferred_qualifier:
            names.add(self._normalize_relation_key(preferred_qualifier))
        if lookup_names:
            names.update({name for name in lookup_names if name})
        return {
            "display_name": display_name,
            "columns": self._clone_columns(columns),
            "source_type": source_type,
            "detail": detail,
            "preferred_qualifier": preferred_qualifier or display_name,
            "lookup_names": names,
        }

    def _clone_relation(
        self,
        relation: dict[str, Any],
        *,
        preferred_qualifier: str = "",
        extra_lookup_names: Optional[Set[str]] = None,
    ) -> dict[str, Any]:
        cloned = self._make_relation(
            relation["display_name"],
            relation.get("columns", []),
            relation.get("source_type", ""),
            relation.get("detail", ""),
            preferred_qualifier=preferred_qualifier or relation.get("preferred_qualifier", ""),
            lookup_names=set(relation.get("lookup_names", set())),
        )
        if extra_lookup_names:
            cloned["lookup_names"].update(extra_lookup_names)
        return cloned

    def _rebuild_schema_index(self) -> None:
        self._table_entries = []
        self._table_lookup = {}

        columns_map = self._schema.get("columns", {}) or {}
        registered_keys: Set[str] = set()
        has_canonical_tables = bool(self._schema.get("tables", []) or [])

        for table in self._schema.get("tables", []) or []:
            if isinstance(table, dict):
                table_name = str(table.get("name", "") or "")
                schema_name = str(table.get("schema", "") or "")
                catalog_name = str(table.get("catalog", "") or "")
                table_database = str(table.get("database", "") or "")
                if (
                    not catalog_name
                    and table_database
                    and self._schema_db_type in ("mssql", "sqlserver")
                ):
                    catalog_name = table_database
                if self._schema_db_type == "databricks" and catalog_name and schema_name:
                    table_key = str(table.get("key") or f"{catalog_name}.{schema_name}.{table_name}")
                else:
                    table_key = str(table.get("key") or (f"{schema_name}.{table_name}" if schema_name else table_name))
                table_type = str(table.get("type", "TABLE") or "TABLE")
            else:
                table_name = str(table)
                schema_name = ""
                catalog_name = ""
                table_key = table_name
                table_type = "TABLE"

            if not table_name:
                continue

            fallback_column_key = f"{schema_name}.{table_name}" if schema_name else table_name
            entry_columns = self._clone_columns(
                columns_map.get(table_key)
                or columns_map.get(fallback_column_key)
                or columns_map.get(table_name)
                or []
            )
            self._register_table_entry(
                name=table_name,
                schema_name=schema_name,
                catalog_name=catalog_name,
                table_key=table_key,
                table_type=table_type,
                columns=entry_columns,
            )
            registered_keys.add(self._normalize_relation_key(table_key))
            if schema_name:
                registered_keys.add(self._normalize_relation_key(f"{schema_name}.{table_name}"))
            if catalog_name and schema_name:
                registered_keys.add(self._normalize_relation_key(f"{catalog_name}.{schema_name}.{table_name}"))

        if has_canonical_tables:
            return

        for table_key, cols in columns_map.items():
            normalized_key = self._normalize_relation_key(table_key)
            if normalized_key in registered_keys:
                continue
            parts = self._split_identifier_parts(table_key)
            table_name = parts[-1] if parts else str(table_key)
            schema_name = parts[-2] if len(parts) >= 2 else ""
            catalog_name = parts[-3] if len(parts) >= 3 else ""
            self._register_table_entry(
                name=table_name,
                schema_name=schema_name,
                catalog_name=catalog_name,
                table_key=str(table_key),
                table_type="TABLE",
                columns=self._clone_columns(cols),
            )

    def _register_table_entry(
        self,
        *,
        name: str,
        schema_name: str,
        catalog_name: str,
        table_key: str,
        table_type: str,
        columns: List[dict[str, Any]],
    ) -> None:
        display_detail = ".".join(part for part in (catalog_name, schema_name, name) if part)
        parts = self._split_identifier_parts(table_key)
        lookup_names = {self._normalize_relation_key(name), self._normalize_relation_key(table_key)}
        if schema_name:
            lookup_names.add(self._normalize_relation_key(f"{schema_name}.{name}"))
        if catalog_name and schema_name:
            lookup_names.add(self._normalize_relation_key(f"{catalog_name}.{schema_name}.{name}"))
        if catalog_name and not schema_name:
            lookup_names.add(self._normalize_relation_key(f"{catalog_name}.{name}"))
            lookup_names.add(self._normalize_relation_key(f"{catalog_name}..{name}"))
            for default_schema in DEFAULT_SCHEMA_PRIORITY:
                lookup_names.add(
                    self._normalize_relation_key(f"{catalog_name}.{default_schema}.{name}")
                )
        for index in range(len(parts)):
            suffix = ".".join(parts[index:])
            lookup_names.add(self._normalize_relation_key(suffix))

        entry = {
            "name": name,
            "schema": schema_name,
            "catalog": catalog_name,
            "key": table_key,
            "type": table_type,
            "detail": display_detail,
            "columns": self._clone_columns(columns),
            "lookup_names": lookup_names,
        }
        self._table_entries.append(entry)
        for lookup_name in lookup_names:
            self._table_lookup.setdefault(lookup_name, []).append(entry)

    def _current_databricks_catalog(self) -> str:
        catalog_name = self._normalize_name(self._schema.get("database", ""))
        if catalog_name:
            return catalog_name
        current_context = self._split_identifier_parts(self._schema.get("current_context", ""))
        return self._normalize_name(current_context[0]) if len(current_context) >= 2 else ""

    def _current_databricks_schema(self) -> str:
        schema_name = self._normalize_name(self._schema.get("current_schema", ""))
        if schema_name:
            return schema_name
        current_context = self._split_identifier_parts(self._schema.get("current_context", ""))
        return self._normalize_name(current_context[1]) if len(current_context) >= 2 else ""

    def _is_current_databricks_entry(self, entry: dict[str, Any]) -> bool:
        if self._schema_db_type != "databricks":
            return False

        current_catalog = self._current_databricks_catalog()
        current_schema = self._current_databricks_schema()
        if not current_catalog or not current_schema:
            return False

        entry_catalog = self._normalize_name(entry.get("catalog", ""))
        entry_schema = self._normalize_name(entry.get("schema", ""))
        return entry_catalog == current_catalog and entry_schema == current_schema

    def _databricks_entry_sort_key(self, entry: dict[str, Any]) -> Tuple[int, str]:
        current_catalog = self._current_databricks_catalog()
        current_schema = self._current_databricks_schema()
        entry_catalog = self._normalize_name(entry.get("catalog", ""))
        entry_schema = self._normalize_name(entry.get("schema", ""))

        if current_catalog and current_schema and entry_catalog == current_catalog and entry_schema == current_schema:
            return (0, str(entry.get("detail", "")))
        if current_catalog and entry_catalog == current_catalog:
            return (1, str(entry.get("detail", "")))
        return (2, str(entry.get("detail", "")))

    def _databricks_table_label(self, entry: dict[str, Any]) -> str:
        if self._is_current_databricks_entry(entry):
            return str(entry.get("name", "") or "")

        name = str(entry.get("name", "") or "")
        schema_name = str(entry.get("schema", "") or "")
        catalog_name = str(entry.get("catalog", "") or "")
        return ".".join(part for part in (catalog_name, schema_name, name) if part)

    def _preferred_dialects(self) -> List[Optional[str]]:
        db_type = self._schema_db_type
        primary = {
            "sqlserver": "tsql",
            "mssql": "tsql",
            "mysql": "mysql",
            "mariadb": "mysql",
            "postgresql": "postgres",
            "databricks": "databricks",
        }.get(db_type)

        dialects: List[Optional[str]] = []
        for dialect in (primary, None, "tsql", "mysql", "postgres", "spark"):
            if dialect not in dialects:
                dialects.append(dialect)
        return dialects

    def _parse_statement(self, sql: str):
        if not HAS_SQLGLOT or not sql.strip():
            return None

        for dialect in self._preferred_dialects():
            try:
                parsed = sqlglot.parse_one(sql, dialect=dialect, error_level="ignore")
                if parsed is not None:
                    return parsed
            except Exception:
                continue
        return None

    def _split_sql_statements(self, sql: str) -> List[str]:
        normalized = self._normalize_batches(sql)
        return [statement.strip() for statement in normalized.split(";") if statement.strip()]

    def _tokenize_with_depth(self, text: str) -> List[Tuple[str, int]]:
        tokens: List[Tuple[str, int]] = []
        depth = 0
        for match in _RE_SQL_TOKEN.finditer(text):
            token = match.group(0)
            if token == "(":
                tokens.append((token, depth))
                depth += 1
                continue
            if token == ")":
                depth = max(depth - 1, 0)
                tokens.append((token, depth))
                continue
            tokens.append((token, depth))
        return tokens

    def _detect_context(self, cleaned_text: str) -> Tuple[str, Optional[Any]]:
        """Determine what type of completions to show based on text before cursor."""
        stripped = cleaned_text.rstrip()
        if not stripped:
            return CTX_DEFAULT, None

        cross_db_match = _RE_CROSS_DB_TABLE.search(stripped)
        if cross_db_match:
            return CTX_TABLE, {
                "cross_database": self._strip_identifier_quotes(cross_db_match.group(1)),
                "table_prefix": cross_db_match.group(2) or "",
            }

        dot_match = _RE_DOT_CONTEXT.search(stripped)
        if dot_match:
            return CTX_DOT, dot_match.group(1)

        variable_tail = re.search(r"@\w*$", stripped)
        if variable_tail:
            parent_context, _ = self._detect_context(stripped[: variable_tail.start()])
            return (CTX_COLUMN if parent_context == CTX_DEFAULT else parent_context), None

        normalized = re.sub(r"\s+", " ", stripped).upper()
        if normalized.endswith(("ORDER BY", "GROUP BY", "PARTITION BY")):
            return CTX_COLUMN, None
        if normalized.endswith(
            (
                "INNER JOIN",
                "LEFT JOIN",
                "RIGHT JOIN",
                "FULL JOIN",
                "CROSS JOIN",
                "LEFT OUTER JOIN",
                "RIGHT OUTER JOIN",
                "FULL OUTER JOIN",
            )
        ):
            return CTX_TABLE, None

        tokens = self._tokenize_with_depth(stripped)
        if not tokens:
            return CTX_DEFAULT, None

        current_depth = tokens[-1][1]
        words = [
            token.upper()
            for token, depth in tokens
            if depth == current_depth and token not in {".", "(", ")", ","} and token.strip()
        ]

        if not words:
            return CTX_DEFAULT, None

        for index in range(len(words) - 1, -1, -1):
            token = words[index]
            if token == "USE":
                return CTX_DATABASE, None

            if token in {"EXEC", "EXECUTE", "CALL"}:
                if index == len(words) - 1:
                    return CTX_ROUTINE, None

            if index >= 2:
                triple = f"{words[index - 2]} {words[index - 1]} {token}"
                if triple in _TABLE_CONTEXT_KW:
                    return CTX_TABLE, None
                if triple in _COLUMN_CONTEXT_KW:
                    return CTX_COLUMN, None

            if index >= 1:
                pair = f"{words[index - 1]} {token}"
                if pair in _TABLE_CONTEXT_KW:
                    return CTX_TABLE, None
                if pair in _COLUMN_CONTEXT_KW:
                    return CTX_COLUMN, None

            if token in _TABLE_CONTEXT_KW:
                return CTX_TABLE, None
            if token in _COLUMN_CONTEXT_KW or token in {"VALUES", "WHEN"}:
                return CTX_COLUMN, None

        return CTX_DEFAULT, None

    def _analyze_context(self, statement_context: StatementContext, context: str) -> dict[str, Any]:
        script_state = self._collect_script_state(statement_context.previous_sql)
        scope_sources: List[dict[str, Any]] = []
        scope_lookup: dict[str, dict[str, Any]] = {}
        cte_sources: List[dict[str, Any]] = []
        cte_lookup: dict[str, dict[str, Any]] = {}

        current_statement = statement_context.current_statement
        if current_statement.strip():
            parsed_analysis = self._analyze_current_statement(
                current_statement,
                statement_context.cursor_offset,
                context,
                script_state,
            )
            scope_sources = parsed_analysis["scope_sources"]
            scope_lookup = parsed_analysis["scope_lookup"]
            cte_sources = parsed_analysis["cte_sources"]
            cte_lookup = parsed_analysis["cte_lookup"]

        return {
            "script_state": script_state,
            "scope_sources": scope_sources,
            "scope_lookup": scope_lookup,
            "cte_sources": cte_sources,
            "cte_lookup": cte_lookup,
        }

    def _inject_cursor_placeholder(self, statement_sql: str, cursor_offset: int, context: str) -> str:
        before = statement_sql[:cursor_offset]
        after = statement_sql[cursor_offset:]

        if context == CTX_DOT:
            dot_match = _RE_DOT_CONTEXT.search(before.rstrip())
            if dot_match:
                start = dot_match.start(0)
                prefix = dot_match.group(1)
                remainder = re.sub(r"^[@#A-Za-z_][\w$]*", "", after, count=1)
                return f"{statement_sql[:start]}{prefix}.{CURSOR_PLACEHOLDER}{remainder}"

        token_start = cursor_offset
        token_end = cursor_offset

        left_match = re.search(r"[@#A-Za-z_][\w$]*$", before)
        if left_match:
            token_start = left_match.start()

        right_match = re.match(r"^[@#A-Za-z_][\w$]*", after)
        if right_match:
            token_end = cursor_offset + right_match.end()

        placeholder = CURSOR_PLACEHOLDER
        if before[token_start:cursor_offset].startswith("@") or after[: max(token_end - cursor_offset, 0)].startswith("@"):
            placeholder = f"@{CURSOR_PLACEHOLDER}"

        return f"{statement_sql[:token_start]}{placeholder}{statement_sql[token_end:]}"

    def _scope_has_cursor(self, scope) -> bool:
        for column in getattr(scope, "columns", []):
            if self._normalize_name(column.name) == CURSOR_PLACEHOLDER:
                return True
            if self._normalize_name(getattr(column, "table", "")) == CURSOR_PLACEHOLDER:
                return True

        for table in getattr(scope, "tables", []):
            if self._normalize_name(getattr(table, "name", "")) == CURSOR_PLACEHOLDER:
                return True
            if self._normalize_name(getattr(table, "db", "")) == CURSOR_PLACEHOLDER:
                return True

        return False

    def _analyze_current_statement(
        self,
        statement_sql: str,
        cursor_offset: int,
        context: str,
        script_state: dict[str, Any],
    ) -> dict[str, Any]:
        parsed = self._parse_statement(self._inject_cursor_placeholder(statement_sql, cursor_offset, context))
        if parsed is None or not HAS_SQLGLOT:
            fallback_sources, fallback_lookup = self._fallback_scope_relations(statement_sql, script_state)
            return {
                "scope_sources": fallback_sources,
                "scope_lookup": fallback_lookup,
                "cte_sources": [],
                "cte_lookup": {},
            }

        scopes = list(traverse_scope(parsed))
        output_cache: dict[int, List[dict[str, Any]]] = {}
        cte_sources, cte_lookup = self._collect_cte_sources(scopes, script_state, output_cache)

        target_scope = None
        for scope in scopes:
            if self._scope_has_cursor(scope):
                target_scope = scope
                break
        if target_scope is None and scopes:
            target_scope = scopes[-1]

        scope_sources: List[dict[str, Any]] = []
        scope_lookup: dict[str, dict[str, Any]] = {}
        if target_scope is not None:
            scope_sources, scope_lookup = self._resolve_scope_sources(target_scope, script_state, output_cache)

        update_relation = self._resolve_update_target(parsed, script_state)
        if update_relation is not None:
            self._append_relation(scope_sources, scope_lookup, update_relation)

        return {
            "scope_sources": scope_sources,
            "scope_lookup": scope_lookup,
            "cte_sources": cte_sources,
            "cte_lookup": cte_lookup,
        }

    def _collect_cte_sources(
        self,
        scopes,
        script_state: dict[str, Any],
        output_cache: dict[int, List[dict[str, Any]]],
    ) -> Tuple[List[dict[str, Any]], dict[str, dict[str, Any]]]:
        relations: List[dict[str, Any]] = []
        lookup: dict[str, dict[str, Any]] = {}
        seen: Set[str] = set()

        for scope in scopes:
            cte_alias_columns = {
                self._normalize_name(cte.alias): list(cte.alias_column_names or [])
                for cte in getattr(scope, "ctes", [])
                if getattr(cte, "alias", "")
            }
            for cte in getattr(scope, "ctes", []):
                cte_name = str(getattr(cte, "alias", "") or "")
                normalized_name = self._normalize_name(cte_name)
                if not cte_name or normalized_name in seen:
                    continue
                source_scope = scope.sources.get(cte_name) or scope.sources.get(normalized_name)
                if not hasattr(source_scope, "expression"):
                    continue
                columns = self._scope_output_columns(source_scope, script_state, output_cache)
                alias_columns = cte_alias_columns.get(normalized_name) or []
                if alias_columns:
                    columns = self._override_column_names(columns, alias_columns)
                relation = self._make_relation(
                    cte_name,
                    columns,
                    "cte",
                    f"CTE - {cte_name}",
                    preferred_qualifier=cte_name,
                )
                self._append_relation(relations, lookup, relation)
                seen.add(normalized_name)

        return relations, lookup

    def _resolve_scope_sources(
        self,
        scope,
        script_state: dict[str, Any],
        output_cache: dict[int, List[dict[str, Any]]],
    ) -> Tuple[List[dict[str, Any]], dict[str, dict[str, Any]]]:
        relations: List[dict[str, Any]] = []
        lookup: dict[str, dict[str, Any]] = {}
        cte_names = {
            self._normalize_name(cte.alias)
            for cte in getattr(scope, "ctes", [])
            if getattr(cte, "alias", "")
        }
        cte_alias_columns = {
            self._normalize_name(cte.alias): list(cte.alias_column_names or [])
            for cte in getattr(scope, "ctes", [])
            if getattr(cte, "alias", "")
        }

        for alias, selected in getattr(scope, "selected_sources", {}).items():
            source_expression, source_object = selected
            relation = self._relation_from_source(
                alias,
                source_expression,
                source_object,
                script_state,
                output_cache,
                cte_names,
                cte_alias_columns,
            )
            if relation is None:
                continue
            self._append_relation(relations, lookup, relation)

        return relations, lookup

    def _append_relation(
        self,
        relations: List[dict[str, Any]],
        lookup: dict[str, dict[str, Any]],
        relation: dict[str, Any],
    ) -> None:
        relation_key = (
            relation.get("display_name", "").lower(),
            relation.get("preferred_qualifier", "").lower(),
            relation.get("source_type", ""),
        )
        if not any(
            (
                existing.get("display_name", "").lower(),
                existing.get("preferred_qualifier", "").lower(),
                existing.get("source_type", ""),
            )
            == relation_key
            for existing in relations
        ):
            relations.append(relation)

        for lookup_name in relation.get("lookup_names", set()):
            lookup[lookup_name] = relation

    def _relation_from_source(
        self,
        alias: str,
        source_expression,
        source_object,
        script_state: dict[str, Any],
        output_cache: dict[int, List[dict[str, Any]]],
        cte_names: Set[str],
        cte_alias_columns: dict[str, List[str]],
    ) -> Optional[dict[str, Any]]:
        alias_name = str(alias or "")

        if isinstance(source_object, exp.Table):
            return self._relation_from_table_expression(source_object, alias_name, script_state)

        if hasattr(source_object, "expression"):
            source_name = ""
            if isinstance(source_expression, exp.Table):
                source_name = self._table_identifier_from_expression(source_expression) or source_expression.name

            columns = self._scope_output_columns(source_object, script_state, output_cache)
            normalized_source_name = self._normalize_relation_key(source_name)
            if normalized_source_name in cte_alias_columns and cte_alias_columns[normalized_source_name]:
                columns = self._override_column_names(columns, cte_alias_columns[normalized_source_name])

            source_type = "cte" if normalized_source_name in cte_names else "subquery"
            detail_label = "CTE" if source_type == "cte" else "Subquery"
            display_name = source_name or alias_name or detail_label.lower()

            lookup_names = {self._normalize_relation_key(alias_name), self._normalize_relation_key(display_name)}
            if isinstance(source_expression, exp.Table) and source_expression.name:
                lookup_names.add(self._normalize_relation_key(source_expression.name))
                if source_expression.db:
                    lookup_names.add(self._normalize_relation_key(f"{source_expression.db}.{source_expression.name}"))

            return self._make_relation(
                display_name,
                columns,
                source_type,
                f"{detail_label} - {display_name}",
                preferred_qualifier=alias_name or display_name,
                lookup_names=lookup_names,
            )

        return None

    def _resolve_update_target(self, parsed, script_state: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not isinstance(parsed, exp.Update):
            return None
        table_expression = parsed.this if isinstance(parsed.this, exp.Table) else None
        if table_expression is None:
            return None
        return self._relation_from_table_expression(table_expression, "", script_state)

    def _scope_output_columns(
        self,
        scope,
        script_state: dict[str, Any],
        output_cache: dict[int, List[dict[str, Any]]],
    ) -> List[dict[str, Any]]:
        scope_id = id(scope)
        if scope_id in output_cache:
            return self._clone_columns(output_cache[scope_id])

        output_cache[scope_id] = []
        source_relations, _ = self._resolve_scope_sources(scope, script_state, output_cache)

        columns: List[dict[str, Any]] = []
        for expression in getattr(scope.expression, "expressions", []) or []:
            columns.extend(self._expression_output_columns(expression, source_relations))

        output_cache[scope_id] = self._dedupe_columns(columns)
        return self._clone_columns(output_cache[scope_id])

    def _expression_output_columns(
        self,
        expression,
        source_relations: List[dict[str, Any]],
    ) -> List[dict[str, Any]]:
        if isinstance(expression, exp.Alias):
            alias_name = str(expression.alias or "").strip()
            if alias_name and self._normalize_name(alias_name) != CURSOR_PLACEHOLDER:
                inferred_type = self._expression_type_hint(expression.this, source_relations)
                return [{"name": alias_name, "type": inferred_type, "display_type": inferred_type}]
            return []

        if isinstance(expression, exp.Star):
            return self._expand_star_columns("", source_relations)

        if isinstance(expression, exp.Column):
            if self._normalize_name(expression.name) == CURSOR_PLACEHOLDER:
                return []
            if expression.name == "*":
                return self._expand_star_columns(getattr(expression, "table", ""), source_relations)
            inferred_type = self._expression_type_hint(expression, source_relations)
            return [{"name": expression.name, "type": inferred_type, "display_type": inferred_type}]

        return []

    def _expand_star_columns(self, qualifier: str, source_relations: List[dict[str, Any]]) -> List[dict[str, Any]]:
        normalized_qualifier = self._normalize_relation_key(qualifier)
        columns: List[dict[str, Any]] = []
        for relation in source_relations:
            if normalized_qualifier and normalized_qualifier not in relation.get("lookup_names", set()):
                continue
            columns.extend(self._clone_columns(relation.get("columns", [])))
        return columns

    def _expression_type_hint(self, expression, source_relations: List[dict[str, Any]]) -> str:
        if isinstance(expression, exp.Column):
            target_column = self._find_column_definition(
                source_relations,
                getattr(expression, "table", ""),
                expression.name,
            )
            if target_column is not None:
                return str(target_column.get("display_type") or target_column.get("type") or "")
        return ""

    def _find_column_definition(
        self,
        relations: List[dict[str, Any]],
        qualifier: str,
        column_name: str,
    ) -> Optional[dict[str, Any]]:
        normalized_column = self._normalize_name(column_name)
        normalized_qualifier = self._normalize_relation_key(qualifier)

        for relation in relations:
            if normalized_qualifier and normalized_qualifier not in relation.get("lookup_names", set()):
                continue
            for column in relation.get("columns", []):
                if self._normalize_name(column.get("name", "")) == normalized_column:
                    return column
        return None

    def _dedupe_columns(self, columns: List[dict[str, Any]]) -> List[dict[str, Any]]:
        seen: Set[str] = set()
        deduped: List[dict[str, Any]] = []
        for column in columns:
            normalized_name = self._normalize_name(column.get("name", ""))
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            deduped.append(column)
        return deduped

    def _override_column_names(self, columns: List[dict[str, Any]], alias_names: List[str]) -> List[dict[str, Any]]:
        renamed: List[dict[str, Any]] = []
        for index, alias_name in enumerate(alias_names):
            base = dict(columns[index]) if index < len(columns) else {"type": "", "display_type": ""}
            base["name"] = alias_name
            renamed.append(base)
        return self._dedupe_columns(renamed)

    def _collect_script_state(self, previous_sql: str) -> dict[str, Any]:
        state = {
            "relation_sources": [],
            "relation_lookup": {},
            "variables": {},
        }
        if not previous_sql.strip():
            return state

        for statement in self._split_sql_statements(previous_sql):
            parsed = self._parse_statement(statement)
            if parsed is None:
                continue

            if isinstance(parsed, exp.Create):
                self._register_create_relation(parsed, state)
                continue

            if isinstance(parsed, exp.Declare):
                self._register_declared_symbols(parsed, state)
                continue

            if isinstance(parsed, exp.Select) and getattr(parsed, "args", {}).get("into") is not None:
                self._register_select_into_relation(parsed, state)

        return state

    def _register_state_relation(self, state: dict[str, Any], relation: dict[str, Any]) -> None:
        state["relation_sources"] = [
            existing
            for existing in state["relation_sources"]
            if existing.get("display_name", "").lower() != relation.get("display_name", "").lower()
        ]
        state["relation_sources"].append(relation)

        for lookup_name, existing in list(state["relation_lookup"].items()):
            if existing.get("display_name", "").lower() == relation.get("display_name", "").lower():
                del state["relation_lookup"][lookup_name]
        for lookup_name in relation.get("lookup_names", set()):
            state["relation_lookup"][lookup_name] = relation

    def _register_create_relation(self, parsed, state: dict[str, Any]) -> None:
        schema_expression = parsed.this if isinstance(parsed.this, exp.Schema) else None
        table_expression = None
        if isinstance(schema_expression, exp.Schema) and isinstance(schema_expression.this, exp.Table):
            table_expression = schema_expression.this
        elif isinstance(parsed.this, exp.Table):
            table_expression = parsed.this

        if table_expression is None:
            return

        is_temporary = self._table_is_temporary(table_expression)
        properties = getattr(parsed, "args", {}).get("properties")
        if not is_temporary and properties is not None:
            for prop in getattr(properties, "expressions", []) or []:
                if isinstance(prop, exp.TemporaryProperty):
                    is_temporary = True
                    break
        if not is_temporary:
            return

        relation_name = self._table_identifier_from_expression(table_expression)
        if not relation_name:
            return

        columns: List[dict[str, Any]] = []
        if isinstance(schema_expression, exp.Schema):
            columns = self._column_defs_to_columns(getattr(schema_expression, "expressions", []) or [])

        create_expression = getattr(parsed, "args", {}).get("expression")
        if create_expression is not None and not columns and isinstance(create_expression, exp.Select):
            columns = self._select_output_columns(create_expression, state)

        relation = self._make_relation(
            relation_name,
            columns,
            "temporary",
            f"Temporary table - {relation_name}",
            preferred_qualifier=relation_name,
            lookup_names=self._relation_lookup_names(relation_name),
        )
        self._register_state_relation(state, relation)

    def _register_declared_symbols(self, parsed, state: dict[str, Any]) -> None:
        for item in getattr(parsed, "expressions", []) or []:
            variable_names = []
            for parameter in getattr(item, "this", []) or []:
                variable_name = self._parameter_identifier(parameter)
                if variable_name:
                    variable_names.append(variable_name)
            if not variable_names:
                continue

            kind = getattr(item, "kind", None) or getattr(item, "args", {}).get("kind")
            if isinstance(kind, exp.Schema):
                columns = self._column_defs_to_columns(getattr(kind, "expressions", []) or [])
                relation_name = variable_names[0]
                relation = self._make_relation(
                    relation_name,
                    columns,
                    "table_variable",
                    f"Table variable - {relation_name}",
                    preferred_qualifier=relation_name,
                    lookup_names=self._relation_lookup_names(relation_name),
                )
                self._register_state_relation(state, relation)
                continue

            type_detail = kind.sql() if kind is not None else ""
            for variable_name in variable_names:
                state["variables"][self._normalize_name(variable_name)] = type_detail

    def _register_select_into_relation(self, parsed, state: dict[str, Any]) -> None:
        into_expression = getattr(parsed, "args", {}).get("into")
        table_expression = into_expression.this if into_expression is not None else None
        if not isinstance(table_expression, exp.Table):
            return
        if not self._table_is_temporary(table_expression):
            return

        relation_name = self._table_identifier_from_expression(table_expression)
        if not relation_name:
            return

        columns = self._select_output_columns(parsed, state)
        relation = self._make_relation(
            relation_name,
            columns,
            "temporary",
            f"Temporary table - {relation_name}",
            preferred_qualifier=relation_name,
            lookup_names=self._relation_lookup_names(relation_name),
        )
        self._register_state_relation(state, relation)

    def _column_defs_to_columns(self, column_defs) -> List[dict[str, Any]]:
        columns: List[dict[str, Any]] = []
        for column_def in column_defs:
            if not isinstance(column_def, exp.ColumnDef):
                continue
            kind = getattr(column_def, "kind", None)
            display_type = kind.sql() if kind is not None else ""
            columns.append(
                {
                    "name": column_def.name,
                    "type": display_type,
                    "display_type": display_type,
                }
            )
        return columns

    def _select_output_columns(self, select_expression, state: dict[str, Any]) -> List[dict[str, Any]]:
        if not HAS_SQLGLOT:
            return []

        output_cache: dict[int, List[dict[str, Any]]] = {}
        scopes = list(traverse_scope(select_expression))
        if not scopes:
            return []
        return self._scope_output_columns(scopes[-1], state, output_cache)

    def _parameter_identifier(self, parameter) -> str:
        if isinstance(parameter, exp.Parameter) and getattr(parameter, "this", None) is not None:
            inner = parameter.this
            if hasattr(inner, "name") and inner.name:
                return f"@{inner.name}"
            if hasattr(inner, "this") and inner.this:
                return f"@{inner.this}"
        return ""

    def _table_is_temporary(self, table_expression) -> bool:
        if not isinstance(table_expression, exp.Table):
            return False
        table_this = table_expression.this
        if isinstance(table_this, exp.Parameter):
            return False
        args = getattr(table_this, "args", {})
        return bool(args.get("temporary") or args.get("global_"))

    def _table_identifier_from_expression(self, table_expression) -> str:
        if not isinstance(table_expression, exp.Table):
            return ""

        table_this = table_expression.this
        if isinstance(table_this, exp.Parameter):
            variable_name = self._parameter_identifier(table_this)
            return variable_name

        name = str(getattr(table_expression, "name", "") or "")
        if not name:
            return ""

        args = getattr(table_this, "args", {})
        if args.get("global_"):
            return f"##{name}"
        if args.get("temporary"):
            return f"#{name}"

        parts = [part for part in (table_expression.catalog, table_expression.db, name) if part]
        return ".".join(parts)

    def _relation_lookup_names(self, identifier: str) -> Set[str]:
        lookup_names = {self._normalize_relation_key(identifier)}
        clean_identifier = identifier
        if identifier.startswith("##"):
            clean_identifier = identifier[2:]
        elif identifier.startswith("#"):
            clean_identifier = identifier[1:]
        lookup_names.add(self._normalize_relation_key(clean_identifier))
        return {name for name in lookup_names if name}

    def _relation_from_table_expression(
        self,
        table_expression,
        alias_name: str,
        script_state: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        relation_identifier = self._table_identifier_from_expression(table_expression)
        lookup_names = self._relation_lookup_names(relation_identifier)
        if table_expression.db:
            lookup_names.add(self._normalize_relation_key(f"{table_expression.db}.{table_expression.name}"))
        if table_expression.name:
            lookup_names.add(self._normalize_relation_key(table_expression.name))
        if alias_name:
            lookup_names.add(self._normalize_relation_key(alias_name))

        for lookup_name in lookup_names:
            scripted_relation = script_state["relation_lookup"].get(lookup_name)
            if scripted_relation is not None:
                return self._clone_relation(
                    scripted_relation,
                    preferred_qualifier=alias_name or scripted_relation.get("preferred_qualifier", ""),
                    extra_lookup_names=lookup_names,
                )

        entry = self._find_schema_entry(table_expression.name, table_expression.db, table_expression.catalog)
        if entry is None:
            return None

        relation = self._make_relation(
            entry["detail"],
            entry.get("columns", []),
            "table",
            f'{entry["type"]} - {entry["detail"]}',
            preferred_qualifier=alias_name or entry["name"],
            lookup_names=set(entry.get("lookup_names", set())) | lookup_names,
        )
        return relation

    def _find_schema_entry(self, table_name: str, schema_name: str = "", catalog_name: str = "") -> Optional[dict[str, Any]]:
        lookup_candidates = []
        if catalog_name and schema_name:
            lookup_candidates.append(self._normalize_relation_key(f"{catalog_name}.{schema_name}.{table_name}"))
        if catalog_name and not schema_name:
            lookup_candidates.append(self._normalize_relation_key(f"{catalog_name}..{table_name}"))
            lookup_candidates.append(self._normalize_relation_key(f"{catalog_name}.{table_name}"))
            for default_schema in DEFAULT_SCHEMA_PRIORITY:
                lookup_candidates.append(
                    self._normalize_relation_key(f"{catalog_name}.{default_schema}.{table_name}")
                )
        if schema_name:
            lookup_candidates.append(self._normalize_relation_key(f"{schema_name}.{table_name}"))
        lookup_candidates.append(self._normalize_relation_key(table_name))

        candidates: List[dict[str, Any]] = []
        for lookup_name in lookup_candidates:
            candidates.extend(self._table_lookup.get(lookup_name, []))

        if not candidates:
            return None

        normalized_schema = self._normalize_name(schema_name)
        normalized_catalog = self._normalize_name(catalog_name)
        current_catalog = self._normalize_name(self._schema.get("database", ""))
        current_schema = self._normalize_name(self._schema.get("current_schema", ""))

        def sort_key(entry: dict[str, Any]) -> Tuple[int, int, int, str]:
            entry_catalog = self._normalize_name(entry.get("catalog", ""))
            entry_schema = self._normalize_name(entry.get("schema", ""))
            if normalized_catalog and entry_catalog == normalized_catalog:
                catalog_rank = 0
            elif current_catalog and entry_catalog == current_catalog:
                catalog_rank = 1
            elif not entry_catalog:
                catalog_rank = 2
            else:
                catalog_rank = 3

            if normalized_schema and entry_schema == normalized_schema:
                return (catalog_rank, 0, 0, entry["detail"])
            if self._schema_db_type == "databricks" and current_schema and entry_schema == current_schema:
                return (catalog_rank, 1, 0, entry["detail"])
            if entry_schema in DEFAULT_SCHEMA_PRIORITY:
                return (catalog_rank, 2, DEFAULT_SCHEMA_PRIORITY.index(entry_schema), entry["detail"])
            if not entry_schema:
                return (catalog_rank, 3, 0, entry["detail"])
            return (catalog_rank, 4, 0, entry["detail"])

        return sorted(candidates, key=sort_key)[0]

    def _fallback_scope_relations(
        self,
        statement_sql: str,
        script_state: dict[str, Any],
    ) -> Tuple[List[dict[str, Any]], dict[str, dict[str, Any]]]:
        relations: List[dict[str, Any]] = []
        lookup: dict[str, dict[str, Any]] = {}
        aliases = self._fallback_resolve_aliases(statement_sql)

        for alias_name, target_name in aliases.items():
            scripted_relation = script_state["relation_lookup"].get(self._normalize_relation_key(target_name))
            if scripted_relation is not None:
                self._append_relation(
                    relations,
                    lookup,
                    self._clone_relation(
                        scripted_relation,
                        preferred_qualifier=alias_name if alias_name != target_name else scripted_relation.get("preferred_qualifier", ""),
                        extra_lookup_names={self._normalize_relation_key(alias_name)},
                    ),
                )
                continue

            entry = self._find_schema_entry(target_name)
            if entry is None:
                continue
            relation = self._make_relation(
                entry["detail"],
                entry.get("columns", []),
                "table",
                f'{entry["type"]} - {entry["detail"]}',
                preferred_qualifier=alias_name,
                lookup_names=set(entry.get("lookup_names", set())) | {self._normalize_relation_key(alias_name)},
            )
            self._append_relation(relations, lookup, relation)

        return relations, lookup

    def _fallback_resolve_aliases(self, sql: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for match in _RE_TABLE_REF.finditer(sql):
            schema_name = self._strip_identifier_quotes(match.group(1) or "")
            table_name = self._strip_identifier_quotes(match.group(2) or "")
            alias_name = self._strip_identifier_quotes(match.group(3) or "")
            if not table_name:
                continue
            bare_table = table_name
            full_table = f"{schema_name}.{table_name}" if schema_name else table_name
            result[bare_table.lower()] = bare_table
            if alias_name and alias_name.upper() not in {kw.upper() for kw in SQL_KEYWORDS}:
                result[alias_name.lower()] = bare_table
            if schema_name:
                result[full_table.lower()] = bare_table
        return result

    def _build_completions(
        self,
        context: str,
        context_arg: Optional[str],
        analysis: dict[str, Any],
    ) -> List[Tuple[str, str, str]]:
        if context == CTX_DOT:
            return self._dot_completions(context_arg or "", analysis)
        if context == CTX_TABLE:
            cross_db = context_arg if isinstance(context_arg, dict) else None
            return self._table_completions(analysis, cross_db=cross_db)
        if context == CTX_COLUMN:
            return self._column_completions(analysis)
        if context == CTX_DATABASE:
            return self._database_completions()
        if context == CTX_ROUTINE:
            return self._routine_completions()
        return (
            self._keyword_completions()
            + self._table_completions(analysis)
            + self._variable_completions(analysis)
            + self._routine_completions()
        )

    def _routine_completions(self) -> List[Tuple[str, str, str]]:
        """Return procedure/function completions from the schema routines list."""
        result: List[Tuple[str, str, str]] = []
        seen: Set[str] = set()
        for routine in self._schema.get("routines", []) or []:
            name = str(routine.get("name", "") or "")
            if not name:
                continue
            normalized = self._normalize_name(name)
            if normalized in seen:
                continue
            seen.add(normalized)
            routine_type = str(routine.get("type", "PROCEDURE") or "PROCEDURE").upper()
            schema_name = str(routine.get("schema", "") or "")
            detail = f"{routine_type} - {schema_name}.{name}" if schema_name else f"{routine_type} - {name}"
            result.append((name, CAT_ROUTINE, detail))
        return result

    def _keyword_completions(self) -> List[Tuple[str, str, str]]:
        """Return SQL keyword completions (both UPPER and lower case)."""
        result = []
        seen = set()
        func_set = {f.upper() for f in SQL_FUNCTIONS}
        for kw in SQL_KEYWORDS:
            upper = kw.upper()
            if upper not in seen:
                seen.add(upper)
                category = CAT_FUNCTION if upper in func_set else CAT_KEYWORD
                result.append((upper, category, ""))
                result.append((upper.lower(), category, ""))
        return result

    def _sqlserver_default_schema(self) -> str:
        if self._schema_db_type in ("mssql", "sqlserver"):
            return "dbo"
        return ""

    def _partial_token_after_final_dot(self, text: str) -> str:
        """Partial identifier after the last dot (schema.table prefix while typing)."""
        stripped = text.rstrip()
        dot_index = stripped.rfind(".")
        if dot_index < 0:
            return ""
        return stripped[dot_index + 1 :].strip()

    def _known_schema_names(self) -> Set[str]:
        schemas: Set[str] = set()
        for entry in self._table_entries:
            schema_name = self._normalize_name(entry.get("schema", "") or "")
            if schema_name:
                schemas.add(schema_name)
        return schemas

    def _is_known_schema(self, name: str) -> bool:
        norm = self._normalize_name(name)
        return bool(norm) and norm in self._known_schema_names()

    def _schema_table_completions(
        self,
        schema_name: str,
        table_prefix: str = "",
    ) -> List[Tuple[str, str, str]]:
        """Tables inside a schema when the user typed schema. (SQL Server)."""
        norm_schema = self._normalize_name(schema_name)
        prefix_norm = self._normalize_name(table_prefix) if table_prefix else ""
        result: List[Tuple[str, str, str]] = []
        seen: Set[str] = set()
        for entry in self._table_entries:
            if self._normalize_name(entry.get("schema", "") or "") != norm_schema:
                continue
            label = str(entry.get("name", "") or "")
            norm_label = self._normalize_name(label)
            if not norm_label or norm_label in seen:
                continue
            if prefix_norm and not norm_label.startswith(prefix_norm):
                continue
            seen.add(norm_label)
            detail = f'{entry["type"]} - {entry["detail"]}'
            result.append((label, CAT_TABLE, detail))
        return result

    def _table_entry_allowed_for_default_context(
        self,
        entry: dict[str, Any],
        *,
        default_schema: str,
    ) -> bool:
        """SQL Server: unqualified table suggestions default to dbo only."""
        if not default_schema:
            return True
        entry_schema = self._normalize_name(entry.get("schema", "") or "")
        if not entry_schema:
            return True
        return entry_schema == self._normalize_name(default_schema)

    def _table_completions(
        self,
        analysis: Optional[dict[str, Any]] = None,
        *,
        cross_db: Optional[dict[str, str]] = None,
    ) -> List[Tuple[str, str, str]]:
        """Return table-like completions from schema, CTEs, temp tables and table variables."""
        result: List[Tuple[str, str, str]] = []
        seen: Set[str] = set()
        database_filter = ""
        table_prefix = ""
        if cross_db:
            database_filter = self._normalize_name(cross_db.get("cross_database", ""))
            table_prefix = self._normalize_name(cross_db.get("table_prefix", ""))

        default_schema = "" if cross_db else self._sqlserver_default_schema()

        def append_table(label: str, detail: str) -> None:
            normalized_label = self._normalize_name(label)
            if not normalized_label or normalized_label in seen:
                return
            if table_prefix and not normalized_label.startswith(table_prefix):
                return
            seen.add(normalized_label)
            result.append((label, CAT_TABLE, detail))

        if analysis:
            for relation in analysis.get("cte_sources", []):
                label = relation["display_name"]
                append_table(label, relation.get("detail", "CTE"))

            script_state = analysis.get("script_state", {})
            for relation in script_state.get("relation_sources", []):
                label = relation["display_name"]
                append_table(label, relation.get("detail", ""))

        entries = self._table_entries
        if self._schema_db_type == "databricks":
            entries = sorted(entries, key=self._databricks_entry_sort_key)

        for entry in entries:
            if database_filter:
                entry_db = self._normalize_name(entry.get("catalog", "") or "")
                if entry_db and entry_db != database_filter:
                    continue
            if not self._table_entry_allowed_for_default_context(
                entry, default_schema=default_schema
            ):
                continue
            detail = f'{entry["type"]} - {entry["detail"]}'
            if self._schema_db_type == "databricks":
                append_table(self._databricks_table_label(entry), detail)
            else:
                append_table(entry["name"], detail)

        return result

    def _column_completions(self, analysis: dict[str, Any]) -> List[Tuple[str, str, str]]:
        """Return column completions from the visible scope, plus variables."""
        scope_sources = analysis.get("scope_sources", [])
        if not scope_sources:
            return self._all_columns_flat() + self._variable_completions(analysis)

        result: List[Tuple[str, str, str]] = []
        seen_names: Set[str] = set()
        seen_qualified: Set[str] = set()

        for relation in scope_sources:
            qualifier = relation.get("preferred_qualifier") or relation.get("display_name")
            for column in relation.get("columns", []):
                column_name = str(column.get("name", "") or "")
                if not column_name:
                    continue
                detail_name = relation.get("display_name", qualifier)
                display_type = str(column.get("display_type") or column.get("type") or "")
                unqualified_key = self._normalize_name(column_name)
                qualified_label = f"{qualifier}.{column_name}" if qualifier else column_name
                qualified_key = self._normalize_relation_key(qualified_label)

                if unqualified_key and unqualified_key not in seen_names:
                    seen_names.add(unqualified_key)
                    detail = f"{detail_name}.{column_name}"
                    if display_type:
                        detail = f"{detail} ({display_type})"
                    result.append((column_name, CAT_COLUMN, detail))

                if qualifier and qualified_key not in seen_qualified:
                    seen_qualified.add(qualified_key)
                    result.append((qualified_label, CAT_COLUMN, display_type))

        return result + self._variable_completions(analysis)

    def _dot_completions(self, prefix: str, analysis: dict[str, Any]) -> List[Tuple[str, str, str]]:
        """Return columns for the table, alias, CTE, subquery or temp relation before the dot."""
        parts = self._split_identifier_parts(prefix)
        if len(parts) == 1 and self._is_known_schema(parts[0]):
            return self._schema_table_completions(
                parts[0],
                str(analysis.get("dot_table_prefix", "") or ""),
            )

        normalized_prefix = self._normalize_relation_key(prefix)

        relation = analysis.get("scope_lookup", {}).get(normalized_prefix)
        if relation is None:
            relation = analysis.get("cte_lookup", {}).get(normalized_prefix)
        if relation is None:
            relation = analysis.get("script_state", {}).get("relation_lookup", {}).get(normalized_prefix)
        if relation is None:
            entry = self._find_schema_entry(prefix)
            if entry is not None:
                relation = self._make_relation(
                    entry["detail"],
                    entry.get("columns", []),
                    "table",
                    f'{entry["type"]} - {entry["detail"]}',
                    preferred_qualifier=prefix,
                    lookup_names=set(entry.get("lookup_names", set())),
                )

        if relation is None:
            namespace_result = self._databricks_namespace_completions(prefix)
            if namespace_result:
                return namespace_result
            logger.debug("No columns found for prefix: %s", prefix)
            return []

        result = []
        for column in relation.get("columns", []):
            column_name = str(column.get("name", "") or "")
            if not column_name:
                continue
            display_type = str(column.get("display_type") or column.get("type") or "")
            detail = display_type or relation.get("detail", "")
            result.append((column_name, CAT_COLUMN, detail))
        return result

    def _databricks_namespace_completions(self, prefix: str) -> List[Tuple[str, str, str]]:
        if self._schema_db_type != "databricks":
            return []

        parts = self._split_identifier_parts(prefix)
        if not parts:
            return []

        def table_items(catalog_name: str, schema_name: str) -> List[Tuple[str, str, str]]:
            result: List[Tuple[str, str, str]] = []
            seen: Set[str] = set()
            normalized_catalog = self._normalize_name(catalog_name)
            normalized_schema = self._normalize_name(schema_name)
            for entry in self._table_entries:
                if normalized_catalog and self._normalize_name(entry.get("catalog", "")) != normalized_catalog:
                    continue
                if self._normalize_name(entry.get("schema", "")) != normalized_schema:
                    continue
                name = entry.get("name", "")
                normalized_name = self._normalize_name(name)
                if not normalized_name or normalized_name in seen:
                    continue
                seen.add(normalized_name)
                result.append((name, CAT_TABLE, f'{entry["type"]} - {entry["detail"]}'))
            return result

        if len(parts) == 1:
            catalog_name = parts[0]
            schemas = set()
            for schema_name in (self._schema.get("catalog_schemas", {}) or {}).get(catalog_name, []) or []:
                if schema_name:
                    schemas.add(str(schema_name))
            for entry in self._table_entries:
                if self._normalize_name(entry.get("catalog", "")) == self._normalize_name(catalog_name):
                    schema_name = entry.get("schema", "")
                    if schema_name:
                        schemas.add(schema_name)
            if schemas:
                return [(schema_name, CAT_DATABASE, f"schema - {catalog_name}.{schema_name}") for schema_name in sorted(schemas)]

            current_catalog = str(self._schema.get("database", "") or "")
            return table_items(current_catalog, catalog_name)

        if len(parts) == 2:
            return table_items(parts[0], parts[1])

        return []

    def _all_columns_flat(self) -> List[Tuple[str, str, str]]:
        """Return all columns from all tables plus table names (fallback for SELECT without FROM)."""
        result: List[Tuple[str, str, str]] = []
        seen: Set[str] = set()

        entries = self._table_entries
        if self._schema_db_type == "databricks":
            entries = sorted(entries, key=self._databricks_entry_sort_key)

        for entry in entries:
            table_label = self._databricks_table_label(entry) if self._schema_db_type == "databricks" else entry["name"]
            normalized_name = self._normalize_name(table_label)
            if normalized_name in seen:
                continue
            seen.add(normalized_name)
            result.append((table_label, CAT_TABLE, f'{entry["type"]} - {entry["detail"]}'))

        for entry in self._table_entries:
            for column in entry.get("columns", []):
                column_name = str(column.get("name", "") or "")
                normalized_column = self._normalize_name(column_name)
                if not normalized_column or normalized_column in seen:
                    continue
                seen.add(normalized_column)
                display_type = str(column.get("display_type") or column.get("type") or "")
                detail = entry["detail"]
                if display_type:
                    detail = f"{detail} ({display_type})"
                result.append((column_name, CAT_COLUMN, detail))

        return result

    def _variable_completions(self, analysis: Optional[dict[str, Any]]) -> List[Tuple[str, str, str]]:
        """Return declared SQL variables visible before the cursor."""
        if not analysis:
            return []
        variables = analysis.get("script_state", {}).get("variables", {})
        return [
            (name, CAT_VARIABLE, detail)
            for name, detail in sorted(variables.items(), key=lambda item: item[0])
        ]

    def _database_completions(self) -> List[Tuple[str, str, str]]:
        """Return database name completions."""
        databases = self._schema.get("databases", [])
        return [(db, CAT_DATABASE, "") for db in databases]

    def _extract_tables_from_query(self, text: str) -> List[str]:
        """Extract visible table-like names from the current statement."""
        aliases = self._resolve_aliases(text)
        table_names = []
        for target in aliases.values():
            if target in {"__cte__", "__subquery__"}:
                continue
            if target not in table_names:
                table_names.append(target)
        return table_names

    def _columns_of(self, table_name: str) -> List[Tuple[str, str, str]]:
        """Return columns of a specific table or temp relation."""
        relation = None
        entry = self._find_schema_entry(table_name)
        if entry is not None:
            relation = self._make_relation(
                entry["detail"],
                entry.get("columns", []),
                "table",
                f'{entry["type"]} - {entry["detail"]}',
                preferred_qualifier=table_name,
            )

        if relation is None:
            return []

        return [
            (str(column.get("name", "") or ""), CAT_COLUMN, str(column.get("display_type") or column.get("type") or ""))
            for column in relation.get("columns", [])
            if column.get("name")
        ]

    def _resolve_aliases(self, text: str) -> Dict[str, str]:
        """Parse SQL and build alias mappings for tables, CTEs and subqueries."""
        result: Dict[str, str] = {}

        for statement in self._split_sql_statements(text):
            parsed = self._parse_statement(statement)
            if parsed is None or not HAS_SQLGLOT:
                continue

            scopes = list(traverse_scope(parsed))
            for scope in scopes:
                cte_names = {
                    self._normalize_name(cte.alias)
                    for cte in getattr(scope, "ctes", [])
                    if getattr(cte, "alias", "")
                }
                for cte_name in cte_names:
                    result[cte_name] = "__cte__"

                for alias_name, selected in getattr(scope, "selected_sources", {}).items():
                    source_expression, source_object = selected
                    normalized_alias = self._normalize_name(alias_name)
                    if isinstance(source_object, exp.Table):
                        bare_name = self._table_identifier_from_expression(source_object) or source_object.name
                        if bare_name:
                            result[normalized_alias] = bare_name
                            if source_object.name:
                                result[self._normalize_name(source_object.name)] = source_object.name
                    elif hasattr(source_object, "expression"):
                        source_name = ""
                        if isinstance(source_expression, exp.Table):
                            source_name = source_expression.name
                        result[normalized_alias] = "__cte__" if self._normalize_name(source_name) in cte_names else "__subquery__"

        if result:
            return result
        return self._fallback_resolve_aliases(text)
