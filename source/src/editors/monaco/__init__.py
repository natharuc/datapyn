"""
Monaco Editor integration package.

Uses Monaco Editor via QWebEngineView for advanced editing features
like ghost text inline completions from GitHub Copilot.
"""

import logging

logger = logging.getLogger(__name__)

# Import with fallback for headless/CI environments where WebEngine may fail
try:
    from .monaco_editor import MonacoEditor
    from .monaco_bridge import MonacoBridge
    from .inline_completion_service import InlineCompletionService
    
    __all__ = ["MonacoEditor", "MonacoBridge", "InlineCompletionService"]
except ImportError as e:
    logger.warning(f"MonacoEditor import failed (headless/CI environment?): {e}")
    # Provide stubs for testing environments
    MonacoEditor = None
    MonacoBridge = None
    InlineCompletionService = None
    __all__ = []
