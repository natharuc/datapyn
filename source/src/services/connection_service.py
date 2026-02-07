"""
Connection Service - Serviço para gerenciamento de conexões de banco de dados

Responsabilidades:
- Criar/remover conexões
- Testar conexões
- Sincronizar com ApplicationState
"""

from dataclasses import dataclass
from typing import Callable, Optional

from ..database import ConnectionManager
from ..state import ApplicationState
from ..workers import DatabaseConnectionWorker, execute_worker


@dataclass
class ConnectionConfig:
    """Configuração de conexão"""

    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str = ""
    password: str = ""
    use_windows_auth: bool = False


class ConnectionService:
    """
    Serviço de gerenciamento de conexões

    Sincroniza com ApplicationState e ConnectionManager.
    Executa conexões via workers assíncronos.

    Exemplo:
        service = ConnectionService()
        config = ConnectionConfig(...)
        service.connect(
            config,
            on_success=self.handle_connected,
            on_error=self.handle_error
        )
    """

    def __init__(self):
        self.app_state = ApplicationState.instance()
        self.conn_manager = ConnectionManager()

    def connect(
        self,
        config: ConnectionConfig,
        *,
        on_success: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_started: Optional[Callable[[], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ):
        """
        Conecta a banco de dados de forma assíncrona

        Args:
            config: Configuração da conexão
            on_success: Callback em caso de sucesso
            on_error: Callback com mensagem de erro
            on_started: Callback ao iniciar
            on_finished: Callback ao finalizar (sempre)
        """
        # Cria worker
        worker = DatabaseConnectionWorker(
            self.conn_manager,
            config.name,
            config.db_type,
            config.host,
            config.port,
            config.database,
            config.username,
            config.password,
            config.use_windows_auth,
        )

        # Conectar callbacks
        if on_started:
            worker.started.connect(on_started)

        if on_finished:
            worker.finished.connect(on_finished)

        def handle_success():
            """Handler interno para sucesso"""
            # Adiciona ao estado
            self.app_state.add_connection(
                name=config.name,
                db_type=config.db_type,
                host=config.host,
                port=config.port,
                database=config.database,
                username=config.username,
            )

            if on_success:
                on_success()

        def handle_error(error_msg: str):
            """Handler interno para erro"""
            if on_error:
                on_error(error_msg)

        worker.connection_success.connect(handle_success)
        worker.error.connect(handle_error)

        # Executa worker
        execute_worker(worker)

    def disconnect(self, conn_name: str) -> tuple[bool, str]:
        """
        Desconecta de um banco

        Returns:
            (success, error_message)
        """
        try:
            # Remove do manager
            self.conn_manager.remove_connection(conn_name)

            # Remove do estado
            self.app_state.remove_connection(conn_name)

            return True, ""
        except Exception as e:
            return False, str(e)

    def test_connection(self, config: ConnectionConfig, *, on_result: Optional[Callable[[bool, str], None]] = None):
        """
        Testa conexão sem salvar

        Args:
            config: Configuração da conexão
            on_result: Callback com (success, message)
        """
        # Usa nome temporário
        temp_name = f"_test_{config.name}"
        temp_config = ConnectionConfig(
            name=temp_name,
            db_type=config.db_type,
            host=config.host,
            port=config.port,
            database=config.database,
            username=config.username,
            password=config.password,
            use_windows_auth=config.use_windows_auth,
        )

        def on_success():
            # Remove conexão de teste
            self.conn_manager.remove_connection(temp_name)
            if on_result:
                on_result(True, "Conexão bem-sucedida!")

        def on_error(error_msg: str):
            if on_result:
                on_result(False, error_msg)

        self.connect(temp_config, on_success=on_success, on_error=on_error)

    def get_active_connection_name(self) -> Optional[str]:
        """Retorna nome da conexão ativa"""
        conn = self.app_state.get_active_connection()
        return conn.name if conn else None

    def set_active_connection(self, conn_name: str):
        """Define conexão ativa"""
        self.app_state.set_active_connection(conn_name)
