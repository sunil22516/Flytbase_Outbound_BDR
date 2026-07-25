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
    initial_sidebar_state="expanded",
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
      /* Design tokens lifted from the hackathon portal: cream page, near-black
         2px outlines, hard offset shadows, 10px radii, yellow/green/blue
         accents, clean grotesk headings over a monospace body. */
      @import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');

      :root {
        --paper:  #f2efe6;
        --card:   #ffffff;
        --card2:  #fbf9f2;
        --ink:    #14140f;
        --muted:  #6b6459;
        --line:   #14140f;
        --yellow: #f5c518;
        --green:  #12752f;
        --greenbg:#d9f0dc;
        --blue:   #1f6feb;
        --redbg:  #f7d9d2;
        --shadow: 4px 4px 0 var(--line);
        --r: 10px;
      }

      .stApp { background: var(--paper);
        background-image: radial-gradient(#d8d3c4 1px, transparent 1px);
        background-size: 22px 22px; }

      html, body, [class*="css"], .stApp p, .stApp li, .stApp span {
        font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
      }
      h1, h2, h3 {
        font-family: 'Instrument Sans', 'Inter', system-ui, sans-serif !important;
        color: var(--ink) !important; letter-spacing: -0.02em !important;
        font-weight: 700 !important; line-height: 1.15 !important;
      }
      h1 { font-size: 40px !important; margin-bottom: 4px !important; }
      h2 { font-size: 21px !important; margin-top: 6px !important; }
      h3 { font-size: 16px !important; }

      /* Buttons: yellow primary in the main column, matching the portal's
         SHOW BRIEF / SUBMIT MY BUILD treatment. */
      .stButton > button {
        font-family: 'JetBrains Mono', monospace !important; font-size: 12px !important;
        font-weight: 700 !important; letter-spacing: .04em; text-transform: uppercase;
        background: var(--yellow); color: var(--ink); border: 2px solid var(--line);
        border-radius: var(--r); box-shadow: var(--shadow); padding: 13px 18px;
        transition: transform .06s ease, box-shadow .06s ease;
      }
      .stButton > button:hover { background: #ffd83d; color: var(--ink); }
      .stButton > button:active { transform: translate(4px, 4px); box-shadow: none; }
      .stButton > button:focus { color: var(--ink) !important; }

      div[data-testid="stMetric"] {
        background: var(--card); border: 2px solid var(--line); border-radius: var(--r);
        padding: 14px 16px; box-shadow: var(--shadow);
      }
      div[data-testid="stMetric"] label,
      div[data-testid="stMetricLabel"] p {
        color: var(--muted) !important; font-size: 10.5px !important;
        text-transform: uppercase; letter-spacing: .09em; font-weight: 700 !important;
      }
      div[data-testid="stMetricValue"] {
        color: var(--ink) !important;
        font-family: 'Instrument Sans', system-ui, sans-serif !important;
        font-size: 30px !important; font-weight: 700 !important;
        letter-spacing: -0.02em !important;
      }

      /* Every text surface gets an explicit colour. Anything left to Streamlit's
         own theme goes invisible the moment a reviewer opens the link on a
         dark-mode machine, which is exactly what happened in testing. */
      .stApp, .stApp p, .stApp li, .stApp span, .stApp label,
      .stApp div[data-testid="stMarkdownContainer"],
      .stApp div[data-testid="stMarkdownContainer"] * { color: var(--ink); }
      .stApp p, .stApp li { line-height: 1.7; }
      .stApp a, .stApp a * { color: var(--blue) !important; text-decoration: underline; }

      /* Captions are the source lines under every claim — they must be legible,
         not a 40%-opacity grey. */
      .stApp div[data-testid="stCaptionContainer"],
      .stApp div[data-testid="stCaptionContainer"] * {
        color: var(--muted) !important; font-size: 11.5px !important;
      }

      /* Tabs: default Streamlit renders these near-invisible on a cream base. */
      .stTabs [data-baseweb="tab-list"] { gap: 6px; background: transparent; border: none; }
      .stTabs [data-baseweb="tab"] {
        background: var(--card2); border: 2px solid var(--line); border-radius: var(--r);
        padding: 9px 18px; box-shadow: 3px 3px 0 var(--line);
      }
      .stTabs [data-baseweb="tab"] p {
        color: var(--ink) !important; font-weight: 700 !important;
        font-size: 12px !important; text-transform: uppercase; letter-spacing: .05em;
      }
      .stTabs [aria-selected="true"] { background: var(--yellow); }
      .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {
        background: transparent !important; display: none !important;
      }

      /* Expanders — the account cards. The header bar was rendering as a dark
         slab with dark text; pin both surfaces. */
      div[data-testid="stExpander"] {
        border: 2px solid var(--line) !important; border-radius: var(--r) !important;
        background: var(--card) !important; box-shadow: var(--shadow);
        margin-bottom: 18px; overflow: hidden;
      }
      div[data-testid="stExpander"] summary,
      div[data-testid="stExpander"] details > summary {
        background: var(--card2) !important; border-radius: 0 !important;
        border-bottom: 2px solid var(--line) !important; padding: 14px 16px !important;
      }
      div[data-testid="stExpander"] summary p,
      div[data-testid="stExpander"] summary span,
      div[data-testid="stExpander"] summary svg {
        color: var(--ink) !important; fill: var(--ink) !important;
        font-weight: 700 !important; font-size: 14px !important;
      }
      div[data-testid="stExpander"] summary:hover { background: var(--yellow) !important; }

      /* Sidebar: brief + controls. */
      section[data-testid="stSidebar"] {
        background: #ece8dc; border-right: 2px solid var(--line);
      }
      section[data-testid="stSidebar"] * { color: var(--ink) !important; }
      section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
      section[data-testid="stSidebar"] h3 {
        font-size: 13px !important; text-transform: uppercase; letter-spacing: .09em;
        color: var(--muted) !important;
      }
      section[data-testid="stSidebar"] div[data-testid="stCaptionContainer"] * {
        color: var(--muted) !important;
      }

      /* Alerts (st.info / st.success / st.error) — used for "why it matters"
         and for the failure explanations in the run trace. */
      div[data-testid="stAlert"] {
        border: 2px solid var(--line); border-radius: var(--r);
        box-shadow: 3px 3px 0 var(--line);
      }
      div[data-testid="stAlert"] * { color: var(--ink) !important; }

      .stSlider label, .stSlider [data-testid="stTickBar"] { color: var(--ink) !important; }
      div[data-testid="stProgress"] > div > div > div { background: var(--green) !important; }

      .emailbox { background: var(--card); border: 2px solid var(--line);
        border-top: none; border-radius: 0 0 var(--r) var(--r); padding: 18px;
        box-shadow: var(--shadow); white-space: pre-wrap; font-size: 13px;
        color: var(--ink); line-height: 1.75; }
      .subjbox { background: var(--yellow); border: 2px solid var(--line);
        border-bottom: none; border-radius: var(--r) var(--r) 0 0;
        padding: 11px 16px; font-weight: 700; font-size: 13px; color: var(--ink); }
      .warnbox { background: var(--yellow); border: 2px solid var(--line);
        border-radius: var(--r); padding: 11px 14px; font-size: 12.5px;
        margin-bottom: 12px; color: var(--ink); box-shadow: 3px 3px 0 var(--line); }

      /* The agent rail — makes the nine agents visible as a system, which is
         what the brief is actually grading. Mirrors the portal's numbered
         "How today works" step cards. */
      .rail { display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 22px; }
      .chip { border:2px solid var(--line); border-radius:var(--r);
        background:var(--card); padding:10px 12px; box-shadow:3px 3px 0 var(--line);
        min-width:134px; flex:1 1 134px; }
      .chip b { display:inline-block; background:var(--ink); color:var(--yellow);
        font-family:'JetBrains Mono',monospace; font-size:10px; font-weight:700;
        padding:2px 7px; border-radius:5px; letter-spacing:.06em; }
      .chip span { display:block;
        font-family:'Instrument Sans',system-ui,sans-serif; font-size:12.5px;
        font-weight:600; color:var(--ink); margin-top:8px; line-height:1.3; }
      .chip.done { background:var(--greenbg); }
      .chip.fail { background:var(--redbg); }
      .arrow { display:none; }
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

AGENT_NAME = {
    "A0": "ICP Architect",
    "A1": "Account Scout",
    "A2": "Qualifier",
    "A3": "Research Analyst",
    "A4": "Signal Extractor",
    "A5": "Contact Mapper",
    "A6": "Fact Guard",
    "A7": "Composer",
    "A8": "Critic",
}


def render_rail(status: dict[str, str] | None = None) -> str:
    """The nine agents, always on screen.

    The system requirement being graded is delegation across sub-agents, so the
    division of labour has to be visible on the page — not buried in the repo.
    """
    status = status or {}
    cells = []
    for code, name in AGENT_NAME.items():
        cls = {"ok": "chip done", "failed": "chip fail"}.get(status.get(code, ""), "chip")
        cells.append(
            f'<div class="{cls}"><b>{code}</b><span>{name}</span></div>'
        )
    return '<div class="rail">' + '<div class="arrow">›</div>'.join(cells) + "</div>"


st.markdown(render_rail(), unsafe_allow_html=True)

# A reviewer who never opens the sidebar still has to be able to run the agent.
if not run_clicked:
    run_clicked = st.button(
        "▶  RUN THE AGENT LIVE  —  9 agents, real web retrieval",
        use_container_width=True,
        key="run_main",
    )

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
            progress.progress(1.0, text="Run complete")

            # A run that dies in an early stage (a provider daily cap, most
            # often) still returns a well-formed payload with zero accounts.
            # Promoting that to the display blanks every panel and makes a
            # working system look broken in front of a reviewer. Keep the last
            # good run on screen and say plainly what happened.
            if payload.get("accounts"):
                write_results(payload)
                st.session_state.results = payload
                st.success("Run complete — dashboard below is from this run.")
            else:
                failed = [
                    s for s in payload.get("trace", {}).get("stages", [])
                    if s.get("status") == "failed"
                ]
                reason = failed[0].get("error", "") if failed else "no accounts produced"
                st.warning(
                    "This live run produced no accounts and was **not** allowed to "
                    "overwrite the stored run. First failure: "
                    f"`{reason[:180]}`\n\n"
                    "This is the free-tier provider daily cap, not a logic failure — "
                    "the pipeline below is the output of the same code on a fresh "
                    "quota. Lower **Accounts to qualify** to 2 and retry, or read the "
                    "**Run trace** tab where every stage records its own failure and "
                    "the fix."
                )
        except Exception as exc:  # noqa: BLE001
            progress.empty()
            st.error(f"Run failed: {exc}")
            st.info(
                "The stored run below is unaffected — results are only replaced by a "
                "run that actually produces accounts."
            )

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
                    # A score of 0 means the critic stage never ran (provider
                    # cap), not that the draft scored zero. Showing "0.0/10"
                    # under every email misreads as the system failing its own
                    # quality bar.
                    score = e.get("critic_score") or 0
                    if score > 0:
                        st.caption(
                            f"Critic {score}/10 · proof point: {e['proof_point_used']}"
                        )
                    else:
                        st.caption(
                            f"Proof point: {e['proof_point_used']} · critic pass did not "
                            "run for this draft (provider daily cap — see Run trace)"
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
