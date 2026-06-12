"""Circuit breaker for AI inline autocomplete (Copilot LSP + Pynia HTTP).

After repeated failures, stops ghost-text AI requests until the app restarts or
the user reconfigures Pynia (token, model, provider, autocomplete toggle).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_THRESHOLD = 3

_breaker: AiAutocompleteCircuitBreaker | None = None
_lock = threading.Lock()


@dataclass
class AiAutocompleteCircuitBreaker:
    """Opens after consecutive failures; stays open until ``reset()``."""

    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    consecutive_failures: int = 0
    is_open: bool = False
    reason: str = ""
    _open_logged: bool = field(default=False, repr=False)

    def allows_requests(self) -> bool:
        return not self.is_open

    def record_success(self) -> None:
        """Clear pre-open failure streak; does not close an open circuit."""
        if self.is_open:
            return
        self.consecutive_failures = 0

    def record_failure(self, reason: str = "") -> None:
        if self.is_open:
            return
        self.consecutive_failures += 1
        if reason:
            self.reason = str(reason)[:300]
        if self.consecutive_failures >= self.failure_threshold:
            self._open(self.reason or reason)

    def reset(self) -> None:
        """User reconfigured Pynia or explicit recovery."""
        was_open = self.is_open
        self.is_open = False
        self.consecutive_failures = 0
        self.reason = ""
        self._open_logged = False
        if was_open:
            logger.info("[Autocomplete] AI inline completion circuit reset — requests resumed.")

    def _open(self, reason: str) -> None:
        self.is_open = True
        if reason:
            self.reason = str(reason)[:300]
        if not self._open_logged:
            self._open_logged = True
            logger.warning(
                "[Autocomplete] AI inline completion paused after repeated failures. "
                "Restart the app or reconfigure Pynia in Settings to retry. %s",
                f"({self.reason})" if self.reason else "",
            )


def get_ai_autocomplete_circuit_breaker() -> AiAutocompleteCircuitBreaker:
    global _breaker
    with _lock:
        if _breaker is None:
            _breaker = AiAutocompleteCircuitBreaker()
        return _breaker


def reset_ai_autocomplete_circuit_breaker() -> None:
    """Call after Pynia settings change or Copilot reconnect."""
    get_ai_autocomplete_circuit_breaker().reset()
