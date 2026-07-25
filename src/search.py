"""Keyless web retrieval.

Gemini's Google Search grounding turned out not to be covered by the free tier
(HTTP 429, "check your plan and billing"), so citations come from here instead.

This is arguably the stronger design for this brief. Rather than trusting a model
to report where it found something, we retrieve a real result set first and hand
the model a *numbered* evidence list. The model cites by index, and we map the
index back to the URL we actually fetched — so a fabricated citation is not
merely discouraged, it is unrepresentable.

Backends, in order: Bing RSS (keyless, returns real result URLs), then Wikipedia's
API to top up thin result sets.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Without an explicit market, Bing's RSS view ignores the query and returns
# locale-default junk (we were getting Chinese minesweeper pages for "Codelco").
# Pinning the market is what makes this backend usable at all.
MARKET = {"mkt": "en-US", "setlang": "en", "cc": "us"}

BING_RSS = "https://www.bing.com/search"
WIKI_API = "https://en.wikipedia.org/w/api.php"

# Domains that are real URLs but too weak to hang a cold-email claim on.
_JUNK = (
    "bing.com", "google.com", "facebook.com", "twitter.com", "x.com",
    "pinterest.com", "reddit.com", "youtube.com", "tiktok.com",
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class Hit:
    title: str
    url: str
    snippet: str = ""
    publisher: str = ""

    @property
    def domain(self) -> str:
        try:
            return urlparse(self.url).netloc.replace("www.", "")
        except Exception:
            return ""


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()


def _usable(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    return not any(j in url.lower() for j in _JUNK)


def bing_rss(query: str, limit: int = 8) -> list[Hit]:
    """Bing exposes an RSS view of results with no API key required."""
    params = {"q": query, "format": "rss", "count": limit}
    params.update(MARKET)
    try:
        resp = requests.get(BING_RSS, params=params, headers=UA, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return []

    hits: list[Hit] = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        if not _usable(link):
            continue
        hits.append(
            Hit(
                title=_clean(item.findtext("title") or ""),
                url=link,
                snippet=_clean(item.findtext("description") or "")[:400],
            )
        )
        if len(hits) >= limit:
            break
    return hits


def wikipedia(query: str, limit: int = 3) -> list[Hit]:
    """Stable, citable background — used to top up thin result sets."""
    try:
        resp = requests.get(
            WIKI_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": limit,
            },
            headers=UA,
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("query", {}).get("search", [])
    except Exception:
        return []

    hits: list[Hit] = []
    for r in results:
        title = r.get("title", "")
        if not title:
            continue
        hits.append(
            Hit(
                title=title,
                url="https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
                snippet=_clean(r.get("snippet", ""))[:300],
                publisher="Wikipedia",
            )
        )
    return hits


def search(queries: list[str], per_query: int = 6, cap: int = 18) -> list[Hit]:
    """Run several queries, dedupe by URL, and return a merged evidence set."""
    seen: set[str] = set()
    merged: list[Hit] = []

    for q in queries:
        if not q:
            continue
        for hit in bing_rss(q, limit=per_query):
            if hit.url in seen:
                continue
            seen.add(hit.url)
            merged.append(hit)
        time.sleep(0.4)  # be a polite client
        if len(merged) >= cap:
            break

    if len(merged) < 4 and queries:
        for hit in wikipedia(queries[0]):
            if hit.url not in seen:
                seen.add(hit.url)
                merged.append(hit)

    return merged[:cap]


_SCRIPT_RE = re.compile(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", re.S | re.I)


def fetch_page(url: str, max_chars: int = 2600) -> str:
    """Pull readable text from a result page. Best effort — failures are fine."""
    try:
        resp = requests.get(url, headers=UA, timeout=18)
        if resp.status_code != 200:
            return ""
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype:
            return ""
        html = _SCRIPT_RE.sub(" ", resp.text)
        return _clean(html)[:max_chars]
    except Exception:
        return ""


def enrich(hits: list[Hit], top_n: int = 5) -> list[Hit]:
    """Fetch page text for the strongest hits so claims rest on real content,
    not on a two-line search snippet."""
    for hit in hits[:top_n]:
        body = fetch_page(hit.url)
        if len(body) > len(hit.snippet):
            hit.snippet = body
    return hits


def evidence_block(hits: list[Hit], per_hit_chars: int = 1200) -> str:
    """Numbered evidence the model must cite by index."""
    lines = []
    for i, h in enumerate(hits):
        lines.append(
            f"[{i}] {h.title}\n    source: {h.domain}\n    {h.snippet[:per_hit_chars]}"
        )
    return "\n".join(lines) if lines else "(no search results returned)"
