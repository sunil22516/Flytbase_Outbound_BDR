"""Agent 8 — Critic.

The reflection loop. Scores every draft against a fixed rubric and sends weak
ones back for exactly one rewrite. A self-correcting agent is a different claim
from a linear chain, and it costs one extra call per weak email.

Two layers, on purpose:
  * deterministic gate — placeholders, length, banned tells. These are the
    disqualifiers from the brief, so they must not depend on a model's opinion.
  * rubric scoring — specificity, trigger use, proof-point fit, CTA quality.
"""

from __future__ import annotations

import re

from ..config import CRITIC_PASS_MARK, MAX_REVISIONS
from ..llm import draft_json
from ..schemas import Email, RunState
from ..trace import Trace

SYSTEM = (
    "You are a demanding sales-email reviewer. You score honestly and you do not "
    "inflate. A generic email that could be sent to any mining company scores "
    "below 5 no matter how well written it is."
)

_PLACEHOLDER_RE = re.compile(r"\{\{?\s*\w+\s*\}?\}|\[\s*(?:company|first[_ ]?name|name|title)\s*\]", re.I)
_BANNED = ("revolutioniz", "revolutionis", "cutting-edge", "leverage", "synerg", "game-chang")


def _hard_checks(email: Email) -> list[str]:
    """Deterministic failures. These are non-negotiable, not matters of taste."""
    problems: list[str] = []
    text = f"{email.subject}\n{email.body}"

    if _PLACEHOLDER_RE.search(text):
        problems.append("contains a merge-field placeholder (mail-merge, not personalisation)")

    words = len(email.body.split())
    if words > 190:
        problems.append(f"body is {words} words - too long for a cold email")
    elif words < 55:
        problems.append(f"body is only {words} words - too thin to carry the research")

    lowered = text.lower()
    for term in _BANNED:
        if term in lowered:
            problems.append(f"uses filler term '{term}'")

    if "hope this finds you well" in lowered:
        problems.append("opens with a generic pleasantry")

    return problems


def _rubric_prompt(account_name: str, title: str, email: Email) -> str:
    return f"""Score this cold email sent to a {title} at {account_name}.

SUBJECT: {email.subject}

BODY:
{email.body}

Score each criterion 0-10:
1. specificity - could this ONLY have been sent to this company? Generic scores low.
2. trigger_use - does it lean on a real, timely event rather than a general observation?
3. proof_point_fit - is the customer reference the right analogue, and used as evidence not decoration?
4. human_voice - does it read like a person who did the homework, or like a tool that ran a prompt?
5. cta_quality - is the ask low-friction and specific?

Return ONLY JSON:

{{
  "scores": {{"specificity": 0, "trigger_use": 0, "proof_point_fit": 0, "human_voice": 0, "cta_quality": 0}},
  "overall": 0.0,
  "notes": ["short, concrete critique"],
  "rewrite_instruction": "if overall is below {CRITIC_PASS_MARK}, say exactly what to change; else empty string"
}}
"""


def _revise_prompt(email: Email, instruction: str, problems: list[str]) -> str:
    issues = "\n".join(f"- {p}" for p in problems + ([instruction] if instruction else []))
    return f"""Rewrite this cold email to fix the issues listed. Keep everything that
already works. Do not add any fact that is not already in the email.

CURRENT SUBJECT: {email.subject}

CURRENT BODY:
{email.body}

ISSUES TO FIX:
{issues}

Return ONLY JSON: {{"subject": "...", "body": "..."}}

Rules: 90-140 words. No placeholders. No em dashes. No exclamation marks.
Keep the opening specific to the company.
"""


def run(state: RunState, trace: Trace) -> None:
    by_contact = {
        f"{a.name}::{c.name}": (a, c) for a in state.accounts for c in a.contacts
    }

    for key, email in state.emails.items():
        account, contact = by_contact.get(key, (None, None))
        if account is None:
            continue

        with trace.stage("A8", f"Critic — {contact.name} @ {account.name}", inputs=key) as rec:
            problems = _hard_checks(email)
            data = draft_json(
                _rubric_prompt(account.name, contact.title, email), system=SYSTEM
            )

            scores = data.get("scores") or {}
            try:
                overall = float(data.get("overall") or 0)
            except (TypeError, ValueError):
                overall = 0.0
            if not overall and scores:
                nums = [float(v) for v in scores.values() if isinstance(v, (int, float))]
                overall = round(sum(nums) / len(nums), 2) if nums else 0.0

            notes = [str(n) for n in (data.get("notes") or [])]
            email.critic_score = round(overall, 2)
            email.critic_notes = problems + notes

            instruction = str(data.get("rewrite_instruction", "")).strip()
            needs_rewrite = bool(problems) or overall < CRITIC_PASS_MARK

            if needs_rewrite and MAX_REVISIONS > 0:
                revised = draft_json(
                    _revise_prompt(email, instruction, problems), system=SYSTEM
                )
                new_subject = str(revised.get("subject", "")).strip()
                new_body = str(revised.get("body", "")).strip()
                if new_subject and new_body:
                    email.subject = new_subject
                    email.body = new_body
                    email.revisions = 1
                    residual = _hard_checks(email)
                    email.critic_notes.append(
                        "revised once by the critic loop"
                        + (f"; residual issues: {'; '.join(residual)}" if residual else "")
                    )
                    rec.output_summary = f"scored {overall}, revised"
                else:
                    rec.status = "partial"
                    rec.error = "rewrite returned empty output; kept the original draft"
                    rec.fix = "Retry the rewrite for this contact only."
                    rec.output_summary = f"scored {overall}, rewrite failed"
            else:
                rec.output_summary = f"scored {overall}, passed"
