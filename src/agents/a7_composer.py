"""Agent 7 — Message Composer.

Writes one email per contact from verified material only. The proof point is a
decision, not decoration: the agent picks the single FlytBase customer that
actually maps to this account rather than name-dropping all three.

Also produces the things an AE needs after the send — a call opener and the two
objections this persona will raise.
"""

from __future__ import annotations

from ..config import BRIEF, COMPANY_CONTEXT, PROOF_POINTS
from ..llm import draft_json
from ..schemas import Account, Contact, Email, RunState
from ..trace import Trace

SYSTEM = (
    "You write outbound email for an enterprise seller. You write like a human "
    "who did the homework: specific, plain, and short. You never use merge-field "
    "placeholders, never open with flattery, and never state a fact that is not "
    "in the supplied research."
)


def _prompt(account: Account, contact: Contact) -> str:
    verified = [c for c in account.research if not c.quarantined]
    research_block = "\n".join(f"- {c.text}" for c in verified[:12]) or "- (none)"
    triggers_block = (
        "\n".join(
            f"- {t.headline}: {t.what_happened} | why it matters: {t.why_it_matters}"
            for t in account.triggers
        )
        or "- (no dated trigger found for this account)"
    )
    proof_block = "\n".join(f"- {k}: {v}" for k, v in PROOF_POINTS.items())

    return f"""{COMPANY_CONTEXT}

Our angle: {BRIEF.angle}

RECIPIENT
- Name: {contact.name}
- Title: {contact.title}
- Company: {account.name} ({account.country}, {account.commodity})
- Why this person owns the problem: {contact.why_this_person}

VERIFIED RESEARCH ON {account.name}:
{research_block}

TRIGGER EVENTS:
{triggers_block}

AVAILABLE PROOF POINTS (choose exactly ONE, the best match):
{proof_block}

Write a cold email to this person.

Return ONLY JSON:

{{
  "subject": "specific, lowercase-ish, under 60 chars, no clickbait",
  "body": "the email body, 90-140 words, plain text, line breaks as \\n",
  "proof_point_used": "Anglo American | Shell | CSX",
  "proof_point_reason": "one line on why that customer is the right analogue here",
  "trigger_referenced": "which trigger the email leans on, or 'none'",
  "call_opener": "one sentence the AE can say out loud on a cold call",
  "objections": [
    {{"objection": "what this persona will actually push back with", "response": "how to handle it in 1-2 sentences"}}
  ]
}}

Hard rules for the body:
- Open with something specific to {account.name}. Never open with "I hope this finds you well" or praise.
- Reference the trigger or a concrete researched fact in the first two sentences.
- Connect to hazardous, 24/7 inspection work currently done by contracted crews.
- Use exactly one proof point, woven in naturally as evidence, not as a logo drop.
- Close with a low-friction ask — a short call, a specific question. No hard sell.
- NEVER use placeholders like {{first_name}} or [Company]. Write the real words.
- No em dashes. No exclamation marks. No "revolutionise", "cutting-edge", "leverage".
- Give exactly 2 objections.
"""


def run(state: RunState, trace: Trace) -> None:
    for account in state.accounts:
        for contact in account.contacts:
            key = f"{account.name}::{contact.name}"
            with trace.stage(
                "A7", f"Composer — {contact.name} @ {account.name}", inputs=key
            ) as rec:
                data = draft_json(_prompt(account, contact), system=SYSTEM)

                subject = str(data.get("subject", "")).strip()
                body = str(data.get("body", "")).strip()
                if not subject or not body:
                    rec.status = "failed"
                    rec.error = "composer returned an empty subject or body"
                    rec.fix = "Retry this single contact; the rest of the run is unaffected."
                    continue

                reason = str(data.get("proof_point_reason", "")).strip()
                proof = str(data.get("proof_point_used", "")).strip()
                objections = [
                    {
                        "objection": str(o.get("objection", "")).strip(),
                        "response": str(o.get("response", "")).strip(),
                    }
                    for o in (data.get("objections") or [])
                    if o.get("objection")
                ]

                state.emails[key] = Email(
                    subject=subject,
                    body=body,
                    proof_point_used=f"{proof} — {reason}" if reason else proof,
                    trigger_referenced=str(data.get("trigger_referenced", "")).strip(),
                    call_opener=str(data.get("call_opener", "")).strip(),
                    objections=objections,
                )
                rec.output_summary = f"{len(body.split())} words, proof point: {proof}"
