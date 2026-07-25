"""Provider layer.

Two providers, two jobs:

  * Gemini + Google Search grounding -> every research call. Grounding returns
    real source URLs, which is what makes the "no fabricated data" rule
    survivable. Grounded calls cannot also use JSON response schemas, so we ask
    for JSON in the prompt and parse defensively.
  * Groq -> the high-volume drafting and critic loop. Fast, and supports real
    JSON mode.

Either provider can be missing; callers degrade rather than crash.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from . import config
from .schemas import Source


class LLMUnavailable(RuntimeError):
    """No provider configured for the requested capability."""


@dataclass
class LLMResult:
    text: str
    sources: list[Source] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    provider: str = ""
    error: str = ""


# --------------------------------------------------------------------------
# JSON extraction — models wrap JSON in prose or fences more often than not.
# --------------------------------------------------------------------------

def extract_json(text: str) -> Any:
    """Pull the first well-formed JSON value out of a model response."""
    if not text:
        raise ValueError("empty response")

    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Scan for the first balanced { } or [ ] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"no parseable JSON in response: {text[:200]!r}")


def _post(url: str, payload: dict, headers: dict | None = None) -> dict:
    last: Exception | None = None
    for attempt in range(config.MAX_RETRIES):
        try:
            resp = requests.post(
                url, json=payload, headers=headers or {}, timeout=config.REQUEST_TIMEOUT
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 2 ** attempt + 1
                time.sleep(wait)
                last = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - surfaced to the trace
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed after {config.MAX_RETRIES} attempts: {last}")


# --------------------------------------------------------------------------
# Gemini — grounded research
# --------------------------------------------------------------------------

_URL_CACHE: dict[str, str] = {}


def resolve_url(url: str) -> str:
    """Gemini returns redirect URLs; follow them so citations are clickable."""
    if not url or "grounding-api-redirect" not in url:
        return url
    if url in _URL_CACHE:
        return _URL_CACHE[url]
    try:
        resp = requests.head(url, allow_redirects=True, timeout=15)
        final = resp.url or url
    except Exception:  # noqa: BLE001 - a redirect failure is not fatal
        final = url
    _URL_CACHE[url] = final
    return final


def gemini_available() -> bool:
    return bool(config.GEMINI_API_KEY)


def gemini_grounded(prompt: str, system: str | None = None) -> LLMResult:
    """Run a research prompt with Google Search grounding enabled."""
    if not gemini_available():
        raise LLMUnavailable("GEMINI_API_KEY is not set")

    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.3},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    url = config.GEMINI_URL.format(model=config.GEMINI_MODEL)
    data = _post(
        url,
        payload,
        headers={
            "x-goog-api-key": config.GEMINI_API_KEY,
            "Content-Type": "application/json",
        },
    )

    candidates = data.get("candidates") or []
    if not candidates:
        return LLMResult(text="", provider="gemini", error="no candidates returned")

    cand = candidates[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)

    meta = cand.get("groundingMetadata") or {}
    sources: list[Source] = []
    seen: set[str] = set()
    for chunk in meta.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        uri = resolve_url(web.get("uri", ""))
        if not uri or uri in seen:
            continue
        seen.add(uri)
        sources.append(
            Source(
                url=uri,
                title=web.get("title", "") or uri,
                publisher=web.get("domain", "") or _domain(uri),
            )
        )

    return LLMResult(
        text=text,
        sources=sources,
        queries=list(meta.get("webSearchQueries") or []),
        provider="gemini",
    )


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).replace("www.", "") if m else ""


# --------------------------------------------------------------------------
# Groq — drafting and critique
# --------------------------------------------------------------------------

def groq_available() -> bool:
    return bool(config.GROQ_API_KEY)


def groq_chat(prompt: str, system: str | None = None, json_mode: bool = False) -> str:
    if not groq_available():
        raise LLMUnavailable("GROQ_API_KEY is not set")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": config.GROQ_MODEL,
        "messages": messages,
        "temperature": 0.4,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    data = _post(
        config.GROQ_URL,
        payload,
        headers={
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    return data["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------
# Capability-oriented helpers used by the agents
# --------------------------------------------------------------------------

def research_json(prompt: str, system: str | None = None) -> tuple[Any, LLMResult]:
    """Grounded research that must return JSON. Gemini only (needs citations)."""
    result = gemini_grounded(prompt, system=system)
    if result.error:
        raise RuntimeError(result.error)
    return extract_json(result.text), result


def draft_json(prompt: str, system: str | None = None) -> Any:
    """Non-grounded structured generation. Groq preferred, Gemini fallback."""
    if groq_available():
        return extract_json(groq_chat(prompt, system=system, json_mode=True))
    if gemini_available():
        return extract_json(gemini_grounded(prompt, system=system).text)
    raise LLMUnavailable("no provider available for drafting")


def provider_status() -> dict[str, Any]:
    return {
        "gemini": {
            "configured": gemini_available(),
            "model": config.GEMINI_MODEL,
            "role": "grounded research + citations",
        },
        "groq": {
            "configured": groq_available(),
            "model": config.GROQ_MODEL,
            "role": "email drafting + critic loop",
        },
    }
