"""
Gerenciador de resultados de queries em memória
"""

from typing import Dict, Optional, Any
import pandas as pd
from datetime import datetime


class ResultsManager:
    """Gerencia DataFrames em memória para uso no editor Python"""

    def __init__(self):
        self.results: Dict[str, pd.DataFrame] = {}
        self.metadata: Dict[str, dict] = {}
        self.history: list = []

        # Variável especial que sempre aponta para o último resultado
        self.last_result: Optional[pd.DataFrame] = None

        # Namespace persistente para variáveis do usuário
        self._user_namespace: Dict[str, Any] = {}

    def add_result(self, df: pd.DataFrame, query: str = "", auto_name: bool = True) -> str:
        """
        Adiciona um resultado à memória

        Args:
            df: DataFrame com o resultado
            query: Query SQL executada
            auto_name: Se True, gera automaticamente um nome (df1, df2, etc)

        Returns:
            str: Nome da variável criada
        """
        if auto_name:
            # Gera nome automático (df1, df2, df3, ...)
            counter = 1
            while f"df{counter}" in self.results:
                counter += 1
            var_name = f"df{counter}"
        else:
            var_name = "df"

        self.results[var_name] = df
        self.last_result = df

        # Salva metadata
        self.metadata[var_name] = {
            "created_at": datetime.now(),
            "query": query,
            "rows": len(df),
            "columns": len(df.columns),
            "memory_usage": df.memory_usage(deep=True).sum(),
        }

        # Adiciona ao histórico
        self.history.append({"timestamp": datetime.now(), "variable": var_name, "query": query, "rows": len(df)})

        return var_name

    def get_result(self, var_name: str) -> Optional[pd.DataFrame]:
        """Retorna um resultado específico"""
        return self.results.get(var_name)

    def get_namespace(self) -> dict:
        """
        Retorna namespace persistente com todos os DataFrames para execução Python.
        Inclui pandas, numpy e variáveis do usuário automaticamente.
        Este namespace é PERSISTENTE entre execuções.
        """
        import numpy as np

        # Atualiza o namespace persistente com os valores base
        self._user_namespace["pd"] = pd
        self._user_namespace["np"] = np
        self._user_namespace["df"] = self.last_result  # 'df' sempre aponta para o último

        # Adiciona todos os resultados nomeados ao namespace
        self._user_namespace.update(self.results)

        return self._user_namespace

    def update_namespace(self, namespace: dict):
        """
        Atualiza o namespace persistente com novas variáveis.
        Usado após execução Python ou cross-syntax para manter as variáveis.
        """
        # Filtra para não sobrescrever variáveis internas com None ou valores temporários
        for key, value in namespace.items():
            if not key.startswith("_") and key not in ("__builtins__",):
                self._user_namespace[key] = value

    def set_variable(self, name: str, value: Any):
        """Define uma variável no namespace do usuário"""
        self._user_namespace[name] = value

        # Se for um DataFrame, também adiciona aos results
        if isinstance(value, pd.DataFrame):
            self.results[name] = value
            self.metadata[name] = {
                "columns": len(value.columns),
                "rows": len(value),
                "memory_usage": value.memory_usage(deep=True).sum(),
                "created_at": datetime.now(),
            }

    def get_variable(self, name: str) -> Optional[Any]:
        """Retorna uma variável do namespace do usuário"""
        return self._user_namespace.get(name)

    def clear_user_namespace(self):
        """Limpa apenas as variáveis do usuário, mantendo pd, np, etc."""
        self._user_namespace.clear()

    def clear_result(self, var_name: str):
        """Remove um resultado específico"""
        if var_name in self.results:
            del self.results[var_name]
            if var_name in self.metadata:
                del self.metadata[var_name]

    def clear_all(self):
        """Limpa todos os resultados e o namespace do usuário"""
        self.results.clear()
        self.metadata.clear()
        self.last_result = None
        self._user_namespace.clear()

    def get_variables_info(self) -> pd.DataFrame:
        """Retorna informações sobre todas as variáveis em memória"""
        if not self.metadata:
            return pd.DataFrame(columns=["Variable", "Rows", "Columns", "Memory (MB)", "Created At"])

        data = []
        for var_name, meta in self.metadata.items():
            data.append(
                {
                    "Variable": var_name,
                    "Rows": meta["rows"],
                    "Columns": meta["columns"],
                    "Memory (MB)": round(meta["memory_usage"] / 1024 / 1024, 2),
                    "Created At": meta["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        return pd.DataFrame(data)

    def get_history(self) -> pd.DataFrame:
        """Retorna histórico de execuções"""
        if not self.history:
            return pd.DataFrame(columns=["Timestamp", "Variable", "Query", "Rows"])

        data = []
        for item in self.history:
            data.append(
                {
                    "Timestamp": item["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                    "Variable": item["variable"],
                    "Query": item["query"][:50] + "..." if len(item["query"]) > 50 else item["query"],
                    "Rows": item["rows"],
                }
            )

        return pd.DataFrame(data)
