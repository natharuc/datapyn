"""Pynia tool types — consolidated DataPyn agent surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass(frozen=True)
class PyniaTool:
    """Single tool exposed to LLM providers."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]

    def to_mcp_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.parameters,
            },
        }

    def to_openai_schema(self) -> Dict[str, Any]:
        required = [
            name
            for name, props in self.parameters.items()
            if not props.get("optional", False)
        ]
        cleaned = {
            name: {k: v for k, v in props.items() if k != "optional"}
            for name, props in self.parameters.items()
        }
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": cleaned,
                    "required": required,
                },
            },
        }
