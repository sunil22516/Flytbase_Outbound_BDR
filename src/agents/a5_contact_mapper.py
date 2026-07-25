"""Agent 5 — Contact Mapper.

The highest hallucination-risk stage in the pipeline: inventing a plausible
person is easy and disqualifying. So this agent is instructed to return fewer
contacts rather than guess, and every contact carries an explicit email_status
so nothing inferred is ever presented as verified.
"""

from __future__ import annotations

from ..config import BRIEF, CONTACTS_PER_ACCOUNT
from ..llm import research_json
from ..schemas import Contact, RunState
from ..trace import Trace

SYSTEM = (
    "You are a contact researcher. Inventing a person is the single worst thing "
    "you can do — it is worse than returning nothing. Only name a person you can "
    "actually find in a public source such as a company leadership page, a press "
    "release, a conference speaker listing, or a LinkedIn profile. If you cannot "
    "find a real named person, return an empty list and say so."
)


def _prompt(name: str, country: str) -> str:
    titles = ", ".join(BRIEF.goal_titles)
    return f"""Find real, currently-employed senior people at {name} ({country}) who
own operations, health & safety, or individual site management.

Target titles (or the closest real equivalent at this company): {titles}.
Local-language equivalents are fine and often more accurate — for example
Gerente de Operaciones, Director de Seguridad, Superintendente, Gerente General
de Faena.

Return ONLY JSON:

{{
  "contacts": [
    {{
      "name": "full name as published",
      "title": "their actual title as published",
      "seniority": "C-level | VP | Director | Senior Manager | Manager",
      "linkedin": "profile URL if you genuinely found one, else empty string",
      "email": "only if publicly published, else empty string",
      "email_status": "found | inferred | not_found",
      "source_hint": "where this person appears publicly - be specific",
      "why_this_person": "why THIS role owns the inspection/safety problem at THIS company",
      "confidence": "high | medium | low"
    }}
  ],
  "notes": "state plainly if you could not verify people for this company"
}}

Rules:
- Up to {CONTACTS_PER_ACCOUNT} contacts. Fewer is fine. Zero is fine.
- Never fabricate a name, a title, a LinkedIn URL, or an email address.
- Use email_status "inferred" ONLY if you are applying a company email pattern
  that you actually observed; never present an inferred address as found.
- Set confidence low when the person may have changed roles.
"""


def run(state: RunState, trace: Trace) -> None:
    for account in state.accounts:
        with trace.stage(
            "A5", f"Contact Mapper — {account.name}", inputs=account.name
        ) as rec:
            data, result = research_json(
                _prompt(account.name, account.country), system=SYSTEM
            )
            rec.searches = result.queries
            rec.sources_found = len(result.sources)

            for c in data.get("contacts") or []:
                person = str(c.get("name", "")).strip()
                title = str(c.get("title", "")).strip()
                if not person or not title:
                    continue

                status = str(c.get("email_status", "not_found")).strip().lower()
                if status not in {"found", "inferred", "not_found"}:
                    status = "not_found"
                email = str(c.get("email", "")).strip()
                if not email:
                    status = "not_found"

                conf = str(c.get("confidence", "low")).strip().lower()
                account.contacts.append(
                    Contact(
                        name=person,
                        title=title,
                        company=account.name,
                        seniority=str(c.get("seniority", "")).strip(),
                        linkedin=str(c.get("linkedin", "")).strip(),
                        email=email,
                        email_status=status,  # type: ignore[arg-type]
                        why_this_person=str(c.get("why_this_person", "")).strip(),
                        sources=list(result.sources),
                        confidence=conf if conf in {"high", "medium", "low"} else "low",
                    )
                )

            rec.output_summary = f"{len(account.contacts)} contacts"
            note = str(data.get("notes", "")).strip()
            if note:
                rec.notes.append(note)

            if not account.contacts:
                rec.status = "partial"
                rec.error = "no verifiable contacts found"
                rec.fix = (
                    "Expected for privately-held LatAm operators with thin public "
                    "leadership pages. Production fix: route these accounts to a "
                    "licensed contact-data provider (Apollo / Cognism / Lusha) or "
                    "a LinkedIn Sales Navigator seat. We return nothing rather "
                    "than guess a name."
                )
