"""
Inline completion service for Monaco Editor — powered by Pynia.

Hybrid approach:
1. Local heuristics for instant keywords / schema hints
2. Pynia API autocomplete (active connector token)
"""

import logging
import re
from typing import Optional, List, Dict

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
from src.services.pynia.settings import get_pynia_settings

logger = logging.getLogger(__name__)


# Common Python imports for quick completion
PYTHON_IMPORTS = {
    "pandas": "pandas as pd",
    "numpy": "numpy as np",
    "matplotlib": "matplotlib.pyplot as plt",
    "os": "os",
    "sys": "sys",
    "json": "json",
    "re": "re",
    "datetime": "datetime",
    "time": "time",
    "collections": "collections",
    "pathlib": "pathlib",
    "typing": "typing",
    "math": "math",
    "random": "random",
    "csv": "csv",
    "logging": "logging",
    "requests": "requests",
    "sqlalchemy": "sqlalchemy",
}

# SQL keywords for completion
SQL_KEYWORDS = [
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "LIKE",
    "ORDER BY", "GROUP BY", "HAVING", "JOIN", "LEFT JOIN", "RIGHT JOIN",
    "INNER JOIN", "OUTER JOIN", "ON", "AS", "DISTINCT", "COUNT",
    "SUM", "AVG", "MIN", "MAX", "LIMIT", "OFFSET", "INSERT INTO",
    "VALUES", "UPDATE", "SET", "DELETE", "CREATE TABLE", "DROP TABLE",
    "ALTER TABLE", "ADD", "COLUMN", "PRIMARY KEY", "FOREIGN KEY",
    "REFERENCES", "INDEX", "UNIQUE", "NULL", "NOT NULL", "DEFAULT",
    "BETWEEN", "EXISTS", "CASE", "WHEN", "THEN", "ELSE", "END",
    "UNION", "EXCEPT", "INTERSECT", "IS NULL", "IS NOT NULL",
]


class InlineCompletionService(QObject):
    """
    Service that provides inline completions for code editors via Pynia.

    - Local heuristics for common SQL/Python patterns (instant)
    - Pynia connector API for AI ghost-text (OpenAI, OpenRouter, Claude, Copilot)
    """
    
    # Signal emitted when completion is ready
    completion_ready = pyqtSignal(str)  # completion_text
    
    # Signal emitted when LSP download is needed
    lsp_download_needed = pyqtSignal()
    
    # Signal for logging to output panel (message, level: info/error/debug)
    log_message = pyqtSignal(str, str)

    _logged_lsp_client_id: Optional[int] = None
    _logged_lsp_username: Optional[str] = None
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # LSP client (primary - fast)
        self._lsp_client = None
        self._lsp_connected = False
        
        # Pynia agent client (API autocomplete)
        self._pynia_client = None
        self._pynia_connected = False
        
        self._pending_request = None
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(180)  # Single debounce layer (JS no longer stacks)
        self._debounce_timer.timeout.connect(self._execute_pending_request)

        # Watchdog: never let a dropped/hung completion wedge the pipeline.
        # If a request stays "in flight" too long, release the lock so the
        # next keystroke is served instead of being silently blocked.
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setSingleShot(True)
        self._watchdog_timer.setInterval(7000)
        self._watchdog_timer.timeout.connect(self._on_request_watchdog)

        # Request tracking
        self._current_request_id = 0
        self._active_request_id = 0
        self._is_processing = False  # Block concurrent requests
        self._last_request_prefix = ""  # Deduplicate identical requests
        
        # Document state for LSP
        self._document_uri = ""
        self._document_version = 0
        self._document_language = "python"
        
        # Database context for SQL completions
        self._database_context = ""
        self._cached_tables: List[str] = []
        self._cached_columns: Dict[str, List[str]] = {}
        
        # Python context for block variables (namespace from previous blocks)
        self._python_namespace: Dict[str, str] = {}  # var_name -> type_name
        self._blocks_code_context: str = ""  # Code from other blocks for context
    
    def _log(self, message: str, level: str = "info") -> None:
        """Log message to both logger and output panel signal."""
        if level == "error":
            logger.error(f"[AUTOCOMPLETE] {message}")
        elif level == "debug":
            logger.debug(f"[AUTOCOMPLETE] {message}")
        else:
            logger.debug(f"[AUTOCOMPLETE] {message}")
        self.log_message.emit(f"[Autocomplete] {message}", level)
    
    def set_database_context(self, context: str) -> None:
        """Set database schema context for SQL completions."""
        self._database_context = context
        self._parse_schema_context(context)
    
    def set_python_namespace(self, namespace: Dict[str, str]) -> None:
        """Set Python namespace for completions.
        
        Args:
            namespace: Dict mapping variable names to type names
                       e.g. {"vendas": "DataFrame", "df": "DataFrame", "x": "int"}
        """
        self._python_namespace = namespace or {}
    
    def set_blocks_code_context(self, code_context: str) -> None:
        """Set code context from other blocks.
        
        This provides the completion service with code from other blocks
        so it can understand the context of variables like BLOCK names
        and SQL queries that generated DataFrames.
        
        Args:
            code_context: Combined code from other blocks
        """
        self._blocks_code_context = code_context or ""
    
    def _build_python_context(self) -> str:
        """Build context string for Python completions."""
        parts = []
        
        # Add namespace variables
        if self._python_namespace:
            var_lines = []
            for name, type_name in sorted(self._python_namespace.items()):
                var_lines.append(f"  {name}: {type_name}")
            if var_lines:
                parts.append("Available variables:\n" + "\n".join(var_lines))
        
        # Add code context from other blocks
        if self._blocks_code_context:
            parts.append(f"Code from other blocks:\n{self._blocks_code_context}")
        
        return "\n\n".join(parts) if parts else ""
    
    def _parse_schema_context(self, context: str) -> None:
        """Parse schema context to extract table and column names."""
        self._cached_tables = []
        self._cached_columns = {}
        
        if not context:
            return
        
        # Parse format:
        # Database: db_name
        # Tables (N):
        #   table_name: col1, col2, col3, ...
        for line in context.split("\n"):
            line = line.strip()
            if line.startswith("Database:") or line.startswith("Tables"):
                continue
            if ":" in line and not line.startswith("..."):
                parts = line.split(":", 1)
                table_name = parts[0].strip()
                if table_name:
                    self._cached_tables.append(table_name)
                    # Parse columns
                    if len(parts) > 1:
                        cols = [
                            c.strip()
                            for c in parts[1].split(",")
                            if c.strip() and not c.strip().startswith("...")
                        ]
                        self._cached_columns[table_name] = cols
        
        logger.debug(
            f"Parsed schema: {len(self._cached_tables)} tables, "
            f"{sum(len(c) for c in self._cached_columns.values())} columns"
        )
    
    def set_pynia_client(self, client) -> None:
        """Set the Pynia agent client for AI inline autocomplete."""
        if self._pynia_client and self._pynia_connected:
            try:
                self._pynia_client.inline_completion_ready.disconnect(
                    self._on_pynia_completion
                )
            except (TypeError, RuntimeError):
                pass
            self._pynia_connected = False

        self._pynia_client = client

        if client and hasattr(client, "inline_completion_ready"):
            client.inline_completion_ready.connect(self._on_pynia_completion)
            self._pynia_connected = True
            auth_status = "ready" if self.has_pynia else "configure token in Settings → Pynia"
            self._log(f"Pynia autocomplete connected ({auth_status})", "info")

    def set_copilot_client(self, client) -> None:
        """Backward-compatible alias for set_pynia_client."""
        self.set_pynia_client(client)
    
    def set_lsp_client(self, client) -> None:
        """Deprecated: LSP autocomplete removed; Pynia API is used instead."""
        self._lsp_client = None
        self._lsp_connected = False
    
    @pyqtSlot(str)
    def _on_lsp_authenticated(self, username: str) -> None:
        """Handle LSP authentication success."""
        self._sign_in_attempted = False  # Reset so we can retry if needed
        if username and username != InlineCompletionService._logged_lsp_username:
            InlineCompletionService._logged_lsp_username = username
            self._log(f"LSP authenticated as {username} - fast completions ready", "info")
    
    def set_document_info(self, uri: str, language: str) -> None:
        """Set the current document info for LSP completion requests."""
        self._document_uri = uri
        self._document_language = language
        self._document_version = 1
        self._last_synced_text = ""
    
    def notify_document_changed(self, text: str) -> None:
        """Notify LSP that the document content changed."""
        if text == getattr(self, "_last_synced_text", None):
            return
        self._last_synced_text = text
        logger.debug(
            "[Autocomplete] notify_document_changed: uri=%s, len=%s",
            self._document_uri,
            len(text),
        )
        if self._lsp_client and self._document_uri:
            self._document_version += 1
            self._lsp_client.change_document(
                self._document_uri,
                self._document_version,
                text
            )

    def open_document(self, uri: str, language: str, text: str) -> None:
        """Open a document in the LSP server."""
        logger.debug("[Autocomplete] open_document: uri=%s, lang=%s, len=%s", uri, language, len(text))
        self._document_version = 1
        self._last_synced_text = text
        
        if self._lsp_client:
            self._lsp_client.open_document(uri, language, text, 1)
    
    def close_document(self) -> None:
        """Close the current document in the LSP server."""
        if self._lsp_client and self._document_uri:
            self._lsp_client.close_document(self._document_uri)
        self._document_uri = ""
        self._document_version = 0
    
    @property
    def has_lsp(self) -> bool:
        """Check if LSP client is available and authenticated."""
        return (
            self._lsp_client is not None
            and self._lsp_client.is_authenticated
        )
    
    @property
    def has_pynia(self) -> bool:
        """Whether Pynia can serve AI autocomplete for the active connector."""
        if not get_pynia_settings().autocomplete_enabled:
            return False
        if not self._pynia_client:
            return False
        if self._pynia_client.provider_id == "copilot":
            return bool(self._pynia_client.is_authenticated)
        from src.services.pynia.settings import get_provider_secret

        return bool(get_provider_secret(self._pynia_client.provider_id))
    
    @pyqtSlot(str)
    def _on_lsp_completion(self, completion: str) -> None:
        """Handle completion from LSP client."""
        # Only process if THIS service was waiting for a completion
        # This prevents duplicate handling when multiple CodeBlocks share LSP client
        if not self._is_processing:
            return  # Ignore - this completion is for another code block

        self._release_processing()  # Release lock
        if completion:
            preview = completion[:60].replace('\n', ' ')
            self._log(f"LSP completion: {preview}...", "info")
        else:
            self._log("LSP returned empty (no suggestion)", "debug")
        self.completion_ready.emit(completion)
        self._maybe_serve_pending()
    
    @pyqtSlot(str)
    def _on_pynia_completion(self, completion: str) -> None:
        """Handle completion from Pynia agent client."""
        if not self._is_processing:
            return

        self._release_processing()
        if completion:
            preview = completion[:60].replace("\n", " ")
            self._log(f"Pynia completion: {preview}...", "info")
        else:
            self._log("Pynia returned empty (no suggestion)", "debug")
        self.completion_ready.emit(completion)
        self._maybe_serve_pending()

    def _build_request_context(self, language: str) -> str:
        if language == "sql" and self._database_context:
            return self._database_context
        if language == "python":
            return self._build_python_context()
        return ""
    
    def request_completion(
        self,
        prefix: str,
        suffix: str,
        language: str,
        line: int,
        column: int,
    ) -> None:
        """
        Request an inline completion.
        
        Args:
            prefix: Text before cursor
            suffix: Text after cursor  
            language: Programming language (python, sql)
            line: Current line number (1-indexed)
            column: Current column (1-indexed)
        """
        # Skip if prefix is too short or just whitespace
        stripped = prefix.rstrip()
        if len(stripped) < 2:
            self.completion_ready.emit("")
            return
        
        # Get last line for context analysis
        lines = prefix.split('\n')
        last_line = lines[-1] if lines else prefix
        
        # Allow empty line if previous line has content (user pressed Enter)
        # This enables "continuation" completions
        if last_line.strip() == "":
            # Check if there's meaningful content in previous lines
            has_previous_content = len(lines) > 1 and any(line.strip() for line in lines[:-1])
            if not has_previous_content:
                self.completion_ready.emit("")
                return
        
        # DEDUPLICATE: Skip if same prefix as last request
        request_key = f"{line}:{column}:{prefix}"
        if request_key == self._last_request_prefix:
            return

        self._last_request_prefix = request_key

        # Supersede any pending request (latest keystroke wins). We do NOT
        # drop the request when one is already in flight — that left Monaco's
        # promise hanging until timeout. Instead we queue the latest request;
        # _execute_pending_request waits for the in-flight call and then serves
        # it (see _maybe_serve_pending).
        self._current_request_id += 1

        # Store request for debounced execution
        self._pending_request = {
            "id": self._current_request_id,
            "prefix": prefix,
            "suffix": suffix,
            "language": language,
            "line": line,
            "column": column,
        }

        # Restart debounce timer
        self._debounce_timer.start()
    
    def cancel_request(self) -> None:
        """Cancel any pending completion request."""
        self._debounce_timer.stop()
        self._pending_request = None
        self._current_request_id += 1
        # Drop the in-flight lock so a late result is ignored and the next
        # keystroke is served immediately.
        self._release_processing()
    
    @pyqtSlot()
    def _execute_pending_request(self) -> None:
        """Execute the debounced completion request.

        Pynia AI autocomplete is the primary source. Local heuristics are only
        a fallback when no AI provider is available — they used to preempt the
        AI and emit contextually-wrong ghost text (e.g. ``(self):`` for a
        module-level def), which is exactly the "invalid hints" complaint.
        """
        if not self._pending_request:
            return

        # A previous request is still in flight. Keep the pending request and
        # let the completion handler re-arm us once the lock is released
        # (_maybe_serve_pending). This serves the latest keystroke instead of
        # dropping it.
        if self._is_processing:
            return

        request = self._pending_request
        self._pending_request = None
        self._active_request_id = request["id"]

        # Mark as processing to block concurrent requests
        self._is_processing = True
        self._watchdog_timer.start()

        last_line = request["prefix"].split('\n')[-1][:40]
        self._log(f"Completion request: '{last_line}' ({request['language']})", "info")

        if self.has_pynia and self._pynia_client:
            ctx = self._build_request_context(request["language"])
            self._log(
                f"Requesting Pynia completion ({request['language']}, "
                f"L{request['line']}:C{request['column']})",
                "info",
            )
            self._pynia_client.request_inline_completion(
                request["prefix"],
                request["suffix"],
                request["language"],
                context=ctx,
            )
            return

        # No AI provider — fall back to safe local heuristics so there is
        # still *something* offline.
        local_completion = self._get_smart_completion(
            request["prefix"],
            request["suffix"],
            request["language"],
        )
        self._release_processing()
        if local_completion:
            preview = local_completion[:40].replace('\\n', ' ')
            self._log(f"Local fallback completion: {preview}...", "info")
        else:
            if not get_pynia_settings().autocomplete_enabled:
                reason = "disabled in Settings → Pynia"
            elif not self._pynia_client:
                reason = "Pynia client not connected"
            else:
                reason = "configure API token in Settings → Pynia"
            self._log(f"AI autocomplete unavailable — {reason}", "info")
        self.completion_ready.emit(local_completion or "")

    def _release_processing(self) -> None:
        """Clear the in-flight lock and stop the watchdog."""
        self._is_processing = False
        self._watchdog_timer.stop()

    def _maybe_serve_pending(self) -> None:
        """If a newer request queued up while we were busy, serve it now."""
        if self._pending_request and not self._debounce_timer.isActive():
            self._debounce_timer.start()

    @pyqtSlot()
    def _on_request_watchdog(self) -> None:
        """Force-release a wedged in-flight request so typing keeps working."""
        if self._is_processing:
            self._log("Completion watchdog: releasing stuck request", "debug")
            self._is_processing = False
            self.completion_ready.emit("")
            self._maybe_serve_pending()
    
    def force_completion(
        self,
        prefix: str,
        suffix: str,
        language: str,
        line: int,
        column: int,
    ) -> None:
        """
        Force an inline completion request (manual trigger, bypasses throttling).
        
        This is triggered by Ctrl+. shortcut and bypasses:
        - Minimum prefix length check
        - Throttling/debouncing
        - Whitespace-only line check
        
        Args:
            prefix: Text before cursor
            suffix: Text after cursor  
            language: Programming language (python, sql)
            line: Current line number (1-indexed)
            column: Current column (1-indexed)
        """
        self._log(f"Force completion request (Ctrl+.) at L{line}:C{column}", "info")
        
        try:
            # Reset processing state to allow immediate request
            self._is_processing = False
            
            # Generate unique request ID
            self._current_request_id += 1
            request_id = self._current_request_id
            self._active_request_id = request_id
            
            # Start processing
            self._is_processing = True
            self._watchdog_timer.start()

            if self.has_pynia and self._pynia_client:
                ctx = self._build_request_context(language)
                self._log(f"Force Pynia completion ({language}, L{line}:C{column})", "info")
                self._pynia_client.request_inline_completion(
                    prefix, suffix, language, context=ctx
                )
                return

            self._log("Force completion failed — configure Pynia in Settings", "warning")
            self._release_processing()
            self.completion_ready.emit("")

        except Exception as e:
            import traceback
            self._log(f"Force completion exception: {e}\n{traceback.format_exc()}", "error")
            self._release_processing()
            self.completion_ready.emit("")

    def _get_smart_completion(
        self,
        prefix: str,
        suffix: str,
        language: str,
    ) -> str:
        """
        Get smart completion based on context.
        
        Provides common completions while Copilot integration is being developed.
        """
        # Get the last line being typed
        lines = prefix.split('\n')
        last_line = lines[-1] if lines else ""
        stripped = last_line.lstrip()
        indent = last_line[:len(last_line) - len(stripped)]
        
        if language == "python":
            return self._python_completion(stripped, indent, prefix)
        elif language == "sql":
            return self._sql_completion(stripped, indent, prefix)
        
        return ""
    
    def _python_completion(self, line: str, indent: str, prefix: str) -> str:
        """Generate Python completions with common patterns."""
        # Import completions - check what module is being imported
        if line.startswith("import "):
            partial = line[7:].strip()
            for module, full_import in PYTHON_IMPORTS.items():
                if module.startswith(partial) and module != partial:
                    return module[len(partial):]
            return ""
        
        if line.startswith("from "):
            partial = line[5:].strip()
            for module in PYTHON_IMPORTS:
                if module.startswith(partial) and " import" not in line:
                    return module[len(partial):] + " import "
            return ""
        
        # Structure completions
        if line.startswith("def ") and "(" not in line:
            # Only assume `self` when the def is clearly inside a class body
            # (indented and a class appears above). A module-level function
            # getting `(self):` was a classic wrong suggestion.
            in_class = bool(indent) and ("class " in prefix)
            return "(self):" if in_class else "():"

        if line.startswith("class ") and ":" not in line:
            return ":"
        
        if line.startswith("for ") and " in " not in line:
            var_hint = line[4:].strip()
            if var_hint:
                return " in range(10):\n" + indent + "    "
            return "item in range(10):\n" + indent + "    "
        
        if line.startswith("if ") and ":" not in line:
            return ":\n" + indent + "    "
        
        if line.startswith("elif ") and ":" not in line:
            return ":\n" + indent + "    "
        
        if line.startswith("while ") and ":" not in line:
            return ":\n" + indent + "    "
        
        if line.startswith("with ") and " as " not in line:
            if "open(" in line:
                return " as f:\n" + indent + "    "
            return " as ctx:\n" + indent + "    "
        
        if line.startswith("try") and line.strip() == "try":
            return ":\n" + indent + "    \n" + indent + "except Exception as e:\n" + indent + "    "
        
        if line.startswith("except") and ":" not in line:
            return " Exception as e:\n" + indent + "    "
        
        # Pandas patterns
        if "pd.read_" in line and "(" not in line:
            if "csv" in line:
                return "('')"
            if "excel" in line:
                return "('')"
            if "sql" in line:
                return "('', conn)"
            return "csv('')"
        
        if ".to_" in line and "(" not in line:
            if "csv" in line:
                return "('')"
            if "excel" in line:
                return "('')"
            return ""
        
        if ".groupby(" in line and ")" not in line:
            return ")"
        
        if ".merge(" in line and ")" not in line:
            return ", on='')"
        
        if ".sort_values(" in line and ")" not in line:
            return "by='')"
        
        if line.endswith("."):
            # Method chaining hints - don't complete, let Copilot handle
            return ""
        
        return ""
    
    def _sql_completion(self, line: str, indent: str, prefix: str) -> str:
        """Generate SQL completions using cached schema."""
        upper = line.upper()
        upper_stripped = upper.rstrip()
        
        # Get first real table name if available
        first_table = self._cached_tables[0] if self._cached_tables else None
        
        # SELECT completion
        if upper_stripped.startswith("SELECT") and "FROM" not in upper_stripped:
            return " * FROM "
        
        # FROM/JOIN table completion - also handle trailing space
        if upper_stripped.endswith("FROM") or upper_stripped.endswith("JOIN"):
            if first_table:
                return f" {first_table}"
            return "table_name"  # Fallback when no cached tables
        
        # Check if line ends with FROM or JOIN followed by space (user wants table)
        if " FROM " in upper and upper.endswith(" "):
            # After "FROM " - suggest table
            if first_table:
                return first_table
            return "table_name"  # Fallback
        
        # Partial table name after FROM/JOIN
        table_match = self._match_partial_table(line)
        if table_match:
            return table_match
        
        # Column completion after table is specified
        if upper_stripped.endswith("SELECT"):
            # Just started SELECT - let user type or use Copilot
            return " "
        
        # WHERE/AND/OR column completion
        if upper_stripped.endswith(("WHERE", "AND", "OR")):
            cols = self._get_columns_from_query(prefix)
            if cols:
                return f" {cols[0]} = "
            return " "
        
        # ORDER BY column completion
        if upper_stripped.endswith("ORDER BY"):
            cols = self._get_columns_from_query(prefix)
            if cols:
                return f" {cols[0]} ASC"
            return " "
        
        # GROUP BY column completion
        if upper.rstrip().endswith("GROUP BY"):
            cols = self._get_columns_from_query(prefix)
            if cols:
                return f" {cols[0]}"
            return " "
        
        # INSERT INTO completion
        if upper.startswith("INSERT INTO") and "VALUES" not in upper:
            if first_table and "(" not in upper:
                table_name = line.split()[-1] if len(line.split()) > 2 else first_table
                cols = self._cached_columns.get(table_name, [])[:5]
                if cols:
                    return f" ({', '.join(cols)}) VALUES ()"
            return ""
        
        # UPDATE completion
        if upper.startswith("UPDATE") and "SET" not in upper:
            if len(line.split()) == 1:  # Just "UPDATE"
                return f" {first_table} SET " if first_table else " "
            return " SET "
        
        # DELETE completion
        if upper.startswith("DELETE") and "FROM" not in upper:
            return f" FROM {first_table}" if first_table else " FROM "
        
        # CREATE TABLE
        if upper.startswith("CREATE TABLE") and "(" not in upper:
            return " (\n    id INT PRIMARY KEY,\n    \n)"
        
        # Keyword completion for partial keywords
        keyword_completion = self._complete_keyword(upper)
        if keyword_completion:
            return keyword_completion
        
        return ""
    
    def _match_partial_table(self, line: str) -> str:
        """Match partial table name and complete it."""
        if not self._cached_tables:
            return ""
        
        # Look for pattern like "FROM tab" or "JOIN us"
        patterns = [r"\bFROM\s+(\w+)$", r"\bJOIN\s+(\w+)$", r"\bINTO\s+(\w+)$"]
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                partial = match.group(1).lower()
                for table in self._cached_tables:
                    if table.lower().startswith(partial) and table.lower() != partial:
                        return table[len(partial):]
        return ""
    
    def _get_columns_from_query(self, prefix: str) -> List[str]:
        """Extract relevant columns from the current query context."""
        # Find table references in the query
        tables_in_query = set()
        for table in self._cached_tables:
            if re.search(rf"\b{re.escape(table)}\b", prefix, re.IGNORECASE):
                tables_in_query.add(table)
        
        # Collect all columns from referenced tables
        all_cols = []
        for table in tables_in_query:
            all_cols.extend(self._cached_columns.get(table, []))
        
        # If no tables found, return columns from first table
        if not all_cols and self._cached_tables:
            first_table = self._cached_tables[0]
            all_cols = self._cached_columns.get(first_table, [])
        
        return all_cols[:5]  # Limit to 5 columns
    
    def _complete_keyword(self, upper: str) -> str:
        """Complete partial SQL keywords."""
        # Get last word
        words = upper.split()
        if not words:
            return ""
        last_word = words[-1]
        
        # Skip if too short or already a complete keyword
        if len(last_word) < 2:
            return ""
        
        # Check for partial keyword matches
        for keyword in SQL_KEYWORDS:
            keyword_parts = keyword.split()
            first_part = keyword_parts[0]
            if first_part.startswith(last_word) and first_part != last_word:
                completion = first_part[len(last_word):]
                if len(keyword_parts) > 1:
                    completion += " " + " ".join(keyword_parts[1:])
                return completion
        
        return ""

    def _clean_completion(self, text: str) -> str:
        """Clean up completion text from chat response."""
        text = text.strip()
        
        # Remove markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            if len(lines) >= 3 and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1])
        
        return text
