"""Run trace.

The brief asks: "If the agent fails or hits a wall anywhere in this pipeline,
show us where, and explain how you'd fix it." This module is that answer — every
stage records what it attempted, what it produced, and how it failed, and the
whole trace ships to the UI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class StageRecord:
    agent: str
    label: str
    status: str = "pending"        # pending | ok | partial | failed | skipped
    started: str = ""
    finished: str = ""
    duration_s: float = 0.0
    inputs: str = ""
    output_summary: str = ""
    searches: list[str] = field(default_factory=list)
    sources_found: int = 0
    error: str = ""
    fix: str = ""                  # how we'd fix it, written when it fails
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Trace:
    def __init__(self) -> None:
        self.started = _now()
        self.stages: list[StageRecord] = []
        self.quarantined: list[dict[str, Any]] = []
        self._t0 = time.time()

    def stage(self, agent: str, label: str, inputs: str = "") -> "StageContext":
        rec = StageRecord(agent=agent, label=label, inputs=inputs, started=_now())
        self.stages.append(rec)
        return StageContext(rec)

    def quarantine(self, subject: str, claim: str, reason: str) -> None:
        """Record a claim the Verifier refused to let through to an email."""
        self.quarantined.append(
            {"subject": subject, "claim": claim, "reason": reason, "at": _now()}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "finished": _now(),
            "total_duration_s": round(time.time() - self._t0, 1),
            "stages": [s.to_dict() for s in self.stages],
            "quarantined": self.quarantined,
            "counts": {
                "ok": sum(1 for s in self.stages if s.status == "ok"),
                "partial": sum(1 for s in self.stages if s.status == "partial"),
                "failed": sum(1 for s in self.stages if s.status == "failed"),
                "skipped": sum(1 for s in self.stages if s.status == "skipped"),
            },
        }


class StageContext:
    """Context manager that stamps timing and captures failures automatically."""

    def __init__(self, record: StageRecord) -> None:
        self.record = record
        self._t0 = time.time()

    def __enter__(self) -> StageRecord:
        return self.record

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.record.finished = _now()
        self.record.duration_s = round(time.time() - self._t0, 1)
        if exc is not None:
            self.record.status = "failed"
            self.record.error = f"{exc_type.__name__}: {exc}"
            if not self.record.fix:
                self.record.fix = (
                    "Stage failed. Re-run this stage in isolation; if the provider "
                    "rate-limited, back off and retry, otherwise fall back to the "
                    "secondary provider."
                )
            return True  # swallow: a failed stage must not kill the run
        if self.record.status == "pending":
            self.record.status = "ok"
        return False
