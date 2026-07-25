"""Agent 1 — Account Scout.

Finds real candidate companies matching the ICP. Deliberately over-fetches: the
Qualifier's job is to cut, and the rejects are part of the deliverable.
"""

from __future__ import annotations

from ..config import BRIEF, TARGET_ACCOUNTS
from ..llm import research_json
from ..schemas import Account, RunState, Source
from ..trace import Trace

SYSTEM = (
    "You are a research analyst sourcing real companies. You never invent a "
    "company, a subsidiary, or an operation. Every company you name must be one "
    "you can point to in a public source."
)


def _prompt(icp_block: str, over_fetch: int) -> str:
    return f"""We are building an account list for this campaign:
- Target vertical: {BRIEF.target_vertical}
- Reference account: {BRIEF.reference_account}
- Geography: {BRIEF.geography}

Here is the ICP we derived from the reference account:

{icp_block}

Search for real mining companies operating in Latin America that plausibly match
this profile. Include the reference account itself so we can sanity-check the
ICP against a known-good example.

Return ONLY JSON:

{{
  "candidates": [
    {{
      "name": "official company name",
      "country": "primary country of operations",
      "commodity": "lithium | copper | iron ore | multiple - be specific",
      "website": "official corporate site if you can find it, else empty string",
      "why_shortlisted": "one or two sentences citing something concrete and real",
      "known_operations": "named mines, sites, or districts you can actually verify"
    }}
  ]
}}

Rules:
- Return about {over_fetch} candidates. Prefer large-scale operators.
- Use official company names. Do not guess at subsidiaries you cannot verify.
- If you are unsure a company operates in Latin America, leave it out.
- Never fabricate a website URL. Empty string is correct when unsure.
"""


def run(state: RunState, trace: Trace) -> None:
    with trace.stage("A1", "Account Scout", inputs="ICP from A0") as rec:
        if state.icp is None:
            rec.status = "skipped"
            rec.error = "no ICP available"
            rec.fix = "A0 must succeed before scouting can run."
            return

        icp_block = "\n".join(
            f"- {d.name} (weight {d.weight}): {d.description} "
            f"| reference: {d.reference_value}"
            for d in state.icp.dimensions
        )
        over_fetch = TARGET_ACCOUNTS + 6  # so the Qualifier has something to reject

        data, result = research_json(_prompt(icp_block, over_fetch), system=SYSTEM)
        rec.searches = result.queries
        rec.sources_found = len(result.sources)

        shared_sources = result.sources
        seen: set[str] = set()
        for c in data.get("candidates") or []:
            name = str(c.get("name", "")).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            state.candidates.append(
                Account(
                    name=name,
                    country=str(c.get("country", "")).strip(),
                    commodity=str(c.get("commodity", "")).strip(),
                    website=str(c.get("website", "")).strip(),
                    fit_rationale=str(c.get("why_shortlisted", "")).strip(),
                    sources=list(shared_sources),
                )
            )

        rec.output_summary = f"{len(state.candidates)} candidate accounts"
        if len(state.candidates) < 3:
            rec.status = "partial"
            rec.error = "scout returned very few candidates"
            rec.fix = (
                "Broaden the search: drop the commodity filter and search by "
                "country plus 'mining company', then re-apply the ICP filter in A2."
            )
