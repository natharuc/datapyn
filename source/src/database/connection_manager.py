"""
Gerenciador de múltiplas conexões de banco de dados
"""

from typing import Dict, Optional, List
from .database_connector import DatabaseConnector
import json
import os
from pathlib import Path
from datetime import datetime


class ConnectionManager:
    """Gerencia múltiplas conexões salvas com suporte a grupos/pastas"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path.home() / ".datapyn" / "connections.json"

        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        self.connections: Dict[str, DatabaseConnector] = {}
        self.saved_configs: dict = self._load_configs()
        self.active_connection: Optional[str] = None

    def _load_configs(self) -> dict:
        """Carrega configurações salvas"""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Migrar formato antigo para novo (com grupos)
                if isinstance(data, dict) and "groups" not in data:
                    # Formato antigo: apenas dict de conexões
                    return {"groups": {}, "connections": data}
                return data
        return {"groups": {}, "connections": {}}

    def _save_configs(self):
        """Salva configurações"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.saved_configs, f, indent=2)

    def save_connection_config(
        self,
        name: str,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str = "",
        save_password: bool = False,
        password: str = "",
        group: str = "",
        use_windows_auth: bool = False,
        color: str = "",
    ):
        """Salva uma configuração de conexão"""
        config = {
            "db_type": db_type,
            "host": host,
            "port": port,
            "database": database,
            "username": username,
            "group": group,
            "use_windows_auth": use_windows_auth,
            "color": color,
            "created_at": datetime.now().isoformat(),
            "last_used": None,
        }

        if save_password and password:
            # TODO: Implementar armazenamento seguro de senha (keyring)
            config["password"] = password

        self.saved_configs["connections"][name] = config
        self._save_configs()

    def get_saved_connections(self) -> list:
        """Retorna lista de conexões salvas"""
        return list(self.saved_configs.get("connections", {}).keys())

    def get_connection_config(self, name: str) -> Optional[dict]:
        """Retorna configuração de uma conexão salva"""
        return self.saved_configs.get("connections", {}).get(name)

    def update_connection_config(
        self,
        old_name: str,
        new_name: str,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str = "",
        save_password: bool = False,
        password: str = "",
        group: str = "",
        use_windows_auth: bool = False,
        color: str = "",
    ):
        """Atualiza uma configuração de conexão existente"""
        if old_name in self.saved_configs.get("connections", {}):
            # Manter data de criação
            old_config = self.saved_configs["connections"][old_name]
            created_at = old_config.get("created_at", datetime.now().isoformat())

            # Remover conexão antiga se nome mudou
            if old_name != new_name:
                del self.saved_configs["connections"][old_name]

            # Salvar com novo nome
            self.save_connection_config(
                new_name,
                db_type,
                host,
                port,
                database,
                username,
                save_password,
                password,
                group,
                use_windows_auth,
                color,
            )

            # Restaurar data de criação
            self.saved_configs["connections"][new_name]["created_at"] = created_at
            self._save_configs()

    def delete_connection_config(self, name: str):
        """Remove uma configuração salva"""
        if name in self.saved_configs.get("connections", {}):
            del self.saved_configs["connections"][name]
            self._save_configs()

    def create_group(self, name: str, color: str = "", parent: str = ""):
        """Cria um grupo/pasta para organizar conexões"""
        if "groups" not in self.saved_configs:
            self.saved_configs["groups"] = {}

        self.saved_configs["groups"][name] = {
            "color": color,
            "parent": parent,
            "created_at": datetime.now().isoformat(),
        }
        self._save_configs()

    def get_groups(self) -> Dict[str, dict]:
        """Retorna todos os grupos"""
        return self.saved_configs.get("groups", {})

    def delete_group(self, name: str):
        """Remove um grupo (move conexões para raiz)"""
        if name in self.saved_configs.get("groups", {}):
            # Move todas as conexões deste grupo para raiz
            for conn_name, conn_config in self.saved_configs.get("connections", {}).items():
                if conn_config.get("group") == name:
                    conn_config["group"] = ""

            del self.saved_configs["groups"][name]
            self._save_configs()

    def rename_group(self, old_name: str, new_name: str):
        """Renomeia um grupo"""
        if old_name in self.saved_configs.get("groups", {}):
            # Atualizar referências nas conexões
            for conn_config in self.saved_configs.get("connections", {}).values():
                if conn_config.get("group") == old_name:
                    conn_config["group"] = new_name

            # Renomear grupo
            self.saved_configs["groups"][new_name] = self.saved_configs["groups"][old_name]
            del self.saved_configs["groups"][old_name]
            self._save_configs()

    def get_connections_by_group(self, group: str = None) -> Dict[str, dict]:
        """Retorna conexões de um grupo específico (None = sem grupo)"""
        group = group or ""
        return {
            name: config
            for name, config in self.saved_configs.get("connections", {}).items()
            if config.get("group", "") == group
        }

    def mark_connection_used(self, name: str):
        """Marca última vez que conexão foi usada"""
        if name in self.saved_configs.get("connections", {}):
            self.saved_configs["connections"][name]["last_used"] = datetime.now().isoformat()
            self._save_configs()

    def create_connection(
        self, name: str, db_type: str, host: str, port: int, database: str, username: str, password: str, **kwargs
    ) -> DatabaseConnector:
        """Cria uma nova conexão"""
        connector = DatabaseConnector()
        connector.connect(db_type, host, port, database, username, password, **kwargs)
        self.connections[name] = connector
        self.active_connection = name
        return connector

    def get_connection(self, name: str) -> Optional[DatabaseConnector]:
        """Retorna uma conexão existente"""
        return self.connections.get(name)

    def get_active_connection(self) -> Optional[DatabaseConnector]:
        """Retorna a conexão ativa"""
        if self.active_connection:
            return self.connections.get(self.active_connection)
        return None

    def set_active_connection(self, name: str):
        """Define a conexão ativa"""
        if name in self.connections:
            self.active_connection = name

    def close_connection(self, name: str):
        """Fecha uma conexão"""
        if name in self.connections:
            self.connections[name].disconnect()
            del self.connections[name]
            if self.active_connection == name:
                self.active_connection = None

    def close_all(self):
        """Fecha todas as conexões"""
        for name in list(self.connections.keys()):
            self.close_connection(name)
