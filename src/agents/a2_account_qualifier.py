"""Agent 2 — Account Qualifier.

Scores every candidate against the ICP and cuts the ones that do not fit. The
rejects are kept and surfaced: a scout that never says no is listing, not
qualifying, and an AE needs to see the boundary of the ICP.
"""

from __future__ import annotations

from ..config import TARGET_ACCOUNTS
from ..llm import research_json
from ..schemas import DimensionScore, RunState
from ..trace import Trace

SYSTEM = (
    "You are a rigorous qualification analyst. You score against the stated "
    "rubric only. You are willing to reject accounts, and you say plainly when "
    "the evidence for a score is thin."
)


def _prompt(icp_block: str, disqualifiers: str, candidates_block: str) -> str:
    return f"""Score each candidate account against this ICP.

ICP DIMENSIONS (each with a weight):
{icp_block}

AUTOMATIC DISQUALIFIERS:
{disqualifiers}

CANDIDATES:
{candidates_block}

For each candidate, score every dimension 0-10 and give a one-line rationale
grounded in something real about that company. Then decide: qualified or
rejected.

Return ONLY JSON:

{{
  "scored": [
    {{
      "name": "company name exactly as given",
      "dimension_scores": [
        {{"dimension": "axis name", "score": 8, "rationale": "concrete reason"}}
      ],
      "fit_rationale": "2-3 sentences on why this account fits, or does not",
      "rejected": false,
      "rejection_reason": "required when rejected is true, else empty string"
    }}
  ]
}}

Rules:
- Score every dimension for every candidate. Do not skip axes.
- Reject anything that trips a disqualifier, and say which one.
- Be willing to reject. A list where nothing is rejected is a failed screen.
- Rationales must reference something specific, not restate the axis name.
"""


def run(state: RunState, trace: Trace) -> None:
    with trace.stage(
        "A2", "Account Qualifier", inputs=f"{len(state.candidates)} candidates"
    ) as rec:
        if state.icp is None or not state.candidates:
            rec.status = "skipped"
            rec.error = "no ICP or no candidates to score"
            rec.fix = "Requires A0 and A1 to have produced output."
            return

        weights = {d.name: d.weight for d in state.icp.dimensions}
        icp_block = "\n".join(
            f"- {d.name} (weight {d.weight}): {d.description}"
            for d in state.icp.dimensions
        )
        disqualifiers = "\n".join(f"- {x}" for x in state.icp.disqualifiers) or "- none"
        candidates_block = "\n".join(
            f"- {c.name} | {c.country} | {c.commodity} | {c.fit_rationale}"
            for c in state.candidates
        )

        data, result = research_json(
            _prompt(icp_block, disqualifiers, candidates_block), system=SYSTEM
        )
        rec.searches = result.queries
        rec.sources_found = len(result.sources)

        by_name = {c.name.lower(): c for c in state.candidates}
        for row in data.get("scored") or []:
            acct = by_name.get(str(row.get("name", "")).strip().lower())
            if acct is None:
                continue

            scores: list[DimensionScore] = []
            weighted = 0.0
            for s in row.get("dimension_scores") or []:
                dim = str(s.get("dimension", "")).strip()
                try:
                    value = float(s.get("score", 0) or 0)
                except (TypeError, ValueError):
                    value = 0.0
                scores.append(
                    DimensionScore(
                        dimension=dim,
                        score=value,
                        rationale=str(s.get("rationale", "")).strip(),
                    )
                )
                weighted += value * weights.get(dim, 0.0)

            acct.dimension_scores = scores
            acct.fit_score = round(weighted, 2)
            acct.fit_rationale = (
                str(row.get("fit_rationale", "")).strip() or acct.fit_rationale
            )
            acct.rejected = bool(row.get("rejected"))
            acct.rejection_reason = str(row.get("rejection_reason", "")).strip()

        qualified = [c for c in state.candidates if not c.rejected]
        qualified.sort(key=lambda a: a.fit_score, reverse=True)

        state.accounts = qualified[:TARGET_ACCOUNTS]
        state.rejected = [c for c in state.candidates if c.rejected]

        # Anything cut purely for ranking is recorded as such, not silently dropped.
        for extra in qualified[TARGET_ACCOUNTS:]:
            extra.rejected = True
            extra.rejection_reason = (
                f"Qualified but ranked below the top {TARGET_ACCOUNTS} by weighted "
                f"ICP score ({extra.fit_score})."
            )
            state.rejected.append(extra)

        rec.output_summary = (
            f"{len(state.accounts)} qualified, {len(state.rejected)} rejected"
        )
        if not state.accounts:
            rec.status = "failed"
            rec.error = "every candidate was rejected"
            rec.fix = (
                "The ICP is likely too strict. Relax the lowest-weighted "
                "dimensions or widen the disqualifier list in A0, then re-run."
            )
