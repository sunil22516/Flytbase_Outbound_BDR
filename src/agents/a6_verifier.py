"""Agent 6 — Verifier / Fact Guard.

Deliberately deterministic. A guard implemented as another LLM call can
hallucinate its own approval, so this stage is plain Python: a claim without a
resolvable source URL never reaches an email, and every contact carries an
explicit verification state.

Everything it rejects is recorded in the trace rather than silently dropped.
"""

from __future__ import annotations

import re

from ..schemas import Claim, RunState
from ..trace import Trace

_URL_RE = re.compile(r"^https?://[^\s]+\.[^\s]+", re.IGNORECASE)

# Sources that are real URLs but too weak to hang a cold-email claim on.
_WEAK_DOMAINS = ("facebook.com", "twitter.com", "x.com", "pinterest.com", "reddit.com")


def _usable_sources(claim: Claim) -> int:
    count = 0
    for s in claim.sources:
        if not _URL_RE.match(s.url or ""):
            continue
        if any(d in s.url.lower() for d in _WEAK_DOMAINS):
            continue
        count += 1
    return count


def run(state: RunState, trace: Trace) -> None:
    with trace.stage(
        "A6", "Verifier / Fact Guard", inputs=f"{len(state.accounts)} accounts"
    ) as rec:
        checked = 0
        quarantined = 0
        contacts_flagged = 0

        for account in state.accounts:
            for claim in account.research:
                checked += 1
                usable = _usable_sources(claim)

                if usable == 0:
                    claim.quarantined = True
                    claim.quarantine_reason = "no resolvable source URL"
                    claim.confidence = "unverified"
                    quarantined += 1
                    trace.quarantine(account.name, claim.text, claim.quarantine_reason)
                    continue

                # Corroboration raises confidence; a single source caps it.
                if usable >= 2 and claim.confidence == "high":
                    claim.confidence = "high"
                elif claim.confidence == "high" and usable == 1:
                    claim.confidence = "medium"

            # Triggers inherit the same rule: no source, no trigger.
            surviving = []
            for t in account.triggers:
                if any(_URL_RE.match(s.url or "") for s in t.sources):
                    surviving.append(t)
                else:
                    quarantined += 1
                    trace.quarantine(
                        account.name, t.headline, "trigger had no resolvable source"
                    )
            account.triggers = surviving

            for contact in account.contacts:
                has_source = any(_URL_RE.match(s.url or "") for s in contact.sources)
                if not has_source:
                    contact.confidence = "unverified"
                    contacts_flagged += 1
                    trace.quarantine(
                        account.name,
                        f"contact: {contact.name} ({contact.title})",
                        "no resolvable source for this person",
                    )

        verified = checked - quarantined
        rec.output_summary = (
            f"{verified}/{checked} claims verified, {quarantined} quarantined, "
            f"{contacts_flagged} contacts flagged unverified"
        )
        if checked and quarantined / checked > 0.5:
            rec.status = "partial"
            rec.error = "more than half of all claims failed verification"
            rec.fix = (
                "Grounding returned few resolvable URLs. Check that redirect "
                "resolution is working in llm.resolve_url, and re-run A3 for the "
                "affected accounts before trusting the emails."
            )
