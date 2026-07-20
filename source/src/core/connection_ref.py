"""Connection identity helpers (group + name composite key)."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.database.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

_STORAGE_SEP = "\x1f"


@dataclass(frozen=True, slots=True)
class ConnectionRef:
    """Saved connection identity: unique within group, repeatable across groups."""

    group: str  # "" = ungrouped
    name: str

    def display(self) -> str:
        """Human-readable label for UI."""
        if self.group:
            return f"{self.group} / {self.name}"
        return self.name

    def storage_key(self) -> str:
        """Stable key for runtime connector dicts."""
        return f"{self.group}{_STORAGE_SEP}{self.name}"

    @classmethod
    def from_storage_key(cls, key: str) -> ConnectionRef:
        if _STORAGE_SEP in key:
            group, name = key.split(_STORAGE_SEP, 1)
            return cls(group=group, name=name)
        return cls(group="", name=key)

    def to_dict(self) -> dict:
        return {"connection_group": self.group, "connection_name": self.name}

    @classmethod
    def from_dict(cls, data: dict) -> Optional[ConnectionRef]:
        name = data.get("connection_name")
        if not name:
            return None
        return cls(group=str(data.get("connection_group") or ""), name=str(name))


def parse_connection_ref(group: str | None, name: str | None) -> Optional[ConnectionRef]:
    if not name:
        return None
    return ConnectionRef(group=str(group or ""), name=str(name))


def resolve_connection_ref(
    manager: ConnectionManager,
    group: str,
    name: str,
) -> Optional[dict]:
    return manager.get_connection_config(group, name)


def resolve_by_name_only(manager: ConnectionManager, name: str) -> Optional[ConnectionRef]:
    """Resolve a legacy name-only reference (sessions/blocks without group)."""
    matches = [ref for ref in manager.get_saved_connections() if ref.name == name]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    ungrouped = [ref for ref in matches if not ref.group]
    if len(ungrouped) == 1:
        return ungrouped[0]
    logger.warning(
        "Ambiguous connection name %r (%d matches); using first match %s",
        name,
        len(matches),
        matches[0].display(),
    )
    return matches[0]
