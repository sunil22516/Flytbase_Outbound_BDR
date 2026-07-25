# Outbound BDR Agent — LatAm Mining

A delegated, source-verified outbound research pipeline. It takes a campaign brief
(target vertical + reference account) and automatically produces a qualified account
list, contacts inside those accounts, cited research, and a personalised email per
contact — plus a run trace showing exactly where it succeeded and where it hit a wall.

Built for the FlytBase Outbound BDR hackathon.

---

## The idea

The hard part of this problem is not getting a language model to write an email.
It is decomposing the job so that **every claim is checkable and every failure is
visible**.

So the system is nine specialist agents with typed handoffs, not one large prompt:

| Agent | Job | Guarantee it provides |
|-------|-----|----------------------|
| **A0** ICP Architect | Deconstruct the reference account (SQM) into a weighted, machine-readable ICP | Scoring is not arbitrary — every axis traces to the anchor account |
| **A1** Account Scout | Grounded search for real LatAm operators matching the ICP | Over-fetches so the qualifier has something to cut |
| **A2** Account Qualifier | Score every candidate on every axis; apply disqualifiers | **Is allowed to say no** — rejects are kept and shown |
| **A3** Research Analyst | Deep grounded research per account | Emits atomic, individually-cited claims, not a prose blob |
| **A4** Signal Extractor | Turn claims into dated trigger events | Separates strategic insight from company trivia |
| **A5** Contact Mapper | Find Head of Ops / VP HSE / Site Directors | Returns nothing rather than inventing a person |
| **A6** Verifier | Quarantine any claim without a resolvable source | **Deterministic Python, not an LLM** — a guard that cannot hallucinate its own approval |
| **A7** Composer | One email per contact from verified material only | Picks *one* proof point that actually fits the account |
| **A8** Critic | Rubric-score the draft, rewrite it once if weak | Deterministic disqualifier gate + scored reflection loop |

The full reasoning, decision points, and tradeoffs are in
[`docs/mindmap.html`](docs/mindmap.html).

---

## Why provenance is structural, not a prompt instruction

"Cite your sources" in a prompt is a suggestion. In this system:

- `Source` is a **required field** on every `Claim`, `Trigger`, and `Contact` (`src/schemas.py`)
- Research runs on Gemini with **Google Search grounding**, which returns real,
  resolvable citation URLs — redirect URLs are followed so links actually open
- **A6 sits between research and writing.** A claim with no resolvable non-social
  source URL is quarantined and the composer physically cannot use it
- Everything quarantined is listed in the run trace, so gaps are visible rather
  than silently filled in

This is the direct answer to *"fabricated data is an automatic disqualifier"* —
the biggest risk in the brief becomes the system's main feature.

---

## Running it

Two free API keys, no credit card:

- **Gemini** — <https://aistudio.google.com/apikey> — grounded research + citations
- **Groq** — <https://console.groq.com/keys> — email drafting + critic loop

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

cp .env.example .env            # then paste your two keys into .env

python run.py --check           # verifies keys and confirms the model IDs exist
python run.py                   # runs the pipeline, writes results.json
```

`run.py --check` is worth running first — it lists the models each provider
actually exposes to your key, so a wrong model ID fails in two seconds instead of
halfway through a run.

Then view the workspace:

```bash
python -m http.server 8080 -d docs
```

---

## Output

One artifact, `data/results.json` (copied to `docs/data/` for the site), containing:

- the derived ICP with weighted dimensions
- qualified accounts, ranked, with per-axis scoring and rationale
- rejected accounts with reasons
- cited research claims, with quarantine status
- dated trigger events
- contacts with `found` / `inferred` / `not_found` email status
- an email per contact, plus a cold-call opener and objection prep
- the full run trace: every stage, duration, searches issued, sources returned,
  failures, and a written fix for each failure

The site in `docs/` renders that file. No build step, no framework — it is served
statically from GitHub Pages.

---

## Layout

```
run.py                    CLI entry point (--check, then run)
src/
  config.py               campaign brief + runtime settings
  schemas.py              typed state; Source is required on every claim
  llm.py                  provider layer (Gemini grounded / Groq drafting)
  trace.py                per-stage run trace
  orchestrator.py         wires the DAG, assembles results.json
  agents/a0..a8           one module per specialist agent
docs/
  index.html app.js styles.css    the BDR workspace
  mindmap.html                    thinking map
  data/results.json               written by the run
```

---

## Known limits

- **Contact discovery is the weakest stage.** Public leadership pages for
  privately-held LatAm operators are thin and much of the useful data sits behind
  LinkedIn auth. The system returns zero contacts for some accounts rather than
  inventing plausible ones. Production fix: route those accounts to a licensed
  contact provider (Apollo / Cognism / Lusha) behind the same verification gate.
- **English-language search bias.** Grounding skews to English coverage, which
  under-reports Spanish and Portuguese local press — exactly where mine-level
  operational news lives. Fix: run A3 twice per account with localised query sets
  and merge on claim similarity.
- **Free-tier rate limits** cap the run at 8 accounts by default. This is a quota
  constraint, not an architectural one — raise `TARGET_ACCOUNTS` in `.env`.
