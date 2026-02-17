"""
Contextual SQL autocomplete service.

Analyzes the SQL text and cursor position to provide context-aware completions:
- After FROM/JOIN: suggests table names
- After SELECT/WHERE/ON/ORDER BY/GROUP BY: suggests columns (with table prefix)
- After "table." or "alias.": suggests columns of that specific table
- After USE/DATABASE: suggests database names
- Default (start of statement): suggests SQL keywords + tables
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

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
        """Return column completions, including table-qualified columns."""
        columns = self._schema.get("columns", {})
        tables = self._schema.get("tables", [])
        result = []
        seen = set()

        # Also suggest table names (useful for table.column qualification)
        for t in tables:
            name = t["name"] if isinstance(t, dict) else str(t)
            if name not in seen:
                seen.add(name)
                result.append((name, CAT_TABLE, ""))

        # Try to resolve aliases from the query
        aliases = self._resolve_aliases(full_text)

        for table_name, cols in columns.items():
            for col in cols:
                cname = col["name"] if isinstance(col, dict) else str(col)
                ctype = col.get("type", "") if isinstance(col, dict) else ""

                # Plain column name
                key = cname.lower()
                if key not in seen:
                    seen.add(key)
                    detail = f"{ctype} ({table_name})" if ctype else table_name
                    result.append((cname, CAT_COLUMN, detail))

                # table.column qualified
                qualified = f"{table_name}.{cname}"
                result.append((qualified, CAT_COLUMN, ctype))

        return result

    def _dot_completions(
        self, prefix: str, full_text: str
    ) -> List[Tuple[str, str, str]]:
        """
        Return columns for the table/alias before the dot.

        Args:
            prefix: The identifier before the dot (table name or alias).
            full_text: Complete SQL text for alias resolution.
        """
        columns = self._schema.get("columns", {})

        # Direct match: prefix is a table name
        if prefix in columns:
            return self._columns_of(prefix)

        # Case-insensitive match
        prefix_lower = prefix.lower()
        for table_name in columns:
            if table_name.lower() == prefix_lower:
                return self._columns_of(table_name)

        # Resolve aliases
        aliases = self._resolve_aliases(full_text)
        real_table = aliases.get(prefix_lower)
        if real_table and real_table in columns:
            return self._columns_of(real_table)

        # Case-insensitive alias->table
        if real_table:
            for table_name in columns:
                if table_name.lower() == real_table.lower():
                    return self._columns_of(table_name)

        # No match - return all columns as fallback
        return self._all_columns_flat()

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
        """Return all columns from all tables (fallback)."""
        columns = self._schema.get("columns", {})
        result = []
        seen = set()
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
        Parse FROM/JOIN clauses to build alias->table_name mapping.

        Returns:
            Dict mapping alias (lowercase) -> real table name.
        """
        cleaned = self._strip_noise(text)
        aliases = {}

        # Find all FROM/JOIN table references
        for match in _RE_TABLE_REF.finditer(cleaned):
            _schema = match.group(1)  # optional schema prefix
            table = match.group(2)    # table name
            alias = match.group(3)    # optional alias

            if not table:
                continue

            # Clean bracket-quoted names: [dbo] -> dbo
            table_clean = table.strip("[]")
            alias_clean = alias.strip("[]") if alias else None

            if alias_clean:
                # Don't treat SQL keywords as aliases
                if alias_clean.upper() not in self._keywords_lower and \
                   alias_clean.upper() not in {kw.upper() for kw in SQL_KEYWORDS}:
                    aliases[alias_clean.lower()] = table_clean

            # Table name itself maps to itself (for case-insensitive lookup)
            aliases[table_clean.lower()] = table_clean

        return aliases
