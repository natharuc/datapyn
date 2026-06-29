"""Fast inline code completion for Monaco editors via Pynia connectors."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from src.services.pynia.settings import get_pynia_settings, get_provider_secret
from src.services.pynia.types import PROVIDERS, ProviderId

logger = logging.getLogger(__name__)

# Last-resort default fast models per provider. Only used when the user has
# not picked an autocomplete model AND no chat model is selected; normally
# completion reuses the connector's chat model (see PyniaSettings.completion_model).
COMPLETION_MODELS: dict[ProviderId, str] = {
    "openai": "gpt-4o-mini",
    "openrouter": "openai/gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "copilot": "gpt-4o-mini",
}

# Convenience suggestions for the autocomplete model picker (editable — the
# user can type any model id their connector supports).
COMPLETION_MODEL_SUGGESTIONS: dict[ProviderId, list[str]] = {
    "openai": ["gpt-4.1-mini", "gpt-4.1-nano", "gpt-4o-mini"],
    "openrouter": [
        "openai/gpt-4.1-mini",
        "anthropic/claude-3.5-haiku",
        "google/gemini-2.0-flash-001",
    ],
    "anthropic": ["claude-3-5-haiku-latest", "claude-3-5-haiku-20241022"],
    "copilot": ["gpt-4.1", "gpt-4o-mini"],
}

SYSTEM_PROMPT = (
    "You are Pynia, an inline code-completion engine inside the DataPyn IDE "
    "(like GitHub Copilot ghost text). Continue the code at <CURSOR>.\n"
    "- Output ONLY the raw text to insert at <CURSOR> — it MAY span multiple lines.\n"
    "- No markdown, no code fences, no comments explaining, no restating existing code.\n"
    "- Match the surrounding style/indentation and the given language.\n"
    "- Use the provided schema/variables when relevant. If nothing sensible fits, output nothing.\n"
    "- For Python DataFrames, use ONLY column names listed in Context — never invent columns."
)


def build_inline_prompt(
    *,
    language: str,
    prefix: str,
    suffix: str,
    context: str = "",
) -> str:
    """Build a fill-in-the-middle completion prompt for a chat model.

    The code is the FOCUSED block only (prefix before the cursor, suffix after);
    ``context`` carries the extra data the editor already has (SQL schema or the
    Python namespace).
    """
    prefix_trunc = prefix[-2000:] if len(prefix) > 2000 else prefix
    suffix_trunc = suffix[:500] if len(suffix) > 500 else suffix
    ctx = ""
    if context:
        ctx_block = context[:2000] if len(context) > 2000 else context
        label = "Database schema" if language == "sql" else "Context"
        ctx = f"{label}:\n{ctx_block}\n\n"
    return (
        f"{ctx}"
        f"Complete the following {language} code at <CURSOR>. "
        f"Output only the text to insert (may be multiple lines):\n\n"
        f"```{language}\n{prefix_trunc}<CURSOR>{suffix_trunc}\n```"
    )


def build_inline_context(
    language: str,
    *,
    database_context: str = "",
    python_namespace_objects: Optional[Dict[str, Any]] = None,
    python_namespace: Optional[Dict[str, str]] = None,
    blocks_code_context: str = "",
) -> str:
    """Build session context for inline completion (run off the UI thread)."""
    if language == "sql":
        return database_context or ""
    if language == "python":
        from src.editors.completion_context import describe_namespace_dataframes

        parts: list[str] = []
        ns_objects = python_namespace_objects or {}
        ns_types = python_namespace or {}
        df_schema = describe_namespace_dataframes(ns_objects)
        if df_schema.strip():
            parts.append(df_schema.strip())
        elif ns_types:
            rows = [
                f"  {name}: {type_name}"
                for name, type_name in sorted(ns_types.items())
            ]
            parts.append("Available variables:\n" + "\n".join(rows))
        if blocks_code_context.strip():
            parts.append("Other blocks in this tab:\n" + blocks_code_context.strip())
        return "\n\n".join(parts)
    return ""


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
    # Keep internal newlines; only trim trailing blank lines at the end.
    while cleaned.endswith("\n"):
        cleaned = cleaned[:-1]
    return cleaned


def fetch_inline_completion(
    provider_id: ProviderId,
    *,
    model: str,
    language: str,
    prompt: str,
    timeout: float = 6.0,
) -> str:
    """Blocking HTTP completion (run from worker thread only).

    Keep this below the Monaco JS promise timeout (~9s) so a slow-but-valid
    completion still reaches the editor instead of being dropped client-side.
    """
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
        "max_tokens": 512,
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
        "max_tokens": 512,
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
        self._database_context = ""
        self._python_namespace_objects: Dict[str, Any] = {}
        self._python_namespace: Dict[str, str] = {}
        self._blocks_code_context = ""
        self._prebuilt_context = ""
        self._prefix = ""
        self._suffix = ""
        self._cancelled = False

    def set_request(
        self,
        provider_id: ProviderId,
        language: str,
        prefix: str,
        suffix: str,
        *,
        database_context: str = "",
        python_namespace_objects: Optional[Dict[str, Any]] = None,
        python_namespace: Optional[Dict[str, str]] = None,
        blocks_code_context: str = "",
        model: Optional[str] = None,
        context: str = "",
    ) -> None:
        """Configure one completion request.

        ``context`` is a backward-compatible pre-built context string; when
        empty, context is assembled from the raw session fields in ``run()``.
        """
        self._provider_id = provider_id
        self._language = language
        self._prefix = prefix
        self._suffix = suffix
        self._database_context = database_context or ""
        self._python_namespace_objects = dict(python_namespace_objects or {})
        self._python_namespace = dict(python_namespace or {})
        self._blocks_code_context = blocks_code_context or ""
        self._prebuilt_context = context or ""
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
            context = self._prebuilt_context
            if not context:
                context = build_inline_context(
                    self._language,
                    database_context=self._database_context,
                    python_namespace_objects=self._python_namespace_objects,
                    python_namespace=self._python_namespace,
                    blocks_code_context=self._blocks_code_context,
                )
            prompt = build_inline_prompt(
                language=self._language,
                prefix=self._prefix,
                suffix=self._suffix,
                context=context,
            )
            if self._cancelled:
                self.inline_complete.emit("")
                return
            raw = fetch_inline_completion(
                self._provider_id,
                model=self._model,
                language=self._language,
                prompt=prompt,
            )
            if self._cancelled:
                self.inline_complete.emit("")
                return
            cleaned = clean_completion_text(raw, self._prefix, self._suffix)
            self.inline_complete.emit(cleaned)
        except Exception as exc:
            logger.debug("Pynia inline completion failed (ignored): %s", exc)
            try:
                self.error.emit(str(exc))
            except RuntimeError:
                pass
            try:
                self.inline_complete.emit("")
            except RuntimeError:
                pass
        finally:
            try:
                self.finished.emit()
            except RuntimeError:
                pass
