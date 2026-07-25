"""Provider layer.

Original design used Gemini's Google Search grounding for citations. That turned
out not to be covered by the free tier (HTTP 429, "check your plan and billing"),
so research now runs retrieval-first:

    1. src.search retrieves a real result set for the stage's queries
    2. the model receives a NUMBERED evidence list and must cite by index
    3. we map indexes back to the URLs we actually fetched

The model never supplies a URL, so it cannot invent one. That is a stronger
guarantee than asking a grounded model to self-report its sources.

Generation runs on Groq (fast, reliable free tier) with Gemini as fallback.
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
from .search import Hit, enrich, evidence_block, search


class LLMUnavailable(RuntimeError):
    """No provider configured."""


@dataclass
class LLMResult:
    text: str = ""
    sources: list[Source] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    provider: str = ""
    error: str = ""


# --------------------------------------------------------------------------
# JSON extraction — models wrap JSON in prose or fences more often than not.
# --------------------------------------------------------------------------

def extract_json(text: str) -> Any:
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
            if resp.status_code in (429,) or resp.status_code >= 500:
                time.sleep(2 ** attempt + 1)
                last = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                continue
            if resp.status_code == 404:
                # Model gone / renamed — retrying will not help.
                raise RuntimeError(f"HTTP 404: {resp.text[:200]}")
            resp.raise_for_status()
            return resp.json()
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced to the trace
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed after {config.MAX_RETRIES} attempts: {last}")


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

def groq_available() -> bool:
    return bool(config.GROQ_API_KEY)


def gemini_available() -> bool:
    return bool(config.GEMINI_API_KEY)


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
        "temperature": 0.35,
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


def gemini_chat(prompt: str, system: str | None = None) -> str:
    if not gemini_available():
        raise LLMUnavailable("GEMINI_API_KEY is not set")
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.35},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    data = _post(
        config.GEMINI_URL.format(model=config.GEMINI_MODEL),
        payload,
        headers={
            "x-goog-api-key": config.GEMINI_API_KEY,
            "Content-Type": "application/json",
        },
    )
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)


# Once a provider reports a *daily* cap there is no point retrying it for the
# rest of the run — every subsequent attempt costs three back-off sleeps before
# failing identically. Trip a breaker and go straight to the fallback.
_EXHAUSTED: set[str] = set()


def _is_daily_cap(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg and ("per day" in msg or "tpd" in msg or "quota" in msg)


def _generate(prompt: str, system: str | None, json_mode: bool) -> tuple[str, str]:
    """Groq first, Gemini as fallback. Returns (text, provider)."""
    errors = []

    if groq_available() and "groq" not in _EXHAUSTED:
        try:
            return groq_chat(prompt, system=system, json_mode=json_mode), "groq"
        except Exception as exc:  # noqa: BLE001
            if _is_daily_cap(exc):
                _EXHAUSTED.add("groq")
            errors.append(f"groq: {exc}")

    if gemini_available() and "gemini" not in _EXHAUSTED:
        try:
            return gemini_chat(prompt, system=system), "gemini"
        except Exception as exc:  # noqa: BLE001
            if _is_daily_cap(exc):
                _EXHAUSTED.add("gemini")
            errors.append(f"gemini: {exc}")

    raise RuntimeError("all providers failed -> " + " | ".join(errors))


def exhausted_providers() -> list[str]:
    return sorted(_EXHAUSTED)


# --------------------------------------------------------------------------
# Capability helpers used by the agents
# --------------------------------------------------------------------------

def hit_to_source(hit: Hit) -> Source:
    return Source(url=hit.url, title=hit.title, publisher=hit.publisher or hit.domain)


def sources_from_indexes(hits: list[Hit], indexes: Any) -> list[Source]:
    """Map model-supplied evidence indexes back to URLs we actually retrieved."""
    out: list[Source] = []
    seen: set[str] = set()
    for idx in indexes or []:
        try:
            hit = hits[int(idx)]
        except (TypeError, ValueError, IndexError):
            continue
        if hit.url in seen:
            continue
        seen.add(hit.url)
        out.append(hit_to_source(hit))
    return out


# Wording matters more than it looks. An earlier, more absolute version of this
# ("returning less is correct") made Gemini answer {"candidates": []} on a page
# of perfectly good evidence — it read the rule as a reason to abstain entirely.
# The rule that actually matters is "never write a URL"; the rest should push
# toward extracting what IS there rather than toward silence.
CITE_RULES = """
CITATION RULES:
- Ground every statement in the EVIDENCE block above and cite it by index.
- NEVER write a URL yourself. Indexes only — the URLs are filled in for you.
- The evidence is real search output, so it normally DOES support useful
  answers: read it carefully and extract what is genuinely there.
- Where the evidence is silent, omit that specific detail. Do not invent
  names, numbers or dates. Omitting a detail is fine; returning an empty
  result when the evidence clearly contains relevant material is not.
"""


def research_json(
    prompt: str,
    queries: list[str],
    system: str | None = None,
    enrich_top: int = 5,
) -> tuple[Any, LLMResult]:
    """Retrieve first, then reason over the retrieved evidence."""
    hits = search(queries)
    if hits:
        enrich(hits, top_n=enrich_top)

    full_prompt = (
        f"EVIDENCE (numbered - cite these by index):\n{evidence_block(hits)}\n\n"
        f"{CITE_RULES}\n\n{prompt}"
    )
    text, provider = _generate(full_prompt, system, json_mode=True)
    result = LLMResult(
        text=text,
        hits=hits,
        sources=[hit_to_source(h) for h in hits],
        queries=queries,
        provider=provider,
    )
    return extract_json(text), result


def draft_json(prompt: str, system: str | None = None) -> Any:
    """Non-retrieval structured generation (composer, critic, signal extractor)."""
    text, _ = _generate(prompt, system, json_mode=True)
    return extract_json(text)


def provider_status() -> dict[str, Any]:
    return {
        "groq": {
            "configured": groq_available(),
            "model": config.GROQ_MODEL,
            "role": "primary generation (research reasoning, drafting, critic)",
        },
        "gemini": {
            "configured": gemini_available(),
            "model": config.GEMINI_MODEL,
            "role": "fallback generation",
        },
        "retrieval": {
            "configured": True,
            "model": "Bing RSS + Wikipedia (keyless)",
            "role": "evidence retrieval - all citations originate here",
        },
    }
