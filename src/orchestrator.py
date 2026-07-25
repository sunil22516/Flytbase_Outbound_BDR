"""Orchestrator.

Runs the agent DAG over one shared state object and writes a single results
artifact. No agent calls another agent — the wiring lives here, so the flow is
readable in one place.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import config
from .agents import (
    a0_icp_architect,
    a1_account_scout,
    a2_account_qualifier,
    a3_research_analyst,
    a4_signal_extractor,
    a5_contact_mapper,
    a6_verifier,
    a7_composer,
    a8_critic,
)
from .llm import provider_status
from .schemas import RunState
from .trace import Trace

PIPELINE = [
    ("A0", "ICP Architect", a0_icp_architect),
    ("A1", "Account Scout", a1_account_scout),
    ("A2", "Account Qualifier", a2_account_qualifier),
    ("A3", "Research Analyst", a3_research_analyst),
    ("A4", "Signal Extractor", a4_signal_extractor),
    ("A5", "Contact Mapper", a5_contact_mapper),
    ("A6", "Verifier", a6_verifier),
    ("A7", "Composer", a7_composer),
    ("A8", "Critic", a8_critic),
]


def run_pipeline(
    verbose: bool = True,
    on_stage: Callable[[str, str, list], None] | None = None,
) -> dict[str, Any]:
    """Run the agent DAG.

    `on_stage(code, label, records)` fires after each agent so a UI can show the
    pipeline executing live rather than waiting for a final blob.
    """
    state = RunState(brief=config.BRIEF)
    trace = Trace()

    for index, (code, label, module) in enumerate(PIPELINE):
        if verbose:
            print(f"[{code}] {label} ...", flush=True)
        if on_stage:
            on_stage(code, label, [])

        module.run(state, trace)

        produced = [s for s in trace.stages if s.agent == code]
        if verbose:
            for s in produced[-3:]:
                mark = {"ok": "ok", "partial": "!", "failed": "X", "skipped": "-"}.get(
                    s.status, "?"
                )
                print(f"      [{mark}] {s.label}: {s.output_summary or s.error}", flush=True)
        if on_stage:
            on_stage(code, label, produced)

    return _assemble(state, trace)


def _assemble(state: RunState, trace: Trace) -> dict[str, Any]:
    accounts: list[dict[str, Any]] = []
    for a in state.accounts:
        d = a.to_dict()
        for c in d["contacts"]:
            key = f"{a.name}::{c['name']}"
            email = state.emails.get(key)
            c["email_draft"] = (
                {
                    "subject": email.subject,
                    "body": email.body,
                    "proof_point_used": email.proof_point_used,
                    "trigger_referenced": email.trigger_referenced,
                    "call_opener": email.call_opener,
                    "objections": email.objections,
                    "critic_score": email.critic_score,
                    "critic_notes": email.critic_notes,
                    "revisions": email.revisions,
                }
                if email
                else None
            )
        accounts.append(d)

    accounts.sort(key=lambda x: x["fit_score"], reverse=True)

    total_contacts = sum(len(a["contacts"]) for a in accounts)
    total_emails = sum(
        1 for a in accounts for c in a["contacts"] if c.get("email_draft")
    )
    all_claims = [c for a in accounts for c in a["research"]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "brief": {
            "target_vertical": state.brief.target_vertical,
            "reference_account": state.brief.reference_account,
            "goal_titles": state.brief.goal_titles,
            "angle": state.brief.angle,
            "geography": state.brief.geography,
        },
        "providers": provider_status(),
        "icp": state.icp.to_dict() if state.icp else None,
        "accounts": accounts,
        "rejected": [
            {
                "name": r.name,
                "country": r.country,
                "commodity": r.commodity,
                "fit_score": r.fit_score,
                "rejection_reason": r.rejection_reason,
            }
            for r in state.rejected
        ],
        "summary": {
            "candidates_screened": len(state.candidates),
            "accounts_qualified": len(accounts),
            "accounts_rejected": len(state.rejected),
            "contacts_found": total_contacts,
            "emails_generated": total_emails,
            "claims_total": len(all_claims),
            "claims_verified": sum(1 for c in all_claims if not c["quarantined"]),
            "claims_quarantined": sum(1 for c in all_claims if c["quarantined"]),
            "unique_sources": len(
                {
                    s["url"]
                    for a in accounts
                    for s in a["sources"]
                    if s.get("url")
                }
            ),
        },
        "trace": trace.to_dict(),
    }


def write_results(payload: dict[str, Any], force: bool = False) -> list[Path]:
    """Write to data/ (the artifact) and docs/data/ (what the live site serves).

    Refuses to clobber a good run with an empty one. A transient provider
    failure in an early stage produces a valid-but-empty payload, and writing
    that over a successful run silently destroys the deliverable — which is
    exactly what happened once before this guard existed.
    """
    written: list[Path] = []
    new_accounts = len(payload.get("accounts") or [])

    for directory in (config.DATA_DIR, config.SITE_DATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "results.json"

        if not force and new_accounts == 0 and path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
            if len(existing.get("accounts") or []) > 0:
                backup = directory / "results.failed.json"
                backup.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                print(
                    f"  REFUSED to overwrite {path.name}: new run has 0 accounts, "
                    f"existing has {len(existing['accounts'])}. "
                    f"Failed payload saved to {backup.name}."
                )
                continue

        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written.append(path)
    return written
