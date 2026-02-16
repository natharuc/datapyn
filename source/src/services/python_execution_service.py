"""
Python Execution Service - Service for Python code execution

Responsibilities:
- Execute Python code via workers
- Manage shared namespace
- Capture outputs and errors
- Validate code before executing
"""

from typing import Optional, Callable, Dict, Any
from datetime import datetime
from dataclasses import dataclass
import ast

from ..workers import PythonExecutionWorker, execute_worker
from ..state import ApplicationState


@dataclass
class PythonExecutionResult:
    """Python execution result"""

    code: str
    result: Any
    stdout: str
    stderr: str
    execution_time: float
    error: Optional[str] = None
    executed_at: datetime = None

    def __post_init__(self):
        if self.executed_at is None:
            self.executed_at = datetime.now()

    @property
    def is_success(self) -> bool:
        return self.error is None

    @property
    def has_output(self) -> bool:
        return bool(self.stdout or self.stderr or self.result is not None)


class PythonExecutionService:
    """
    Python code execution service

    Manages shared namespace between executions.
    Executes code via async workers.

    Example:
        service = PythonExecutionService()
        service.execute_code(
            "df.head()",
            on_success=self.handle_result,
            on_error=self.handle_error
        )
    """

    def __init__(self):
        self.app_state = ApplicationState.instance()
        self._init_namespace()

    def _init_namespace(self):
        """Initialize namespace with common imports"""
        namespace = self.app_state.get_namespace()

        # Add standard imports if they don't exist
        if "pd" not in namespace:
            import pandas as pd

            namespace["pd"] = pd

        if "np" not in namespace:
            try:
                import numpy as np

                namespace["np"] = np
            except ImportError:
                pass

    def execute_code(
        self,
        code: str,
        *,
        is_expression: bool = False,
        on_success: Optional[Callable[[PythonExecutionResult], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_started: Optional[Callable[[], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ):
        """
        Execute Python code asynchronously

        Args:
            code: Python code to execute
            is_expression: If True, evaluate as expression (uses eval)
            on_success: Callback with PythonExecutionResult
            on_error: Callback with error message
            on_started: Callback on start
            on_finished: Callback on finish (always)
        """
        # Validate code
        is_valid, error_msg = self.validate_code(code)
        if not is_valid:
            if on_error:
                on_error(error_msg)
            return

        # Shared namespace
        namespace = self.app_state.get_namespace()

        # Create worker
        worker = PythonExecutionWorker(code, namespace, is_expression)

        # Start time
        start_time = datetime.now()

        # Connect callbacks
        if on_started:
            worker.started.connect(on_started)

        if on_finished:
            worker.finished.connect(on_finished)

        def handle_result(result, stdout, stderr):
            """Internal handler for result"""
            execution_time = (datetime.now() - start_time).total_seconds()

            exec_result = PythonExecutionResult(
                code=code, result=result, stdout=stdout, stderr=stderr, execution_time=execution_time
            )

            # Update variables in state if there are new values
            self._update_state_variables(namespace)

            if on_success:
                on_success(exec_result)

        def handle_error(error_msg: str):
            """Internal handler for error"""
            execution_time = (datetime.now() - start_time).total_seconds()

            exec_result = PythonExecutionResult(
                code=code, result=None, stdout="", stderr="", execution_time=execution_time, error=error_msg
            )

            if on_error:
                on_error(error_msg)

        worker.execution_complete.connect(handle_result)
        worker.error.connect(handle_error)

        # Execute worker
        execute_worker(worker)

    def _update_state_variables(self, namespace: Dict[str, Any]):
        """Update ApplicationState with new variables from namespace"""
        import pandas as pd

        # Only sync DataFrames and basic types
        for name, value in namespace.items():
            # Ignore private and builtins
            if name.startswith("_"):
                continue

            # Only types that make sense to show
            if isinstance(value, (pd.DataFrame, pd.Series, int, float, str, list, dict)):
                current = self.app_state.get_variable(name)
                if current is not value:  # Changed
                    self.app_state.set_variable(name, value)

    def validate_code(self, code: str) -> tuple[bool, str]:
        """
        Validate Python code (syntax)

        Returns:
            (is_valid, error_message)
        """
        code = code.strip()

        if not code:
            return False, "Empty code"

        try:
            # Try to parse as AST
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Syntax error: {e}"

    def get_namespace(self) -> Dict[str, Any]:
        """Return current namespace"""
        return self.app_state.get_namespace()

    def clear_namespace(self):
        """Clear namespace (keep standard imports)"""
        self.app_state.clear_namespace()
        self._init_namespace()
