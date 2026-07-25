/* BDR workspace — renders results.json produced by the agent pipeline. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

const host = (u) => {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; }
};

const scoreClass = (n) => (n >= 7 ? "" : n >= 5 ? "mid" : "low");

let DATA = null;
let activeAccount = 0;

/* ---------------- boot ---------------- */

async function boot() {
  try {
    const res = await fetch("data/results.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    showNoData(err);
    return;
  }
  render();
}

function showNoData(err) {
  $("#briefLine").textContent = "No run data found.";
  $("#detail").innerHTML = `
    <div class="notice">
      <strong>No results yet.</strong><br />
      Run the pipeline to generate <code>docs/data/results.json</code>:<br /><br />
      <code>python run.py --check</code> &nbsp;then&nbsp; <code>python run.py</code><br /><br />
      <span class="small">If you are opening this file directly from disk, the browser blocks
      the JSON fetch. Serve it instead: <code>python -m http.server -d docs 8080</code>.</span><br />
      <span class="small muted">(${esc(err.message)})</span>
    </div>`;
}

/* ---------------- render ---------------- */

function render() {
  const b = DATA.brief || {};
  $("#briefLine").innerHTML =
    `<strong>${esc(b.target_vertical)}</strong> · anchored on ${esc(b.reference_account)} · ` +
    `targeting ${esc((b.goal_titles || []).join(", "))}`;

  const s = DATA.summary || {};
  $("#stats").innerHTML = [
    ["Screened", s.candidates_screened],
    ["Qualified", s.accounts_qualified],
    ["Rejected", s.accounts_rejected],
    ["Contacts", s.contacts_found],
    ["Emails", s.emails_generated],
    ["Claims verified", `${s.claims_verified}/${s.claims_total}`],
    ["Sources", s.unique_sources],
  ]
    .map(([k, v]) => `<div class="stat"><b>${esc(v ?? "—")}</b><span>${esc(k)}</span></div>`)
    .join("");

  $("#footMeta").textContent =
    `Generated ${DATA.generated_at} · ` +
    `research: ${DATA.providers?.gemini?.model || "n/a"} (grounded) · ` +
    `drafting: ${DATA.providers?.groq?.model || "n/a"}`;

  renderAccounts();
  renderICP();
  renderRejected();
  renderTrace();
  wireTabs();
}

function wireTabs() {
  $$(".tab[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab[data-view]").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      $$(".view").forEach((v) =>
        v.classList.toggle("is-active", v.dataset.view === btn.dataset.view)
      );
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
}

/* ---------------- accounts ---------------- */

function renderAccounts() {
  const accounts = DATA.accounts || [];
  $("#acctCount").textContent = `${accounts.length} ranked`;

  $("#accountList").innerHTML = accounts
    .map(
      (a, i) => `
      <button class="acct ${i === 0 ? "is-active" : ""}" data-i="${i}">
        <div class="acct-top">
          <span class="acct-name">${esc(a.name)}</span>
          <span class="score ${scoreClass(a.fit_score)}">${a.fit_score.toFixed(1)}</span>
        </div>
        <div class="acct-meta">${esc(a.country)} · ${esc(a.commodity)} ·
          ${a.contacts.length} contact${a.contacts.length === 1 ? "" : "s"} ·
          ${a.triggers.length} trigger${a.triggers.length === 1 ? "" : "s"}</div>
      </button>`
    )
    .join("");

  $$(".acct").forEach((el) =>
    el.addEventListener("click", () => {
      activeAccount = Number(el.dataset.i);
      $$(".acct").forEach((x) => x.classList.remove("is-active"));
      el.classList.add("is-active");
      renderDetail();
    })
  );

  if (accounts.length) renderDetail();
}

function citeRow(sources) {
  if (!sources || !sources.length) return "";
  const seen = new Set();
  const links = sources
    .filter((s) => s.url && !seen.has(s.url) && seen.add(s.url))
    .slice(0, 4)
    .map(
      (s) =>
        `<a class="cite" href="${esc(s.url)}" target="_blank" rel="noopener"
            title="${esc(s.title || s.url)}">${esc(host(s.url))} ↗</a>`
    )
    .join("");
  return `<div class="cites">${links}</div>`;
}

function renderDetail() {
  const a = (DATA.accounts || [])[activeAccount];
  if (!a) return;

  const dims = a.dimension_scores
    .map(
      (d) => `
      <div class="dim">
        <div><div class="dim-name">${esc(d.dimension)}</div></div>
        <div class="dim-why">${esc(d.rationale)}</div>
        <div style="display:flex;gap:8px;align-items:center">
          <div class="bar"><i style="width:${Math.max(0, Math.min(100, d.score * 10))}%"></i></div>
          <span class="score ${scoreClass(d.score)}">${d.score}</span>
        </div>
      </div>`
    )
    .join("");

  const triggers = a.triggers.length
    ? a.triggers
        .map(
          (t) => `
        <div class="trigger">
          <h4>${esc(t.headline)} ${t.date ? `<span class="when">${esc(t.date)}</span>` : ""}</h4>
          <p>${esc(t.what_happened)}</p>
          <p class="why"><strong>Why now:</strong> ${esc(t.why_it_matters)}</p>
          ${citeRow(t.sources)}
        </div>`
        )
        .join("")
    : `<p class="muted small">No dated trigger event found. Outreach for this account
       falls back to profile-based personalisation, which is weaker — consider deprioritising.</p>`;

  const claims = a.research
    .map(
      (c) => `
      <div class="claim ${c.quarantined ? "q" : ""}">
        <span class="dot ${esc(c.confidence)}"></span>
        <div>
          <div>${esc(c.text)}</div>
          ${c.quarantined
            ? `<div class="muted small">Quarantined: ${esc(c.quarantine_reason)}</div>`
            : citeRow(c.sources)}
        </div>
      </div>`
    )
    .join("");

  const contacts = a.contacts.length
    ? a.contacts.map(contactCard).join("")
    : `<p class="muted small">No verifiable contact found for this account. The system
       returns nothing rather than guessing a name — see the run trace for the fix.</p>`;

  $("#detail").innerHTML = `
    <div class="dhead">
      <h2>${esc(a.name)}</h2>
      <div class="tagrow">
        <span class="tag">${esc(a.country)}</span>
        <span class="tag">${esc(a.commodity)}</span>
        <span class="tag">ICP fit ${a.fit_score.toFixed(1)} / 10</span>
        ${a.website ? `<a class="tag" href="${esc(a.website)}" target="_blank" rel="noopener">website ↗</a>` : ""}
      </div>
    </div>

    <div class="block">
      <h3>Why this account</h3>
      <div class="prose">${esc(a.fit_rationale)}</div>
    </div>

    <div class="block">
      <h3>ICP scoring breakdown</h3>
      <span class="muted small">Each axis scored against the profile derived from the reference account.</span>
      ${dims}
    </div>

    <div class="block">
      <h3>Trigger events — why now</h3>
      <span class="muted small">Dated, cited events that create demand for autonomous inspection.</span>
      ${triggers}
    </div>

    <div class="block">
      <h3>Research (${a.research.filter((c) => !c.quarantined).length} verified of ${a.research.length})</h3>
      <span class="muted small">Every claim links to its source. Greyed rows failed verification and were kept out of the emails.</span>
      ${claims}
    </div>

    <div class="block">
      <h3>Contacts &amp; outreach</h3>
      ${contacts}
    </div>`;

  $$(".copy-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      const wrap = btn.closest(".email");
      const text = `Subject: ${$(".email-subj", wrap).textContent.trim()}\n\n${$(".email-body", wrap).textContent.trim()}`;
      navigator.clipboard.writeText(text).then(() => {
        btn.textContent = "Copied";
        setTimeout(() => (btn.textContent = "Copy email"), 1600);
      });
    })
  );
}

function contactCard(c) {
  const e = c.email_draft;
  const objections = (e?.objections || [])
    .map((o) => `<div class="obj"><b>${esc(o.objection)}</b><span>${esc(o.response)}</span></div>`)
    .join("");

  return `
    <div class="contact">
      <div class="contact-head">
        <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:baseline">
          <div>
            <div class="contact-name">${esc(c.name)}</div>
            <div class="contact-title">${esc(c.title)}${c.seniority ? ` · ${esc(c.seniority)}` : ""}</div>
          </div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            <span class="badge ${esc(c.email_status)}">email ${esc(c.email_status.replace("_", " "))}</span>
            ${c.linkedin ? `<a class="cite" href="${esc(c.linkedin)}" target="_blank" rel="noopener">LinkedIn ↗</a>` : ""}
          </div>
        </div>
        ${c.email ? `<div class="muted small" style="margin-top:6px">${esc(c.email)}</div>` : ""}
        ${citeRow(c.sources)}
      </div>

      <div class="contact-body">
        <div class="kv"><b>Why this person</b>${esc(c.why_this_person)}</div>

        ${e ? `
          <div class="email">
            <div class="email-subj">${esc(e.subject)}</div>
            <div class="email-body">${esc(e.body)}</div>
            <div class="email-foot">
              <button class="btn copy-btn">Copy email</button>
              <span>Critic ${e.critic_score}/10${e.revisions ? ` · revised ${e.revisions}×` : ""}</span>
              ${e.proof_point_used ? `<span>· Proof point: ${esc(e.proof_point_used)}</span>` : ""}
            </div>
          </div>

          ${e.call_opener ? `<div class="kv" style="margin-top:14px"><b>Cold-call opener</b>${esc(e.call_opener)}</div>` : ""}
          ${objections ? `<div class="kv" style="margin-top:6px"><b>Likely objections</b>${objections}</div>` : ""}
        ` : `<p class="muted small">No email generated for this contact — see the run trace.</p>`}
      </div>
    </div>`;
}

/* ---------------- icp / rejected / trace ---------------- */

function renderICP() {
  const icp = DATA.icp;
  if (!icp) { $("#icpMeta").textContent = "ICP was not produced in this run."; return; }

  $("#icpMeta").textContent = `Derived from ${icp.reference_account} · ${icp.geography}`;
  $("#icpNotes").textContent = icp.notes || "";

  $("#icpDims").innerHTML = icp.dimensions
    .map(
      (d) => `
      <div class="dim">
        <div>
          <div class="dim-name">${esc(d.name)}</div>
          <div class="muted small">weight ${d.weight}</div>
        </div>
        <div class="dim-why">
          ${esc(d.description)}
          <div class="muted small" style="margin-top:4px"><strong>Reference:</strong> ${esc(d.reference_value)}</div>
        </div>
        <div class="bar"><i style="width:${Math.round(d.weight * 100 / 0.35 * 1)}%"></i></div>
      </div>`
    )
    .join("");

  $("#icpDq").innerHTML = (icp.disqualifiers || []).map((x) => `<li>${esc(x)}</li>`).join("");
}

function renderRejected() {
  const rows = DATA.rejected || [];
  $("#rejectedList").innerHTML = rows.length
    ? rows
        .map(
          (r) => `
        <div class="rej">
          <div><strong>${esc(r.name)}</strong><div class="muted small">${esc(r.country)} · ${esc(r.commodity)}</div></div>
          <div class="muted">${esc(r.rejection_reason)}</div>
          <span class="score ${scoreClass(r.fit_score)}">${(r.fit_score || 0).toFixed(1)}</span>
        </div>`
        )
        .join("")
    : `<p class="muted">Nothing was rejected in this run.</p>`;
}

function renderTrace() {
  const t = DATA.trace;
  if (!t) return;

  $("#traceCounts").innerHTML = [
    ["ok", t.counts.ok],
    ["partial", t.counts.partial],
    ["failed", t.counts.failed],
    ["skipped", t.counts.skipped],
  ]
    .map(([k, v]) => `<span class="badge ${k}">${k}: ${v}</span>`)
    .join("") + `<span class="badge skipped">total ${t.total_duration_s}s</span>`;

  $("#traceList").innerHTML = t.stages
    .map(
      (s) => `
      <div class="stage">
        <div class="stage-code">${esc(s.agent)}</div>
        <div>
          <div class="stage-label">${esc(s.label)} <span class="badge ${esc(s.status)}">${esc(s.status)}</span></div>
          ${s.output_summary ? `<div class="stage-out">${esc(s.output_summary)}</div>` : ""}
          ${s.searches?.length ? `<div class="muted small">searched: ${esc(s.searches.slice(0, 3).join(" · "))}</div>` : ""}
          ${s.sources_found ? `<div class="muted small">${s.sources_found} sources returned</div>` : ""}
          ${s.error ? `<div class="stage-err">${esc(s.error)}</div>` : ""}
          ${s.fix ? `<div class="stage-fix"><strong>How we'd fix it:</strong> ${esc(s.fix)}</div>` : ""}
          ${(s.notes || []).map((n) => `<div class="muted small">${esc(n)}</div>`).join("")}
        </div>
        <div class="stage-time">${s.duration_s}s</div>
      </div>`
    )
    .join("");

  $("#quarantineList").innerHTML = (t.quarantined || []).length
    ? t.quarantined
        .map(
          (q) => `<div class="qrow"><b>${esc(q.subject)}</b> — ${esc(q.claim)}
                  <span>(${esc(q.reason)})</span></div>`
        )
        .join("")
    : `<p class="muted small">Nothing was quarantined — every claim resolved to a source.</p>`;
}

boot();
