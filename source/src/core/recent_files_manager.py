"""
Recent files manager - tracks and persists recently opened files.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

MAX_RECENT_FILES = 5


class RecentFilesManager:
    """Manages a list of recently opened files with JSON persistence."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            from src.core.workspace_service import get_workspace_service
            config_path = str(
                get_workspace_service().get_config_path("recent_files.json")
            )

        self.config_path = Path(config_path)
        self._recent_files: List[Dict[str, str]] = self._load()

    def _load(self) -> List[Dict[str, str]]:
        """Load recent files list from disk."""
        if not self.config_path.exists():
            return []
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data[:MAX_RECENT_FILES]
            return []
        except Exception:
            logger.warning("Failed to load recent files from %s", self.config_path)
            return []

    def _save(self):
        """Persist current list to disk."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._recent_files, f, indent=2, ensure_ascii=False)
        except Exception:
            logger.warning("Failed to save recent files to %s", self.config_path)

    def add(self, filepath: str):
        """Register a file as recently opened (moves to top if already present)."""
        normalised = os.path.normpath(filepath)

        # Remove existing entry for same path
        self._recent_files = [
            entry for entry in self._recent_files
            if os.path.normpath(entry.get("path", "")) != normalised
        ]

        self._recent_files.insert(0, {
            "path": normalised,
            "name": os.path.basename(normalised),
            "timestamp": datetime.now().isoformat(),
        })

        # Trim to max
        self._recent_files = self._recent_files[:MAX_RECENT_FILES]
        self._save()

    def get_recent(self) -> List[Dict[str, str]]:
        """Return the list of recent files (newest first)."""
        return list(self._recent_files)

    def clear(self):
        """Remove all recent files entries."""
        self._recent_files.clear()
        self._save()
