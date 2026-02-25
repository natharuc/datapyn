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
from typing import Dict, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)

# Try to import sqlglot for advanced parsing
try:
    import sqlglot
    from sqlglot import exp
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

# Context constants
CTX_TABLE = "table"         # Expects table names (FROM, JOIN, INTO, UPDATE, etc.)
CTX_COLUMN = "column"       # Expects column names (SELECT, WHERE, ON, etc.)
CTX_DOT = "dot"             # After "something." - resolve to table/alias columns
CTX_DATABASE = "database"   # Expects database names (USE)
CTX_DEFAULT = "default"     # Keywords + tables

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
        self._context_parser = SqlContextParser()

    def set_schema(self, schema: Optional[dict]) -> None:
        """Update the database schema used for completions.

        Args:
            schema: dict with {tables: [...], columns: {...}, database: str, databases: [str]}
        """
        self._schema = schema if schema else {}

    def get_schema(self) -> dict:
        """Return current schema dict."""
        return self._schema

    def get_completions(
        self, text: str, cursor_line: int, cursor_col: int
    ) -> List[Tuple[str, str, str]]:
        """
        Get contextual completions at cursor position.

        Args:
            text: Full SQL text of the editor.
            cursor_line: 0-based line number of cursor.
            cursor_col: 0-based column of cursor.

        Returns:
            List of (name, category, detail) tuples.
        """
        text_before = self._text_before_cursor(text, cursor_line, cursor_col)
        if not text_before.strip():
            return self._keyword_completions()

        # Strip comments and string literals for cleaner parsing
        cleaned = self._strip_noise(text_before)

        # Detect context
        context, context_arg = self._detect_context(cleaned)

        return self._build_completions(context, context_arg, text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _text_before_cursor(text: str, line: int, col: int) -> str:
        """Extract text from start up to cursor position."""
        lines = text.split("\n")
        if line >= len(lines):
            return text
        result_lines = lines[:line]
        result_lines.append(lines[line][:col])
        return "\n".join(result_lines)

    @staticmethod
    def _strip_noise(text: str) -> str:
        """Remove comments and string literals to simplify parsing."""
        text = _RE_BLOCK_COMMENT.sub(" ", text)
        text = _RE_LINE_COMMENT.sub(" ", text)
        text = _RE_STRING_LITERAL.sub("''", text)
        return text

    def _detect_context(self, cleaned_text: str) -> Tuple[str, Optional[str]]:
        """
        Determine what type of completions to show based on text before cursor.

        Returns:
            (context_type, context_arg) where context_arg is table/alias name for DOT context.
        """
        stripped = cleaned_text.rstrip()

        # Check for dot context: "something." at the end
        dot_match = re.search(r"(\w+)\.\s*(\w*)$", stripped)
        if dot_match and stripped.rstrip().endswith("."):
            prefix = dot_match.group(1)
            return CTX_DOT, prefix

        # Also handle partial word after dot: "t.col_na"
        dot_partial = re.search(r"(\w+)\.(\w+)$", stripped)
        if dot_partial:
            prefix = dot_partial.group(1)
            return CTX_DOT, prefix

        # Tokenize: find the last significant keyword/phrase
        # Normalize whitespace
        normalized = re.sub(r"\s+", " ", stripped).upper().strip()

        # Check multi-word keywords first (ORDER BY, GROUP BY, etc.)
        for multi_kw in ("ORDER BY", "GROUP BY", "PARTITION BY",
                         "INNER JOIN", "LEFT JOIN", "RIGHT JOIN",
                         "FULL JOIN", "CROSS JOIN",
                         "LEFT OUTER JOIN", "RIGHT OUTER JOIN",
                         "FULL OUTER JOIN"):
            pattern = re.escape(multi_kw) + r"(?:\s+\w+\s*,)*\s*(?:\w+\.?\w*\s*,\s*)*\s*\w*$"
            if re.search(pattern, normalized):
                if multi_kw in _TABLE_CONTEXT_KW:
                    return CTX_TABLE, None
                if multi_kw in _COLUMN_CONTEXT_KW:
                    return CTX_COLUMN, None

        # Check single keywords - find the last relevant keyword
        # Split by non-identifier chars, walk backwards
        tokens = re.findall(r"\w+", normalized)
        if not tokens:
            return CTX_DEFAULT, None

        # Walk backwards to find last context-setting keyword
        for i in range(len(tokens) - 1, -1, -1):
            tk = tokens[i]

            # USE -> database context
            if tk == "USE":
                return CTX_DATABASE, None

            # Check if this token + next form a multi-word kw
            if i < len(tokens) - 1:
                pair = tk + " " + tokens[i + 1]
                if pair in _TABLE_CONTEXT_KW:
                    return CTX_TABLE, None
                if pair in _COLUMN_CONTEXT_KW:
                    return CTX_COLUMN, None

            if tk in {"FROM", "JOIN", "INTO", "UPDATE", "TABLE", "TRUNCATE"}:
                return CTX_TABLE, None

            if tk in {"SELECT", "WHERE", "ON", "SET", "HAVING", "AND", "OR"}:
                return CTX_COLUMN, None

            # After comma in SELECT clause -> column context
            # After comma in FROM clause -> table context
            if tk == ",":
                # Need to find what clause we're in
                continue

            # If we hit a table-context keyword before, these are values after
            # e.g., SELECT a, b, c FROM  -> after FROM
            # If we already passed the last keyword, stop
            if tk in self._keywords_lower or tk in {k.upper() for k in self._keywords_lower}:
                # It's a keyword but not context-setting, continue looking
                continue

        # Default: keywords + tables
        return CTX_DEFAULT, None

    def _build_completions(
        self, context: str, context_arg: Optional[str], full_text: str
    ) -> List[Tuple[str, str, str]]:
        """Build completion list based on detected context."""

        if context == CTX_DOT:
            return self._dot_completions(context_arg, full_text)

        if context == CTX_TABLE:
            return self._table_completions()

        if context == CTX_COLUMN:
            return self._column_completions(full_text)

        if context == CTX_DATABASE:
            return self._database_completions()

        # CTX_DEFAULT: keywords + tables
        return self._keyword_completions() + self._table_completions()

    def _keyword_completions(self) -> List[Tuple[str, str, str]]:
        """Return SQL keyword completions (both UPPER and lower case)."""
        result = []
        seen = set()
        func_set = {f.upper() for f in SQL_FUNCTIONS}
        for kw in SQL_KEYWORDS:
            upper = kw.upper()
            if upper not in seen:
                seen.add(upper)
                cat = CAT_FUNCTION if upper in func_set else CAT_KEYWORD
                result.append((upper, cat, ""))
                result.append((upper.lower(), cat, ""))
        return result

    def _table_completions(self) -> List[Tuple[str, str, str]]:
        """Return table name completions from schema."""
        tables = self._schema.get("tables", [])
        result = []
        for t in tables:
            name = t["name"] if isinstance(t, dict) else str(t)
            schema_name = t.get("schema", "") if isinstance(t, dict) else ""
            ttype = t.get("type", "TABLE") if isinstance(t, dict) else "TABLE"
            detail = f"{schema_name}.{name}" if schema_name else name
            result.append((name, CAT_TABLE, f"{ttype} - {detail}"))
        return result

    def _column_completions(self, full_text: str) -> List[Tuple[str, str, str]]:
        """Return column completions from tables mentioned in FROM/JOIN clauses."""
        columns = self._schema.get("columns", {})
        result = []
        seen = set()

        # Extract tables from FROM/JOIN clauses
        tables_in_query = self._extract_tables_from_query(full_text)
        
        # Also resolve aliases to get real table names
        aliases = self._resolve_aliases(full_text)
        
        # Build set of table names to include
        relevant_tables = set()
        for t in tables_in_query:
            relevant_tables.add(t.lower())
            # If it's an alias, add the real table too
            real_table = aliases.get(t.lower())
            if real_table and real_table not in ("__cte__", "__subquery__"):
                relevant_tables.add(real_table.lower())
        
        # Add real table names from aliases
        for alias, table in aliases.items():
            if table not in ("__cte__", "__subquery__"):
                relevant_tables.add(table.lower())
        
        # If no tables found, maybe user is still typing - show all columns
        if not relevant_tables:
            return self._all_columns_flat()
        
        # Get columns only from relevant tables
        for table_name, cols in columns.items():
            if table_name.lower() not in relevant_tables:
                continue
                
            for col in cols:
                cname = col["name"] if isinstance(col, dict) else str(col)
                ctype = col.get("type", "") if isinstance(col, dict) else ""

                key = cname.lower()
                if key not in seen:
                    seen.add(key)
                    detail = f"{table_name}.{cname} ({ctype})" if ctype else f"{table_name}.{cname}"
                    result.append((cname, CAT_COLUMN, detail))

        # Also suggest qualified table.column for tables in query
        for table_name, cols in columns.items():
            if table_name.lower() not in relevant_tables:
                continue
            for col in cols:
                cname = col["name"] if isinstance(col, dict) else str(col)
                ctype = col.get("type", "") if isinstance(col, dict) else ""
                qualified = f"{table_name}.{cname}"
                if qualified.lower() not in seen:
                    result.append((qualified, CAT_COLUMN, ctype))

        return result

    def _extract_tables_from_query(self, text: str) -> List[str]:
        """Extract table names from FROM and JOIN clauses."""
        tables = []
        
        # Clean the text
        cleaned = self._strip_noise(text.upper())
        
        # Pattern: FROM table_name [AS alias] or FROM table_name alias
        from_pattern = r'\bFROM\s+(\w+)'
        for match in re.finditer(from_pattern, cleaned, re.IGNORECASE):
            tables.append(match.group(1))
        
        # Pattern: JOIN table_name [AS alias]
        join_pattern = r'\bJOIN\s+(\w+)'
        for match in re.finditer(join_pattern, cleaned, re.IGNORECASE):
            tables.append(match.group(1))
        
        # Pattern: UPDATE table_name
        update_pattern = r'\bUPDATE\s+(\w+)'
        for match in re.finditer(update_pattern, cleaned, re.IGNORECASE):
            tables.append(match.group(1))
        
        # Pattern: INSERT INTO table_name
        insert_pattern = r'\bINTO\s+(\w+)'
        for match in re.finditer(insert_pattern, cleaned, re.IGNORECASE):
            tables.append(match.group(1))
        
        return tables

    def _dot_completions(
        self, prefix: str, full_text: str
    ) -> List[Tuple[str, str, str]]:
        """
        Return columns for the table/alias/CTE/subquery before the dot.

        Args:
            prefix: The identifier before the dot (table name, alias, CTE, or subquery).
            full_text: Complete SQL text for alias resolution.
        """
        columns = self._schema.get("columns", {})
        prefix_lower = prefix.lower()

        # First resolve aliases (including CTEs and subqueries)
        aliases = self._resolve_aliases(full_text)
        real_target = aliases.get(prefix_lower)

        # Check if it's a CTE
        if real_target == "__cte__":
            cte_cols = self._context_parser.get_cte_columns(prefix_lower)
            if cte_cols:
                return [(col, CAT_COLUMN, "CTE column") for col in cte_cols]
            # CTE with unknown columns - return empty (no fallback to all columns)
            return []

        # Check if it's a subquery alias
        if real_target == "__subquery__":
            subq_cols = self._context_parser.get_subquery_columns(prefix_lower)
            if subq_cols:
                return [(col, CAT_COLUMN, "Subquery column") for col in subq_cols]
            # Subquery with unknown columns - return empty
            return []

        # Direct match: prefix is a table name
        if prefix in columns:
            return self._columns_of(prefix)

        # Case-insensitive match for table name
        for table_name in columns:
            if table_name.lower() == prefix_lower:
                return self._columns_of(table_name)

        # Alias points to a real table
        if real_target and real_target in columns:
            return self._columns_of(real_target)

        # Case-insensitive alias->table
        if real_target:
            for table_name in columns:
                if table_name.lower() == real_target.lower():
                    return self._columns_of(table_name)

        # No match - return empty list (don't flood with all columns)
        logger.debug(f"No columns found for prefix: {prefix}")
        return []

    def _columns_of(self, table_name: str) -> List[Tuple[str, str, str]]:
        """Return columns of a specific table."""
        columns = self._schema.get("columns", {})
        cols = columns.get(table_name, [])
        result = []
        for col in cols:
            cname = col["name"] if isinstance(col, dict) else str(col)
            ctype = col.get("type", "") if isinstance(col, dict) else ""
            result.append((cname, CAT_COLUMN, ctype))
        return result

    def _all_columns_flat(self) -> List[Tuple[str, str, str]]:
        """Return all columns from all tables plus table names (fallback for SELECT without FROM)."""
        columns = self._schema.get("columns", {})
        tables = self._schema.get("tables", [])
        result = []
        seen = set()
        
        # Include table names for qualification (e.g., SELECT users.id)
        for t in tables:
            name = t["name"] if isinstance(t, dict) else str(t)
            if name.lower() not in seen:
                seen.add(name.lower())
                result.append((name, CAT_TABLE, ""))
        
        # Include all columns
        for table_name, cols in columns.items():
            for col in cols:
                cname = col["name"] if isinstance(col, dict) else str(col)
                ctype = col.get("type", "") if isinstance(col, dict) else ""
                key = cname.lower()
                if key not in seen:
                    seen.add(key)
                    detail = f"{ctype} ({table_name})" if ctype else table_name
                    result.append((cname, CAT_COLUMN, detail))
        return result

    def _database_completions(self) -> List[Tuple[str, str, str]]:
        """Return database name completions."""
        databases = self._schema.get("databases", [])
        return [(db, CAT_DATABASE, "") for db in databases]

    def _resolve_aliases(self, text: str) -> Dict[str, str]:
        """
        Parse SQL to build alias->table_name mapping including CTEs and subqueries.

        Returns:
            Dict mapping alias/CTE name (lowercase) -> real table name or '__cte__'/'__subquery__'.
        """
        schema_columns = self._schema.get("columns", {})
        return self._context_parser.parse(text, schema_columns)
