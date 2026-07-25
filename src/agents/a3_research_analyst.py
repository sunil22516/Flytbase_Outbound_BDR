"""Agent 3 — Research Analyst.

Fans out one grounded research pass per qualified account. Produces atomic,
individually-cited claims rather than a prose blob, so the Verifier can
quarantine at claim granularity instead of throwing away a whole brief.
"""

from __future__ import annotations

from ..config import BRIEF, COMPANY_CONTEXT
from ..llm import research_json
from ..schemas import Account, Claim, RunState, Source
from ..trace import Trace

SYSTEM = (
    "You are a research analyst preparing a briefing that a salesperson will "
    "quote in a real email. Accuracy matters more than volume. If you cannot "
    "verify a detail, omit it. Never invent numbers, dates, names, or incidents."
)


def _prompt(account: Account) -> str:
    return f"""{COMPANY_CONTEXT}

Research the mining company: {account.name} ({account.country}, {account.commodity}).

We sell autonomous drone inspection that replaces contracted inspection crews at
hazardous, 24/7 extraction sites. Research this company with that lens.

Cover, using current public sources:
1. Operational footprint — named mines/sites, scale, whether operations run continuously
2. Recent news in roughly the last 18 months — expansion, capex, production targets
3. Any signals of technology investment, automation, digital transformation, or autonomy pilots
4. HSE record and pressure — incidents, regulatory findings, safety commitments
5. Use of contractors for inspection, maintenance, surveying, or monitoring
6. Anything that suggests the cost or risk of manual inspection is a live problem

Return ONLY JSON:

{{
  "claims": [
    {{
      "text": "one specific, self-contained, factual statement",
      "category": "footprint | news | technology | hse | contractors | other",
      "date": "YYYY-MM or YYYY if the source gives one, else empty string",
      "confidence": "high | medium | low"
    }}
  ],
  "strategic_summary": "3-4 sentences a BDR could actually use, connecting this company's situation to hazardous 24/7 inspection work"
}}

Rules:
- 8 to 14 claims. Each must be a single fact, not a paragraph.
- Prefer specific over general: named sites, dated events, real figures.
- Mark confidence low when the source is weak or indirect. Do not pad.
- Do not state anything you did not actually find in a source.
"""


def run(state: RunState, trace: Trace) -> None:
    for account in state.accounts:
        with trace.stage(
            "A3", f"Research Analyst — {account.name}", inputs=account.name
        ) as rec:
            data, result = research_json(_prompt(account), system=SYSTEM)
            rec.searches = result.queries
            rec.sources_found = len(result.sources)

            # Grounding sources are returned per-call, so they attach to the
            # account. The Verifier decides which claims they actually support.
            account.sources = _merge(account.sources, result.sources)

            for c in data.get("claims") or []:
                text = str(c.get("text", "")).strip()
                if not text:
                    continue
                conf = str(c.get("confidence", "low")).strip().lower()
                account.research.append(
                    Claim(
                        text=text,
                        sources=list(result.sources),
                        confidence=conf if conf in {"high", "medium", "low"} else "low",
                    )
                )

            summary = str(data.get("strategic_summary", "")).strip()
            if summary:
                account.fit_rationale = (
                    account.fit_rationale + "\n\n" + summary
                ).strip()

            rec.output_summary = f"{len(account.research)} claims"
            if not account.research:
                rec.status = "partial"
                rec.error = "no claims extracted"
                rec.fix = (
                    "Usually means the company has thin English-language coverage. "
                    "Retry with Spanish/Portuguese search terms, or drop the "
                    "account rather than emailing on no evidence."
                )


def _merge(existing: list[Source], incoming: list[Source]) -> list[Source]:
    seen = {s.url for s in existing}
    return existing + [s for s in incoming if s.url and s.url not in seen]
