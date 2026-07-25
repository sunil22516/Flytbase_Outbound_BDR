"""Campaign brief (the system's only input) and runtime settings."""

from __future__ import annotations

import os
from pathlib import Path

from .schemas import CampaignBrief

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SITE_DATA_DIR = ROOT / "docs" / "data"


def _load_dotenv() -> None:
    """Minimal .env loader so the repo has no hard dependency on python-dotenv."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# --- Providers -------------------------------------------------------------
# Gemini carries the research stages because Google Search grounding returns
# real source URLs. Groq carries the high-volume drafting/critic loop.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "120"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

# --- Run shape -------------------------------------------------------------
# Depth over breadth: the brief rewards strategic insight, not volume.
TARGET_ACCOUNTS = int(os.environ.get("TARGET_ACCOUNTS", "8"))
CONTACTS_PER_ACCOUNT = int(os.environ.get("CONTACTS_PER_ACCOUNT", "2"))
CRITIC_PASS_MARK = float(os.environ.get("CRITIC_PASS_MARK", "7.5"))
MAX_REVISIONS = int(os.environ.get("MAX_REVISIONS", "1"))


# --- The campaign brief ----------------------------------------------------
BRIEF = CampaignBrief(
    target_vertical=(
        "Large-scale lithium, copper, and iron ore mining operations in Latin America"
    ),
    reference_account="Sociedad Química y Minera de Chile (SQM)",
    goal_titles=["Head of Operations", "VP of HSE", "Site Director"],
    angle=(
        "Autonomous drone inspection replacing contracted crews at hazardous, "
        "24/7 extraction sites"
    ),
    geography="Latin America",
)

# FlytBase proof points. The Composer picks the ONE that fits the account,
# rather than name-dropping all three.
PROOF_POINTS = {
    "Anglo American": "a mining major — closest operational analogue for a copper/iron ore producer",
    "Shell": "hazardous, continuous-process industrial sites running 24/7",
    "CSX": "sprawling linear and rail-served infrastructure across large footprints",
}

COMPANY_CONTEXT = (
    "FlytBase is the global category leader in Physical AI for large industrial sites. "
    "The platform powers mission-critical autonomous operations across 300+ enterprise "
    "sites in 40+ countries. Customers include Shell, CSX, UK Police, Airbus, "
    "Anglo American, Dole, and Statnett."
)
