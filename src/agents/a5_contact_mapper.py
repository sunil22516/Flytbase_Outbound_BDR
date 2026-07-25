"""Agent 5 — Contact Mapper.

The highest hallucination-risk stage in the pipeline: inventing a plausible
person is easy and disqualifying. So this agent is instructed to return fewer
contacts rather than guess, and every contact carries an explicit email_status
so nothing inferred is ever presented as verified.
"""

from __future__ import annotations

from ..config import BRIEF, CONTACTS_PER_ACCOUNT
from ..llm import research_json, sources_from_indexes
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
      "source_indexes": [1],
      "why_this_person": "why THIS role owns the inspection/safety problem at THIS company",
      "confidence": "high | medium | low"
    }}
  ],
  "notes": "state plainly if you could not verify people for this company"
}}

Rules:
- Up to {CONTACTS_PER_ACCOUNT} contacts. Fewer is fine. Zero is fine.
- Every contact MUST carry source_indexes pointing at the evidence naming them.
  A person you cannot tie to an evidence item does not go in the list.
- Never fabricate a name, a title, a LinkedIn URL, or an email address.
- Use email_status "inferred" ONLY if you are applying a company email pattern
  that you actually observed; never present an inferred address as found.
- Set confidence low when the person may have changed roles.
"""


def _short_name(name: str) -> str:
    """'Sociedad Química y Minera de Chile (SQM)' -> 'SQM'.

    Long legal names dilute the query; the ticker or trading name is what
    appointment coverage actually uses.
    """
    import re

    paren = re.search(r"\(([^)]{2,12})\)", name)
    if paren:
        return paren.group(1).strip()
    trimmed = re.sub(r"\b(S\.A\.|S\.A|PLC|Plc|Ltd|Limited|Inc\.?|Corp\.?|Group)\b", "", name)
    return trimmed.strip(" ,.-") or name


def run(state: RunState, trace: Trace) -> None:
    for account in state.accounts:
        with trace.stage(
            "A5", f"Contact Mapper — {account.name}", inputs=account.name
        ) as rec:
            # Corporate "our leadership" pages are usually JS-rendered and
            # returned no names at all. Appointment news is plain HTML and
            # states the person, the title and the date in the first sentence,
            # so we search for the announcement rather than the org chart.
            short = _short_name(account.name)
            queries = [
                f"{short} appoints chief operating officer vice president operations",
                f"{short} names new head of operations executive appointment",
                f"{short} appoints health safety sustainability director",
                f"{short} executive team senior management biography",
                f"{short} general manager mine site appointed",
            ]
            data, result = research_json(
                _prompt(account.name, account.country),
                queries,
                system=SYSTEM,
                enrich_top=9,  # names live deeper in the result set than claims do
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
                cited = sources_from_indexes(result.hits, c.get("source_indexes"))
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
                        sources=cited,
                        confidence=conf if conf in {"high", "medium", "low"} else "low",
                    )
                )

            note = str(data.get("notes", "")).strip()
            if note:
                rec.notes.append(note)

            named = len(account.contacts)

            if not account.contacts:
                # We will not invent a person. But an account with zero outreach
                # is useless to an AE, so we fall back to ROLE-targeted outreach:
                # a real, named job function at a real company, explicitly flagged
                # as unassigned. Nothing here is fabricated - there is simply no
                # person attached yet, and the UI says so.
                for title in BRIEF.goal_titles[:CONTACTS_PER_ACCOUNT]:
                    account.contacts.append(
                        Contact(
                            name=f"{title} (unassigned)",
                            title=title,
                            company=account.name,
                            seniority="role-targeted",
                            email_status="not_found",
                            why_this_person=(
                                f"No individual holding this role at {account.name} could be "
                                f"verified from public sources, so this is role-targeted "
                                f"outreach rather than a named contact. The {title} owns "
                                f"inspection cost, crew exposure and uptime at extraction "
                                f"sites, which is where our angle lands."
                            ),
                            sources=[],
                            confidence="unverified",
                        )
                    )
                rec.status = "partial"
                rec.error = "no verifiable named contacts; fell back to role-targeted outreach"
                rec.fix = (
                    "Keyless web search cannot reliably surface named operations and HSE "
                    "leaders: corporate leadership pages are JavaScript-rendered and the "
                    "richest source (LinkedIn) is behind auth. We refuse to invent a person, "
                    "so the pipeline degrades to role-targeted outreach and flags it. "
                    "Production fix: put a licensed contact provider (Apollo / Cognism / "
                    "Lusha) or a Sales Navigator seat behind this same stage - the verifier "
                    "gate downstream is unchanged, so nothing enters an email unsourced."
                )
                rec.output_summary = f"0 named, {len(account.contacts)} role-targeted"
            else:
                rec.output_summary = f"{named} named contacts"
