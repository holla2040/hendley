"""The app page — one self-contained HTML document, vanilla JS, no CDN.

Three surfaces over the JSON API: **House Parts** (the AVL manager),
**Resolve** (intake → resolution → approval queue → re-resolve), **Order**
(gate + emit + snapshots). All state lives in the page; every button is one
API call.
"""

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hendley</title>
<style>
:root { --fg:#1a1a1a; --bg:#fafafa; --line:#d8d8d8; --accent:#0a5ba8;
        --ok:#1a7f37; --warn:#9a6700; --err:#c0392b; --dim:#6a6a6a; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e6e6e6; --bg:#161616; --line:#3a3a3a; --accent:#5aa2e0;
          --ok:#4ac26b; --warn:#d4a72c; --err:#e5734f; --dim:#9a9a9a; }
}
* { box-sizing:border-box; }
body { margin:0; font:15px/1.45 system-ui, sans-serif; color:var(--fg);
       background:var(--bg); }
header { display:flex; align-items:baseline; gap:1rem; padding:.7rem 1.2rem;
         border-bottom:1px solid var(--line); }
header h1 { font-size:1.15rem; margin:0; }
header .tag { color:var(--dim); font-size:.85rem; }
nav button { background:none; border:none; font:inherit; color:var(--dim);
             padding:.4rem .8rem; cursor:pointer; border-bottom:2px solid transparent; }
nav button.active { color:var(--fg); border-bottom-color:var(--accent); }
main { padding:1rem 1.2rem 4rem; max-width:1100px; margin:0 auto; }
section.tab { display:none; } section.tab.active { display:block; }
table { border-collapse:collapse; width:100%; margin:.6rem 0; }
th, td { text-align:left; padding:.3rem .55rem; border-bottom:1px solid var(--line);
         vertical-align:top; }
th { color:var(--dim); font-weight:600; font-size:.8rem; text-transform:uppercase; }
input, select, textarea { font:inherit; color:var(--fg); background:var(--bg);
  border:1px solid var(--line); border-radius:4px; padding:.3rem .5rem; }
textarea { width:100%; font-family:ui-monospace, monospace; font-size:.85rem; }
button.act { font:inherit; padding:.35rem .9rem; border-radius:5px; cursor:pointer;
  border:1px solid var(--accent); background:var(--accent); color:#fff; }
button.quiet { background:none; color:var(--accent); }
button.small { padding:.1rem .5rem; font-size:.85rem; }
.row { display:flex; gap:.6rem; flex-wrap:wrap; align-items:end; margin:.5rem 0; }
.row label { display:flex; flex-direction:column; font-size:.8rem; color:var(--dim); }
.ok { color:var(--ok); } .warn { color:var(--warn); } .err { color:var(--err); }
.dim { color:var(--dim); }
.badge { display:inline-block; padding:0 .45rem; border-radius:8px;
  font-size:.78rem; border:1px solid var(--line); }
.badge.err { border-color:var(--err); } .badge.warn { border-color:var(--warn); }
.badge.info { border-color:var(--line); }
.card { border:1px solid var(--line); border-radius:8px; padding:.8rem 1rem;
        margin:.8rem 0; }
.card h3 { margin:.1rem 0 .4rem; font-size:1rem; }
#msg { position:fixed; bottom:0; left:0; right:0; padding:.5rem 1.2rem;
  background:var(--bg); border-top:1px solid var(--line); font-size:.9rem;
  white-space:pre-wrap; }
details > summary { cursor:pointer; color:var(--dim); }
.why { font-size:.85rem; color:var(--dim); margin:.1rem 0 0 .2rem; }
h2 { font-size:1.05rem; margin:1.2rem 0 .3rem; }
code { font-family:ui-monospace, monospace; font-size:.88em; }
</style>
</head>
<body>
<header>
  <h1>Hendley</h1><span class="tag">free engineers to do design</span>
  <nav>
    <button data-tab="parts" class="active">House Parts</button>
    <button data-tab="resolve">Resolve</button>
    <button data-tab="order">Order</button>
  </nav>
</header>
<main>

<section class="tab active" id="tab-parts">
  <div class="row">
    <label>kind filter <input id="p-kind" placeholder="resistor"></label>
    <button class="act" onclick="loadParts()">Load</button>
    <button class="act quiet" onclick="refreshStock()">Live-refresh stock</button>
  </div>
  <div id="parts"></div>
  <h2>Approve a Part Choice</h2>
  <div class="row" id="rec">
    <label>kind <input id="r-kind"></label>
    <label>value <input id="r-value"></label>
    <label>package <input id="r-package"></label>
    <label>qualifier <input id="r-qualifier"></label>
    <label>LCSC <input id="r-lcsc" placeholder="C31850"></label>
    <label>MPN <input id="r-mpn"></label>
    <label>manufacturer <input id="r-manufacturer"></label>
    <label>rank <input id="r-rank" value="1" size="3"></label>
    <label>note <input id="r-note" size="28"></label>
    <button class="act" onclick="recordChoice()">Record</button>
  </div>
</section>

<section class="tab" id="tab-resolve">
  <div class="row">
    <label>Production Quantity (boards) <input id="q-n" value="1" size="6"></label>
    <label>provider
      <select id="q-provider"><option>jlcpcb</option><option>pcbway</option></select>
    </label>
    <button class="act" onclick="intake()">Read open Fusion design</button>
    <button class="act quiet" onclick="runResolve()">Resolve</button>
  </div>
  <details><summary>Requirements BOM (JSON, for inspection — the tool fills it)</summary>
    <textarea id="q-req" rows="10" placeholder='{"productionQuantity": 1, "lines": [...]}'></textarea>
  </details>
  <div id="confirms"></div>
  <div id="resolution"></div>
  <div id="queue"></div>
</section>

<section class="tab" id="tab-order">
  <div class="row">
    <button class="act" onclick="emitFiles()">Emit order files</button>
    <span class="dim">writes to the server's output directory from the last resolution</span>
  </div>
  <div id="emit"></div>
  <h2>Release snapshots</h2>
  <div class="row"><button class="act quiet" onclick="loadSnaps()">Refresh list</button></div>
  <div id="snaps"></div>
</section>

</main>
<div id="msg" class="dim">ready</div>
<script>
"use strict";
const $ = id => document.getElementById(id);
const S = { requirements: null, placements: null, resolution: null, queue: null,
            uninterpreted: [],   // intake lines awaiting a one-time spec confirm
            proposals: {} };     // entryIndex -> ordered candidate rows (the AVL-to-be)

function msg(text, cls) { const m = $("msg"); m.textContent = text;
  m.className = cls || "dim"; }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

async function api(path, body) {
  const opts = body === undefined ? {} :
    { method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
async function run(label, fn) {
  msg(label + " …");
  try { await fn(); } catch (e) { msg(label + " failed: " + e.message, "err"); }
}

document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.remove("active"));
  document.querySelectorAll("section.tab").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); $("tab-" + b.dataset.tab).classList.add("active");
});

/* ---- House Parts (7a) -------------------------------------------------- */

function specQS(p) { return `kind=${encodeURIComponent(p.kind)}&value=${
  encodeURIComponent(p.value)}&package=${encodeURIComponent(p.package)}&qualifier=${
  encodeURIComponent(p.qualifier || "")}`; }

function loadParts() { run("loading parts", async () => {
  const kind = $("p-kind").value.trim();
  const data = await api("/api/parts" + (kind ? `?kind=${encodeURIComponent(kind)}` : ""));
  $("parts").innerHTML = data.parts.length ? data.parts.map(partCard).join("")
    : '<p class="dim">no House Parts yet — record the first below.</p>';
  msg(`${data.parts.length} House Part(s)`);
}); }

function partCard(p) {
  const spec = `${p.kind} ${p.value} ${p.package}${p.qualifier ? " " + p.qualifier : ""}`;
  const key = JSON.stringify({kind:p.kind, value:p.value, package:p.package,
                              qualifier:p.qualifier});
  const rows = p.choices.map(c => `<tr>
    <td>${c.rank}</td><td><code>${esc(c.lcscCode || "")}</code></td>
    <td>${esc(c.mpn || "")}</td><td>${esc(c.manufacturer || "")}</td>
    <td>${c.lastStock ?? "—"}${c.lastVerifiedAt ?
        ` <span class="dim">@ ${esc(c.lastVerifiedAt.slice(0,10))}</span>` : ""}</td>
    <td>${c.lastPrice ?? "—"}</td><td class="dim">${esc(c.note || "")}</td>
    <td>
      <button class="act quiet small" onclick='rerankChoice(${key},
        ${JSON.stringify(c.lcscCode || c.mpn)}, 1)'>→ rank 1</button>
      <button class="act quiet small" onclick='removeChoice(${key},
        ${JSON.stringify(c.lcscCode || c.mpn)})'>remove</button>
    </td></tr>`).join("");
  return `<div class="card"><h3>${esc(spec)}</h3>
    <table><tr><th>rank</th><th>lcsc</th><th>mpn</th><th>maker</th>
    <th>stock (advisory)</th><th>price</th><th>note</th><th></th></tr>${rows}</table>
    <details ontoggle='if (this.open) loadHistory(${key}, ${p.id})'>
      <summary>audit history</summary>
      <div id="hist-${p.id}" class="dim">…</div></details></div>`;
}

function loadHistory(spec, id) { run("history", async () => {
  const data = await api("/api/part?" + specQS(spec));
  $("hist-" + id).innerHTML = data.history.map(h =>
    `<div>${esc(h.at)} — <b>${esc(h.event)}</b> ${esc(h.providerRef || "")} ` +
    `${h.note ? "· " + esc(h.note) : ""}</div>`).join("") || "no events";
}); }

function recordChoice() { run("recording", async () => {
  const body = { kind: $("r-kind").value.trim(), value: $("r-value").value.trim(),
    package: $("r-package").value.trim(), qualifier: $("r-qualifier").value.trim(),
    lcsc: $("r-lcsc").value.trim(), mpn: $("r-mpn").value.trim(),
    manufacturer: $("r-manufacturer").value.trim(),
    rank: parseInt($("r-rank").value || "1", 10), note: $("r-note").value.trim() };
  const data = await api("/api/record", body);
  msg(`recorded at rank ${data.choice.rank}`, "ok"); loadParts();
}); }

function rerankChoice(spec, ref, rank) { run("reranking", async () => {
  await api("/api/rerank", {spec, ref, rank});
  msg(`moved ${ref} to rank ${rank}`, "ok"); loadParts();
}); }

function removeChoice(spec, ref) { run("removing", async () => {
  const note = prompt(`Why remove ${ref}? (audited)`) || undefined;
  await api("/api/remove", {spec, ref, note});
  msg(`removed ${ref} (state change — audited)`, "ok"); loadParts();
}); }

function refreshStock() { run("live refresh", async () => {
  const d = await api("/api/refresh", {});
  msg(`refreshed ${d.refreshed} · out of stock: ${d.outOfStock.join(", ") || "none"}` +
      ` · missing: ${d.missing.join(", ") || "none"}`,
      d.outOfStock.length || d.missing.length ? "warn" : "ok");
  loadParts();
}); }

/* ---- Resolve (7b) ------------------------------------------------------ */

function intake() { run("reading Fusion (interpreting new parts may take a minute)",
                        async () => {
  const n = parseInt($("q-n").value || "1", 10);
  const data = await api("/api/intake", {productionQuantity: n});
  S.requirements = data.requirements; S.placements = data.placements;
  S.uninterpreted = data.uninterpreted || [];
  $("q-req").value = JSON.stringify(S.requirements, null, 2);
  renderConfirms();
  const un = S.uninterpreted.length;
  msg(`read '${data.requirements.design || "design"}': ` +
      `${data.requirements.lines.length} line(s)` +
      (un ? ` — ${un} part(s) need a one-time spec confirm below` : " — hit Resolve"),
      un ? "warn" : "ok");
}); }

function renderConfirms() {
  const u = S.uninterpreted;
  if (!u.length) { $("confirms").innerHTML = ""; return; }
  $("confirms").innerHTML = `<h2>New parts — confirm the spec once</h2>
    <p class="dim">These strings weren't confidently interpretable. Your answer
    is cached forever — this question never repeats for the same part text.</p>` +
    u.map((x, i) => {
      const g = (x.guess && x.guess.spec) || {};
      return `<div class="card"><h3>${esc(x.designators.join(","))} —
        “${esc(x.value)}” on ${esc(x.footprint || "?")}</h3>
        ${x.guess && x.guess.rationale ?
          `<div class="dim">guess: ${esc(x.guess.rationale)}</div>` : ""}
        <div class="row">
          <label>kind <input id="cf-kind-${i}" value="${esc(g.kind || "")}"></label>
          <label>value <input id="cf-value-${i}" value="${esc(g.value || "")}"></label>
          <label>package <input id="cf-package-${i}"
            value="${esc(g.package || x.footprint || "")}"></label>
          <label>qualifier <input id="cf-qual-${i}"
            value="${esc(g.qualifier || "")}"></label>
          <button class="act" onclick="confirmSpec(${i})">Confirm</button>
        </div></div>`;
    }).join("");
}

function confirmSpec(i) { run("confirming", async () => {
  const x = S.uninterpreted[i];
  const spec = { kind: $(`cf-kind-${i}`).value.trim(),
                 value: $(`cf-value-${i}`).value.trim(),
                 package: $(`cf-package-${i}`).value.trim(),
                 qualifier: $(`cf-qual-${i}`).value.trim() };
  const envelope = (x.guess && x.guess.envelope) || undefined;
  const data = await api("/api/confirm-spec", {
    kindHint: x.kindHint, value: x.value, footprint: x.footprint,
    spec, envelope });
  S.requirements.lines[x.lineIndex].spec = data.spec;
  $("q-req").value = JSON.stringify(S.requirements, null, 2);
  S.uninterpreted.splice(i, 1);
  renderConfirms();
  msg(S.uninterpreted.length ? "confirmed — next one" :
      "all confirmed — hit Resolve", "ok");
}); }

function runResolve() { run("resolving", async () => {
  const text = $("q-req").value.trim();
  if (!text) throw new Error("no Requirements BOM — intake from Fusion or paste one");
  S.requirements = JSON.parse(text);
  S.requirements.productionQuantity = parseInt($("q-n").value || "1", 10);
  const data = await api("/api/resolve", {
    requirements: S.requirements, placements: S.placements,
    provider: $("q-provider").value });
  S.resolution = data.resolution; S.queue = data.queue || null;
  S.proposals = {};
  if (S.queue) S.queue.entries.forEach((e, i) => S.proposals[i] = [...e.proposal]);
  renderResolution(); renderQueue();
  const esc_ = data.resolution.escalations.length;
  msg(esc_ ? `${esc_} escalation(s) — clear the approval queue below` : "all clean",
      esc_ ? "warn" : "ok");
}); }

function checkBadges(checks) { return (checks || []).map(c =>
  `<span class="badge ${c.severity === "error" ? "err" :
     c.severity === "warning" ? "warn" : "info"}" title="${esc(c.message)}">` +
  `${esc(c.check)}</span>`).join(" "); }

function renderResolution() {
  const r = S.resolution;
  if (!r) { $("resolution").innerHTML = ""; return; }
  const rows = r.lines.map(l => `<tr${l.dnp ? ' class="dim"' : ""}>
    <td>${esc(l.designators.join(","))}</td><td>${esc(l.comment || "")}</td>
    <td>${esc(l.footprint || "")}</td>
    <td><code>${esc(l.ref || "")}</code>${l.mpn ? `<br><span class="dim">${esc(l.mpn)}</span>` : ""}</td>
    <td>${l.rankUsed ?? ""}${l.substitution ? ' <span class="warn">sub</span>' : ""}</td>
    <td>${l.liveStock ?? "—"} / ${l.requiredQty}</td>
    <td>${l.unitPrice ?? "—"}</td><td>${checkBadges(l.checks)}</td></tr>`).join("");
  $("resolution").innerHTML = `<h2>Resolution — ${r.lines.length} line(s) ×
    ${r.productionQuantity} board(s) · ${esc(r.provider)}</h2>
    <table><tr><th>designators</th><th>comment</th><th>footprint</th><th>part</th>
    <th>rank</th><th>stock/need</th><th>unit $</th><th>checks</th></tr>${rows}</table>`;
}

function renderQueue() {
  const q = S.queue;
  if (!q || !q.entries.length) { $("queue").innerHTML = ""; return; }
  $("queue").innerHTML = `<h2>Approval queue — ${q.entries.length} decision(s)</h2>
    <p class="dim">Each part comes with a proposed AVL: rank 1 + two alternates,
    reasons shown. Reorder or swap if you disagree, then Approve — the list as
    you leave it becomes the approved parts list for this spec, everywhere,
    from now on.</p>` +
    q.entries.map((e, i) => queueCard(e, i)).join("") +
    `<div class="row"><button class="act" onclick="approveAll()">
     Approve all &amp; re-resolve</button></div>`;
}

function candRow(c, controls) {
  const params = Object.values(c.keyParams || {}).map(esc).join(" · ");
  return `<td>${controls}</td>
    <td><code>${esc(c.code)}</code></td><td>${esc(c.model || "")}</td>
    <td>${params}</td>
    <td>${c.liveStock ?? "—"}</td><td>${c.unitPrice1 ?? "—"}</td>
    <td>${esc(c.libraryType || "")}</td>
    <td class="why">${(c.why || c.fitUnknownBecause || []).map(esc).join("<br>")}</td>`;
}

const CAND_HEAD = `<tr><th></th><th>code</th><th>mpn</th><th>specs</th>
  <th>stock</th><th>unit $</th><th>class</th><th>why</th></tr>`;

function queueCard(e, i) {
  const spec = e.spec ? `${e.spec.kind} ${e.spec.value} ${e.spec.package}` : (e.ref || e.mpn || "?");
  const avl = e.avlChoices.length ? `<div class="dim">current AVL: ` + e.avlChoices.map(c =>
    `rank-${c.rank ?? "—"} ${esc(c.ref || c.mpn || "?")} (stock ${c.liveStock})`)
    .join(" · ") + `</div>` : "";
  const prop = S.proposals[i] || [];
  const proposal = prop.length ? `<table>${CAND_HEAD}` +
    prop.map((c, r) => `<tr>${candRow(c,
      `<b>rank ${r + 1}</b>
       ${r > 0 ? `<button class="act quiet small" onclick="moveUp(${i},${r})">↑</button>` : ""}
       <button class="act quiet small" onclick="dropRow(${i},${r})">✕</button>`
    )}</tr>`).join("") + `</table>` :
    `<p class="dim">${esc(e.discovery.note || "no fit-confirmed candidates — " +
      "promote one from below, or search manually")}</p>`;
  const extra = (title, rows, cls) => rows.length ?
    `<details><summary>${title} (${rows.length})</summary><table>${CAND_HEAD}` +
    rows.map(c => `<tr class="${cls}">${candRow(c,
      `<button class="act quiet small" onclick='promote(${i},
        ${JSON.stringify(c.code)})'>add</button>`)}</tr>`).join("") +
    `</table></details>` : "";
  return `<div class="card"><h3>${esc(e.designators.join(","))} — ${esc(spec)}
    <span class="badge err">${esc(e.reason)}</span>
    <span class="dim">need ${e.requiredQty}</span></h3>${avl}
    <div><b>Proposed AVL</b> — approve as-is or reorder:</div>${proposal}
    ${extra("also found (fit OK, ranked lower)", e.alsoFound, "")}
    ${extra("⚠ fit unconfirmed — check dimensions before promoting",
            e.fitUnconfirmed, "dim")}</div>`;
}

function moveUp(i, r) {
  const p = S.proposals[i];
  [p[r - 1], p[r]] = [p[r], p[r - 1]];
  renderQueue();
}

function dropRow(i, r) { S.proposals[i].splice(r, 1); renderQueue(); }

function promote(i, code) {
  const e = S.queue.entries[i];
  const all = [...e.candidates, ...e.alsoFound, ...e.fitUnconfirmed];
  const c = all.find(x => x.code === code);
  if (c && !S.proposals[i].some(x => x.code === code)) S.proposals[i].push(c);
  renderQueue();
}

function approveAll() { run("recording approvals", async () => {
  const approvals = [];
  for (const [i, rows] of Object.entries(S.proposals)) {
    const e = S.queue.entries[i];
    rows.forEach((c, idx) => approvals.push({
      spec: e.spec, lcsc: c.code, mpn: c.model || undefined, rank: idx + 1,
      design: S.resolution.design || undefined,
      note: `approved AVL rank ${idx + 1} (queue: ${e.reason})`,
    }));
  }
  if (!approvals.length) throw new Error("no proposal rows to approve");
  await api("/api/approve", {approvals});
  msg(`recorded ${approvals.length} choice(s) — re-resolving`, "ok");
  await runResolve(); loadParts();
}); }

/* ---- Order (7c) --------------------------------------------------------- */

function emitFiles() { run("emitting", async () => {
  if (!S.resolution) throw new Error("resolve first (Resolve tab)");
  const d = await api("/api/emit", {resolution: S.resolution});
  const files = d.files.map(f => `<code>${esc(f)}</code>`).join("<br>");
  const gate = d.readyToUpload
    ? '<p class="ok"><b>READY TO UPLOAD</b></p>'
    : `<p class="err"><b>${d.blockers.length} BLOCKER(S) — DO NOT UPLOAD</b></p>` +
      d.blockers.map(b => `<div class="err">${esc(b.check)}: ${esc(b.message)}</div>`).join("");
  $("emit").innerHTML = `<div class="card">${gate}${files}
    ${d.snapshot ? `<div class="dim">snapshot: <code>${esc(d.snapshot)}</code></div>` : ""}
    ${d.notes.map(n => `<div class="dim">${esc(n)}</div>`).join("")}</div>`;
  msg(d.readyToUpload ? "order files ready" : "blocked — do not upload",
      d.readyToUpload ? "ok" : "err");
  loadSnaps();
}); }

function loadSnaps() { run("snapshots", async () => {
  const d = await api("/api/snapshots");
  $("snaps").innerHTML = d.snapshots.length ? "<table>" + d.snapshots.map(s =>
    `<tr><td><code>${esc(s.name)}</code></td><td class="dim">${s.size} B</td>
     <td><button class="act quiet small" onclick='viewSnap(${JSON.stringify(s.name)})'>
     view</button></td></tr>`).join("") + "</table>"
    : '<p class="dim">no release snapshots yet.</p>';
}); }

function viewSnap(name) { run("snapshot", async () => {
  const d = await api(`/api/snapshot?name=${encodeURIComponent(name)}`);
  const w = window.open("", "_blank");
  w.document.write(`<pre>${esc(JSON.stringify(d, null, 2))}</pre>`);
  w.document.title = name;
}); }

loadParts();
</script>
</body>
</html>
"""
