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
from src.llm import gemini_available, groq_available, provider_status
from src.orchestrator import run_pipeline, write_results


def check() -> int:
    status = provider_status()
    print("Provider status\n" + "-" * 60)
    for name, info in status.items():
        mark = "OK " if info["configured"] else "-- "
        print(f"[{mark}] {name:8} model={info['model']:32} {info['role']}")
    print()

    ok = True

    if gemini_available():
        try:
            resp = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": config.GEMINI_API_KEY},
                timeout=30,
            )
            resp.raise_for_status()
            names = [
                m["name"].split("/")[-1]
                for m in resp.json().get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])
            ]
            hit = config.GEMINI_MODEL in names
            print(f"Gemini reachable. {len(names)} models available.")
            print(f"  configured model '{config.GEMINI_MODEL}': {'FOUND' if hit else 'NOT FOUND'}")
            if not hit:
                ok = False
                flash = [n for n in names if "flash" in n and "2." in n][:5]
                print(f"  try one of: {flash or names[:5]}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"Gemini check FAILED: {exc}")
    else:
        ok = False
        print("GEMINI_API_KEY not set - grounded research will not run.")

    print()

    if groq_available():
        try:
            resp = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                timeout=30,
            )
            resp.raise_for_status()
            names = [m["id"] for m in resp.json().get("data", [])]
            hit = config.GROQ_MODEL in names
            print(f"Groq reachable. {len(names)} models available.")
            print(f"  configured model '{config.GROQ_MODEL}': {'FOUND' if hit else 'NOT FOUND'}")
            if not hit:
                ok = False
                print(f"  available: {names[:8]}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"Groq check FAILED: {exc}")
    else:
        ok = False
        print("GROQ_API_KEY not set - drafting will fall back to Gemini.")

    print()
    print("READY" if ok else "NOT READY - fix the items above, then re-run --check")
    return 0 if ok else 1


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
