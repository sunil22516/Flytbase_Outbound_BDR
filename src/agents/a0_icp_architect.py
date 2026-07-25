"""Agent 0 — ICP Architect.

Turns the reference account (SQM) into a weighted, machine-readable ICP. Every
downstream agent scores against this, so the ICP is the contract for the run.
"""

from __future__ import annotations

from ..config import BRIEF, COMPANY_CONTEXT
from ..llm import research_json
from ..schemas import ICP, ICPDimension, RunState
from ..trace import Trace

SYSTEM = (
    "You are an ICP analyst for an enterprise outbound team. You work only from "
    "real, publicly verifiable information. If you cannot verify something, you "
    "say so rather than inventing it."
)

PROMPT = f"""{COMPANY_CONTEXT}

We are building an outbound campaign with this brief:
- Target vertical: {BRIEF.target_vertical}
- Reference account (the anchor we model the ICP on): {BRIEF.reference_account}
- Goal: book discovery calls with {", ".join(BRIEF.goal_titles)}
- Our angle: {BRIEF.angle}

Research {BRIEF.reference_account} using current public sources, then deconstruct
it into an Ideal Customer Profile.

Think about what actually makes an account a good fit for autonomous drone
inspection: scale of the physical footprint, whether sites run continuously,
hazard exposure, how much inspection is currently outsourced to contracted
crews, appetite for automation, and regulatory/HSE pressure.

Return ONLY a JSON object shaped like this:

{{
  "reference_summary": "3-4 sentences on what SQM actually is, operationally",
  "geography": "the geographic scope this ICP covers",
  "dimensions": [
    {{
      "name": "short axis name",
      "description": "what we are measuring and why it predicts fit",
      "weight": 0.20,
      "reference_value": "what SQM specifically looks like on this axis"
    }}
  ],
  "disqualifiers": [
    "concrete conditions that should rule an account OUT"
  ],
  "notes": "anything a BDR should know before using this ICP"
}}

Rules:
- Produce 6 to 8 dimensions. Weights must sum to 1.0.
- Every reference_value must describe SQM concretely, not generically.
- Disqualifiers must be things you can actually check.
"""


QUERIES = [
    "SQM Sociedad Quimica y Minera Salar de Atacama lithium operations",
    "SQM Chile lithium production capacity expansion capex",
    "SQM mining safety HSE contractors inspection",
    "SQM annual report operations sites Chile",
]


def run(state: RunState, trace: Trace) -> None:
    with trace.stage(
        "A0", "ICP Architect", inputs=f"reference account: {BRIEF.reference_account}"
    ) as rec:
        data, result = research_json(PROMPT, QUERIES, system=SYSTEM)
        rec.searches = result.queries
        rec.sources_found = len(result.sources)

        dims = [
            ICPDimension(
                name=str(d.get("name", "")).strip(),
                description=str(d.get("description", "")).strip(),
                weight=float(d.get("weight", 0) or 0),
                reference_value=str(d.get("reference_value", "")).strip(),
            )
            for d in (data.get("dimensions") or [])
            if d.get("name")
        ]

        if not dims:
            rec.status = "failed"
            rec.error = "model returned no usable ICP dimensions"
            rec.fix = (
                "The ICP is the contract for every downstream stage, so the run "
                "cannot proceed without it. Re-run this stage; if it fails twice, "
                "fall back to a hand-authored ICP checked into config."
            )
            return

        # Normalise weights so scoring is well-defined even if the model drifts.
        total = sum(d.weight for d in dims) or 1.0
        for d in dims:
            d.weight = round(d.weight / total, 4)

        state.icp = ICP(
            reference_account=BRIEF.reference_account,
            vertical=BRIEF.target_vertical,
            geography=str(data.get("geography") or BRIEF.geography),
            dimensions=dims,
            disqualifiers=[str(x) for x in (data.get("disqualifiers") or [])],
            notes=str(data.get("reference_summary") or "")
            + ("\n\n" + str(data["notes"]) if data.get("notes") else ""),
        )

        rec.output_summary = (
            f"{len(dims)} weighted dimensions, "
            f"{len(state.icp.disqualifiers)} disqualifiers"
        )
