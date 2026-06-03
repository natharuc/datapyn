"""SQL execution for PoC (in-memory SQLite; extensible to v1 connectors later)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class SqlExecutor:
    """PoC executor using a shared in-memory SQLite engine."""

    def __init__(self) -> None:
        self._engine: Optional[Engine] = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine("sqlite:///:memory:")
        return self._engine

    def execute_sql(self, sql: str) -> Dict[str, Any]:
        sql = (sql or "").strip()
        if not sql:
            raise ValueError("SQL is empty")

        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn)

        columns: List[str] = [str(c) for c in df.columns.tolist()]
        rows: List[List[Any]] = _dataframe_to_json_rows(df)

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": False,
        }


def _dataframe_to_json_rows(df: pd.DataFrame) -> List[List[Any]]:
    out: List[List[Any]] = []
    for record in df.to_dict(orient="records"):
        row = []
        for col in df.columns:
            row.append(_json_safe(record[col]))
        out.append(row)
    return out


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    return str(value)
