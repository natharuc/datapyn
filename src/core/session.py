"""
Session - Representa uma sessão de trabalho independente

Cada aba do editor é uma sessão que contém:
- Conexão de banco própria
- Namespace Python próprio (variáveis)
- Estado de execução
- Threads próprias
"""
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from typing import Optional, Dict, Any
from datetime import datetime
import traceback
import sys
from io import StringIO


class Session(QObject):
    """
    Representa uma sessão de trabalho independente.
    
    Cada sessão tem seu próprio:
    - Conexão de banco de dados
    - Namespace Python (variáveis)
    - Estado de execução
    - Workers/Threads
    """
    
    # Sinais para notificar mudanças de estado
    connection_changed = pyqtSignal(str)  # connection_name ou ''
    status_changed = pyqtSignal(str)  # status text
    execution_started = pyqtSignal(str)  # mode (sql, python, cross)
    execution_finished = pyqtSignal(bool, str)  # success, message
    variables_changed = pyqtSignal(dict)  # namespace
    
    def __init__(self, session_id: str, title: str = "Script"):
        super().__init__()
        
        self.session_id = session_id
        self.title = title
        self.created_at = datetime.now()
        
        # Conexão de banco (referência, não o objeto em si)
        self._connection_name: Optional[str] = None
        self._connector = None
        
        # Namespace Python para variáveis
        self._namespace: Dict[str, Any] = {}
        
        # Estado
        self._is_executing = False
        self._last_status = "Pronto"
        self._code = ""  # Compatibilidade
        self._blocks: list = []  # Lista de blocos [{language, code}]
        
        # Workers ativos (threads)
        self._active_threads: list = []
    
    # === PROPRIEDADES ===
    
    @property
    def connection_name(self) -> Optional[str]:
        return self._connection_name
    
    @property
    def connector(self):
        return self._connector
    
    @property
    def is_connected(self) -> bool:
        return self._connector is not None and self._connector.is_connected
    
    @property
    def namespace(self) -> Dict[str, Any]:
        return self._namespace
    
    @property
    def is_executing(self) -> bool:
        return self._is_executing
    
    @property
    def code(self) -> str:
        return self._code
    
    @code.setter
    def code(self, value: str):
        self._code = value
    
    @property
    def blocks(self) -> list:
        """Lista de blocos [{language, code}]"""
        return self._blocks
    
    @blocks.setter
    def blocks(self, value: list):
        self._blocks = value
    
    # === CONEXÃO ===
    
    def set_connection(self, connection_name: str, connector):
        """Define a conexão desta sessão"""
        self._connection_name = connection_name
        self._connector = connector
        self.connection_changed.emit(connection_name)
        self.status_changed.emit(f"Conectado a {connection_name}")
    
    def clear_connection(self):
        """Remove a conexão desta sessão"""
        self._connection_name = None
        self._connector = None
        self.connection_changed.emit('')
        self.status_changed.emit("Desconectado")
    
    # === NAMESPACE (VARIÁVEIS) ===
    
    def set_variable(self, name: str, value: Any):
        """Define uma variável no namespace"""
        self._namespace[name] = value
        self.variables_changed.emit(self._namespace)
    
    def get_variable(self, name: str) -> Any:
        """Obtém uma variável do namespace"""
        return self._namespace.get(name)
    
    def clear_namespace(self):
        """Limpa todas as variáveis"""
        self._namespace.clear()
        self.variables_changed.emit(self._namespace)
    
    def update_namespace(self, variables: Dict[str, Any]):
        """Atualiza múltiplas variáveis"""
        self._namespace.update(variables)
        self.variables_changed.emit(self._namespace)
    
    # === EXECUÇÃO ===
    
    def start_execution(self, mode: str):
        """Marca início de execução"""
        self._is_executing = True
        self.execution_started.emit(mode)
    
    def finish_execution(self, success: bool, message: str):
        """Marca fim de execução"""
        self._is_executing = False
        self._last_status = message
        self.execution_finished.emit(success, message)
        self.status_changed.emit(message)
    
    # === THREAD MANAGEMENT ===
    
    def register_thread(self, thread: QThread):
        """Registra uma thread ativa"""
        self._active_threads.append(thread)
    
    def unregister_thread(self, thread: QThread):
        """Remove uma thread da lista"""
        if thread in self._active_threads:
            self._active_threads.remove(thread)
    
    def stop_all_threads(self):
        """Para todas as threads ativas"""
        for thread in self._active_threads[:]:
            if thread.isRunning():
                thread.quit()
                thread.wait(1000)
            self._active_threads.remove(thread)
    
    # === SERIALIZAÇÃO ===
    
    def serialize(self) -> Dict[str, Any]:
        """Serializa a sessão para persistência"""
        return {
            'session_id': self.session_id,
            'title': self.title,
            'connection_name': self._connection_name,
            'code': self._code,  # Compatibilidade
            'blocks': self._blocks,  # Novo: lista de blocos
            'created_at': self.created_at.isoformat(),
            # Não serializa namespace (pode ter objetos não serializáveis)
            # Não serializa connector (precisa reconectar)
        }
    
    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> 'Session':
        """Cria uma sessão a partir de dados serializados"""
        session = cls(
            session_id=data.get('session_id', ''),
            title=data.get('title', 'Script')
        )
        session._connection_name = data.get('connection_name')
        session._code = data.get('code', '')
        session._blocks = data.get('blocks', [])
        if data.get('created_at'):
            try:
                session.created_at = datetime.fromisoformat(data['created_at'])
            except:
                pass
        return session
    
    def initialize(self, connection_manager=None):
        """
        Inicializa a sessão após deserialização.
        Reconecta ao banco se necessário.
        """
        if self._connection_name and connection_manager:
            # Primeiro tenta pegar conexão existente
            connector = connection_manager.get_connection(self._connection_name)
            if connector and connector.is_connected():
                self._connector = connector
                self.connection_changed.emit(self._connection_name)
            else:
                # Tenta reconectar automaticamente
                try:
                    config = connection_manager.get_connection_config(self._connection_name)
                    if config:
                        connector = connection_manager.create_connection(
                            self._connection_name,
                            config['db_type'],
                            config['host'],
                            config['port'],
                            config['database'],
                            config.get('username', ''),
                            config.get('password', ''),
                            use_windows_auth=config.get('use_windows_auth', False)
                        )
                        if connector:
                            self._connector = connector
                            self.connection_changed.emit(self._connection_name)
                except Exception as e:
                    print(f"Erro ao reconectar sessão '{self.title}' a '{self._connection_name}': {e}")
                    # Limpa conexão se falhar
                    self._connection_name = None
    
    # === CLEANUP ===
    
    def cleanup(self):
        """Limpa recursos da sessão"""
        self.stop_all_threads()
        self._namespace.clear()
        # Não desconecta o banco aqui (pode ser compartilhado)
    
    def __del__(self):
        self.cleanup()
