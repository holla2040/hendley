"""The app page — one self-contained HTML document, vanilla JS, no CDN.

The single-page design (approved via mockup, 2026-07-12): a left rail with
the open Fusion design's components colored by stock state (green = covers
the order, red = short, amber = needs a spec search, dashed = DNP), a detail
panel driven by clicking a component, and an Export button in the title bar
that stays disabled until every row is green.

One gesture everywhere: a radio column picks the part that mounts for this
order. A pick that overrides an existing approved part is order-only (the
requirements line is pinned in memory and re-resolved — nothing written to
the parts DB); the FIRST pick for a spec with no house part is permanent
(recorded as the approved part at rank 1). In-progress picks persist through
page reloads via the server-side draft (``/api/draft``).

Two provenance signals ride the list: a value the app assigned (the schematic
carries no VALUE — the spec came from the confirm card / spec search) renders
with a small ``app`` tag, and any line can be marked DNP for the current board
run only ("DNP this run" on the panel title — draft-persisted, restored with
one click, cleared by a clean export; schematic DNP stays Fusion's call).
"""

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hendley</title>
<style>
:root {
  --board:#0E241B; --panel:#143024; --line:#27493A;
  --silk:#E9EEE7; --tin:#8FA79A; --pad:#D9A441;
  --ok-bg:#BFE3C4; --err-bg:#F0C9C2; --warn-bg:#EFDCA8; --chip-fg:#13221A;
  --ok:#6FD59A; --err:#F08373; --warn:#E5C063;
  --mono:ui-monospace,"Cascadia Mono","SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,"Segoe UI",sans-serif;
}
* { box-sizing:border-box; }
html, body { margin:0; height:100%; overflow:hidden; }
body { background:var(--board); color:var(--silk); font:14px/1.5 var(--sans);
       display:flex; flex-direction:column; }
button { font:inherit; cursor:pointer; }
body.busy, body.busy * { cursor:wait !important; }
:focus-visible { outline:2px solid var(--pad); outline-offset:2px; }
@media (prefers-reduced-motion: reduce) { * { transition:none !important; } }

/* ---- header -------------------------------------------------------------- */
.top { display:flex; align-items:center; gap:14px; padding:10px 22px;
       border-bottom:1px solid var(--line); position:relative; flex:none; }
.brand { font:600 15px var(--mono); letter-spacing:.35em; color:var(--silk); }
.tag { color:var(--tin); font-size:12.5px; }
.design { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%);
          font:600 13px var(--mono); color:var(--silk); }
.meta { margin-left:auto; display:flex; align-items:center; gap:10px;
        font:12px var(--mono); color:var(--tin); }
.adapter { background:var(--panel); border:1px solid var(--line); border-radius:4px;
           color:var(--silk); font:12px var(--mono); padding:3px 6px; }
.btn { background:none; border:1px solid var(--pad); color:var(--pad);
       border-radius:4px; padding:7px 12px; font:600 13px var(--mono); }
.btn:hover { background:rgba(217,164,65,.12); }
.btn.solid { background:var(--pad); color:#1A1406; }
.btn.solid:hover { background:#E4B45C; }
.btn.solid[aria-disabled="true"] { background:var(--panel); color:var(--tin);
  border-color:var(--line); cursor:not-allowed; }
.meta .btn { padding:5px 12px; }

/* ---- frame ---------------------------------------------------------------- */
.wrap { display:grid; grid-template-columns:308px 1fr;
        flex:1; min-height:0; }
.wrap > main { overflow-y:auto; min-height:0; }
@media (max-width:760px) { .wrap { grid-template-columns:1fr; }
  .rail { border-right:none; border-bottom:1px solid var(--line); } }

/* ---- left rail ------------------------------------------------------------ */
.rail { border-right:1px solid var(--line); display:flex; flex-direction:column;
        min-height:0; }
.rail-top { display:flex; gap:8px; align-items:center; padding:14px 14px 8px; }
.qty { display:flex; align-items:center; gap:6px; font:12px var(--mono);
       color:var(--tin); }
.qty input { width:52px; background:var(--panel); border:1px solid var(--line);
  border-radius:4px; color:var(--silk); font:13px var(--mono); padding:6px 8px;
  text-align:right; }
.read-note { margin:0; padding:0 16px 6px; font:11.5px var(--mono); color:var(--tin); }
.comps { display:flex; flex-direction:column; gap:4px;
         padding:4px 14px 48px; overflow-y:auto; flex:1; min-height:0; }
.comp { display:flex; justify-content:space-between; align-items:baseline; gap:10px;
  width:100%; text-align:left; border:1px solid transparent; border-radius:4px;
  padding:3px 11px; font:12.5px var(--mono); background:var(--panel);
  color:var(--silk); }
.comp .ref { font-weight:700; }
.comp .desc { opacity:.78; margin-left:6px; }
.comp .stat { font-variant-numeric:tabular-nums; white-space:nowrap; }
.comp.st-ok    { background:var(--ok-bg);  color:var(--chip-fg); }
.comp.st-short { background:var(--err-bg); color:var(--chip-fg); }
.comp.st-conf  { background:var(--warn-bg); color:var(--chip-fg); }
.comp.st-dnp   { background:transparent; color:var(--tin);
                 border:1px dashed var(--line); }
.comp.st-na    { background:var(--panel); color:var(--silk); }
.comp.sel { outline:2px solid var(--pad); outline-offset:2px; }

/* the search line — part type, what you want, Search */
.sect.search { border-top:1px solid var(--line); padding-top:14px; }
.sect.search .form { gap:10px; }
select.cat { font:12px var(--mono); max-width:210px; }
input.grow { flex:1 1 auto; min-width:240px; font:13px var(--mono); }
/* the agent is reading this part: the box says so, and pulses while it does */
input.grow.working { color:var(--pad); border-color:var(--pad);
  animation:pulse 1.4s ease-in-out infinite; }
input.grow.working::placeholder { color:var(--pad); opacity:1; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.45; } }
.say { font:13px var(--mono); color:var(--pad); margin:12px 0 0; }
.say .count { color:var(--tin); font-size:12px; margin-left:10px; }

/* the query, laid bare and editable */
details.query { margin:8px 0 0; }
details.query > summary { cursor:pointer; color:var(--tin);
  font:12px var(--mono); }
details.query > summary:hover { color:var(--pad); }
details.query .req { font:12.5px var(--mono); color:var(--silk); margin:10px 0; }
details.query .req .mono { color:var(--pad); }
table.terms td { padding:3px 12px 3px 0; border:none; font-size:12.5px; }
table.terms td.op { color:var(--pad); text-align:center; }
.form.addterm { margin-top:8px; gap:8px; }
.form.addterm input { font:12px var(--mono); max-width:180px; }
.form.addterm input.unit { max-width:64px; }
.form.addterm select { font:12px var(--mono); }

/* ---- main / detail --------------------------------------------------------- */
.panel { padding:12px 30px 60px; }
.crumb { font:12px var(--mono); color:var(--pad); background:none; border:none;
         padding:0; margin-bottom:14px; }
.crumb:hover { text-decoration:underline; }
.part-title { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap;
              margin:0 0 4px; }
.part-title .ref { font:700 21px var(--mono); color:var(--pad);
                   letter-spacing:.04em; }
.part-title .spec { font:400 16px var(--sans); color:var(--silk); }
.badge { font:700 10.5px var(--mono); letter-spacing:.1em; text-transform:uppercase;
         border-radius:3px; padding:3px 8px; color:var(--chip-fg); }
.badge.ok { background:var(--ok-bg); } .badge.short { background:var(--err-bg); }
.badge.conf { background:var(--warn-bg); }
.badge.na { background:var(--panel); color:var(--tin);
            border:1px solid var(--line); }
.sub { color:var(--tin); font-size:13px; margin:0 0 6px; }
.per-board { margin-left:auto; font:600 13px var(--mono); color:var(--silk);
             white-space:nowrap; }
.sect { border-top:1px solid var(--line); margin-top:22px; padding-top:14px; }
.sect.tight { margin-top:8px; padding-top:6px; }
.sect.tight td { border-bottom:none; }
.sect.tight tr:nth-child(even) td { background:rgba(233,238,231,.04); }
.sect.tight tr.linkrow:hover td { background:rgba(217,164,65,.08); }
.eyebrow { font:600 11px var(--mono); letter-spacing:.16em;
           text-transform:uppercase; color:var(--tin); margin:0 0 10px; }
.tablewrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th { text-align:left; font:600 11px var(--mono); letter-spacing:.1em;
     text-transform:uppercase; color:var(--tin); padding:5px 12px 5px 0;
     border-bottom:1px solid var(--line); }
td { padding:7px 12px 7px 0; border-bottom:1px solid var(--line); font-size:13px;
     vertical-align:top; }
td code, .mono { font:12.5px var(--mono); }
tr.picked td { background:rgba(217,164,65,.07); }
/* the comparison table: a rejected part keeps its row and all its numbers —
   only the ONE value that failed is red. That is the cell you scan for. */
table.results td.bad { color:var(--err); font-weight:600; }
table.results tr.reject td { opacity:.66; }
table.results tr.reject:hover td { opacity:1; }
table.results th .th-sort { white-space:nowrap; }
/* already on the approved list above: it says so, instead of carrying a second
   radio — two radios for one part means the lower one steals the selection */
table.results tr.onlist td { background:rgba(217,164,65,.05); }
table.results .listed { font:11px var(--mono); color:var(--pad);
  white-space:nowrap; }
tr.linkrow { cursor:pointer; }
tr.linkrow:hover td { background:rgba(217,164,65,.06); }
.num { text-align:right; } th.num { text-align:right; }
.short-num { color:var(--err); font-weight:600; }
.ok-num { color:var(--ok); }
.dimtd { color:var(--tin); }
.why { color:var(--tin); font-size:12px; line-height:1.45; }
.th-sort { background:none; border:none; padding:0; cursor:pointer;
  font:600 11px var(--mono); letter-spacing:.1em; text-transform:uppercase;
  color:var(--tin); white-space:nowrap; }
.th-sort:hover { color:var(--pad); }
.btn.mini { padding:2px 9px; font-size:11px; margin-left:8px;
  white-space:nowrap; }
details.unconf { margin-top:12px; }
details.unconf > summary { cursor:pointer; color:var(--pad);
  border:1px solid var(--pad); border-radius:4px; padding:4px 10px;
  width:max-content; font:600 12px var(--mono); }
details.unconf > summary:hover { background:rgba(217,164,65,.12); }
.note { color:var(--tin); font-size:12.5px; margin:10px 0 0; }
.alert { color:var(--err); font-size:13px; margin:10px 0; }
input[type=radio], input[type=checkbox] { accent-color:var(--pad);
  width:16px; height:16px; cursor:pointer; }
td.pick { padding-right:4px; }
.title-actions { margin-left:auto; display:flex; align-items:center;
                 gap:8px; }
.title-actions .btn.mini { margin-left:0; padding:3px 9px; font-size:10.5px;
                           line-height:1.35; }
a { color:var(--pad); }
.form { display:flex; gap:10px; align-items:end; margin-top:6px; }
.form label { display:flex; flex-direction:column; gap:4px; font:11px var(--mono);
  letter-spacing:.08em; text-transform:uppercase; color:var(--tin);
  flex:1 1 0; min-width:0; }
.form input, .form select, .place select {
  background:var(--panel); border:1px solid var(--line); border-radius:4px;
  color:var(--silk); font:13px var(--mono); padding:7px 9px; width:100%; }
.place select { width:auto; padding:4px 6px; }
.form input.suspect { border-color:var(--warn); }
.form .btn { flex:0 0 auto; white-space:nowrap; }
@media (max-width:900px) { .form { flex-wrap:wrap; }
  .form label { flex:1 1 140px; } }
.place { display:flex; gap:26px; flex-wrap:wrap; align-items:center;
         font:13px var(--mono); }
.place span b { color:var(--tin); font-weight:400; margin-right:6px; }
.effective { color:var(--pad); }
.card { border:1px solid var(--line); border-radius:6px; padding:12px 16px;
        margin:14px 0; }
.card.dismiss { cursor:pointer; }
.ok-line { color:var(--ok); }
#msg { position:fixed; bottom:0; left:0; right:0; padding:.45rem 1.2rem;
  background:var(--board); border-top:1px solid var(--line); font-size:.9rem;
  white-space:pre-wrap; color:var(--tin); }
#msg.ok { color:var(--ok); } #msg.err { color:var(--err); }
#msg.warn { color:var(--warn); }
</style>
</head>
<body>
<header class="top">
  <span class="brand">HENDLEY</span>
  <span class="tag">free engineers to do design</span>
  <span class="design" id="design-name"></span>
  <span class="meta">
    <select class="adapter" id="provider" aria-label="output adapter">
      <option value="jlcpcb">JLCPCB</option><option value="pcbway">PCBWay</option>
    </select>
    <button class="btn solid" id="export-btn" aria-disabled="true"
      title="Refresh the design first.">Export BOM/CPL</button>
  </span>
</header>

<div class="wrap">
<aside class="rail">
  <div class="rail-top">
    <button class="btn" id="refresh-btn">&#10227; Refresh</button>
    <span class="qty">boards <input id="qty" value="1" aria-label="board quantity"></span>
  </div>
  <p class="read-note" id="read-note"></p>
  <nav class="comps" id="comps"></nav>
</aside>
<main><div class="panel" id="main">
  <p class="sub">Hit <b>Refresh</b> to read the open Fusion design (schematic
  view active) and check every part against live stock.</p>
</div></main>
</div>
<div id="msg">ready</div>

<script>
"use strict";
const $ = id => document.getElementById(id);
const S = {
  requirements: null,  // intake result — never mutated by order-only picks
  placements: null,
  uninterpreted: [],   // lines awaiting a spec search (by lineIndex)
  resolution: null,
  queue: null,
  overrides: {},       // lineKey -> {code}: order-only pins, draft-persisted
  rotations: [],
  avlCache: {},        // spec JSON -> housePart (this session)
  searches: {},        // lineKey -> the engineer's search terms (draft-persisted)
  manualDnp: {},       // lineKey -> true — DNP for this run only (draft-persisted)
  acks: {},            // lineKey -> the unnamed part was looked at (draft)
  results: {},         // lineKey ("" = overview) -> the last search's result
  busySearch: null,    // lineKey currently searching
  categories: [],      // the catalog's tables + their filterable columns
  catPick: {},         // lineKey -> the part type YOU chose ("" = auto)
  showQuery: true,     // the criteria ARE the point — open unless you close it
  showSpecs: false,    // the comparison table's other catalog parameters
  readings: {},        // lineKey -> what the agent read this part to BE
  reading: null,       // lineKey being read right now
  seed: {},            // lineKey -> the seeded terms, as YOU edited them before
                       // searching (unset = the reading's own plan stands)
  typed: {},           // lineKey -> what YOU typed in the box (session only —
                       // the app's own seed is never stored as if you typed it)
  staged: {},          // lineKey -> {radio, checks:{code:bool}} — UNSAVED
                       // selections; nothing writes until Update is pressed
  altSort: {key: null, dir: -1},  // alternates sort: "stock" | "price"
  showUnconfirmed: false,  // the collapsed package-not-confirmed block
  selected: null,      // lineIndex of the open detail panel
  design: "",
  exportResult: null,
};

function msg(text, cls) { const m = $("msg"); m.textContent = text;
  m.className = cls || ""; }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function fmt(n) { return n == null ? "—" : Number(n).toLocaleString("en-US"); }
function money(unit, qty) {
  return unit == null ? "—" : (Number(unit) * qty).toFixed(2); }
function unitStr(u) { return u == null ? "—" : String(u); }
function qty() { return Math.max(1, parseInt($("qty").value || "1", 10) || 1); }
function provider() { return $("provider").value; }
function lineKey(line) { return line.designators.join(","); }
function specQS(spec) {
  return "kind=" + encodeURIComponent(spec.kind) +
    "&value=" + encodeURIComponent(spec.value) +
    "&package=" + encodeURIComponent(spec.package) +
    "&qualifier=" + encodeURIComponent(spec.qualifier || "");
}

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
  try { await fn(); }
  catch (e) { msg(label + " failed: " + e.message, "err"); }
}

/* ---- refresh: intake -> draft -> resolve --------------------------------- */

async function hydrate(data, readAt) {
  S.requirements = data.requirements;
  S.placements = data.placements;
  S.uninterpreted = data.uninterpreted || [];
  S.design = data.requirements.design || "";
  S.selected = null;
  S.exportResult = null;
  $("design-name").textContent = S.design || "(unnamed design)";
  $("read-note").textContent = "read " + readAt.toLocaleString();
  const d = await api("/api/draft?design=" + encodeURIComponent(S.design));
  S.overrides = {};
  S.searches = {};
  S.manualDnp = {};
  S.acks = {};
  S.results = {};
  S.readings = {};
  S.typed = {};
  S.staged = {};
  if (d.draft) {
    if (d.draft.productionQuantity) $("qty").value = d.draft.productionQuantity;
    const valid = new Set(S.requirements.lines.map(lineKey));
    for (const [k, v] of Object.entries(d.draft.overrides || {}))
      if (valid.has(k)) S.overrides[k] = v;   // stale picks drop silently
    for (const [k, v] of Object.entries(d.draft.searches || {}))
      if (valid.has(k)) S.searches[k] = v;
    for (const k of Object.keys(d.draft.manualDnp || {}))
      if (valid.has(k)) S.manualDnp[k] = true;
    for (const k of Object.keys(d.draft.acks || {}))
      if (valid.has(k)) S.acks[k] = true;
  }
  try { S.rotations = (await api("/api/rotations")).corrections; }
  catch (e) { S.rotations = []; }
  await resolveNow();
}

async function refresh() {
  document.body.classList.add("busy");   // wait cursor until the read lands
  try {
    $("comps").innerHTML = "";   // stale rows never sit under a fresh read
    $("main").innerHTML =
      '<p class="sub">Reading the open Fusion design …</p>';
    await run(
    "reading Fusion (interpreting new parts can take a minute)", async () => {
    const data = await api("/api/intake", {productionQuantity: qty()});
    await hydrate(data, new Date());
    msg("read “" + (S.design || "design") + "” — " +
        S.requirements.lines.length + " part type" +
        (S.requirements.lines.length === 1 ? "" : "s") + ". " +
        "(Click Fusion’s schematic tab before the next Refresh.)", "ok");
  }); } finally { document.body.classList.remove("busy"); }
}

/* page load: repopulate from the last read — every correction reapplies
   (confirmed specs from the DB, picks from the draft, rotations from the
   corrections file); Refresh re-reads Fusion whenever you want */
async function loadCache() {
  let cached = null;
  try { cached = (await api("/api/intake-cache")).cached; } catch (e) {}
  if (!cached) return;
  await run("loading last design", async () => {
    await hydrate(cached, cached.savedAt ? new Date(cached.savedAt) : new Date());
    msg("loaded “" + (S.design || "design") +
        "” from the last read — Refresh re-reads Fusion.", "ok");
  });
}

function effectiveRequirements() {
  const req = JSON.parse(JSON.stringify(S.requirements));
  req.productionQuantity = qty();
  for (const line of req.lines)
    if (S.manualDnp[lineKey(line)]) line.dnp = true;   // this run only
  if (provider() === "jlcpcb") {
    for (const line of req.lines) {
      const o = S.overrides[lineKey(line)];
      if (o && o.code) {   // order-only pin: pick replaces the mode in memory
        delete line.spec; delete line.mpn; delete line.manufacturer;
        line.providerRefs = {jlcpcb: o.code};
      }
    }
  }
  return req;
}

/* resolve = the approved-parts database answering the design. Searches are
   the engineer's own act (/api/search) and never ride along here — nothing
   is ever queried behind their back. */
async function resolveNow() {
  const data = await api("/api/resolve", {
    requirements: effectiveRequirements(),
    placements: S.placements, provider: provider()});
  S.resolution = data.resolution;
  S.queue = data.queue || null;
  S.altSort = {key: null, dir: -1};
  S.staged = {};   // committed state changed — staged diffs are stale
  adoptAutoLookups();
  render();
  saveDraft();
}

/* A dense R/C value on a chip package needs no judgment, so the app looks it
   up without being asked. It still lands in the SAME results table as your
   own searches, under a line saying what it looked up — a part list with no
   query attached to it is exactly the thing you can't check. */
function adoptAutoLookups() {
  for (const q of ((S.queue || {}).entries || [])) {
    const rl = S.requirements.lines[q.lineIndex];
    if (!rl || !rl.spec) continue;
    const key = lineKey(rl);
    if (S.results[key]) continue;          // your own search always wins
    if (!(q.discovery || {}).automatic) continue;
    const reasons = (c, k) => (c[k] || []).map(w => ({field: "package", why: w}));
    const query = (q.discovery || {}).query || null;
    S.results[key] = {
      terms: "",
      planned: {say: [rl.spec.value, rl.spec.package].filter(Boolean).join(" ") +
        " — looked up from the schematic, you didn’t have to ask",
        category: (q.discovery || {}).category},
      // the app ran this one unasked, so it owes you the query all the more —
      // every constraint it enforced, listed and droppable like any other
      query: query,
      proved: Object.entries((query || {}).params || {}).map(
        ([k, v]) => ({field: NET_COL[k] || k, op: "eq", value: v})),
      candidates: [].concat(q.proposal || [], q.alsoFound || []),
      misses: [].concat(
        (q.fitUnconfirmed || []).map(c =>
          ({...c, failed: reasons(c, "fitUnknownBecause")})),
        (q.rejectedCandidates || []).map(c =>
          ({...c, failed: reasons(c, "rejectedBecause")}))),
      scanned: (q.candidates || []).length + (q.rejectedCandidates || []).length +
               (q.fitUnconfirmed || []).length,
      truncated: false};
  }
}

function saveDraft() {
  if (!S.design) return;
  api("/api/draft", {design: S.design, draft: {
    productionQuantity: qty(),
    overrides: S.overrides,
    searches: S.searches,
    manualDnp: S.manualDnp,
    acks: S.acks,
    savedAt: new Date().toISOString(),
  }}).catch(() => {});   // draft is a convenience — never break the flow
}

/* ---- state per line -------------------------------------------------------- */

function escFor(i) {
  return (S.resolution.escalations || []).find(e => e.lineIndex === i) || null;
}
function queueFor(i) {
  return S.queue ? (S.queue.entries || []).find(e => e.lineIndex === i) || null
                 : null;
}
function uninterpFor(i) {
  return S.uninterpreted.find(u => u.lineIndex === i) || null;
}
/* THE SCHEMATIC never named this part — no VALUE, no MPN, just a footprint.
   Whatever the app remembers for it is a guess about intent (the same
   footprint in the next design could be a different device), so it never
   mounts silently: one look, one Update, per design. */
function unnamed(i) {
  const rl = S.requirements.lines[i];
  return !rl.comment && !rl.mpn &&
    !Object.keys(rl.providerRefs || {}).length;
}
function needsAck(i) {
  const l = S.resolution.lines[i];
  if (!l.ref || !unnamed(i)) return false;
  return !S.acks[lineKey(S.requirements.lines[i])];
}
function lineState(i) {
  const l = S.resolution.lines[i];
  if (l.dnp) return "dnp";
  if (needsAck(i)) return "conf";
  if (escFor(i)) return "short";
  if (l.ref || l.mpn) {
    if ((l.checks || []).some(c => c.check === "unverified")) return "na";
    return "ok";
  }
  return "short";
}
function isOverridden(i) {
  const rl = S.requirements.lines[i];
  return !!S.overrides[lineKey(rl)];
}
function isManualDnp(i) {
  return !!S.manualDnp[lineKey(S.requirements.lines[i])];
}

/* ---- staged selections (radio + backup checkboxes, saved on Update) -------- */

function stagedFor(i) {
  const key = lineKey(S.requirements.lines[i]);
  return S.staged[key] || (S.staged[key] = {radio: undefined, checks: {}});
}
function committedRadio(i) { return S.resolution.lines[i].ref || null; }
function committedChecks(i) {
  // codes on the spec's approved list, mounted part included — every
  // active AVL choice is "checked"; unchecking any of them prunes it
  const rl = S.requirements.lines[i];
  const house = rl.spec ? S.avlCache[JSON.stringify(rl.spec)] : null;
  return new Set(((house && house.choices) || [])
    .map(c => c.lcscCode).filter(Boolean));
}
function effRadio(i) {
  const st = stagedFor(i);
  return st.radio !== undefined ? st.radio : committedRadio(i);
}
function effCheck(i, code) {
  const st = stagedFor(i);
  return code in st.checks ? st.checks[code] : committedChecks(i).has(code);
}
function stagedDirty(i) {
  const st = S.staged[lineKey(S.requirements.lines[i])];
  if (!st) return false;
  if (st.radio !== undefined && st.radio !== committedRadio(i)) return true;
  const com = committedChecks(i);
  return Object.entries(st.checks).some(([c, on]) => on !== com.has(c));
}

/* ---- render ----------------------------------------------------------------- */

function render() { renderRail(); renderExport(); renderMain(); }

const STATE_BADGE = {ok: "ok", short: "short", conf: "conf", na: "na",
                     dnp: null};

function railStat(i, state) {
  const l = S.resolution.lines[i];
  if (state === "dnp") return isManualDnp(i) ? "DNP · this run" : "DNP";
  if (state === "conf") return "confirm";
  if (state === "na") return "unverified";
  if (state === "short") return "short";
  let tail = "✓";
  if (isOverridden(i)) tail += " alt";
  else if (l.substitution) tail += " sub";
  return tail;
}

/* THE DESIGN'S OWN WORDS, always — read off the REQUIREMENT (what Refresh
   brought over), never the resolution (what the app then decided): the
   schematic VALUE, the schematic MPN, the library footprint name, verbatim.
   What the app worked out about a part belongs in the panel's "recorded as"
   line. A rail that shows the app's own guesses back to you can't be checked. */
function designWords(i) {
  const rl = S.requirements.lines[i];
  return [rl.comment || rl.mpn, rl.footprint].filter(Boolean);
}

function renderRail() {
  if (!S.resolution) { $("comps").innerHTML = ""; return; }
  const order = S.resolution.lines.map((l, i) => i)
    .sort((a, b) => (S.resolution.lines[a].dnp ? 1 : 0) -
                    (S.resolution.lines[b].dnp ? 1 : 0));
  $("comps").innerHTML = order.map(i => {
    const l = S.resolution.lines[i];
    const state = lineState(i);
    const sel = S.selected === i ? " sel" : "";
    return '<button class="comp st-' + state + sel + '" data-line="' + i + '">' +
      '<span><span class="ref">' + esc(l.designators.join(" ")) + '</span>' +
      '<span class="desc">' + designWords(i).map(esc).join(" · ") +
      '</span></span>' +
      '<span class="stat">' + esc(railStat(i, state)) + '</span></button>';
  }).join("");
  document.querySelectorAll("#comps .comp").forEach(b =>
    b.onclick = () => select(parseInt(b.dataset.line, 10)));
}

function select(i) {
  S.selected = (S.selected === i) ? null : i;
  S.altSort = {key: null, dir: -1};
  S.showUnconfirmed = false;
  S.staged = {};   // navigating away discards unsaved selections
  if (S.selected != null) {
    // every open re-verifies the whole list — the panel shows NOW
    const rl = S.requirements.lines[S.selected];
    if (rl && rl.spec) delete S.avlCache[JSON.stringify(rl.spec)];
  }
  render();
}

function renderExport() {
  const b = $("export-btn");
  // a manually-DNP'd line's pending spec search never blocks the export —
  // the part sits out this run; restoring it brings the card and gate back
  const open = S.uninterpreted.filter(u => !isManualDnp(u.lineIndex));
  const ready = !!S.resolution &&
    (S.resolution.escalations || []).length === 0 &&
    open.length === 0;
  b.setAttribute("aria-disabled", ready ? "false" : "true");
  if (ready) b.removeAttribute("title");
  else b.title = S.resolution
    ? "Complete the part substitutions — every part in the list must be green."
    : "Refresh the design first.";
}

function renderMain() {
  if (!S.resolution) return;
  $("main").innerHTML = (S.selected == null) ? overviewHtml() : detailHtml(S.selected);
  wireMain();
}

/* checks the red panel already communicates by its own layout — the table
   IS the explanation; the export gate still enforces them */
const PANEL_SILENT_CHECKS = ["no-part-choices", "avl-exhausted"];

function checksHtml(l) {
  return (l.checks || [])
    .filter(c => c.severity !== "info" &&
                 !PANEL_SILENT_CHECKS.includes(c.check))
    .map(c => '<div class="' +
      (c.severity === "error" ? "alert" : "why") + '">' +
      esc(c.check) + ": " + esc(c.message) + "</div>").join("");
}

function overviewHtml() {
  const r = S.resolution;
  const order = r.lines.map((l, i) => i)
    .sort((a, b) => (r.lines[a].dnp ? 1 : 0) - (r.lines[b].dnp ? 1 : 0));
  const rows = order.map((i, n) => {
    const l = r.lines[i];
    const state = lineState(i);
    const lcsc = l.ref
      ? '<a href="https://www.lcsc.com/product-detail/' +
        encodeURIComponent(l.ref) + '.html" target="_blank" rel="noopener" ' +
        'onclick="event.stopPropagation()"><code>' + esc(l.ref) + "</code></a>"
      : "—";
    const stock = state === "short"
      ? '<td class="num short-num">' +
        (Math.max(0, ...(((escFor(i) || {}).choices || []).map(
          c => c.liveStock || 0))) || "—") + " / " + fmt(l.requiredQty) + '</td>'
      : '<td class="num' + (l.liveStock == null ? " dimtd" : "") + '">' +
        (l.dnp ? "—" : fmt(l.liveStock) + " / " + fmt(l.requiredQty)) + '</td>';
    return '<tr class="linkrow" data-line="' + i + '"' +
      (l.dnp ? ' style="color:var(--tin)"' : "") + '>' +
      '<td class="dimtd mono">' + (n + 1) + '</td>' +
      '<td class="mono">' + esc(l.designators.join(" ")) + '</td>' +
      '<td>' + esc(l.comment || l.mpn || "") +
        (l.footprint ? ' <span class="dimtd">' + esc(l.footprint) + '</span>' : "") +
      '</td>' +
      '<td>' + lcsc + '</td>' + stock +
      '<td class="num">' + esc(unitStr(l.unitPrice)) + '</td>' +
      '<td class="num">' + esc(l.dnp ? "—" : money(l.unitPrice, l.requiredQty)) +
      '</td><td' + (l.offerClass ? "" : ' class="dimtd"') + '>' +
      esc(l.dnp ? "—" : offerLabel(l.offerClass)) + '</td></tr>';
  }).join("");
  const priced = r.lines.filter(l => !l.dnp);
  const total = priced.reduce((t, l) =>
    t + (l.unitPrice == null ? 0 : Number(l.unitPrice) * l.requiredQty), 0);
  const partial = priced.some(l => l.unitPrice == null);
  const perBoard = total > 0
    ? '<span class="per-board">' + (partial ? "≥ " : "") +
      "$" + (total / r.productionQuantity).toFixed(2) + " / board</span>"
    : "";
  return exportCardHtml() +
    '<h2 class="part-title"><span class="spec">Design Overview</span>' +
    perBoard + '</h2>' +
    '<div class="sect tight"><div class="tablewrap"><table>' +
    '<tr><th>#</th><th>designators</th><th>part</th><th>lcsc</th>' +
    '<th class="num">stock / need</th><th class="num">unit $</th>' +
    '<th class="num">order $</th><th>class</th></tr>' + rows +
    '</table></div></div>' +
    // the catalog is searchable without opening a part — look anything up
    searchHtml(null);
}

function exportCardHtml() {
  const d = S.exportResult;
  if (!d) return "";
  const files = d.files.map(f => "<code>" + esc(f) + "</code>").join("<br>");
  const blockers = (d.blockers || []).map(b =>
    '<div class="alert">' + esc(b.check) + ": " + esc(b.message) + "</div>").join("");
  const notes = (d.notes || []).map(n =>
    '<div class="why">' + esc(n) + "</div>").join("");
  return '<div class="card dismiss" id="export-card">' +
    (d.readyToUpload
      ? '<div class="ok-line"><b>Files written</b>' +
        (d.savedTo ? " — saved to <b>" + esc(d.savedTo) + "</b>" : "") + "</div>"
      : '<div class="alert"><b>Blocked — do not upload</b></div>') +
    files + blockers + notes + "</div>";
}

/* ---- detail panel ------------------------------------------------------------ */

const PART_TABLE_HEAD =
  '<tr><th></th><th>alt</th><th>lcsc</th><th>manufacturer</th><th>mpn</th>' +
  '<th>package</th>' +
  '<th class="num">live stock</th><th class="num">need</th>' +
  '<th class="num">unit $</th><th class="num">order $</th>' +
  '<th>class</th><th>why</th></tr>';

function lcscLink(code) {
  return code
    ? '<a href="https://www.lcsc.com/product-detail/' +
      encodeURIComponent(code) + '.html" target="_blank" rel="noopener">' +
      "<code>" + esc(code) + "</code></a>"
    : "<code>—</code>";
}

function partRow(o) {
  // o: {radio, checked, code, mpn, maker, pkg, cls, stock, stockCls, need,
  //     unit, why, action, check:{show,on}} — radio/checkbox changes STAGE;
  //     nothing writes until the panel's Update button
  const radio = o.radio
    ? '<input type="radio" name="pick" ' + (o.checked ? "checked " : "") +
      'data-stage="' + esc(o.code) + '" aria-label="use ' + esc(o.code) +
      ' for this order">'
    : "";
  const check = o.check && o.check.show
    ? '<input type="checkbox" data-check="' + esc(o.code) + '"' +
      (o.check.on ? " checked" : "") + ' aria-label="alt ' + esc(o.code) +
      '">'
    : "";
  return '<tr' + (o.checked ? ' class="picked"' : "") + '>' +
    '<td class="pick">' + radio + '</td>' +
    '<td class="pick">' + check + '</td>' +
    '<td>' + lcscLink(o.code) + '</td>' +
    '<td>' + esc(o.maker || "—") + '</td>' +
    '<td class="mono">' + esc(o.mpn || "") + '</td>' +
    '<td class="mono">' + esc(o.pkg || "—") + '</td>' +
    '<td class="num ' + (o.stockCls || "") + '">' +
    (o.unknown ? "????" : fmt(o.stock)) + '</td>' +
    '<td class="num">' + fmt(o.need) + '</td>' +
    '<td class="num">' + (o.unknown ? "????" : esc(unitStr(o.unit))) + '</td>' +
    '<td class="num">' + (o.unknown ? "????" : esc(money(o.unit, o.need))) +
    '</td>' +
    '<td' + (o.cls ? "" : ' class="dimtd"') + '>' +
    esc(o.cls ? offerLabel(o.cls) : "—") + '</td>' +
    '<td class="why">' + (o.why || "") +
    (o.action ? ' <button class="btn mini" data-act="' + o.action.act +
      '">' + o.action.label + "</button>" : "") +
    '</td></tr>';
}

function detailHtml(i) {
  const l = S.resolution.lines[i];
  const rl = S.requirements.lines[i];
  const state = lineState(i);
  const badge = STATE_BADGE[state]
    ? '<span class="badge ' + STATE_BADGE[state] + '">' +
      (state === "conf" ? "confirm" : state === "na" ? "unverified" : state) +
      '</span>' : "";
  // the schematic's own words — never the app's reading of them
  const title = designWords(i).join(" · ");
  let body;
  if (l.dnp) {
    body = isManualDnp(i)
      ? '<p class="sub">Marked DNP for this board run — excluded from the ' +
        "BOM and CPL. Cleared automatically after a clean export.</p>"
      : '<p class="sub">Marked DNP in the schematic — excluded from the ' +
        "BOM and CPL. Nothing to resolve.</p>";
  } else if (!rl.spec && (rl.providerRefs || rl.mpn)) {
    body = pinnedBody(i);
  } else {
    body = specBody(i);
  }
  // the search box is on EVERY part, always — hunting a better part is not a
  // thing you should have to be in trouble to do
  const search = l.dnp ? "" : searchHtml(i);
  return '<button class="crumb" data-line="-1">&#8592; design overview</button>' +
    '<h2 class="part-title"><span class="ref">' +
    esc(l.designators.join(" ")) + '</span><span class="spec">' + esc(title) +
    '</span>' + badge + titleActionsHtml(i) + '</h2>' +
    ackHtml(i) + body + search + placementHtml(i);
}

/* an unnamed part (no schematic VALUE, no MPN) resolved from memory — say so
   out loud and make them look, every design, before it can ship */
function ackHtml(i) {
  if (lineState(i) !== "conf") return "";
  const rl = S.requirements.lines[i];
  return '<p class="alert">The schematic doesn’t say what this part is — ' +
    'it’s mounting <b>' + esc(S.resolution.lines[i].ref || "") + '</b> ' +
    'because that’s what you approved for <span class="mono">' +
    esc(rl.footprint || "") + '</span> before. Check it, then press ' +
    '<b>Update</b> to confirm it for this design.</p>';
}

/* what the approved-parts database filed this requirement under. Bookkeeping,
   shown so it can be audited — never a form, never the title. */
function recordedHtml(i) {
  const rl = S.requirements.lines[i];
  if (!rl.spec) return "";
  const bits = [rl.spec.kind, rl.spec.value, rl.spec.package, rl.spec.qualifier]
    .filter(Boolean).map(esc).join(" · ");
  return '<p class="note">recorded as <span class="mono">' + bits +
    "</span> — search again and pick to change it</p>";
}

/* The schematic names an exact part. That is the DEFAULT, not a lock: tick this
   row and the ones you approve below, press Update, and the agent names the
   requirement — the pinned part becomes rank 1 of its own approved list, and a
   future run can substitute down it when this part goes short. Until you do
   that, the pin stands alone and a short part blocks the order. */
function pinnedBody(i) {
  const l = S.resolution.lines[i];
  const e = escFor(i);
  const rl = S.requirements.lines[i];
  const over = isOverridden(i);
  const schematicCode = (rl.providerRefs || {}).jlcpcb || "";
  const code = l.ref || (e && e.ref) || schematicCode;
  const row = partRow({
    radio: !!code, checked: effRadio(i) === code, code: code, mpn: l.mpn,
    maker: l.manufacturer,
    pkg: l.footprint, cls: l.offerClass,
    stock: l.liveStock, stockCls: e ? "short-num" : "ok-num",
    need: l.requiredQty, unit: l.unitPrice,
    // the schematic's own part can be approved onto the list it heads —
    // without this it could never be rank 1 of its own AVL
    check: code ? {show: true, on: effCheck(i, code)} : undefined,
    why: over ? "your pick — this order only"
      : schematicCode ? "schematic LCSC attribute"
      : "schematic MPN attribute “" + esc(rl.mpn || "") + "” only",
    action: over
      ? {act: "clearover", label: "undo — use the schematic part"}
      : null});
  let extra = "";
  if (e && schematicCode) {
    const lcscUrl = "https://www.lcsc.com/product-detail/" +
      encodeURIComponent(code) + ".html";
    extra = '<p class="alert">' + esc(e.reason) +
      ' — resolve this in Fusion; the schematic pins this exact part.' +
      ' <a href="' + lcscUrl + '" target="_blank" rel="noopener">' +
      esc(code) + " on LCSC</a></p>";
  } else if (e) {
    extra = '<p class="alert">the schematic gives only an MPN — JLC can’t ' +
      "verify by MPN. Add the LCSC attribute in Fusion, or pick a part " +
      "below for this order.</p>";
  }
  return '<div class="sect"><div class="tablewrap"><table>' + PART_TABLE_HEAD +
    row + "</table></div>" + extra + checksHtml(l) + "</div>";
}

/* ---- THE SEARCH BOX — one box, every part, type anything ------------------ */

/* What to put in the box before they touch it: what they last typed, else the
   words the app has for this part (the agent's reading, or the schematic's own
   text). Only a starting point — whatever ends up in the box is what gets
   read and searched. */
/* What goes in the box, in order of authority:
     1. what YOU typed — nothing outranks that;
     2. what the agent READ this part to be (the catalog's own answer, when the
        design pins a part number);
     3. the words behind its spec;
     4. last resort, the schematic's raw text — which is not searchable, and is
        the app admitting it never looked.
   The app's own seed is NEVER written back into (1). It used to be — the
   popup handler and the search button both saved the box's contents to the
   draft as if the engineer had typed them, so a raw "10uF@50V C-E-5" the app
   put there itself came back forever and outranked every reading after it. */
function seedFor(i) {
  if (i == null) return S.typed[""] || "";
  const rl = S.requirements.lines[i];
  const key = lineKey(rl);
  if (S.typed[key]) return S.typed[key];
  const read0 = S.readings[key];
  if (read0 && read0.search) return read0.search;
  const u = uninterpFor(i);
  const read = (u && u.guess && (u.guess.spec || u.guess.partial)) || null;
  // with no value to search on, the kind is what you'd type ("diode SOD-323")
  const bits = rl.spec
    ? [rl.spec.value || rl.spec.kind, rl.spec.package, rl.spec.qualifier]
    : read
      ? [read.value || rl.comment || read.kind,
         read.package || (u && u.judgedPackage), read.qualifier]
      : [rl.comment || rl.mpn, rl.footprint];
  return bits.filter(Boolean).join(" ");
}

/* the part type actually used — the popup shows it, so it is never a decision
   made behind your back. "auto" = let the agent read it off the design line. */
function catFor(i, key) {
  if (key in S.catPick) return S.catPick[key];
  const r = S.results[key];
  if (r && r.planned && r.planned.category) return r.planned.category;
  const read0 = S.readings[key];               // what the part was read to be
  if (read0 && read0.plan && read0.plan.category) return read0.plan.category;
  return "";                                   // auto
}

function catSelectHtml(i, key) {
  const cur = catFor(i, key);
  const opt = (v, label, sel) => '<option value="' + esc(v) + '"' +
    (sel ? " selected" : "") + ">" + esc(label) + "</option>";
  return '<select id="sf-cat" class="cat" aria-label="part type">' +
    opt("", i == null ? "— no part type —" : "auto — read it from the part",
        !cur) +
    opt("components", "— no part type —", cur === "components") +
    '<option disabled>──────────</option>' +
    S.categories.filter(c => c.slug !== "components")
      .map(c => opt(c.slug, c.slug.replace(/_/g, " ") + (c.empty ? " (empty)" : ""),
                    cur === c.slug)).join("") +
    "</select>";
}

/* Picking NO part type means the catalog is never narrowed to a table: your
   words are matched against part NAMES and nothing else. That is the right
   tool for a part number and the wrong one for "22k" — so say so, before the
   search runs, not after it disappoints. */
function noTypeHintHtml(i, key) {
  const cur = catFor(i, key);
  const none = cur === "components" || (i == null && !cur);
  if (!none) return "";
  return '<p class="alert">No part type — your words will be matched against ' +
    "part <b>names</b> only, so they have to be specific: a part number " +
    "(<span class=\"mono\">1N4148WS</span>), a series, a maker's name. A " +
    "value on its own (<span class=\"mono\">22k</span>) finds parts with " +
    "“22k” <i>in the name</i>, not 22k parts — pick a part type above for " +
    "that.</p>";
}

function searchHtml(i) {
  const key = i == null ? "" : lineKey(S.requirements.lines[i]);
  const busy = S.busySearch === key;
  // the agent is working out what this part is — say so IN the box, where the
  // answer is about to appear, not in a status line at the far edge of the page
  const reading = S.reading === key;
  const field = reading
    ? '<input id="sf-terms" class="grow working" value="" disabled ' +
      'placeholder="reading this part — asking the catalog what it is …" ' +
      'aria-label="reading this part">'
    : '<input id="sf-terms" class="grow" value="' + esc(seedFor(i)) +
      '" placeholder="22k 0603 1% · 10uF 0805 X7R 25V · 1N4148WS · C25804" ' +
      'aria-label="search in-stock parts">';
  const label = reading ? "Reading …" : busy ? "Searching …" : "Search";
  // ONE line: what kind of part · what you want · Search
  return '<div class="sect search"><p class="eyebrow">Search in-stock parts</p>' +
    '<div class="form">' + catSelectHtml(i, key) + field +
    '<button class="btn solid" id="terms-search" data-line="' +
    (i == null ? -1 : i) + '"' +
    (busy || reading ? ' aria-disabled="true"' : "") + ">" + label +
    "</button></div>" +
    noTypeHintHtml(i, key) + readingHtml(i, key) +
    // before you search, the terms the agent read off THIS part are already on
    // screen — the search is never a black box you fire and hope. After a
    // search, the results section carries the same panel, showing what it PROVED.
    (S.results[key] ? "" : queryHtml(i, key)) +
    (i == null ? "" : recordedHtml(i)) +
    "</div>" + resultsHtml(i, key);
}

/* what the agent read this part to BE, and where it got it — so a reading
   taken from the part's own catalog record is never mistaken for a guess at
   the schematic's words */
function readingHtml(i, key) {
  if (i == null) return "";
  if (S.reading === key) return "";   // the box itself is saying it
  if (!(key in S.readings)) return "";
  const r = S.readings[key];
  if (!r)
    return '<p class="note">couldn’t read this part — the agent isn’t ' +
      "available, so the box holds the schematic’s own words</p>";
  return '<p class="note">read as <b>' + esc(r.is) + "</b>" +
    (r.rationale ? " — " + esc(r.rationale) : "") + "</p>";
}

/* The terms that WILL be sent: the ones you staged, else the reading's own plan
   — the part's spec table, straight from the catalog. (This is LCSC's "show
   similar products" checkboxes, except every box here is one Python can PROVE.) */
function seedTerms(key) {
  if (S.seed[key]) return S.seed[key];
  const r = S.readings[key];
  return (r && r.plan && r.plan.sieve) || [];
}

/* The seeded terms speak for the words the AGENT read off this part. Retype the
   box and they no longer describe what you're asking — so they neither show nor
   fire, and the agent reads your words afresh. */
function seedApplies(key, text) {
  const r = S.readings[key];
  if (!r || !r.plan || !(r.plan.sieve || []).length) return false;
  const box = text !== undefined ? text
    : S.typed[key] !== undefined ? S.typed[key] : (r.search || "");
  return box.trim() === (r.search || "").trim();
}

/* The request a set of terms produces — rebuilt from the terms EXACTLY as the
   server rebuilds it, so what you read here is what gets sent. */
function requestFor(cat, terms, words) {
  if (!cat || cat === "components")
    return "components?search=" + esc(words);
  const params = [];
  Object.entries(NET_COL).forEach(([param, column]) => {
    const t = terms.find(x => x.op === "eq" && x.field === column);
    if (t) params.push(esc(param) + "=" + esc(String(t.value)));
  });
  return esc(cat) + "?" + params.join("&");
}

/* THE QUERY, laid out exactly as it was sent — or exactly as it is about to be
   — and every part of it yours to change. A search you can't see is a search you
   can't correct. */
function queryHtml(i, key) {
  const r = S.results[key];
  const seeded = !r && seedApplies(key);
  if ((!r || !r.planned) && !seeded) return "";
  const words = S.typed[key] !== undefined ? S.typed[key] : seedFor(i);
  const plan = r ? r.planned : S.readings[key].plan;
  const shown = r ? (r.proved || []) : seedTerms(key);
  const cat = r ? ((r.query || {}).category || "") : (plan.category || "");
  const req = r
    ? (r.query
        ? esc(r.query.category) + "?" + Object.entries(r.query.params || {})
            .map(([k, v]) => esc(k) + "=" + esc(v)).join("&")
        : plan.mode === "code"
          ? "the part number, looked up directly"
          : "nothing — no query was sent")
    : requestFor(cat, shown, words);
  const terms = shown.map((t, n) =>
    '<tr><td class="mono">' + esc(t.field) + "</td>" +
    '<td class="mono op">' + esc(OPS[t.op] || t.op) + "</td>" +
    '<td class="mono">' + esc(String(t.value)) + esc(t.unit || "") + "</td>" +
    '<td><button class="btn mini" data-drop="' + n + '">drop</button></td></tr>')
    .join("");
  const cols = (S.categories.find(c => c.slug === cat) || {}).columns || [];
  // the catalog's OWN parameter names — the vocabulary this part is published
  // in, and the only one that spans manufacturers (one datasheet says "Diameter",
  // the next says "φD"; the catalog says "Diameter" for both)
  const cr = (S.readings[key] || {}).catalog || {};
  const catalogCols = Object.keys(cr.parameters || {});
  return '<details class="query"' + (S.showQuery ? " open" : "") + ">" +
    "<summary>the actual search — change any of it</summary>" +
    '<p class="req">' + (r ? "asked" : "will ask") +
    ' the catalog for <span class="mono">' + req + "</span></p>" +
    (terms
      ? '<p class="note">' + (r ? "then proved every part against these"
                                : "then every part must be proven against these") +
        " — a part that fails one, or can’t be checked against it, is not a " +
        "result:</p>" +
        '<div class="tablewrap"><table class="terms">' + terms + "</table></div>"
      : '<p class="note">nothing further was demanded of the results</p>') +
    '<div class="form addterm">' +
    '<input id="qt-field" list="qt-cols" placeholder="field" class="mono">' +
    '<datalist id="qt-cols">' +
    catalogCols.concat(cols).map(c => "<option>" + esc(c) + "</option>").join("") +
    "</datalist>" +
    '<select id="qt-op">' + Object.entries(OPS).map(([k, v]) =>
      '<option value="' + esc(k) + '">' + esc(v) + "</option>").join("") +
    "</select>" +
    '<input id="qt-val" placeholder="value" class="mono">' +
    '<input id="qt-unit" placeholder="unit" class="mono unit">' +
    '<button class="btn mini" id="qt-add">add this term</button></div>' +
    '<p class="note">a catalog value is text ("50V") — give the unit and “' +
    esc(OPS.gte) + ' 50 V” compares; leave it off and only “=” can.</p>' +
    "</details>";
}

const OPS = {eq: "=", ne: "≠", lte: "≤", gte: "≥", lt: "<", gt: ">",
             contains: "contains", isTrue: "is true", isFalse: "is false"};

/* a query param and the column that proves it (the index calls them different
   things: you ask for `capacitance`, the row publishes `capacitance_farads`) */
const NET_COL = {package: "package", resistance: "resistance",
                 capacitance: "capacitance_farads"};

/* THE COMPARISON TABLE.

   Every part the query found, in ONE table, with its ACTUAL values under the
   criteria you searched on. This is how a part gets picked: you read down a
   column. A part that fails a term keeps its row and all its numbers — only the
   cell that failed goes red — because "35V" in a column you can scan beats a
   sentence saying "is 35, not ≥ 50V" at the far right of a row, and it beats
   opening fifty datasheets one at a time. */

function allRows(r) {
  return (r.candidates || []).concat(r.misses || []);
}

/* The columns worth comparing: the terms the CATALOG names. `package` and
   `capacitance_farads` are how the QUERY was built, not what you judge a part
   on — they are already on screen, in "the actual search". */
function specCols(r) {
  const rows = allRows(r);
  return (r.proved || []).filter(t => rows.some(
    row => (row.proof || []).some(p => p.field === t.field && p.catalog)));
}

/* Everything else the catalog publishes for these parts — ripple current, ESR,
   lifetime. Not searched on, but often what decides it. */
function extraCols(r, criteria) {
  const named = new Set(criteria.map(t => t.field));
  const out = [];
  for (const row of allRows(r))
    for (const p of (row.parameters || []))
      if (!named.has(p.parameterName) && out.indexOf(p.parameterName) < 0)
        out.push(p.parameterName);
  return out;
}

/* The codes the panel ALREADY lists above the search results — the mounted part
   and its approved list.

   The radio group is one per line, because only one part can mount. So a code
   must never emit a SECOND radio: a browser keeps only the LAST checked input in
   a group, and the duplicate down here would silently steal the selection from
   the row above it — which is exactly why the top table's radio kept going blank.
   Down here that part shows its RANK instead. Its checkbox stays live, so you can
   still prune it from the list from either table. */
function shownAbove(i) {
  const out = new Map();
  if (i == null) return out;
  const l = S.resolution.lines[i];
  const rl = S.requirements.lines[i];
  const house = rl.spec ? S.avlCache[JSON.stringify(rl.spec)] : null;
  for (const c of ((house && house.choices) || []))
    if (c.lcscCode) out.set(c.lcscCode, "alternate");
  const e = escFor(i);
  for (const c of ((e && e.choices) || []))
    if (c.ref) out.set(c.ref, "alternate");
  const pinned = (rl.providerRefs || {}).jlcpcb;
  if (pinned && !out.has(pinned)) out.set(pinned, "schematic");
  // The order of the approved list is bookkeeping — the engineer never asked for
  // a numbered list, they asked for alternates. So a part is either the one they
  // CHOSE (the radio above says so) or one of its alternates. Nothing is numbered
  // at them.
  if (l.ref) out.set(l.ref, "chosen");
  return out;
}

function proofOf(c) {
  const m = {};
  for (const p of (c.proof || [])) m[p.field] = p;
  return m;
}
function paramsOf(c) {
  const m = {};
  for (const p of (c.parameters || [])) m[p.parameterName] = p.parameterValue;
  return m;
}
function cellOf(c, field) {
  const p = proofOf(c)[field];
  if (p) return {text: p.shown, bad: !p.ok, why: p.why || ""};
  const v = paramsOf(c)[field];
  return {text: v === undefined ? "—" : v, bad: false, why: ""};
}

const SORT_VAL = {
  stock: c => c.liveStock || 0,
  price: c => (c.unitPrice1 == null ? Infinity : c.unitPrice1),
  class: c => c.libraryType || "",
};

/* the headers actually sort now — a column you can't order is a column you
   can't pick from */
function sortRows(rows) {
  const k = S.altSort.key;
  if (!k) return rows;
  const get = SORT_VAL[k] || (c => {
    const raw = cellOf(c, k).text;
    const n = parseFloat(raw);
    return isNaN(n) ? String(raw) : n;
  });
  return rows.slice().sort((a, b) => {
    const x = get(a), y = get(b);
    if (x < y) return -S.altSort.dir;
    if (x > y) return S.altSort.dir;
    return 0;
  });
}

function compareHead(criteria, extras) {
  const h = (label, key, num) => {
    const active = S.altSort.key === key;
    const arrow = active ? (S.altSort.dir === 1 ? " ▲" : " ▼") : "";
    return "<th" + (num ? ' class="num"' : "") +
      '><button class="th-sort" data-sortkey="' + esc(key) + '">' +
      esc(label) + arrow + "</button></th>";
  };
  // the header IS the criterion: "Voltage Rating ≥ 50V"
  const crit = t => t.field + " " + (OPS[t.op] || t.op) +
    (t.value === undefined ? "" : " " + String(t.value) + (t.unit || ""));
  return "<tr><th></th><th>alt</th><th>lcsc</th><th>manufacturer</th>" +
    "<th>mpn</th><th>package</th>" +
    criteria.map(t => h(crit(t), t.field, false)).join("") +
    extras.map(f => h(f, f, false)).join("") +
    h("live stock", "stock", true) + '<th class="num">need</th>' +
    h("unit $", "price", true) + '<th class="num">order $</th>' +
    h("class", "class", false) + "</tr>";
}

function compareRow(i, c, criteria, extras, need, above) {
  const cover = (c.liveStock || 0) >= need;
  const bad = (c.failed || []).length > 0;
  const mine = i != null && effRadio(i) === c.code;
  const listed = above.get(c.code);
  // EVERY row is pickable, rejects included: you are the engineer, and 35 V may
  // be fine on your rail. The cell says what it fails; picking it says so too,
  // and the requirement gets named from the part you ACTUALLY picked.
  const flag = bad ? ' data-bad="1"' : "";
  const radio = listed
    ? '<span class="listed" title="already on the approved list above — choose ' +
      'it there">' + esc(listed) + "</span>"
    : '<input type="radio" name="pick"' + (mine ? " checked" : "") +
      ' data-stage="' + esc(c.code) + '"' + flag +
      ' aria-label="mount ' + esc(c.code) + '">';
  const check = i == null ? "" :
    '<input type="checkbox" data-check="' + esc(c.code) + '"' +
    (effCheck(i, c.code) ? " checked" : "") + flag +
    ' aria-label="approve ' + esc(c.code) + ' as an alternate">';
  const td = field => {
    const cell = cellOf(c, field);
    return '<td class="mono' + (cell.bad ? " bad" : "") + '"' +
      (cell.why ? ' title="' + esc(cell.why) + '"' : "") + ">" +
      esc(cell.text) + "</td>";
  };
  return '<tr class="' + (mine ? "picked " : "") + (listed ? "onlist " : "") +
    (bad ? "reject" : "") + '">' +
    '<td class="pick">' + radio + "</td>" +
    '<td class="pick">' + check + "</td>" +
    "<td>" + lcscLink(c.code) + "</td>" +
    "<td>" + esc(c.manufacturer || "—") + "</td>" +
    '<td class="mono">' + esc(c.model || "") + "</td>" +
    '<td class="mono">' + esc(c.package || "—") + "</td>" +
    criteria.map(t => td(t.field)).join("") +
    extras.map(f => td(f)).join("") +
    '<td class="num ' + (cover ? "ok-num" : "short-num") + '">' +
    fmt(c.liveStock) + "</td>" +
    '<td class="num">' + fmt(need) + "</td>" +
    '<td class="num">' + esc(unitStr(c.unitPrice1)) + "</td>" +
    '<td class="num">' + esc(money(c.unitPrice1, need)) + "</td>" +
    "<td>" + esc(c.libraryType ? offerLabel(c.libraryType) : "—") + "</td>" +
    "</tr>";
}

function resultsHtml(i, key) {
  const r = S.results[key];
  if (!r) return "";
  const need = i == null ? 1 : S.resolution.lines[i].requiredQty;
  const criteria = specCols(r);
  const others = extraCols(r, criteria);
  const extras = S.showSpecs ? others : [];
  const hits = r.candidates || [];
  const rejects = r.misses || [];
  // matched parts first — then the rejects, still sorted, still comparable
  const rows = sortRows(hits).concat(sortRows(rejects));

  const say = '<p class="say">' + esc(r.planned.say || r.terms) +
    ' <span class="count">' + r.scanned + " looked at · " + hits.length +
    " matched · " + rejects.length + " rejected" +
    (r.truncated ? " · the index stops at the 100 best-stocked — narrow it "
                 + "down if what you want isn’t here" : "") + "</span></p>" +
    queryHtml(i, key);

  if (!rows.length)
    return say + '<p class="alert">the query came back empty — nothing in the ' +
      "catalog matched even the request. Loosen a term, or change the part " +
      "type, and search again.</p>";

  const toggle = others.length
    ? ' <button class="btn mini" id="show-specs">' +
      (S.showSpecs ? "hide the other specs" : "show all " + others.length +
       " specs") + "</button>"
    : "";
  const lead = hits.length
    ? "read down a column to compare; a red cell is the one thing that part " +
      "fails, and you can still pick it. Ticking a box saves it — there is " +
      "nothing to press."
    : "nothing passed every term — but every part is here with its numbers, so " +
      "you can see what to loosen (or take one anyway).";

  const above = shownAbove(i);
  return say + '<div class="sect"><p class="note">' + lead + toggle + "</p>" +
    '<div class="tablewrap"><table class="results">' +
    compareHead(criteria, extras) +
    rows.map(c => compareRow(i, c, criteria, extras, need, above)).join("") +
    "</table></div></div>";
}

/* a spec line: the single list — your part(s) first, then search results */
function specBody(i) {
  const l = S.resolution.lines[i];
  const rl = S.requirements.lines[i];
  const e = escFor(i);
  const q = queueFor(i);
  const need = l.requiredQty;
  if (!e) {
    // green: the mounted pick + the rest of the approved list, with the
    // provenance of the pick and its undo in plain words
    const key = rl.spec ? JSON.stringify(rl.spec) : null;
    const house = (key && S.avlCache[key]) || null;
    const choices = (house && house.choices) || [];
    const mine = choices.find(c => c.lcscCode === l.ref) || {};
    const over = isOverridden(i);
    let rows = partRow({
      radio: true, checked: effRadio(i) === l.ref, code: l.ref, mpn: l.mpn,
      maker: l.manufacturer,
      pkg: (l.spec && l.spec.package) || (rl.spec && rl.spec.package) ||
           l.footprint,
      cls: l.offerClass,
      stock: l.liveStock, stockCls: "ok-num",
      need: need, unit: l.unitPrice,
      check: {show: !!mine.rank, on: effCheck(i, l.ref)},
      why: over ? "your pick — this order only"
        : l.substitution ? "substituted — preferred part is short"
        : esc(mine.note || (mine.rank ? "your approved part" : "")),
      action: over
        ? {act: "clearover", label: "undo — use the automatic pick"}
        : null});
    rows += choices
      .filter(c => c.lcscCode && c.lcscCode !== l.ref)
      .map(c => {
        const stock = c.lastStock;
        const canPick = !c.stockUnknown && (stock || 0) >= need;
        return partRow({
          radio: canPick, checked: effRadio(i) === c.lcscCode,
          code: c.lcscCode, mpn: c.mpn,
          maker: c.manufacturer, pkg: rl.spec ? rl.spec.package : null,
          check: {show: true, on: effCheck(i, c.lcscCode)},
          unknown: c.stockUnknown,
          stock: stock, stockCls: canPick ? "" : "short-num",
          need: need, unit: c.lastPrice, why: ""});
      }).join("");
    return '<div class="sect"><div class="tablewrap"><table>' +
      PART_TABLE_HEAD + rows + "</table></div>" + checksHtml(l) + "</div>";
  }
  // red: approved-but-short rows first (no radio), then verified alternates;
  // maker/price for the short rows come from the AVL cache once fetched
  const house = rl.spec ? S.avlCache[JSON.stringify(rl.spec)] : null;
  const avlInfo = code =>
    ((house && house.choices) || []).find(c => c.lcscCode === code) || {};
  const avlRows = (e.choices || []).map(c => {
    const x = avlInfo(c.ref);
    return partRow({
      radio: false, code: c.ref, mpn: c.mpn || x.mpn, maker: x.manufacturer,
      pkg: rl.spec ? rl.spec.package : null,
      check: {show: !!c.ref, on: effCheck(i, c.ref)},
      stock: c.liveStock, stockCls: "short-num", need: need,
      unit: x.stockUnknown ? null : x.lastPrice, why: "your part"});
  });
  // everything else — the app's own lookups and your searches alike — lands
  // in the one results table below the search box
  const empty = !avlRows.length
    ? '<p class="alert">' + esc(e.reason === "no-part-choices"
        ? "no approved part for this yet — search below and pick one"
        : e.reason) + "</p>"
    : "";
  return '<div class="sect">' +
    (avlRows.length ? '<div class="tablewrap"><table>' + PART_TABLE_HEAD +
      avlRows.join("") + "</table></div>" : "") +
    empty + checksHtml(l) + "</div>";
}

/* the acknowledgement: staged selections write to the database (or the
   order draft) only when this button is pressed */
/* Picks and approvals SAVE THEMSELVES — tick a box and it is recorded, in the
   list you ticked it in. So the only thing left for a button is the one act
   that is not a selection at all: confirming an UNNAMED part, where looking at
   it IS the act. Nothing else needs pressing, so nothing else is offered. */
function updateBtnHtml(i) {
  if (lineState(i) !== "conf") return "";
  return '<button class="btn solid mini" id="update-btn" data-line="' + i +
    '" title="this part has no value and no part number — confirm you have ' +
    'looked at what it will mount">I’ve looked at this</button>';
}

/* the title-line actions: search alternates + Update, right side */
function titleActionsHtml(i) {
  const l = S.resolution.lines[i];
  const rl = S.requirements.lines[i];
  if (l.dnp)   // schematic DNP is Fusion's call; manual DNP restores in place
    return isManualDnp(i)
      ? '<span class="title-actions"><button class="btn mini" ' +
        'id="populate-btn">Populate this run</button></span>'
      : "";
  const dnpBtn = '<button class="btn mini" id="dnp-btn">DNP this run</button>';
  return '<span class="title-actions">' +
    updateBtnHtml(i) + dnpBtn + "</span>";
}

function offerLabel(v) {
  if (!v) return "—";
  const t = String(v).toLowerCase();
  return t === "expand" || t === "extended" ? "Extended"
    : t === "base" || t === "basic" ? "Basic" : String(v);
}


/* rotation / placement — JLCPCB CPL only */
function placementHtml(i) {
  const l = S.resolution.lines[i];
  if (l.dnp || provider() !== "jlcpcb" || !S.placements) return "";
  const p = (S.placements || []).find(
    pl => l.designators.includes(pl.designator));
  if (!p) return "";
  const c = S.rotations.find(r =>
    (r.lcsc && l.ref && r.lcsc === l.ref) ||
    (r.footprint && r.footprint === p.footprint));
  const off = c ? (c.rotationOffsetDeg || 0) : 0;
  const ships = ((Number(p.angle) || 0) + off) % 360;
  const opts = [0, 90, 180, 270].map(d =>
    '<option value="' + d + '"' + (d === off ? " selected" : "") + '>' +
    (d ? "+" + d + "° CCW" : "0°") + "</option>").join("");
  return '<div class="sect"><p class="eyebrow">Placement (CPL)</p>' +
    '<div class="place">' +
    '<span><b>x</b>' + esc(p.x) + '</span><span><b>y</b>' + esc(p.y) +
    '</span><span><b>board angle</b>' + esc(p.angle) + "°</span>" +
    '<span><b>correction</b><select id="rot-select" data-line="' + i +
    '" data-footprint="' + esc(p.footprint || "") + '">' + opts +
    "</select></span>" +
    '<span class="effective"><b>ships as</b>' + ships + "°</span></div>" +
    '<p class="note">Applies to footprint <span class="mono">' +
    esc(p.footprint || "?") + "</span> in every design.</p></div>";
}

/* ---- wiring + actions --------------------------------------------------------- */

function wireMain() {
  document.querySelectorAll("#main [data-line]").forEach(el => {
    if (el.classList.contains("crumb"))
      el.onclick = () => { S.selected = null; render(); };
    else if (el.classList.contains("linkrow"))
      el.onclick = () => select(parseInt(el.dataset.line, 10));
  });
  // radios and backup checkboxes STAGE; the Update button commits
  // Picking a part that FAILS a term is allowed — you are the engineer, and 35 V
  // may be fine on your rail. But it is never silent: you are told what it fails,
  // and Update names the requirement from the part you actually picked, so the
  // approved list records what you chose rather than what you searched for.
  const warnBad = (el, what) => {
    if (!el.dataset.bad || !el.checked) return;
    msg(what + " fails a term you searched for — see the red cell. It will be " +
        "recorded as what it IS, not as what you asked for.", "warn");
  };
  document.querySelectorAll('#main input[type=radio][data-stage]').forEach(r => {
    r.onchange = () => {
      stagedFor(S.selected).radio = r.dataset.stage;
      warnBad(r, r.dataset.stage);
      applyStaged(S.selected);       // the pick IS the act — it saves itself
    };
  });
  document.querySelectorAll('#main input[type=checkbox][data-check]').forEach(cb => {
    cb.onchange = () => {
      stagedFor(S.selected).checks[cb.dataset.check] = cb.checked;
      warnBad(cb, cb.dataset.check);
      applyStaged(S.selected);       // approving and pruning save themselves too
    };
  });
  const specs = $("show-specs");
  if (specs) specs.onclick = () => { S.showSpecs = !S.showSpecs; render(); };
  const upd = $("update-btn");
  if (upd) upd.onclick = () => applyStaged(parseInt(upd.dataset.line, 10), true);
  const terms = $("terms-search");
  if (terms) {
    const n = parseInt(terms.dataset.line, 10);
    const line = n < 0 ? null : n;
    const fire = () => {
      if (terms.getAttribute("aria-disabled") === "true") return;
      doSearch(line);
    };
    terms.onclick = fire;
    const key = line == null ? "" : lineKey(S.requirements.lines[line]);
    const input = $("sf-terms");
    if (input) {
      input.onkeydown = ev => { if (ev.key === "Enter") fire(); };
      // ONLY your own keystrokes count as yours
      input.oninput = () => { S.typed[key] = input.value; };
    }
    // choosing a part type says so at once (picking NO type changes what a
    // search can even do) — and never eats what you've already typed
    const cat = $("sf-cat");
    if (cat) cat.onchange = () => {
      S.catPick[key] = cat.value;
      render();
    };
    // the query panel: drop a term, add a term — fired exactly as edited
    const q = document.querySelector("#main details.query");
    if (q) q.ontoggle = () => { S.showQuery = q.open; };
    // the terms on screen: what a search PROVED, or — before you've searched —
    // what it WILL prove. Editing either is the same gesture; the difference is
    // that one re-fires and the other just waits for you to press Search.
    const shown = S.results[key] ? ((S.results[key] || {}).proved || [])
                                 : seedTerms(key);
    const restage = next => {
      if (S.results[key]) { rerun(line, next); return; }
      S.seed[key] = next;
      S.showQuery = true;
      render();
    };
    document.querySelectorAll("#main [data-drop]").forEach(btn => {
      btn.onclick = () => restage(
        shown.filter((_, n2) => n2 !== parseInt(btn.dataset.drop, 10)));
    });
    const add = $("qt-add");
    if (add) add.onclick = () => {
      const f = $("qt-field").value.trim();
      if (!f) { msg("name a field to test — the list shows what this part " +
                    "type publishes", "warn"); return; }
      const raw = $("qt-val").value.trim();
      const num = raw !== "" && !isNaN(Number(raw));
      const term = {field: f, op: $("qt-op").value,
                    value: num ? Number(raw) : raw};
      const unit = $("qt-unit") ? $("qt-unit").value.trim() : "";
      if (unit) term.unit = unit;   // "50V" is text: the unit is what compares it
      restage(shown.concat([term]));
    };
  }
  const rot = $("rot-select");
  if (rot) rot.onchange = () =>
    setRotation(parseInt(rot.dataset.line, 10), rot.dataset.footprint, rot.value);
  const card = $("export-card");
  if (card) card.onclick = () => { S.exportResult = null; render(); };
  const un = document.querySelector("#main details.unconf");
  if (un) un.ontoggle = () => { S.showUnconfirmed = un.open; };
  document.querySelectorAll("#main .th-sort").forEach(btn => {
    btn.onclick = () => {
      const key = btn.dataset.sortkey;
      if (S.altSort.key === key) S.altSort.dir = -S.altSort.dir;
      else S.altSort = {key: key, dir: key === "stock" ? -1 : 1};
      render();
    };
  });
  document.querySelectorAll("#main [data-act]").forEach(btn => {
    btn.onclick = () => clearOverride(S.selected);
  });
  const dnp = $("dnp-btn");
  if (dnp) dnp.onclick = () => {
    S.manualDnp[lineKey(S.requirements.lines[S.selected])] = true;
    run("re-resolving", resolveNow);
  };
  const pop = $("populate-btn");
  if (pop) pop.onclick = () => {
    delete S.manualDnp[lineKey(S.requirements.lines[S.selected])];
    run("re-resolving", resolveNow);
  };
  if (S.selected != null) { ensureReading(S.selected); ensureAvl(S.selected); }
}

/* OPENING A PART READS IT. Every part, every time — pinned, spec, unnamed
   alike; the old code read some lines and not others, and the ones it skipped
   (the ones the schematic pinned, which carry a part number and are therefore
   the BEST known parts in the design) fell back to showing you raw schematic
   text in the search box. The agent gets everything: the schematic's words,
   this shop's designator conventions, and — when a part number is pinned or
   mounted — that part's own record from the live catalog. Judged once, cached
   forever. */
async function ensureReading(i) {
  const rl = S.requirements.lines[i];
  const l = S.resolution.lines[i];
  if (!rl || l.dnp) return;
  const key = lineKey(rl);
  if (key in S.readings || S.reading === key) return;
  S.reading = key;
  render();   // say it AT ONCE — the guard above stops this recursing
  msg("reading this part …");
  try {
    const d = await api("/api/read", {
      lineIndex: i, requirements: S.requirements,
      // the pinned part number, else whatever is mounted — either one lets
      // the catalog answer instead of the agent guessing
      code: (rl.providerRefs || {}).jlcpcb || l.ref || undefined});
    S.readings[key] = d.reading;      // null = the agent couldn't be reached
    if (d.reading) msg("read: " + d.reading.is, "ok");
    else msg("");
  } catch (e) {
    S.readings[key] = null;
    msg("");
  } finally {
    S.reading = null;
  }
  if (S.selected === i) render();
}

/* any spec line's panel: fetch the approved list once (provenance, makers,
   backups), then re-render with the cache warm */
async function ensureAvl(i) {
  const rl = S.requirements.lines[i];
  if (!rl || !rl.spec) return;
  const key = JSON.stringify(rl.spec);
  if (key in S.avlCache) return;
  try {
    // verify=1: the panel shows CURRENT stock for every choice, not the
    // advisory cache
    S.avlCache[key] = (await api(
      "/api/part?" + specQS(rl.spec) + "&verify=1")).housePart;
  }
  catch (e) { S.avlCache[key] = null; return; }
  if (S.selected === i) render();
}

/* THE search. Whatever is in the box is what gets read: the agent turns the
   words into a query, and every part that comes back has been proven against
   every term (the ones that failed come back too, with the reason).
   `override` carries an edited query (a category you chose, terms you dropped
   or added) — when it does, it is fired EXACTLY as given: your query outranks
   the agent's, always. */
async function doSearch(i, override) { await run("searching", async () => {
  const t = $("sf-terms").value.trim();
  if (!t) throw new Error("type what you want, then Search");
  const key = i == null ? "" : lineKey(S.requirements.lines[i]);
  const cat = $("sf-cat") ? $("sf-cat").value : "";
  // The terms shown ARE the search. If they still speak for what's in the box,
  // fire them exactly as they stand — no second judgment call, and no chance of
  // the agent quietly answering a question different from the one on screen.
  let extra = override;
  if (!extra && !S.results[key] && seedApplies(key, t))
    extra = {category: cat || S.readings[key].plan.category,
             sieve: seedTerms(key)};
  S.catPick[key] = cat;
  S.typed[key] = t;          // you fired these words: the box keeps them
  S.busySearch = key;
  render();
  try {
    if (i != null) { S.searches[key] = t; saveDraft(); }
    S.results[key] = await api("/api/search", {
      terms: t, lineIndex: i == null ? undefined : i,
      requirements: S.requirements,
      category: cat || undefined,
      ...(extra || {})});
  } finally {
    S.busySearch = null;
  }
  render();
  const r = S.results[key];
  const n = (r.candidates || []).length;
  msg(n ? n + " part(s) matched — pick one"
        : "nothing matched every term — see what was rejected, below",
      n ? "ok" : "warn");
}); }

/* re-fire the SAME query with the terms edited — no judgment call, no agent:
   exactly what you asked for */
/* the edited terms ARE the query now — the server rebuilds the request from
   them, so a term you drop is really gone (it can't sneak back in as a query
   param) */
function rerun(i, sieve) {
  const key = i == null ? "" : lineKey(S.requirements.lines[i]);
  const r = S.results[key];
  if (!r || !r.query) return;
  S.showQuery = true;
  S.catPick[key] = r.query.category;
  doSearch(i, {category: r.query.category, sieve: sieve, say: r.planned.say});
}

/* undo an order-only pick: the resolver's own choice comes back */
async function clearOverride(i) { await run("undoing pick", async () => {
  delete S.overrides[lineKey(S.requirements.lines[i])];
  await resolveNow();
  msg("back to the automatic pick", "ok");
}); }

function candFor(i, code) {
  const q = queueFor(i);
  const key = lineKey(S.requirements.lines[i]);
  const r = S.results[key] || {};
  const pool = [].concat(
    q ? q.candidates || [] : [], q ? q.fitUnconfirmed || [] : [],
    r.candidates || [], r.misses || []);
  return pool.find(x => x.code === code) || null;
}
function modelFor(i, code) {
  const c = candFor(i, code);
  return c ? c.model : null;
}

/* SAVE THE SELECTION YOU JUST MADE. Fires on the tick itself, not on a button:
   first pick -> rank 1; a checked part joins the approved list; an unchecked one
   is pruned from it (audited); an overriding radio pins this order only.

   ``ack`` is the OTHER act — confirming an unnamed part — and it is deliberate,
   so it never rides along on a checkbox. */
async function applyStaged(i, ack) { await run("saving", async () => {
  const rl = S.requirements.lines[i];
  const key = lineKey(rl);
  const st = S.staged[key];
  if (ack && (!st || !stagedDirty(i))) {
    S.acks[key] = true;
    saveDraft();
    render();
    msg("confirmed for this design", "ok");
    return;
  }
  if (!st || !stagedDirty(i)) return;
  const e = escFor(i);
  // The AGENT names the requirement — from this design line, the words you
  // searched, and the part you picked. You never fill in database fields.
  // It re-names when your search says something new about a part the
  // schematic never named ("1n4148ws" / "zener 10V" is what it IS); picking
  // an already-approved part never re-names anything.
  const found = (S.results[key] || {}).candidates || [];
  const fromSearch = !!st.radio && found.some(c => c.code === st.radio);
  // What MOUNTS: the part you picked, else the one already mounted. On a line
  // the schematic pinned, that is the schematic's own part — so approving an
  // alternate is enough to bring the requirement into being, with the pinned
  // part at the head of it. Without this, ticking alternates on a pinned line
  // was silently dropped and the approved list could never be built at all.
  const pick = st.radio || committedRadio(i);
  const approving = Object.keys(st.checks).some(c => st.checks[c]);
  const needsKey = rl.spec
    ? (!!st.radio && unnamed(i) && fromSearch)
    : (!!pick && (!!st.radio || approving));
  let rekeyed = false;
  if (needsKey) {
    msg("naming this requirement …");
    const named = await api("/api/key", {
      lineIndex: i, requirements: S.requirements,
      terms: S.typed[key] || S.searches[key] || "",   // YOUR words, if any
      part: candFor(i, pick) || {code: pick}});
    rekeyed = JSON.stringify(named.spec) !== JSON.stringify(rl.spec);
    rl.spec = named.spec;
    delete rl.mpn; delete rl.manufacturer; delete rl.providerRefs;
    S.uninterpreted = S.uninterpreted.filter(x => x.lineIndex !== i);
  }
  // a fresh key has no approved list yet, so whatever mounts is its rank 1
  const firstPick = !!rl.spec && (rekeyed ||
    ((!e || e.reason === "no-part-choices") && !committedRadio(i)));
  const com = committedChecks(i);
  const approvals = [];
  let overrideSet = false;
  if (firstPick && pick) {
    approvals.push({spec: rl.spec, lcsc: pick,
      mpn: modelFor(i, pick) || undefined, rank: 1,
      design: S.design || undefined, note: "picked in the app"});
  } else if (st.radio && st.radio !== committedRadio(i)) {
    S.overrides[key] = {code: st.radio};
    overrideSet = true;
  }
  const removals = [];
  if (rl.spec) {
    // newly checked codes append in the current table order
    const q = queueFor(i);
    const r = S.results[key] || {};
    const ordered = [].concat(
      q ? (q.candidates || []).map(c => c.code) : [],
      (r.candidates || []).map(c => c.code),
      (r.misses || []).map(c => c.code),   // you may deliberately take a reject
      Object.keys(st.checks));
    const seen = new Set();
    for (const code of ordered) {
      if (seen.has(code)) continue;
      seen.add(code);
      if (!(code in st.checks) || st.checks[code] === com.has(code)) continue;
      if (st.checks[code]) {
        if (firstPick && code === pick) continue;      // rank 1 covers it
        approvals.push({spec: rl.spec, lcsc: code,
          mpn: modelFor(i, code) || undefined, rank: 999,  // clamps to end
          design: S.design || undefined,
          note: "approved alt in the app"});
      } else {
        removals.push(code);
      }
    }
  }
  if (approvals.length) await api("/api/approve", {approvals: approvals});
  for (const code of removals)
    await api("/api/remove", {spec: rl.spec, ref: code,
                              note: code === committedRadio(i)
                                ? "removed in the app"
                                : "alt removed in the app"});
  if (rl.spec) delete S.avlCache[JSON.stringify(rl.spec)];
  // the selection is committed: nothing is "staged" any more, and the tables
  // must now read their state from the DB, not from a diff against it
  delete S.staged[key];
  await resolveNow();
  const done = [];
  if (approvals.length) done.push(approvals.length + " approved");
  if (removals.length) done.push(removals.length + " removed");
  if (overrideSet) done.push("pick applies to this order only");
  msg("saved — " + (done.join(" · ") || "updated"), "ok");
}); }

async function setRotation(i, footprint, deg) {
  await run("saving rotation", async () => {
    const l = S.resolution.lines[i];
    const d = await api("/api/rotation", {
      footprint: footprint || undefined, lcsc: l.ref || undefined,
      mpn: l.mpn || undefined, rotationOffsetDeg: parseInt(deg, 10)});
    S.rotations = d.corrections;
    render();
    msg("rotation saved — applies to every export from now on", "ok");
  });
}

async function doExport() {
  const b = $("export-btn");
  if (b.getAttribute("aria-disabled") === "true") return;
  // the directory dialog must open inside the click gesture (Chrome/Edge);
  // browsers without the API fall back to the server's output directory
  let dir = null;
  if (window.showDirectoryPicker) {
    try { dir = await window.showDirectoryPicker({mode: "readwrite"}); }
    catch (e) { msg("export canceled", "warn"); return; }
  }
  await run("exporting", async () => {
    const d = await api("/api/emit", {
      resolution: S.resolution, provider: provider()});
    d.savedTo = null;
    if (dir && d.readyToUpload && d.fileContents) {
      for (const [name, text] of Object.entries(d.fileContents)) {
        const fh = await dir.getFileHandle(name, {create: true});
        const w = await fh.createWritable();
        await w.write(text);
        await w.close();
      }
      d.savedTo = dir.name;
    }
    S.exportResult = d;
    S.selected = null;
    render();
    msg(d.readyToUpload
        ? "order files written" + (d.savedTo ? " to " + d.savedTo : "")
        : "blocked — do not upload",
        d.readyToUpload ? "ok" : "err");
  });
}

/* ---- top-level wiring ------------------------------------------------------------ */

$("refresh-btn").onclick = refresh;
$("export-btn").onclick = doExport;
$("provider").onchange = () => {
  if (S.requirements) run("re-resolving", resolveNow);
};
$("qty").onchange = () => {
  if (S.requirements) run("re-resolving", resolveNow);
};
// the catalog's own tables, for the part-type popup — no magic words to guess
api("/api/categories").then(d => { S.categories = d.categories; render(); })
  .catch(() => {});
loadCache();
</script>
</body>
</html>
"""
