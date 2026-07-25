#!/usr/bin/env python3
"""CLI entry point.

    python run.py --check     verify provider keys and list available models
    python run.py             run the full pipeline and write results.json
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

from src import config
from src.llm import (
    gemini_available,
    gemini_chat,
    groq_available,
    groq_chat,
    provider_status,
)
from src.orchestrator import run_pipeline, write_results
from src.search import search


def check() -> int:
    """Validate by actually calling each dependency.

    An earlier version only *listed* models, which passed happily on a model the
    API then rejected at call time with "no longer available to new users".
    Listing is not validation — every check here issues a real request.
    """
    status = provider_status()
    print("Provider status\n" + "-" * 66)
    for name, info in status.items():
        mark = "OK " if info["configured"] else "-- "
        print(f"[{mark}] {name:10} {info['model']:34} {info['role']}")
    print()

    ok = True

    # --- retrieval: the source of every citation ---------------------------
    try:
        hits = search(["Codelco copper Chile operations"], per_query=5)
        if hits:
            print(f"Retrieval OK. {len(hits)} results, e.g. {hits[0].domain}")
        else:
            ok = False
            print("Retrieval returned NOTHING - citations would be impossible.")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"Retrieval FAILED: {exc}")

    # --- generation: issue a real completion, not a model list -------------
    if groq_available():
        try:
            groq_chat("Reply with the single word: ready", json_mode=False)
            print(f"Groq OK. '{config.GROQ_MODEL}' answered a live request.")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"Groq FAILED on '{config.GROQ_MODEL}': {str(exc)[:160]}")
            _suggest_groq()
    else:
        print("GROQ_API_KEY not set - will fall back to Gemini.")

    if gemini_available():
        try:
            gemini_chat("Reply with the single word: ready")
            print(f"Gemini OK. '{config.GEMINI_MODEL}' answered a live request.")
        except Exception as exc:  # noqa: BLE001
            print(f"Gemini fallback unavailable on '{config.GEMINI_MODEL}': {str(exc)[:160]}")
            _suggest_gemini()
    else:
        print("GEMINI_API_KEY not set - no fallback provider.")

    if not groq_available() and not gemini_available():
        ok = False

    print()
    print("READY" if ok else "NOT READY - fix the items above, then re-run --check")
    return 0 if ok else 1


def _suggest_groq() -> None:
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            timeout=30,
        )
        names = [m["id"] for m in resp.json().get("data", [])]
        print(f"  models on this key: {names[:8]}")
    except Exception:  # noqa: BLE001
        pass


def _suggest_gemini() -> None:
    try:
        resp = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": config.GEMINI_API_KEY},
            timeout=30,
        )
        names = [
            m["name"].split("/")[-1]
            for m in resp.json().get("models", [])
            if "generateContent" in (m.get("supportedGenerationMethods") or [])
        ]
        flash = [n for n in names if "flash" in n][:6]
        print(f"  try: {flash or names[:6]}  (note: listed != callable)")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="FlytBase outbound BDR agent")
    parser.add_argument("--check", action="store_true", help="verify providers and exit")
    parser.add_argument("--quiet", action="store_true", help="suppress stage logging")
    args = parser.parse_args()

    if args.check:
        return check()

    if not gemini_available() and not groq_available():
        print("No provider configured. Copy .env.example to .env and add a key.")
        return 1

    payload = run_pipeline(verbose=not args.quiet)
    paths = write_results(payload)

    s = payload["summary"]
    print("\n" + "=" * 60)
    print("RUN COMPLETE")
    print("=" * 60)
    print(f"  candidates screened : {s['candidates_screened']}")
    print(f"  accounts qualified  : {s['accounts_qualified']}")
    print(f"  accounts rejected   : {s['accounts_rejected']}")
    print(f"  contacts found      : {s['contacts_found']}")
    print(f"  emails generated    : {s['emails_generated']}")
    print(f"  claims verified     : {s['claims_verified']}/{s['claims_total']}")
    print(f"  unique sources      : {s['unique_sources']}")
    t = payload["trace"]["counts"]
    print(f"  stages ok/partial/failed: {t['ok']}/{t['partial']}/{t['failed']}")
    for p in paths:
        print(f"  wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
