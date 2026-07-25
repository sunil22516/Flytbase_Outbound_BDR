"""Streamlit front end — run the outbound BDR agent live.

Reviewers can press a button and watch the nine agents execute stage by stage,
rather than only reading a pre-computed artifact.

Secrets are read from st.secrets and pushed into the environment BEFORE any
src.* import, because src.config resolves its settings at import time.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Outbound BDR Agent — LatAm Mining",
    page_icon="🛰️",
    layout="wide",
)

ROOT = Path(__file__).resolve().parent


# --------------------------------------------------------------------------
# Secrets -> environment, before src.config is imported
# --------------------------------------------------------------------------
def _load_secrets() -> None:
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "GEMINI_MODEL", "GROQ_MODEL"):
        try:
            value = st.secrets[key]
        except Exception:
            continue
        if value:
            os.environ[key] = str(value)


_load_secrets()


def _apply_run_shape(accounts: int, contacts: int) -> None:
    os.environ["TARGET_ACCOUNTS"] = str(accounts)
    os.environ["CONTACTS_PER_ACCOUNT"] = str(contacts)


# --------------------------------------------------------------------------
# Styling — carries the same identity as the static workspace
# --------------------------------------------------------------------------
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=IBM+Plex+Mono:wght@400;600&display=swap');
      .stApp { background: #e9e7d2;
        background-image: radial-gradient(#c9c8ae 1.2px, transparent 1.2px);
        background-size: 14px 14px; }
      html, body, [class*="css"] { font-family: 'IBM Plex Mono', monospace; }
      h1, h2, h3 { font-family: 'Press Start 2P', monospace !important;
        color: #d2600e !important; line-height: 1.5 !important; }
      h1 { font-size: 20px !important; }
      h2 { font-size: 14px !important; }
      h3 { font-size: 11px !important; }
      .stButton > button {
        font-family: 'Press Start 2P', monospace; font-size: 9px;
        background: #f0b31e; color: #231a12; border: 3px solid #231a12;
        border-radius: 0; box-shadow: 4px 4px 0 #231a12; padding: 12px 16px;
      }
      .stButton > button:hover { background: #1c9bd8; color: #fff; }
      .stButton > button:active { transform: translate(4px, 4px); box-shadow: none; }
      div[data-testid="stMetric"] {
        background: #fbfaf2; border: 3px solid #231a12; padding: 12px;
        box-shadow: 4px 4px 0 #231a12;
      }
      .emailbox { background:#fff; border:3px solid #231a12; padding:16px;
        box-shadow:4px 4px 0 #231a12; white-space:pre-wrap; font-size:13px; }
      .subjbox { background:#f0b31e; border:3px solid #231a12; border-bottom:none;
        padding:10px 14px; font-weight:700; font-size:13px; }
      .warnbox { background:#f0b31e; border:3px solid #231a12; padding:10px 13px;
        font-size:12.5px; margin-bottom:12px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_results() -> dict | None:
    for path in (ROOT / "docs" / "data" / "results.json", ROOT / "data" / "results.json"):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


if "results" not in st.session_state:
    st.session_state.results = load_results()


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("Campaign brief")
    st.markdown(
        """
**Target vertical**
Large-scale lithium, copper and iron ore mining in Latin America

**Reference account**
Sociedad Química y Minera de Chile (SQM)

**Goal**
Book discovery calls with Head of Operations, VP of HSE, Site Directors

**Angle**
Autonomous drone inspection replacing contracted crews at hazardous, 24/7
extraction sites
        """
    )

    st.divider()
    st.header("Run settings")
    accounts = st.slider("Accounts to qualify", 2, 10, 3)
    contacts = st.slider("Contacts per account", 1, 3, 2)
    st.caption(
        "A 3-account run takes roughly 4-6 minutes: every stage does real web "
        "retrieval and page fetching, not cached data."
    )

    from src.llm import gemini_available, groq_available  # noqa: E402

    st.divider()
    st.header("Providers")
    st.write("Generation:", "✅ Groq" if groq_available() else "❌ Groq")
    st.write("Fallback:", "✅ Gemini" if gemini_available() else "❌ Gemini")
    st.write("Retrieval:", "✅ Bing RSS + Wikipedia (keyless)")

    run_clicked = st.button("▶  RUN THE AGENT LIVE", use_container_width=True)


st.title("Outbound BDR Agent — LatAm Mining")
st.caption(
    "Nine specialist agents. Every claim carries a source, and anything the fact "
    "guard cannot tie to a retrieved URL never reaches an email."
)


# --------------------------------------------------------------------------
# Live run
# --------------------------------------------------------------------------
AGENT_BLURB = {
    "A0": "Deconstructing the reference account into a weighted ICP",
    "A1": "Searching for real LatAm operators matching that profile",
    "A2": "Scoring every candidate and rejecting the non-fits",
    "A3": "Deep retrieval per account — claims with citations",
    "A4": "Turning claims into dated trigger events",
    "A5": "Finding the humans who own the problem",
    "A6": "Fact guard — quarantining anything unsourced",
    "A7": "Writing one email per contact from verified material",
    "A8": "Critic — scoring drafts and rewriting the weak ones",
}

if run_clicked:
    _apply_run_shape(accounts, contacts)

    from src.orchestrator import run_pipeline, write_results  # noqa: E402

    progress = st.progress(0.0, text="Starting…")
    log = st.container()
    seen: set[str] = set()
    total = len(AGENT_BLURB)

    def on_stage(code: str, label: str, produced: list) -> None:
        done = len([c for c in AGENT_BLURB if c in seen])
        progress.progress(min(done / total, 1.0), text=f"{code} · {AGENT_BLURB.get(code, label)}")
        if produced:
            seen.add(code)
            with log:
                for s in produced[-4:]:
                    icon = {"ok": "✅", "partial": "⚠️", "failed": "❌", "skipped": "⏭️"}.get(
                        s.status, "•"
                    )
                    st.write(f"{icon} **{code}** {s.label} — {s.output_summary or s.error}")

    with st.spinner("Agents running — this is doing real web retrieval…"):
        try:
            payload = run_pipeline(verbose=False, on_stage=on_stage)
            write_results(payload)
            st.session_state.results = payload
            progress.progress(1.0, text="Run complete")
            st.success("Run complete.")
        except Exception as exc:  # noqa: BLE001
            progress.empty()
            st.error(f"Run failed: {exc}")

data = st.session_state.results

if not data:
    st.info("No run yet. Press **RUN THE AGENT LIVE** in the sidebar.")
    st.stop()


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------
s = data.get("summary", {})
cols = st.columns(6)
for col, (label, value) in zip(
    cols,
    [
        ("Screened", s.get("candidates_screened")),
        ("Qualified", s.get("accounts_qualified")),
        ("Rejected", s.get("accounts_rejected")),
        ("Emails", s.get("emails_generated")),
        ("Verified", f"{s.get('claims_verified')}/{s.get('claims_total')}"),
        ("Sources", s.get("unique_sources")),
    ],
):
    col.metric(label, value)

tab_acc, tab_icp, tab_rej, tab_trace = st.tabs(
    ["Accounts", "ICP", "Rejected", "Run trace"]
)

with tab_acc:
    for a in data.get("accounts", []):
        with st.expander(
            f"{a['name']}  ·  fit {a['fit_score']:.1f}/10  ·  "
            f"{len(a['contacts'])} contact(s)  ·  {len(a['triggers'])} trigger(s)"
        ):
            st.caption(f"{a['country']} · {a['commodity']}")
            st.write(a["fit_rationale"])

            if a["triggers"]:
                st.subheader("Why now")
                for t in a["triggers"]:
                    st.markdown(f"**{t['headline']}** {t.get('date','')}")
                    st.write(t["what_happened"])
                    st.info(t["why_it_matters"])
                    for src in t["sources"][:3]:
                        st.caption(f"↗ {src['url']}")

            st.subheader("Contacts & outreach")
            for c in a["contacts"]:
                role_only = c.get("seniority") == "role-targeted"
                st.markdown(f"**{c['name']}** — {c['title']}")
                if role_only:
                    st.markdown(
                        '<div class="warnbox">No individual could be verified for this '
                        "role from public sources. This is <strong>role-targeted "
                        "outreach</strong> — the system does not invent people.</div>",
                        unsafe_allow_html=True,
                    )
                st.caption(c["why_this_person"])
                e = c.get("email_draft")
                if e:
                    st.markdown(f'<div class="subjbox">{e["subject"]}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="emailbox">{e["body"]}</div>', unsafe_allow_html=True)
                    st.caption(
                        f"Critic {e['critic_score']}/10 · proof point: {e['proof_point_used']}"
                    )
                    if e.get("call_opener"):
                        st.markdown(f"**Call opener:** {e['call_opener']}")
                    for o in e.get("objections", []):
                        st.markdown(f"- **{o['objection']}** → {o['response']}")
                st.divider()

            st.subheader(f"Researched facts ({len(a['research'])})")
            for c in a["research"]:
                mark = "🚫" if c["quarantined"] else "✅"
                st.markdown(f"{mark} {c['text']}")
                for src in c["sources"][:2]:
                    st.caption(f"↗ {src['url']}")

with tab_icp:
    icp = data.get("icp")
    if icp:
        st.write(icp.get("notes", ""))
        for d in icp.get("dimensions", []):
            st.markdown(f"**{d['name']}** — weight {d['weight']}")
            st.caption(f"{d['description']}  ·  SQM: {d['reference_value']}")
        st.subheader("Disqualifiers")
        for x in icp.get("disqualifiers", []):
            st.markdown(f"- {x}")

with tab_rej:
    st.caption("A scout that never says no is listing, not qualifying.")
    for r in data.get("rejected", []):
        st.markdown(f"**{r['name']}** ({r['country']}) — {r['rejection_reason']}")

with tab_trace:
    t = data.get("trace", {})
    counts = t.get("counts", {})
    st.write(
        f"ok {counts.get('ok')} · partial {counts.get('partial')} · "
        f"failed {counts.get('failed')} · skipped {counts.get('skipped')} · "
        f"{t.get('total_duration_s')}s"
    )
    for stage in t.get("stages", []):
        icon = {"ok": "✅", "partial": "⚠️", "failed": "❌", "skipped": "⏭️"}.get(
            stage["status"], "•"
        )
        st.markdown(f"{icon} **{stage['agent']}** {stage['label']} — {stage['duration_s']}s")
        if stage.get("output_summary"):
            st.caption(stage["output_summary"])
        if stage.get("error"):
            st.error(stage["error"])
        if stage.get("fix"):
            st.info(f"How we'd fix it: {stage['fix']}")

    if t.get("quarantined"):
        st.subheader("Quarantined by the fact guard")
        for q in t["quarantined"]:
            st.markdown(f"- **{q['subject']}** — {q['claim']} _({q['reason']})_")
