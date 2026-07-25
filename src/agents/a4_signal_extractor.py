"""Agent 4 — Signal Extractor.

Converts raw research into trigger events: dated, cited reasons that make
outreach relevant *now*. This is the layer that separates strategic insight from
company trivia, so it is deliberately a separate agent rather than a prompt
clause bolted onto research.

Runs on the drafting provider — it reasons over claims A3 already sourced, so it
needs no new search, and keeping it off the grounded provider spreads free-tier
quota across the run.
"""

from __future__ import annotations

from ..config import BRIEF, COMPANY_CONTEXT
from ..llm import draft_json
from ..schemas import RunState, Trigger
from ..trace import Trace

SYSTEM = (
    "You turn research into sales triggers. You only use facts present in the "
    "supplied claims. You never add outside knowledge and never speculate about "
    "events that are not in the claims."
)


def _prompt(name: str, claims_block: str) -> str:
    return f"""{COMPANY_CONTEXT}

Our angle: {BRIEF.angle}

Below are researched, sourced claims about {name}. Identify the strongest
trigger events — the specific, timely reasons this company should care about
autonomous inspection right now.

CLAIMS:
{claims_block}

Return ONLY JSON:

{{
  "triggers": [
    {{
      "headline": "short punchy label for the trigger",
      "what_happened": "the factual event, drawn strictly from the claims above",
      "why_it_matters": "how this specifically creates demand for autonomous inspection replacing contracted crews",
      "date": "YYYY-MM or YYYY if the claims give one, else empty string",
      "claim_indexes": [0, 3]
    }}
  ]
}}

Rules:
- Return 2 to 4 triggers, strongest first. Quality over quantity.
- what_happened must be traceable to the claims. Do not introduce new facts.
- why_it_matters must be specific to this company, not generic mining commentary.
- claim_indexes must reference the numbered claims above, so we can keep citations.
- If the claims genuinely support no trigger, return an empty list. That is a
  valid and useful answer.
"""


def run(state: RunState, trace: Trace) -> None:
    for account in state.accounts:
        with trace.stage(
            "A4", f"Signal Extractor — {account.name}", inputs=f"{len(account.research)} claims"
        ) as rec:
            if not account.research:
                rec.status = "skipped"
                rec.error = "no research claims to work from"
                rec.fix = "Depends on A3 producing claims for this account."
                continue

            claims_block = "\n".join(
                f"[{i}] {c.text}" for i, c in enumerate(account.research)
            )
            data = draft_json(_prompt(account.name, claims_block), system=SYSTEM)

            for t in data.get("triggers") or []:
                headline = str(t.get("headline", "")).strip()
                if not headline:
                    continue

                # Carry citations forward from the claims the trigger cites.
                sources = []
                seen: set[str] = set()
                for idx in t.get("claim_indexes") or []:
                    try:
                        claim = account.research[int(idx)]
                    except (ValueError, TypeError, IndexError):
                        continue
                    for s in claim.sources:
                        if s.url not in seen:
                            seen.add(s.url)
                            sources.append(s)

                account.triggers.append(
                    Trigger(
                        headline=headline,
                        what_happened=str(t.get("what_happened", "")).strip(),
                        why_it_matters=str(t.get("why_it_matters", "")).strip(),
                        date=str(t.get("date", "")).strip(),
                        sources=sources or list(account.sources[:3]),
                    )
                )

            rec.output_summary = f"{len(account.triggers)} triggers"
            if not account.triggers:
                rec.status = "partial"
                rec.error = "no trigger events found in the research"
                rec.fix = (
                    "Not necessarily a bug — it can mean the account is a poor "
                    "timing fit. The email for this account will fall back to "
                    "profile-based personalisation, which is weaker; consider "
                    "deprioritising the account instead."
                )
