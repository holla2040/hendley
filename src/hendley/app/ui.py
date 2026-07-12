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
details.unconf > summary { cursor:pointer; color:var(--tin);
  font:12px var(--mono); }
details.unconf > summary:hover { color:var(--pad); }
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
  exploring: {},       // lineKey -> the pinned part's explore panel is open
  exploreResults: {},  // lineKey -> live-verified explore candidates (session)
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
function specStr(spec) {
  if (!spec) return "";
  return [spec.kind, spec.value, spec.package, spec.qualifier]
    .filter(Boolean).join(" · ");
}
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
  S.exploring = {};
  S.exploreResults = {};
  S.staged = {};
  if (d.draft) {
    if (d.draft.productionQuantity) $("qty").value = d.draft.productionQuantity;
    const valid = new Set(S.requirements.lines.map(lineKey));
    for (const [k, v] of Object.entries(d.draft.overrides || {}))
      if (valid.has(k)) S.overrides[k] = v;   // stale picks drop silently
    for (const [k, v] of Object.entries(d.draft.searches || {}))
      if (valid.has(k)) S.searches[k] = v;
  }
  try { S.rotations = (await api("/api/rotations")).corrections; }
  catch (e) { S.rotations = []; }
  await resolveNow();
}

async function refresh() {
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
}); }

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

async function resolveNow() {
  const searches = {};
  S.requirements.lines.forEach((ln, idx) => {
    const t = S.searches[lineKey(ln)];
    if (t) searches[idx] = t;
  });
  const data = await api("/api/resolve", {
    requirements: effectiveRequirements(),
    placements: S.placements, provider: provider(), searches: searches});
  S.resolution = data.resolution;
  S.queue = data.queue || null;
  S.altSort = {key: null, dir: -1};
  S.staged = {};   // committed state changed — staged diffs are stale
  render();
  saveDraft();
}

function saveDraft() {
  if (!S.design) return;
  api("/api/draft", {design: S.design, draft: {
    productionQuantity: qty(),
    overrides: S.overrides,
    searches: S.searches,
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
function lineState(i) {
  const l = S.resolution.lines[i];
  if (l.dnp) return "dnp";
  if (uninterpFor(i)) return "conf";
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

/* ---- staged selections (radio + backup checkboxes, saved on Update) -------- */

function stagedFor(i) {
  const key = lineKey(S.requirements.lines[i]);
  return S.staged[key] || (S.staged[key] = {radio: undefined, checks: {}});
}
function committedRadio(i) { return S.resolution.lines[i].ref || null; }
function committedChecks(i) {
  // codes on the spec's approved list, minus the mounted part (rank 1
  // isn't a "backup")
  const rl = S.requirements.lines[i];
  const house = rl.spec ? S.avlCache[JSON.stringify(rl.spec)] : null;
  const mounted = committedRadio(i);
  return new Set(((house && house.choices) || [])
    .map(c => c.lcscCode).filter(c => c && c !== mounted));
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
  if (state === "dnp") return "DNP";
  if (state === "conf") return "search";
  if (state === "na") return "unverified";
  if (state === "short") return "short";
  let tail = "✓";
  if (isOverridden(i)) tail += " alt";
  else if (l.substitution) tail += " sub";
  return tail;
}

function railDesc(l) {
  const bits = [];
  if (l.comment) bits.push(l.comment);
  else if (l.mpn) bits.push(l.mpn);
  if (l.spec && l.spec.package) bits.push(l.spec.package);
  else if (l.footprint) bits.push(l.footprint);
  return bits.join(" · ");
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
      '<span class="desc">' + esc(railDesc(l)) + '</span></span>' +
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
  const ready = !!S.resolution &&
    (S.resolution.escalations || []).length === 0 &&
    S.uninterpreted.length === 0;
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
    '</table></div></div>';
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

/* the alternates table: stock, price, and class headers sort the candidates */
function sortableHead() {
  const h = (label, key, num) => {
    const active = S.altSort.key === key;
    const arrow = active ? (S.altSort.dir === 1 ? " ▲" : " ▼") : "";
    return '<th' + (num ? ' class="num"' : "") +
      '><button class="th-sort" data-sortkey="' + key +
      '">' + label + arrow + "</button></th>";
  };
  return '<tr><th></th><th>alt</th><th>lcsc</th><th>manufacturer</th>' +
    '<th>mpn</th><th>package</th>' +
    h("live stock", "stock", true) + '<th class="num">need</th>' +
    h("unit $", "price", true) + '<th class="num">order $</th>' +
    h("class", "class", false) + '<th>why</th></tr>';
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
  const lcsc = o.code
    ? '<a href="https://www.lcsc.com/product-detail/' +
      encodeURIComponent(o.code) + '.html" target="_blank" rel="noopener">' +
      '<code>' + esc(o.code) + '</code></a>'
    : '<code>—</code>';
  return '<tr' + (o.checked ? ' class="picked"' : "") + '>' +
    '<td class="pick">' + radio + '</td>' +
    '<td class="pick">' + check + '</td>' +
    '<td>' + lcsc + '</td>' +
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
      (state === "conf" ? "search" : state === "na" ? "unverified" : state) +
      '</span>' : "";
  const title = l.spec ? specStr(l.spec)
    : (l.comment || l.mpn || "") +
      (l.footprint ? " on " + l.footprint : "");
  let body;
  if (l.dnp) {
    body = '<p class="sub">Marked DNP in the schematic — excluded from the ' +
      "BOM and CPL. Nothing to resolve.</p>";
  } else if (state === "conf") {
    body = confBody(i);
  } else if (!rl.spec && (rl.providerRefs || rl.mpn)) {
    body = pinnedBody(i);
  } else {
    body = specBody(i);
  }
  return '<button class="crumb" data-line="-1">&#8592; design overview</button>' +
    '<h2 class="part-title"><span class="ref">' +
    esc(l.designators.join(" ")) + '</span><span class="spec">' + esc(title) +
    '</span>' + badge + titleActionsHtml(i) + '</h2>' + body +
    placementHtml(i);
}

/* a line awaiting its one-time spec search */
function confBody(i) {
  const u = uninterpFor(i);
  const g = (u && u.guess && u.guess.spec) || {};
  const rationale = u && u.guess && u.guess.rationale
    ? '<p class="sub">' + esc(u.guess.rationale) + "</p>" : "";
  return rationale + specFormHtml(i, {
    kind: g.kind || "", value: g.value || (u ? u.value : ""),
    package: g.package || (u ? u.footprint : "") || "",
    qualifier: g.qualifier || ""}, null);
}

/* the schematic names an exact part; alternates are explored on demand and
   any pick is order-only (the schematic stays authoritative) */
function pinnedBody(i) {
  const l = S.resolution.lines[i];
  const e = escFor(i);
  const rl = S.requirements.lines[i];
  const key = lineKey(rl);
  const over = isOverridden(i);
  const schematicCode = (rl.providerRefs || {}).jlcpcb || "";
  const code = l.ref || (e && e.ref) || schematicCode;
  const row = partRow({
    radio: false, checked: !e, code: code, mpn: l.mpn, maker: l.manufacturer,
    pkg: l.footprint, cls: l.offerClass,
    stock: l.liveStock, stockCls: e ? "short-num" : "ok-num",
    need: l.requiredQty, unit: l.unitPrice,
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
  let exploreHtml = "";
  if (S.exploring[key]) {
    // seed is value only: library footprint names return zero FTS rows;
    // the package narrowing is the agent-judged filter, not the search
    const seed = S.searches[key] || l.comment || l.mpn || "";
    exploreHtml = '<div class="sect"><div class="form">' +
      '<label>search in-stock parts <input id="sf-explore" value="' +
      esc(seed) + '"></label>' +
      '<button class="btn solid" id="explore-search" data-line="' + i +
      '">Search</button></div></div>' + exploreResultsHtml(i, l);
  }
  return '<div class="sect"><div class="tablewrap"><table>' + PART_TABLE_HEAD +
    row + "</table></div>" + extra + checksHtml(l) + "</div>" + exploreHtml;
}

function exploreResultsHtml(i, l) {
  const rl = S.requirements.lines[i];
  const key = lineKey(rl);
  const r = S.exploreResults[key];
  if (!r) return "";
  const need = l.requiredQty;
  const all = r.candidates || [];
  const pkgOk = c => !r.package || (c.package || "") === r.package;
  const covers = c => (c.liveStock || 0) >= need;
  const exploreRow = (c, radio) => partRow({
    radio: radio, checked: effRadio(i) === c.code, code: c.code, mpn: c.model,
    maker: c.manufacturer, pkg: c.package, cls: c.libraryType,
    check: rl.spec ? {show: true, on: effCheck(i, c.code)} : undefined,
    stock: c.liveStock, stockCls: covers(c) ? "ok-num" : "short-num",
    need: need, unit: c.unitPrice1, why: ""});

  const main = all.filter(c => pkgOk(c) && covers(c));
  const otherPkg = all.filter(c => !pkgOk(c));           // pickable: aliases exist
  const short = all.filter(c => pkgOk(c) && !covers(c)); // never pickable

  const block = (list, summary, radio) => list.length
    ? '<details class="unconf"><summary>' + summary + "</summary>" +
      '<div class="tablewrap"><table>' + PART_TABLE_HEAD +
      list.map(c => exploreRow(c, radio)).join("") + "</table></div></details>"
    : "";
  const blocks =
    block(otherPkg, otherPkg.length + " other package" +
      (otherPkg.length === 1 ? "" : "s"), true) +
    block(short, short.length + " can’t cover " + need, false);
  const note = r.package
    ? '<p class="note">package ' + esc(r.package) + " only</p>" : "";

  if (!main.length) {
    const alert = all.length
      ? "search found " + all.length + " — " +
        [otherPkg.length ? otherPkg.length + " other packages" : "",
         short.length ? short.length + " can’t cover " + need : ""]
          .filter(Boolean).join(", ")
      : "search found nothing — adjust the terms and search again";
    return note + '<p class="alert">' + esc(alert) + "</p>" + blocks;
  }
  return note +
    '<div class="sect"><div class="tablewrap"><table>' + PART_TABLE_HEAD +
    main.map(c => exploreRow(c, true)).join("") + "</table></div></div>" +
    blocks;
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
      why: over ? "your pick — this order only"
        : l.substitution ? "substituted — preferred part is short"
        : esc(mine.note || (mine.rank ? "your approved part" : "")),
      action: over
        ? {act: "clearover", label: "undo — use the automatic pick"}
        : (mine.rank ? {act: "stopusing", label: "stop using this part"}
                     : null)});
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
    // the search stays reachable after picks are saved: search more
    // alternates any time, results committed by the same Update button
    const lk = lineKey(rl);
    let explore = "";
    if (S.exploring[lk]) {
      const seed = S.searches[lk] ||
        [rl.spec.qualifier, rl.spec.value].filter(Boolean).join(" ");
      explore = '<div class="sect"><div class="form">' +
        '<label>search in-stock parts <input id="sf-explore" value="' +
        esc(seed) + '"></label>' +
        '<button class="btn solid" id="explore-search" data-line="' + i +
        '">Search</button></div></div>' + exploreResultsHtml(i, l);
    }
    return '<div class="sect"><div class="tablewrap"><table>' +
      PART_TABLE_HEAD + rows + "</table></div>" + checksHtml(l) + "</div>" +
      explore;
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
  const firstPick = e.reason === "no-part-choices";
  const disc = (q && q.discovery) || {};
  const searchable = disc.needsSearch || disc.search != null;
  // only parts that can actually cover this order are offered
  const coversNeed = c => (c.liveStock || 0) >= need;
  const confirmed = (q ? [].concat(q.proposal || [], q.alsoFound || []) : [])
    .filter(coversNeed);
  const unconf = (q ? (q.fitUnconfirmed || []) : []).filter(coversNeed);
  if (S.altSort.key) {
    const dir = S.altSort.dir;
    const val = c => S.altSort.key === "stock" ? c.liveStock
      : S.altSort.key === "price" ? c.unitPrice1
      : (c.libraryType ? offerLabel(c.libraryType) : null);
    const cmp = (a, b) => {
      const av = val(a), bv = val(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;   // unknowns sort last either direction
      if (bv == null) return -1;
      if (typeof av === "string") return av.localeCompare(bv) * dir;
      return (av - bv) * dir;
    };
    confirmed.sort(cmp); unconf.sort(cmp);
  }
  const candRows = confirmed.map(c => partRow({
    radio: true, checked: effRadio(i) === c.code, code: c.code, mpn: c.model,
    maker: c.manufacturer, pkg: c.package, cls: c.libraryType,
    check: {show: true, on: effCheck(i, c.code)},
    stock: c.liveStock,
    stockCls: (c.liveStock || 0) >= need ? "ok-num" : "",
    need: need, unit: c.unitPrice1,
    why: candWhy(c)}));
  const unconfRows = unconf.map(c => partRow({
    radio: true, checked: effRadio(i) === c.code, code: c.code, mpn: c.model,
    maker: c.manufacturer, pkg: c.package, cls: c.libraryType,
    check: {show: true, on: effCheck(i, c.code)},
    stock: c.liveStock, stockCls: "",
    need: need, unit: c.unitPrice1,
    why: "⚠ " + esc((c.fitUnknownBecause || []).join(" · "))}));
  const unconfBlock = unconf.length
    ? '<details class="unconf"' + (S.showUnconfirmed ? " open" : "") + '>' +
      "<summary>" + unconf.length + " more — package not confirmed</summary>" +
      '<div class="tablewrap"><table>' + PART_TABLE_HEAD + unconfRows.join("") +
      "</table></div></details>"
    : "";
  const yourPart = '<div class="sect"><div class="tablewrap"><table>' +
    PART_TABLE_HEAD + avlRows.join("") + "</table></div>";
  if (!confirmed.length && !unconf.length) {
    if (searchable) {
      // no candidates until the engineer fires a search — nothing invented
      const miss = disc.search != null
        ? '<p class="alert">searched “' + esc(disc.search) + '” — nothing ' +
          "in stock matched; adjust the terms and search again</p>"
        : "";
      return yourPart + miss + "</div>" + searchRowHtml(i, l);
    }
    const noteText = disc.note ? disc.note
      : disc.automatic
        ? "no in-stock part matches package “" +
          (l.spec ? l.spec.package : "") +
          "” exactly — package matching has no wildcards; " +
          "correct the term and search again"
        : "no search ran — check the terms and search again";
    return yourPart +
      '<p class="alert">' + esc(noteText) + "</p></div>" +
      specFormHtml(i, l.spec || {}, disc.automatic ? "package" : "kind");
  }
  return (searchable ? searchRowHtml(i, l) : "") +
    '<div class="sect"><div class="tablewrap"><table>' + sortableHead() +
    avlRows.join("") + candRows.join("") + "</table></div>" +
    unconfBlock + checksHtml(l) + "</div>";
}

/* the acknowledgement: staged selections write to the database (or the
   order draft) only when this button is pressed */
function updateBtnHtml(i) {
  const dirty = stagedDirty(i);
  return '<button class="btn solid mini" id="update-btn" ' +
    'data-line="' + i + '"' +
    (dirty ? "" : ' aria-disabled="true" title="no changes to save"') +
    ">Update</button>";
}

/* the title-line actions: search alternates + Update, right side */
function titleActionsHtml(i) {
  const l = S.resolution.lines[i];
  const rl = S.requirements.lines[i];
  if (l.dnp || lineState(i) === "conf") return "";
  const pinned = !rl.spec && (rl.providerRefs || rl.mpn);
  if (!pinned && !rl.spec) return "";
  const canSearch = (pinned || !escFor(i)) &&
    !S.exploring[lineKey(rl)];   // red spec panels carry the search inline
  return '<span class="title-actions">' +
    (canSearch ? '<button class="btn mini" id="open-search">' +
      "Search Alternates</button>" : "") +
    updateBtnHtml(i) + "</span>";
}

function offerLabel(v) {
  if (!v) return "—";
  const t = String(v).toLowerCase();
  return t === "expand" || t === "extended" ? "Extended"
    : t === "base" || t === "basic" ? "Basic" : String(v);
}

/* the why column carries only judgments the columns don't already show —
   stock and price restatements are dropped by their score factor */
function candWhy(c) {
  const bits = [];
  for (const x of (c.scoreContributions || [])) {
    // stock/price restatements and the fee class have their own columns
    if (["stock-margin", "price", "offer-class"].includes(x.factor)) continue;
    bits.push(x.why);
  }
  return bits.map(esc).join(" · ");
}

/* the engineer's search: seeded from the spec, edited and FIRED by a human —
   no query composed or run behind their back */
function searchRowHtml(i, l) {
  const key = lineKey(S.requirements.lines[i]);
  const spec = l.spec || S.requirements.lines[i].spec || {};
  const seed = S.searches[key] ||
    [spec.qualifier, spec.value, spec.package].filter(Boolean).join(" ");
  return '<div class="sect"><div class="form">' +
    '<label>search in-stock parts <input id="sf-terms" value="' + esc(seed) +
    '"></label>' +
    '<button class="btn solid" id="terms-search" data-line="' + i +
    '">Search</button></div></div>';
}

function specFormHtml(i, spec, suspect) {
  const f = (name, val) =>
    '<label>' + name + ' <input id="sf-' + name + '" value="' + esc(val || "") +
    '"' + (suspect === name ? ' class="suspect"' : "") + "></label>";
  return '<div class="sect"><div class="form">' +
    f("kind", spec.kind) + f("value", spec.value) +
    f("package", spec.package) + f("qualifier", spec.qualifier) +
    '<button class="btn solid" id="spec-search" data-line="' + i +
    '">Search</button></div></div>';
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
  document.querySelectorAll('#main input[type=radio][data-stage]').forEach(r => {
    r.onchange = () => {
      stagedFor(S.selected).radio = r.dataset.stage;
      render();
    };
  });
  document.querySelectorAll('#main input[type=checkbox][data-check]').forEach(cb => {
    cb.onchange = () => {
      stagedFor(S.selected).checks[cb.dataset.check] = cb.checked;
      render();
    };
  });
  const upd = $("update-btn");
  if (upd) upd.onclick = () => {
    if (upd.getAttribute("aria-disabled") === "true") return;
    applyStaged(parseInt(upd.dataset.line, 10));
  };
  const search = $("spec-search");
  if (search) search.onclick = () => doSearch(parseInt(search.dataset.line, 10));
  const terms = $("terms-search");
  if (terms) {
    const fire = () => doTermsSearch(parseInt(terms.dataset.line, 10));
    terms.onclick = fire;
    const input = $("sf-terms");
    if (input) input.onkeydown = ev => { if (ev.key === "Enter") fire(); };
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
    btn.onclick = () => {
      if (btn.dataset.act === "clearover") clearOverride(S.selected);
      else stopUsing(S.selected);
    };
  });
  const expl = $("explore-search");
  if (expl) {
    const fire = () => doExploreSearch(parseInt(expl.dataset.line, 10));
    expl.onclick = fire;
    const input = $("sf-explore");
    if (input) input.onkeydown = ev => { if (ev.key === "Enter") fire(); };
  }
  const ge = $("open-search");
  if (ge) ge.onclick = () => {
    S.exploring[lineKey(S.requirements.lines[S.selected])] = true;
    render();
  };
  if (S.selected != null) ensureAvl(S.selected);
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

async function doExploreSearch(i) { await run(
  "searching (judging a new footprint can take a few seconds)", async () => {
  const t = $("sf-explore").value.trim();
  if (!t) throw new Error("enter search terms first");
  const rl = S.requirements.lines[i];
  const key = lineKey(rl);
  S.searches[key] = t;
  saveDraft();
  const d = await api("/api/explore", {
    search: t,
    // a spec line's package is already agent-normalized — no judgment call
    package: rl.spec ? rl.spec.package : undefined,
    footprint: rl.spec ? undefined
      : (S.resolution.lines[i].footprint || undefined)});
  S.exploreResults[key] = d;
  render();
  const n = (d.candidates || []).length;
  msg(n ? n + " part(s) found — pick one for this order"
        : "nothing found — adjust the terms and search again",
      n ? "ok" : "warn");
}); }

/* undo an order-only pick: the resolver's own choice comes back */
async function clearOverride(i) { await run("undoing pick", async () => {
  delete S.overrides[lineKey(S.requirements.lines[i])];
  await resolveNow();
  msg("back to the automatic pick", "ok");
}); }

/* undo a recorded pick: audited removal, the spec goes back to needing one */
async function stopUsing(i) { await run("removing part", async () => {
  const rl = S.requirements.lines[i];
  const l = S.resolution.lines[i];
  await api("/api/remove", {spec: rl.spec, ref: l.ref,
                            note: "removed in the app (undo pick)"});
  if (rl.spec) delete S.avlCache[JSON.stringify(rl.spec)];
  await resolveNow();
  msg("removed " + l.ref + " — pick again below", "ok");
}); }

function modelFor(i, code) {
  const q = queueFor(i);
  const key = lineKey(S.requirements.lines[i]);
  const pool = [].concat(
    q ? q.candidates || [] : [], q ? q.fitUnconfirmed || [] : [],
    (S.exploreResults[key] || {}).candidates || []);
  const c = pool.find(x => x.code === code);
  return c ? c.model : null;
}

/* commit the staged diff in one act: first pick -> rank 1; checked backups
   append to the approved list in table order; unchecked members are removed
   (audited); an overriding radio pins this order only */
async function applyStaged(i) { await run("saving", async () => {
  const rl = S.requirements.lines[i];
  const key = lineKey(rl);
  const st = S.staged[key];
  if (!st || !stagedDirty(i)) return;
  const e = escFor(i);
  const firstPick = !!(rl.spec && e && e.reason === "no-part-choices");
  const com = committedChecks(i);
  const approvals = [];
  let overrideSet = false;
  if (st.radio !== undefined && st.radio && st.radio !== committedRadio(i)) {
    if (firstPick) {
      approvals.push({spec: rl.spec, lcsc: st.radio,
        mpn: modelFor(i, st.radio) || undefined, rank: 1,
        design: S.design || undefined, note: "picked in the app"});
    } else {
      S.overrides[key] = {code: st.radio};
      overrideSet = true;
    }
  }
  const removals = [];
  if (rl.spec) {
    // newly checked codes append in the current table order
    const q = queueFor(i);
    const ordered = [].concat(
      q ? (q.candidates || []).map(c => c.code) : [],
      q ? (q.fitUnconfirmed || []).map(c => c.code) : [],
      Object.keys(st.checks));
    const seen = new Set();
    for (const code of ordered) {
      if (seen.has(code)) continue;
      seen.add(code);
      if (!(code in st.checks) || st.checks[code] === com.has(code)) continue;
      if (st.checks[code]) {
        if (firstPick && code === st.radio) continue;  // rank 1 covers it
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
                              note: "alt removed in the app"});
  if (rl.spec) delete S.avlCache[JSON.stringify(rl.spec)];
  await resolveNow();
  const done = [];
  if (approvals.length) done.push(approvals.length + " approved");
  if (removals.length) done.push(removals.length + " removed");
  if (overrideSet) done.push("pick applies to this order only");
  msg("saved — " + (done.join(" · ") || "updated"), "ok");
}); }

async function doSearch(i) { await run("searching", async () => {
  const spec = {
    kind: $("sf-kind").value.trim(), value: $("sf-value").value.trim(),
    package: $("sf-package").value.trim(),
    qualifier: $("sf-qualifier").value.trim()};
  const rl = S.requirements.lines[i];
  const u = uninterpFor(i);
  const hint = ((rl.designators[0] || "").match(/^[A-Za-z]+/) || [""])[0]
    .toUpperCase();
  // remember the answer silently (a user answer is never re-asked) …
  await api("/api/confirm-spec", {
    kindHint: u ? u.kindHint : hint,
    value: u ? u.value : (rl.comment || ""),
    footprint: u ? u.footprint : (rl.footprint || ""),
    spec: spec,
    envelope: (u && u.guess && u.guess.envelope) || undefined});
  // … then search: the line becomes a spec line and re-resolves
  rl.spec = spec;
  delete rl.mpn; delete rl.manufacturer; delete rl.providerRefs;
  S.uninterpreted = S.uninterpreted.filter(x => x.lineIndex !== i);
  delete S.overrides[lineKey(rl)];
  await resolveNow();
  const q = queueFor(i);
  const found = q ? (q.candidates || []).length + (q.fitUnconfirmed || []).length
                  : 0;
  msg(found ? found + " part(s) found — pick one"
            : "nothing found — adjust a term and search again",
      found ? "ok" : "warn");
}); }

async function doTermsSearch(i) { await run("searching", async () => {
  const t = $("sf-terms").value.trim();
  if (!t) throw new Error("enter search terms first");
  S.searches[lineKey(S.requirements.lines[i])] = t;
  await resolveNow();
  const q = queueFor(i);
  const found = q
    ? (q.candidates || []).length + (q.fitUnconfirmed || []).length : 0;
  msg(found ? found + " part(s) found — pick one"
            : "nothing found — adjust the terms and search again",
      found ? "ok" : "warn");
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
loadCache();
</script>
</body>
</html>
"""
