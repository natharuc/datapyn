"""
Python Execution Service - Serviço para execução de código Python

Responsabilidades:
- Executar código Python via workers
- Gerenciar namespace compartilhado
- Capturar outputs e erros
- Validar código antes de executar
"""
from typing import Optional, Callable, Dict, Any
from datetime import datetime
from dataclasses import dataclass
import ast

from ..workers import PythonExecutionWorker, execute_worker
from ..state import ApplicationState


@dataclass
class PythonExecutionResult:
    """Resultado de execução Python"""
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
    Serviço de execução de código Python
    
    Gerencia namespace compartilhado entre execuções.
    Executa código via workers assíncronos.
    
    Exemplo:
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
        """Inicializa namespace com imports comuns"""
        namespace = self.app_state.get_namespace()
        
        # Adiciona imports padrão se não existirem
        if 'pd' not in namespace:
            import pandas as pd
            namespace['pd'] = pd
        
        if 'np' not in namespace:
            try:
                import numpy as np
                namespace['np'] = np
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
        on_finished: Optional[Callable[[], None]] = None
    ):
        """
        Executa código Python de forma assíncrona
        
        Args:
            code: Código Python a executar
            is_expression: Se True, avalia como expressão (usa eval)
            on_success: Callback com PythonExecutionResult
            on_error: Callback com mensagem de erro
            on_started: Callback ao iniciar
            on_finished: Callback ao finalizar (sempre)
        """
        # Valida código
        is_valid, error_msg = self.validate_code(code)
        if not is_valid:
            if on_error:
                on_error(error_msg)
            return
        
        # Namespace compartilhado
        namespace = self.app_state.get_namespace()
        
        # Cria worker
        worker = PythonExecutionWorker(code, namespace, is_expression)
        
        # Tempo de início
        start_time = datetime.now()
        
        # Conectar callbacks
        if on_started:
            worker.started.connect(on_started)
        
        if on_finished:
            worker.finished.connect(on_finished)
        
        def handle_result(result, stdout, stderr):
            """Handler interno para resultado"""
            execution_time = (datetime.now() - start_time).total_seconds()
            
            exec_result = PythonExecutionResult(
                code=code,
                result=result,
                stdout=stdout,
                stderr=stderr,
                execution_time=execution_time
            )
            
            # Atualiza variáveis no estado se houver novos valores
            self._update_state_variables(namespace)
            
            if on_success:
                on_success(exec_result)
        
        def handle_error(error_msg: str):
            """Handler interno para erro"""
            execution_time = (datetime.now() - start_time).total_seconds()
            
            exec_result = PythonExecutionResult(
                code=code,
                result=None,
                stdout="",
                stderr="",
                execution_time=execution_time,
                error=error_msg
            )
            
            if on_error:
                on_error(error_msg)
        
        worker.execution_complete.connect(handle_result)
        worker.error.connect(handle_error)
        
        # Executa worker
        execute_worker(worker)
    
    def _update_state_variables(self, namespace: Dict[str, Any]):
        """Atualiza ApplicationState com novas variáveis do namespace"""
        import pandas as pd
        
        # Apenas sincroniza DataFrames e tipos básicos
        for name, value in namespace.items():
            # Ignora privados e builtins
            if name.startswith('_'):
                continue
            
            # Apenas tipos que fazem sentido mostrar
            if isinstance(value, (pd.DataFrame, pd.Series, int, float, str, list, dict)):
                current = self.app_state.get_variable(name)
                if current is not value:  # Mudou
                    self.app_state.set_variable(name, value)
    
    def validate_code(self, code: str) -> tuple[bool, str]:
        """
        Valida código Python (sintaxe)
        
        Returns:
            (is_valid, error_message)
        """
        code = code.strip()
        
        if not code:
            return False, "Código vazio"
        
        try:
            # Tenta parsear como AST
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Erro de sintaxe: {e}"
    
    def get_namespace(self) -> Dict[str, Any]:
        """Retorna namespace atual"""
        return self.app_state.get_namespace()
    
    def clear_namespace(self):
        """Limpa namespace (mantém imports padrão)"""
        self.app_state.clear_namespace()
        self._init_namespace()
