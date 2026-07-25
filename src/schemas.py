"""Typed state passed between agents.

Every fact that reaches an email must carry a Source. The Verifier agent
quarantines anything that does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any, Literal

Confidence = Literal["high", "medium", "low", "unverified"]


@dataclass
class Source:
    """Provenance for a single claim. No claim ships without one."""

    url: str
    title: str = ""
    publisher: str = ""
    published: str = ""          # ISO date if the page exposes one
    retrieved: str = field(default_factory=lambda: date.today().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Claim:
    """An atomic, attributable statement about an account."""

    text: str
    sources: list[Source] = field(default_factory=list)
    confidence: Confidence = "unverified"
    quarantined: bool = False
    quarantine_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sources"] = [s.to_dict() for s in self.sources]
        return d


@dataclass
class ICPDimension:
    """One weighted axis of the ideal customer profile, derived from SQM."""

    name: str
    description: str
    weight: float
    reference_value: str          # what SQM looks like on this axis


@dataclass
class ICP:
    """Machine-readable ICP produced by Agent 0 from the reference account."""

    reference_account: str
    vertical: str
    geography: str
    dimensions: list[ICPDimension] = field(default_factory=list)
    disqualifiers: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_account": self.reference_account,
            "vertical": self.vertical,
            "geography": self.geography,
            "dimensions": [asdict(d) for d in self.dimensions],
            "disqualifiers": self.disqualifiers,
            "notes": self.notes,
        }


@dataclass
class DimensionScore:
    dimension: str
    score: float                  # 0-10
    rationale: str
    sources: list[Source] = field(default_factory=list)


@dataclass
class Trigger:
    """A dated, cited event that makes outreach relevant NOW."""

    headline: str
    what_happened: str
    why_it_matters: str           # mapped to the FlytBase angle
    date: str = ""
    sources: list[Source] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sources"] = [s.to_dict() for s in self.sources]
        return d


@dataclass
class Contact:
    name: str
    title: str
    company: str
    seniority: str = ""
    linkedin: str = ""
    email: str = ""
    email_status: Literal["found", "inferred", "not_found"] = "not_found"
    why_this_person: str = ""
    sources: list[Source] = field(default_factory=list)
    confidence: Confidence = "unverified"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sources"] = [s.to_dict() for s in self.sources]
        return d


@dataclass
class Email:
    subject: str
    body: str
    proof_point_used: str = ""    # Shell / Anglo American / CSX, and why
    trigger_referenced: str = ""
    call_opener: str = ""
    objections: list[dict[str, str]] = field(default_factory=list)
    critic_score: float = 0.0
    critic_notes: list[str] = field(default_factory=list)
    revisions: int = 0


@dataclass
class Account:
    name: str
    country: str = ""
    commodity: str = ""
    website: str = ""
    fit_score: float = 0.0
    dimension_scores: list[DimensionScore] = field(default_factory=list)
    fit_rationale: str = ""
    rejected: bool = False
    rejection_reason: str = ""
    research: list[Claim] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "country": self.country,
            "commodity": self.commodity,
            "website": self.website,
            "fit_score": self.fit_score,
            "dimension_scores": [
                {
                    "dimension": s.dimension,
                    "score": s.score,
                    "rationale": s.rationale,
                    "sources": [x.to_dict() for x in s.sources],
                }
                for s in self.dimension_scores
            ],
            "fit_rationale": self.fit_rationale,
            "rejected": self.rejected,
            "rejection_reason": self.rejection_reason,
            "research": [c.to_dict() for c in self.research],
            "triggers": [t.to_dict() for t in self.triggers],
            "contacts": [c.to_dict() for c in self.contacts],
            "sources": [s.to_dict() for s in self.sources],
        }


@dataclass
class CampaignBrief:
    """The single input to the whole system."""

    target_vertical: str
    reference_account: str
    goal_titles: list[str]
    angle: str
    geography: str


@dataclass
class RunState:
    """Shared state threaded through every agent in the DAG."""

    brief: CampaignBrief
    icp: ICP | None = None
    candidates: list[Account] = field(default_factory=list)
    accounts: list[Account] = field(default_factory=list)   # qualified
    rejected: list[Account] = field(default_factory=list)   # shown, not discarded
    emails: dict[str, Email] = field(default_factory=dict)  # keyed "Company::Name"
