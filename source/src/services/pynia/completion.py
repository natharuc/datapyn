"""Fast inline code completion for Monaco editors via Pynia connectors."""

from __future__ import annotations

import logging
import re
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from src.services.pynia.settings import get_pynia_settings, get_provider_secret
from src.services.pynia.types import PROVIDERS, ProviderId

logger = logging.getLogger(__name__)

# Fast models per provider (low latency, low cost)
COMPLETION_MODELS: dict[ProviderId, str] = {
    "openai": "gpt-4o-mini",
    "openrouter": "openai/gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-20241022",
    "copilot": "gpt-4o-mini",
}

SYSTEM_PROMPT = (
    "You are Pynia inline autocomplete inside DataPyn. "
    "Output ONLY the text to insert at <CURSOR>. No markdown, no fences, no explanation."
)


def build_inline_prompt(
    *,
    language: str,
    prefix: str,
    suffix: str,
    context: str = "",
) -> str:
    """Build a minimal completion prompt."""
    prefix_trunc = prefix[-1200:] if len(prefix) > 1200 else prefix
    suffix_trunc = suffix[:300] if len(suffix) > 300 else suffix
    ctx = ""
    if context:
        ctx_block = context[:2000] if len(context) > 2000 else context
        ctx = f"\n\nContext:\n{ctx_block}\n"
    return (
        f"Complete this {language} code at <CURSOR>. Output only the insertion text.{ctx}\n"
        f"```{language}\n{prefix_trunc}<CURSOR>{suffix_trunc}\n```"
    )


def clean_completion_text(text: str, prefix: str, suffix: str) -> str:
    """Normalize model output to ghost-text insertion."""
    if not text:
        return ""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            cleaned = "\n".join(lines[1:-1])
        elif len(lines) >= 2:
            cleaned = "\n".join(lines[1:])
    cleaned = cleaned.replace("<CURSOR>", "").strip()
    # If model echoed full file, keep only the middle insertion
    if prefix and cleaned.startswith(prefix) and suffix and cleaned.endswith(suffix):
        cleaned = cleaned[len(prefix) : len(cleaned) - len(suffix)]
    # Strip accidental duplicate of prefix tail
    if prefix and cleaned.startswith(prefix[-80:]):
        cleaned = cleaned[len(prefix[-80:]) :]
    return cleaned.rstrip("\n")


def fetch_inline_completion(
    provider_id: ProviderId,
    *,
    model: str,
    language: str,
    prompt: str,
    timeout: float = 8.0,
) -> str:
    """Blocking HTTP completion (run from worker thread only)."""
    settings = get_pynia_settings()
    api_key = get_provider_secret(provider_id)
    if not api_key:
        raise RuntimeError("No API token configured for Pynia autocomplete.")

    if provider_id == "anthropic":
        return _fetch_anthropic(settings.base_url("anthropic"), api_key, model, prompt, timeout)
    return _fetch_openai_compatible(
        settings.base_url(provider_id),
        api_key,
        model,
        prompt,
        provider_id,
        timeout,
    )


def _fetch_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    provider_id: ProviderId,
    timeout: float,
) -> str:
    import requests

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider_id == "openrouter":
        headers["HTTP-Referer"] = "https://datapyn.app"
        headers["X-Title"] = "DataPyn Pynia"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 256,
        "temperature": 0.2,
        "stream": False,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code == 401:
        raise RuntimeError("Invalid API token for autocomplete.")
    if resp.status_code != 200:
        body = (resp.text or "")[:300]
        raise RuntimeError(f"Autocomplete HTTP {resp.status_code}: {body}")

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return (message.get("content") or "").strip()


def _fetch_anthropic(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float,
) -> str:
    import requests

    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 256,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code == 401:
        raise RuntimeError("Invalid API token for autocomplete.")
    if resp.status_code != 200:
        body = (resp.text or "")[:300]
        raise RuntimeError(f"Autocomplete HTTP {resp.status_code}: {body}")

    data = resp.json()
    parts = data.get("content") or []
    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    return "".join(texts).strip()


class PyniaInlineCompletionWorker(QObject):
    """Runs one inline completion off the UI thread."""

    inline_complete = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._provider_id: ProviderId = "openai"
        self._model = COMPLETION_MODELS["openai"]
        self._language = "python"
        self._prompt = ""
        self._prefix = ""
        self._suffix = ""
        self._cancelled = False

    def set_request(
        self,
        provider_id: ProviderId,
        language: str,
        prompt: str,
        prefix: str,
        suffix: str,
        model: Optional[str] = None,
    ) -> None:
        self._provider_id = provider_id
        self._language = language
        self._prompt = prompt
        self._prefix = prefix
        self._suffix = suffix
        self._model = model or COMPLETION_MODELS.get(provider_id, COMPLETION_MODELS["openai"])
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self._cancelled:
                self.inline_complete.emit("")
                return
            raw = fetch_inline_completion(
                self._provider_id,
                model=self._model,
                language=self._language,
                prompt=self._prompt,
            )
            if self._cancelled:
                self.inline_complete.emit("")
                return
            cleaned = clean_completion_text(raw, self._prefix, self._suffix)
            self.inline_complete.emit(cleaned)
        except Exception as exc:
            logger.warning("Pynia autocomplete failed: %s", exc)
            self.error.emit(str(exc))
            self.inline_complete.emit("")
        finally:
            self.finished.emit()
