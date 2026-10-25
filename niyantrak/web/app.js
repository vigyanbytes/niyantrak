/* Niyantrak panel (open evaluation edition). No framework; ECharts is optional (charts hide if it cannot load). */
const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue("--" + n).trim();
const TITLES = { decisions: "Decisions", docs: "Docs", proof: "Proof", rules: "Rule book", people: "People & roles", playbook: "Officer playbook", activity: "Activity (6W)", overview: "Overview", fleet: "Fleet", add: "Add machine", try: "Try it", compliance: "Compliance",
  access: "AI access", approvals: "Approvals", audit: "Audit & evidence" };
const state = { counts: {}, peers: {}, node: null, charts: {}, joins: {} };
const DEMO = /[?&]demo=1/.test(location.search);
const BUNDLE = window.NIYANTRAK_DEMO_DATA || null;      // standalone demo with the sample team (tools/demo-data.py)

function show(id) {
  $$("main>section").forEach((s) => (s.hidden = s.id !== id));
  $$(".rail button").forEach((b) => b.setAttribute("aria-current", b.dataset.p === id ? "page" : "false"));
  $("#title").textContent = TITLES[id] || id;
  window.scrollTo(0, 0);
  try { history.replaceState(null, "", "#" + id); } catch (e) {}
  if (isLive(id)) return renderLive(id);
  if (id === "overview") drawCharts();
  if (id === "fleet") { renderFleet(); loadJoins().then(() => { refreshCounts(); renderFleet(); }); }
  if (id === "activity") drawActivity();
  if (id === "rules") renderRules();
  if (id === "people") renderPeople();
  if (id === "approvals") renderApprovals();
  if (id === "proof") renderProof();
  if (id === "decisions") renderDecisions();
  if (id === "docs") renderDocs();
}
$$(".rail button").forEach((b) => (b.onclick = () => show(b.dataset.p)));
document.addEventListener("click", (e) => { const g = e.target.closest("[data-go]"); if (g) show(g.dataset.go); });

async function api(path, body) {
  const r = await fetch("api/" + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.status);
  return d;
}

/* ── Try it ─────────────────────────────────────────────────────────────────────────────────────────── */
async function scan() {
  const text = $("#msg").value;
  $("#status").textContent = "Checking…";
  try {
    const d = await api("scan", { text });
    $("#sent").textContent = text;
    $("#masked").innerHTML = esc(d.masked).replace(/&lt;([A-Z0-9_]+_\d+)&gt;/g, '<span class="ph">&lt;$1&gt;</span>');
    const f = Object.entries(d.counts);
    $("#found").innerHTML = f.length ? f.map(([k, v]) => `<span>${esc(k)} ${v}</span>`).join("") : "<span>none found</span>";
    state.counts = d.session_counts || state.counts;
    $("#t-found").textContent = Object.values(state.counts).reduce((a, b) => a + b, 0);
    $("#status").textContent = "";
    if (!$("#overview").hidden) drawCharts();
  } catch (e) { $("#status").textContent = "Could not check: " + e.message; }
}
$("#go").onclick = scan;
const SAMPLES = {
  in: "Hi, I am Ramesh. My Aadhaar is 2345 6789 0124 and PAN ABCPE1234F. Please refund Rs 1,200 to ramesh@okhdfc and confirm on +91 98450 12345. Card 4111 1111 1111 1111.",
  eu: "Hello, this is Anna. Please refund the €120 to IBAN GB82 WEST 1234 5698 7654 32. My NI number is AB 12 34 56 C, email anna@example.de, phone +49 30 1234 5678.",
  us: "Hi, it's John. My SSN is 123-45-6789, please charge card 4111 1111 1111 1111 and email john@example.com or call +1 415 555 0134 about my appointment."
};
$$("[data-sample]").forEach((b) => (b.onclick = () => {
  $$("[data-sample]").forEach((x) => x.setAttribute("aria-selected", x === b));
  $("#msg").value = SAMPLES[b.dataset.sample]; scan();
}));

/* ── Fleet ──────────────────────────────────────────────────────────────────────────────────────────── */
function nodeCard(n, self) {
  const checks = (n.checks || []).map((c) => `<tr><td>${esc(c.name)}</td><td><span class="pill ${c.ok ? "ok" : "crit"}">${c.ok ? "Passing" : "Failing"}</span></td></tr>`).join("");
  const v4 = (n.ipv4 || []).join(", ") || "—", v6 = (n.ipv6 || []).join(", ") || "—";
  const trust = self ? '<span class="pill ok">This machine</span>' : n.verified ? '<span class="pill ok">Verified</span>' : '<span class="pill warn">Not verified yet</span>';
  return `<div class="card node"><div class="card-h"><h2>${esc(n.hostname || n.node_id)}</h2>${trust}</div>
    <div class="muted mono">${esc(n.node_id || "")}${n.role ? " · " + esc(n.role) : ""}${n.os ? " · " + esc(n.os) : ""}</div>
    <div class="addr"><div class="muted">IPv4 <span class="mono">${esc(v4)}</span></div><div class="muted">IPv6 <span class="mono">${esc(v6)}</span></div></div>
    ${checks ? `<table>${checks}</table>` : self ? `<p class="muted">Not set up yet — run the bootstrap once (see <button class="link" data-go="add">Add machine</button>) and its governance checks appear here.</p>` : `<p class="muted">Seen ${esc(n.seen_at || "")}. Approve it after its signed card checks out.</p>`}</div>`;
}
function joinCard(j) {
  const c = j.card || {}, a = c.addresses || {}, os = c.os ? `${c.os.id || ""} ${c.os.version || ""}`.trim() : "";
  return `<div class="card node"><div class="card-h"><h2>${esc(c.hostname || j.node_id)}</h2><span class="pill warn">Waiting for approval</span></div>
    <div class="muted mono">${esc(j.node_id)}${c.role ? " · " + esc(c.role) : ""}${os ? " · " + esc(os) : ""}</div>
    <div class="addr"><div class="muted">IPv4 <span class="mono">${esc((a.ipv4 || []).join(", ") || "—")}</span></div><div class="muted">IPv6 <span class="mono">${esc((a.ipv6 || []).join(", ") || "—")}</span></div></div>
    <p class="muted">Signed card checked against its host key · asked ${esc(j.requested_at || "")}<br><span class="mono">card ${esc((j.card_sha256 || "").slice(0, 16))}…</span></p>
    <div class="row"><button class="btn small" data-decide="approve" data-node="${esc(j.node_id)}">Approve</button>
      <button class="btn ghost small" data-decide="reject" data-node="${esc(j.node_id)}">Reject</button></div></div>`;
}
async function loadJoins() {
  if (DEMO && !BUNDLE) return;                        // sample data only; the demo never calls the join API
  try { state.joins = (await api("nodes")).nodes || {}; } catch (e) { state.joins = {}; }
}
function renderFleet() {
  const list = [], joins = Object.values(state.joins);
  const pending = joins.filter((j) => j.state === "pending");
  $("#join-requests").innerHTML = pending.length ? `<h2>Asking to join (${pending.length})</h2><div class="nodes">${pending.map(joinCard).join("")}</div><h2>Machines</h2>` : "";
  if (state.node) list.push(nodeCard(state.node, true));
  Object.values(state.peers).forEach((p) => { if (!state.node || p.node_id !== state.node.node_id) list.push(nodeCard(p, false)); });
  joins.filter((j) => j.state === "approved" && !state.peers[j.node_id] && (!state.node || j.node_id !== state.node.node_id)).forEach((j) => {
    const c = j.card || {}, a = c.addresses || {};
    list.push(nodeCard({ node_id: j.node_id, hostname: c.hostname, role: c.role, os: c.os ? `${c.os.id} ${c.os.version}` : "", ipv4: a.ipv4, ipv6: a.ipv6, verified: true, seen_at: j.requested_at }, false));
  });
  $("#nodes").innerHTML = list.join("") || '<div class="card"><p>No machines yet. Use <b>Look for machines</b>, or <button class="link" data-go="add">add one</button>.</p></div>';
}
if (!DEMO) {
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-decide]"); if (!b) return;
    b.disabled = true;
    try { await api("nodes/" + encodeURIComponent(b.dataset.node) + (b.dataset.decide === "approve" ? "/approve" : "/reject"), {}); $("#disc-status").textContent = ""; }
    catch (err) { $("#disc-status").textContent = "Could not record the decision: " + err.message; }
    await loadJoins(); refreshCounts(); renderFleet();
  });
  $("#invite").onclick = async () => {
    try {
      const d = await api("join/token", {}), c = d.commands || {};
      const info = await api("join/info").catch(() => ({}));
      $("#cmd-join").textContent = c.address || ""; $("#join-by-addr").hidden = !c.address;
      $("#cmd-join-mdns").textContent = c.mdns || ""; $("#join-by-name").hidden = !c.mdns;
      $("#cmd-join-win").textContent = c.windows || ""; $("#join-token").textContent = c.windows ? d.token : "";
      $("#join-win").hidden = !c.windows;
      $("#join-note").textContent = d.note || ""; $("#join-note").hidden = !d.note;
      $("#join-fp").textContent = info.fingerprint ? "sha256:" + info.fingerprint : "— (join listener is off)";
      $("#invite-out").hidden = false;
    }
    catch (err) { $("#disc-status").textContent = "Could not create an invitation: " + err.message; }
  };
} else $("#invite").onclick = () => { $("#disc-status").textContent = "This is the demo: invitations are created in the installed panel."; };
$("#discover").onclick = async () => {
  $("#disc-status").textContent = "Listening for machines on your network for 5 seconds…";
  try { const d = await api("discover", {}); state.peers = d.peers || {}; $("#disc-status").textContent = d.message || ""; refreshCounts(); renderFleet(); }
  catch (e) { $("#disc-status").textContent = "Discovery is not available here: " + e.message; }
};

/* ── Add machine ────────────────────────────────────────────────────────────────────────────────────── */
function pickOS(os) {
  $$(".seg button").forEach((b) => b.setAttribute("aria-selected", b.dataset.os === os));
  $("#os-linux").hidden = os !== "linux"; $("#os-windows").hidden = os !== "windows";
}
$$(".seg button").forEach((b) => (b.onclick = () => pickOS(b.dataset.os)));
pickOS(/Windows/i.test(navigator.userAgent) ? "windows" : "linux");
$$("[data-copy]").forEach((b) => (b.onclick = async () => {
  const t = document.getElementById(b.dataset.copy).textContent;
  try { await navigator.clipboard.writeText(t); b.textContent = "Copied"; } catch (e) { const r = document.createRange(); r.selectNodeContents(document.getElementById(b.dataset.copy)); getSelection().removeAllRanges(); getSelection().addRange(r); b.textContent = "Selected — press Ctrl+C"; }
  setTimeout(() => (b.textContent = "Copy"), 2000);
}));

/* ── Overview ───────────────────────────────────────────────────────────────────────────────────────── */
function refreshCounts() {
  const peers = Object.keys(state.peers).filter((k) => !state.node || k !== state.node.node_id).length;
  const joined = Object.values(state.joins).filter((j) => j.state === "approved" && !state.peers[j.node_id] && (!state.node || j.node_id !== state.node.node_id)).length;
  const total = (state.node ? 1 : 0) + peers + joined;
  $("#t-nodes").textContent = total; $("#n-fleet").textContent = total;
  $("#t-verified").textContent = (state.node && state.node.bootstrapped ? 1 : 0) + Object.values(state.peers).filter((p) => p.verified).length + joined;
  const c = state.node ? state.node.checks || [] : [];
  $("#t-checks").textContent = c.length ? `${c.filter((x) => x.ok).length} / ${c.length}` : "—";
}
function theme() {
  return { color: ["c1", "c2", "c3", "c4", "c5", "c6"].map(css), textStyle: { fontFamily: "Inter, sans-serif", color: css("body") },
    tooltip: { backgroundColor: css("ink"), borderWidth: 0, textStyle: { color: css("bg") } } };
}
function drawCharts() {
  if (!window.echarts) return;
  const types = Object.entries(state.counts);
  $("#c-types-empty").hidden = types.length > 0;
  const a = state.charts.types || (state.charts.types = echarts.init($("#c-types")));
  a.setOption({ ...theme(), grid: { left: 90, right: 16, top: 8, bottom: 24 },
    xAxis: { type: "value", minInterval: 1, axisLabel: { color: css("axis") }, splitLine: { lineStyle: { color: css("grid") } } },
    yAxis: { type: "category", data: types.map((t) => t[0]), axisLabel: { color: css("axis"), fontFamily: "JetBrains Mono" }, axisLine: { lineStyle: { color: css("grid") } } },
    series: [{ type: "bar", data: types.map((t) => t[1]), itemStyle: { borderRadius: [0, 4, 4, 0], color: css("c4") }, barMaxWidth: 18 }] }, true);
  const nodes = [], links = [];
  const self = state.node ? (state.node.hostname || state.node.node_id) : "this machine";
  nodes.push({ name: self, symbolSize: 34, itemStyle: { color: css("c1") }, label: { show: true, color: css("ink") } });
  Object.values(state.peers).forEach((p) => { if (p.node_id === self) return;
    nodes.push({ name: p.hostname || p.node_id, symbolSize: 22, itemStyle: { color: p.verified ? css("c3") : css("c6") }, label: { show: true, color: css("body") } });
    links.push({ source: self, target: p.hostname || p.node_id }); });
  const b = state.charts.net || (state.charts.net = echarts.init($("#c-net")));
  b.setOption({ ...theme(), series: [{ type: "graph", layout: "force", roam: true, data: nodes, links,
    force: { repulsion: 260, edgeLength: 110 }, label: { position: "right", fontSize: 12 }, lineStyle: { color: css("line2"), width: 1.5 } }] }, true);
}

/* ── Activity (6W): who · agent · which · what · where · why ─────────────────────────────────────────── */
// Real data: GET api/activity (the 6W store, niyantrak/telemetry). Sample data when the store is empty, the optional
// [telemetry] extra is missing, or this is the demo. Both paths produce the same shapes and share one renderer.
const OUTCOME_LABEL = { allowed: "Allowed", masked: "Cloud · masked", local: "Local GPU", blocked: "Blocked", needs_approval: "Needs approval",
  approved: "Approved", rejected: "Rejected", error: "Error" };
const OUTCOME_KEY_COLOR = () => ({ allowed: css("info"), masked: css("cloud"), local: css("local"), blocked: css("block"), needs_approval: css("warn"),
  approved: css("ok"), rejected: css("crit"), error: css("crit") });
const SAMPLE_OUTCOME = { "Cloud · masked": "masked", "Local GPU": "local", "Blocked": "blocked", "Needs approval": "needs_approval", "Approved": "approved" };
function sampleEvents() {           // shape of a 6W event; real ones come from the 6W store when installed
  const who = ["Priya (DevOps)", "Arjun (Developer)", "Clinic bot", "Support bot", "Meera (Officer)"];
  const agent = { "Priya (DevOps)": "Claude Code", "Arjun (Developer)": "Codex", "Clinic bot": "WhatsApp gateway", "Support bot": "Voice gateway", "Meera (Officer)": "Panel" };
  const which = { "Priya (DevOps)": "acme/infra", "Arjun (Developer)": "acme/payments-api", "Clinic bot": "acme/clinic-bot", "Support bot": "acme/support-bot", "Meera (Officer)": null };
  const plan = [
    ["Clinic bot", "Answer patient query", "Cloud · masked", "RB-ROUTE-001 mask personal data", 220],
    ["Clinic bot", "Answer patient query", "Local GPU", "RB-PII-HEALTH-LOCAL keep health data local", 90],
    ["Support bot", "Refund request", "Cloud · masked", "RB-ROUTE-001 mask personal data", 140],
    ["Support bot", "Card payment", "Local GPU", "RB-PII-CARD-LOCAL cards never leave", 35],
    ["Priya (DevOps)", "Open firewall port", "Needs approval", "RB-INFRA-EDGE-002 approval for edge changes", 6],
    ["Priya (DevOps)", "Read secrets folder", "Blocked", "Hard stop: secret access", 2],
    ["Arjun (Developer)", "Edit code", "Cloud · masked", "RB-ROUTE-005 internal code may use cloud", 60],
    ["Arjun (Developer)", "Delete data folder", "Blocked", "Hard stop: destructive command", 1],
    ["Meera (Officer)", "Approve plan", "Approved", "Approver is not the requester", 5]];
  const ev = [];
  plan.forEach(([w, what, where, why, n]) => { for (let i = 0; i < n; i++) ev.push({ who: w, agent: agent[w], which: which[w], what, where, why, outcome: SAMPLE_OUTCOME[where], day: (i * 3 + n) % 7 }); });
  return ev;
}
function sampleShapes(ev) {          // same shapes as GET api/activity
  const nodes = [], names = new Map(), links = new Map();
  const node = (col, v) => { const key = col + "\u0000" + v;
    if (!names.has(key)) { const d = nodes.some((n) => n.name === v) ? `${v} (${col})` : v; names.set(key, d); nodes.push({ name: d, col, value: v }); }
    return names.get(key); };
  ev.forEach((e) => { const p = ["who", "agent", "which", "what", "where"].filter((c) => c !== "which" || e.which != null).map((c) => node(c, e[c]));
    for (let i = 0; i < p.length - 1; i++) { const k = p[i] + "\u0000" + p[i + 1]; links.set(k, (links.get(k) || 0) + 1); } });
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], outcomes = Object.keys(OUTCOME_LABEL).filter((o) => ev.some((e) => e.outcome === o));
  const whys = {}, projects = {}; ev.forEach((e) => { whys[e.why] = (whys[e.why] || 0) + 1; if (e.which != null) projects[e.which] = (projects[e.which] || 0) + 1; });
  const ranked = (o) => Object.entries(o).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value || (a.name < b.name ? -1 : 1));
  return { total: ev.length,
    sankey: { nodes, links: [...links].map(([k, v]) => { const [source, target] = k.split("\u0000"); return { source, target, value: v }; }) },
    week: { days, outcomes, series: outcomes.map((o) => ({ name: o, data: days.map((_, d) => ev.filter((e) => e.outcome === o && e.day === d).length) })) },
    why: ranked(whys), by: { which: ranked(projects) },
    infra: { hosts: ["control-01", "ai-node-01", "edge-01", "laptop-07"],
      series: [["Approved changes", "ok", [4, 2, 3, 1]], ["Drift caught and reverted", "warn", [1, 0, 2, 1]], ["Blocked by gate", "crit", [2, 1, 0, 1]]].map(([name, color, data]) => ({ name, color, data })) } };
}
const ACT = { events: null, filter: null, shapes: null, seq: 0 };
const OUTCOME_COLOR = () => ({ "Cloud · masked": css("cloud"), "Local GPU": css("local"), "Blocked": css("block"), "Needs approval": css("warn"), "Approved": css("ok") });
const SAMPLE_NOTE = "Sample activity until the 6W store is connected. Personal values are never part of an event — only who, which agent, which project, what, where and why.";
const dayLabel = (d) => /^\d{4}-\d{2}-\d{2}$/.test(d) ? new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { weekday: "short", day: "numeric", timeZone: "UTC" }) : d;
async function drawActivity() {
  if (!window.echarts) { $("#act-note").textContent = "Charts need an internet connection to load the chart library."; return; }
  const f = ACT.filter, seq = ++ACT.seq;
  $("#act-filter").textContent = f ? `${f.v}` : "all activity";
  let a = null;
  if (!DEMO || BUNDLE) {
    try { a = await api("activity?days=7" + (f ? `&k=${encodeURIComponent(f.k)}&v=${encodeURIComponent(f.v)}` : "")); } catch (e) { a = null; }
    if (seq !== ACT.seq) return;                          // a newer click already redrew
  }
  if (a && a.integrity === "failed") {
    $("#act-note").textContent = a.reason;
    return renderActivity({ total: 0, sankey: { nodes: [], links: [] }, week: { days: [], outcomes: [], series: [] }, why: [], by: { which: [] }, infra: { hosts: [], series: [] } });
  }
  if (a && !a.empty && a.sample) {
    $("#act-note").textContent = `${a.sample}: ${a.total.toLocaleString()} event(s), ${a.from} to ${a.to}, computed by the real 6W store. Events hold labels and counts only — never message text or identifier values.`;
    return renderActivity(a);
  }
  if (a && !a.empty) {
    $("#act-note").textContent = `Live activity from the 6W store: ${a.total.toLocaleString()} event(s), ${a.from} to ${a.to}. Events hold labels and counts only — never message text or identifier values.`;
    return renderActivity(a);
  }
  if (!ACT.events) ACT.events = sampleEvents();
  $("#act-note").textContent = SAMPLE_NOTE;
  renderActivity(sampleShapes(ACT.events.filter((e) => !f || e[f.k] === f.v)));
}
function renderActivity(a) {
  ACT.shapes = a;
  const oc = OUTCOME_COLOR(), kc = OUTCOME_KEY_COLOR(), lbl = (o) => OUTCOME_LABEL[o] || o;
  const flow = ACT.c1 || (ACT.c1 = echarts.init($("#c-flow")));
  flow.setOption({ ...theme(), tooltip: { trigger: "item" }, series: [{ type: "sankey", left: 8, right: 120, nodeGap: 10, emphasis: { focus: "adjacency" },
    data: a.sankey.nodes.map((n) => ({ name: n.name, itemStyle: oc[n.name] ? { color: oc[n.name] } : undefined })),
    links: a.sankey.links, label: { color: css("body"), fontSize: 12 }, lineStyle: { color: "gradient", opacity: 0.35 } }] }, true);
  const time = ACT.c2 || (ACT.c2 = echarts.init($("#c-time")));
  time.setOption({ ...theme(), tooltip: { trigger: "axis" }, legend: { top: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: css("body"), fontSize: 11.5 } }, grid: { left: 40, right: 10, top: 56, bottom: 24 },
    xAxis: { type: "category", data: a.week.days.map(dayLabel), axisLabel: { color: css("axis") } }, yAxis: { type: "value", axisLabel: { color: css("axis") }, splitLine: { lineStyle: { color: css("grid") } } },
    series: a.week.series.map((s) => ({ name: lbl(s.name), type: "bar", stack: "x", itemStyle: { color: kc[s.name] }, data: s.data })) }, true);
  const why = ACT.c3 || (ACT.c3 = echarts.init($("#c-why")));
  why.setOption({ ...theme(), tooltip: { trigger: "item" }, series: [{ type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false },
    label: { color: "#fff", fontSize: 11.5, fontFamily: "JetBrains Mono", formatter: (p) => p.name.split(" ")[0].replace(/^Hard$/, "Hard stop") },
    tooltip: { formatter: (p) => `${esc(p.name)}<br>${p.value} events` }, data: a.why }] }, true);
  const proj = ACT.c5 || (ACT.c5 = echarts.init($("#c-which"))), projects = ((a.by && a.by.which) || []).slice().reverse();
  if (!projects.length) {                         // events without `which` (recorded before 6W, or not in a project)
    proj.setOption({ title: { text: "No project recorded for this activity.", left: "center", top: "middle",
      textStyle: { color: css("muted"), fontSize: 13, fontWeight: 400 } }, series: [] }, true);
  } else proj.setOption({ ...theme(), tooltip: { trigger: "axis", axisPointer: { type: "shadow" } }, grid: { left: 150, right: 24, top: 8, bottom: 24 },
    yAxis: { type: "category", data: projects.map((p) => p.name), axisLabel: { color: css("axis"), fontFamily: "JetBrains Mono" } },
    xAxis: { type: "value", axisLabel: { color: css("axis") }, splitLine: { lineStyle: { color: css("grid") } } },
    series: [{ name: "events", type: "bar", itemStyle: { color: css("info") }, data: projects.map((p) => p.value) }] }, true);
  const infra = ACT.c4 || (ACT.c4 = echarts.init($("#c-infra")));
  if (!a.infra.hosts.length) {                    // no machine-tagged events in this period: say so, no empty axis
    infra.setOption({ title: { text: "No machine changes, drift or approvals recorded in this period.", left: "center", top: "middle",
      textStyle: { color: css("muted"), fontSize: 13, fontWeight: 400 } }, series: [] }, true);
  } else infra.setOption({ ...theme(), tooltip: { trigger: "axis" }, legend: { top: 0, textStyle: { color: css("body") } }, grid: { left: 104, right: 10, top: 36, bottom: 24 },
    yAxis: { type: "category", data: a.infra.hosts, axisLabel: { color: css("axis"), fontFamily: "JetBrains Mono" } }, xAxis: { type: "value", axisLabel: { color: css("axis") }, splitLine: { lineStyle: { color: css("grid") } } },
    series: a.infra.series.map((s) => ({ name: lbl(s.name), type: "bar", stack: "i", itemStyle: { color: s.color ? css(s.color) : kc[s.name] }, data: s.data })) }, true);
  flow.off("click"); flow.on("click", (p) => { if (p.dataType !== "node") return;
    const n = a.sankey.nodes.find((x) => x.name === p.name); if (!n) return;
    ACT.filter = { k: n.col, v: n.value ?? n.name }; drawActivity(); });
  why.off("click"); why.on("click", (p) => { if (p.name) { ACT.filter = { k: "why", v: p.name }; drawActivity(); } });
  proj.off("click"); proj.on("click", (p) => { if (p.name) { ACT.filter = { k: "which", v: p.name }; drawActivity(); } });
}

/* ── Proof: test evidence kept in the repository (tools/prove.py → proof/latest + proof/history.jsonl) ─────── */
async function renderProof() {
  let d = null, why = "No proof run yet — run tools/prove.py";
  try { d = await api("proof"); } catch (e) { why = e.message || why; }
  const has = !!(d && d.summary);
  $("#proof-empty").hidden = has; $("#proof-body").hidden = !has;
  if (!has) { $("#proof-empty-msg").textContent = why; $("#proof-source").textContent = ""; return; }
  const s = d.summary, t = s.tests || {}, hist = d.history || [];
  const standalone = !!window.NIYANTRAK_STANDALONE;
  $("#proof-source").textContent = (standalone ? "Real numbers from the repository's latest proof run" : "From proof/latest on this machine") +
    ` · ${s.result === "pass" ? "PASS" : "FAIL"} · ${s.tree_clean ? "clean tree" : "uncommitted changes"} · branch ${s.branch || "—"}`;
  $("#pf-tests").textContent = `${t.passed ?? "–"} / ${t.total ?? "–"}`;
  $("#pf-tests-s").textContent = `${t.failed || 0} failed · ${t.skipped || 0} skipped`;
  $("#pf-cov").textContent = s.coverage_pct == null ? "n/a" : s.coverage_pct + "%";
  $("#pf-leak").innerHTML = `<span class="pill ${s.leak_scan === "clean" ? "ok" : "crit"}">${esc(s.leak_scan)}</span>`;
  $("#pf-commit").textContent = s.commit || "–";
  $("#pf-date").textContent = String(s.date || "").slice(0, 16).replace("T", " ");
  $("#pf-runs").textContent = `${hist.length} run(s)`;
  $("#pf-links").hidden = standalone; $("#pf-links-note").hidden = !standalone;
  $("#pf-files tbody").innerHTML = (s.files || []).map((f) => `<tr><td class="mono">${esc(f.file)}</td><td>${f.passed}</td><td>${f.failed}</td><td>${f.skipped}</td>
    <td>${Number(f.time || 0).toFixed(2)}s</td><td><span class="pill ${f.failed ? "crit" : "ok"}">${f.failed ? "Failing" : "Passing"}</span></td></tr>`).join("") ||
    '<tr><td colspan="6" class="muted">No tests recorded.</td></tr>';
  if (!window.echarts && document.readyState !== "complete") {        // chart library still loading: draw on load
    addEventListener("load", () => { if (!$("#proof").hidden) renderProof(); }, { once: true });
  }
  $("#c-proof-empty").hidden = !!window.echarts; $("#c-proof").hidden = !window.echarts;
  if (!window.echarts) return;
  const c = state.charts.proof || (state.charts.proof = echarts.init($("#c-proof")));
  c.setOption({ ...theme(), tooltip: { trigger: "axis" }, legend: { top: 0, textStyle: { color: css("body") } }, grid: { left: 44, right: 44, top: 36, bottom: 28 },
    xAxis: { type: "category", data: hist.map((h) => h.commit), axisLabel: { color: css("axis"), fontFamily: "JetBrains Mono" } },
    yAxis: [{ type: "value", name: "tests", minInterval: 1, axisLabel: { color: css("axis") }, splitLine: { lineStyle: { color: css("grid") } } },
      { type: "value", name: "coverage %", min: 0, max: 100, axisLabel: { color: css("axis") }, splitLine: { show: false } }],
    series: [{ name: "Tests passed", type: "line", data: hist.map((h) => h.passed), itemStyle: { color: css("c2") } },
      { name: "Coverage %", type: "line", yAxisIndex: 1, data: hist.map((h) => h.coverage_pct), itemStyle: { color: css("c1") } }] }, true);
}

/* ── Decisions: append-only decision log as a graph (GET /api/decisions) ─────────────────────────────────── */
const DG = { data: null, on: null, query: "" };
const DG_CATS = [["Decisions", "d:in force", "In force", "ok"], ["Decisions", "d:pending", "Waiting for sign-off", "mask"],
  ["Decisions", "d:superseded", "Superseded", "c6"], ["Decisions", "d:retired", "Retired", "warn"],
  ["Work", "w:proposed", "Proposed", "c4"], ["Work", "w:to do", "To do", "c2"], ["Work", "w:in progress", "In progress", "c1"],
  ["Work", "w:blocked", "Blocked / on hold", "crit"], ["Work", "w:done", "Done", "c5"], ["Work", "w:dropped", "Dropped / deferred", "c6"],
  ["Other", "THING", "Things", "c6"], ["Other", "SESSION", "Agent sessions", "info"]];
const dgCat = (n) => n.kind === "DECISION" ? "d:" + n.status : n.kind === "WORK" ? "w:" + n.status : n.kind;
const dgColour = (c) => css((DG_CATS.find((x) => x[1] === c) || [0, 0, 0, "c6"])[3]);
const dgShape = (n) => n.kind === "DECISION" ? "diamond" : n.kind === "WORK" ? "circle" : n.kind === "SESSION" ? "triangle" : "roundRect";
const dgHit = (n) => DG.query && (n.id.toLowerCase().includes(DG.query) || String(n.title || "").toLowerCase().includes(DG.query));
async function renderDecisions() {
  let d = null, why = "";
  try { d = await api("decisions"); } catch (e) { why = e.message; }
  const empty = !d || d.empty;
  $("#dg-empty").hidden = !empty; $("#dg-body").hidden = empty;
  if (empty) { $("#dg-empty-msg").textContent = (d && d.message) || why || "No decisions recorded yet."; return; }
  DG.data = d;
  if (!DG.on) DG.on = Object.fromEntries(DG_CATS.map((c) => [c[1], !["w:done", "w:dropped", "d:superseded", "SESSION"].includes(c[1])]));
  let grp = "";
  $("#dg-chips").innerHTML = DG_CATS.filter((c) => d.counts[c[1]]).map(([g, key, label, col]) => {
    const head = g !== grp ? `<span class="grp">${g}</span>` : ""; grp = g;
    return head + `<button type="button" data-k="${esc(key)}" aria-pressed="${DG.on[key]}"><span class="dot" style="background:${dgColour(key)}"></span>${esc(label)} <span class="n">${d.counts[key]}</span></button>`;
  }).join("");
  $$("#dg-chips button").forEach((b) => (b.onclick = () => { DG.on[b.dataset.k] = !DG.on[b.dataset.k]; b.setAttribute("aria-pressed", DG.on[b.dataset.k]); drawDecisions(); }));
  if (!window.echarts && document.readyState !== "complete") addEventListener("load", () => { if (!$("#decisions").hidden) drawDecisions(); }, { once: true });
  drawDecisions(); dgOpen();
}
function drawDecisions() {
  const d = DG.data; if (!d) return;
  const ns = d.nodes.filter((n) => DG.on[dgCat(n)]), ids = new Set(ns.map((n) => n.id));
  const ls = d.links.filter((l) => ids.has(l.source) && ids.has(l.target));
  const deg = {}; d.links.forEach((l) => { deg[l.source] = (deg[l.source] || 0) + 1; deg[l.target] = (deg[l.target] || 0) + 1; });
  $("#dg-meta").textContent = `${ns.length} of ${d.nodes.length} shown`;
  $("#c-dg-empty").hidden = !!window.echarts; $("#c-dg").hidden = !window.echarts;
  if (!window.echarts) return;
  const c = state.charts.dg || (state.charts.dg = echarts.init($("#c-dg")));
  c.setOption({ ...theme(),
    tooltip: { ...theme().tooltip, formatter: (p) => p.dataType === "edge" ? esc(p.data.kind) : `<b>${esc(p.data.id)}</b> · ${esc(p.data.status || p.data.kind)}<br>${esc(String(p.data.title || "").slice(0, 110))}` },
    series: [{ type: "graph", layout: "force", roam: true, draggable: true, force: { repulsion: 220, edgeLength: [60, 170], gravity: 0.06 },
      edgeSymbol: ["none", "arrow"], edgeSymbolSize: 6,
      label: { show: true, position: "right", fontSize: 11, color: css("body"), formatter: (p) => (p.data.kind === "THING" || dgHit(p.data)) ? p.data.id : "" },
      lineStyle: { color: "source", opacity: 0.45, curveness: 0.1 }, emphasis: { focus: "adjacency", label: { show: true, formatter: (p) => p.data.id } },
      data: ns.map((n) => ({ ...n, name: n.id, symbol: dgShape(n), symbolSize: 12 + Math.min(18, 2 * (deg[n.id] || 0)) + (dgHit(n) ? 10 : 0),
        itemStyle: { color: dgColour(dgCat(n)), borderColor: dgHit(n) ? css("ink") : "transparent", borderWidth: dgHit(n) ? 3 : 0, opacity: DG.query && !dgHit(n) ? 0.35 : 1 } })),
      links: ls.map((l) => ({ ...l, lineStyle: l.kind === "SUPERSEDED_BY" ? { width: 2.5 } : l.kind === "REFERENCES" ? { type: "dashed" } : {} })) }] }, true);
  c.off("click"); c.on("click", (p) => { if (p.dataType === "node") dgShow(p.data.id); });
}
function dgOpen() {         // exact lists from the server, narrowed by the search box
  const groups = (DG.data.open || []).map((g) => ({ ...g, items: g.items.filter((n) => !DG.query || dgHit(n)) })).filter((g) => g.items.length);
  $("#dg-side").innerHTML = '<h2>Open items</h2><div id="dg-open">' + (groups.map((g) => `<div class="label">${esc(g.label)} (${g.items.length})</div><ul>` +
    g.items.slice(0, 25).map((n) => `<li><button type="button" class="lnk" data-id="${esc(n.id)}">${esc(n.id)}</button> — ${esc(String(n.title || "").slice(0, 80))}</li>`).join("") +
    (g.items.length > 25 ? `<li class="muted">… ${g.items.length - 25} more (use search)</li>` : "") + "</ul>").join("") ||
    '<p class="muted">Nothing open' + (DG.query ? " matches the search." : " — every decision is settled and no work is waiting.") + "</p>") + "</div>";
  $$("#dg-side .lnk").forEach((x) => (x.onclick = () => dgShow(x.dataset.id)));
}
function dgShow(id) {
  const n = DG.data.nodes.find((m) => m.id === id); if (!n) return;
  const out = DG.data.links.filter((l) => l.source === id), inc = DG.data.links.filter((l) => l.target === id);
  const link = (x) => `<button type="button" class="lnk" data-id="${esc(x)}">${esc(x)}</button>`;
  const li = (arr, f) => arr.length ? "<ul>" + arr.map((l) => `<li>${esc(l.kind)} ${f(l)}</li>`).join("") + "</ul>" : '<p class="muted">none</p>';
  const who = [n.user && "person " + n.user, n.agent && "agent " + n.agent, n.product && "product " + n.product].filter(Boolean).join(" · ");
  $("#dg-side").innerHTML = `<h2>${esc(n.id)}</h2><span class="pill" style="color:#fff;background:${dgColour(dgCat(n))}">${esc(n.status || n.kind)}</span>` +
    (n.ts ? ` <span class="muted">${esc(String(n.ts).slice(0, 10))}</span>` : "") +
    `<div class="label">Title</div><p>${esc(n.title)}</p>` + (n.text ? `<div class="label">${n.kind === "WORK" ? "Next step" : "Detail"}</div><p>${esc(n.text)}</p>` : "") +
    (who ? `<div class="label">Recorded by</div><p>${esc(who)}</p>` : "") + (n.auto_closed ? `<div class="label">Closed automatically</div><p>${esc(n.auto_closed)}</p>` : "") +
    `<div class="label">Points to</div>${li(out, (l) => "→ " + link(l.target))}<div class="label">Pointed at by</div>${li(inc, (l) => "← " + link(l.source))}` +
    '<p><button type="button" class="link" id="dg-back">← Open items</button></p>';
  $$("#dg-side .lnk").forEach((x) => (x.onclick = () => dgShow(x.dataset.id)));
  $("#dg-back").onclick = dgOpen;
}
$("#dg-search").addEventListener("input", (e) => { DG.query = e.target.value.trim().toLowerCase(); drawDecisions(); dgOpen(); });

/* ── Docs: as-built pages from node cards + join store (GET /api/docs, POST /api/docs/regenerate) ─────────── */
const DOCS = { pages: [], current: null };
function docsShow(d) {
  DOCS.pages = d.pages || [];
  const has = DOCS.pages.length > 0;
  $("#docs-empty").hidden = has; $("#docs-body").hidden = !has;
  if (!has) return;
  if (!DOCS.pages.some((p) => p.file === DOCS.current)) DOCS.current = DOCS.pages[0].file;
  const kind = { fleet: "overview", map: "map", node: "machine" };
  $("#docs-list").innerHTML = DOCS.pages.map((p) => `<li><button type="button" data-f="${esc(p.file)}" aria-current="${p.file === DOCS.current}">${esc(p.title)}<small>${kind[p.kind] || ""}</small></button></li>`).join("");
  $$("#docs-list button").forEach((b) => (b.onclick = () => { DOCS.current = b.dataset.f; docsShow({ pages: DOCS.pages }); }));
  const src = "docs/" + encodeURIComponent(DOCS.current);
  if ($("#docs-frame").getAttribute("src") !== src) $("#docs-frame").setAttribute("src", src);
}
async function renderDocs() {
  let d = { pages: [] };
  try { d = await api("docs"); } catch (e) { $("#docs-status").textContent = e.message; }
  docsShow(d);
}
$("#docs-regen").onclick = async () => {
  const b = $("#docs-regen"); b.disabled = true; $("#docs-status").textContent = "Writing documents…";
  try {
    const d = await api("docs/regenerate", {});
    $("#docs-status").textContent = d.changed && d.changed.length ? `Updated ${d.changed.length} file(s).` : "Nothing changed — the documents already match the machines.";
    docsShow(d);
    const f = $("#docs-frame"); if (f.getAttribute("src")) f.setAttribute("src", f.getAttribute("src"));
  } catch (e) { $("#docs-status").textContent = e.message; }
  b.disabled = false;
};

/* ── Governance: roles, people, rule book, approvals (sample data; enforced the same way in the paid panel) ─ */
const ROLES = {
  owner:     { name: "Owner (super user)", can: ["assign roles", "licence & billing", "emergency access", "read audit"] },
  officer:   { name: "Governance officer", can: ["edit rule book", "approve exceptions", "sign evidence", "read audit"] },
  approver:  { name: "Approver", can: ["approve plans", "approve rule book", "read audit"] },
  operator:  { name: "Operator / DevOps", can: ["propose plans", "add machines", "run agents"] },
  developer: { name: "Developer", can: ["use AI agents", "propose plans"] },
  auditor:   { name: "Auditor", can: ["read audit", "export evidence"] } };
const ACTIONS = ["assign roles", "licence & billing", "edit rule book", "approve rule book", "approve plans", "approve exceptions",
  "propose plans", "add machines", "run agents", "use AI agents", "sign evidence", "export evidence", "read audit", "emergency access"];
const me = { owner: "Asha", officer: "Kavya", approver: "Rohit", operator: "Priya", developer: "Arjun", auditor: "Ananya (external)" };
const can = (action) => (ROLES[$("#viewas").value].can.includes(action) || ($("#viewas").value === "owner" && action === "read audit"));
const who = () => me[$("#viewas").value];
const GOV = {
  people: [
    { name: "Asha", role: "owner", login: "Password + passkey", last: "now" },
    { name: "Kavya", role: "officer", login: "Company SSO", last: "12 min ago" },
    { name: "Rohit", role: "approver", login: "Company SSO", last: "1 h ago" },
    { name: "Priya", role: "operator", login: "Company SSO", last: "3 h ago" },
    { name: "Arjun", role: "developer", login: "Company SSO · laptop-07", last: "today" },
    { name: "Ananya (external)", role: "auditor", login: "Password + passkey", last: "last week" } ],
  rules: [
    { id: "RB-ROUTE-001", says: "Personal data (IDs, bank and card numbers, phones) is masked before any AI model sees it.", applies: "all bots and agents", dc: "personal", action: "mask", laws: "GDPR · DPDP · US privacy · OWASP LLM02", status: "enforced", v: 3 },
    { id: "RB-PII-HEALTH-LOCAL", says: "Health details are processed only by AI on our own machines.", applies: "clinic bot", dc: "personal", action: "local only", laws: "GDPR Art. 9 · HIPAA · DPDP", status: "enforced", v: 2 },
    { id: "RB-PII-CARD-LOCAL", says: "Card numbers never leave our machines, not even masked.", applies: "all bots", dc: "personal", action: "local only", laws: "PCI DSS · GDPR · DPDP", status: "enforced", v: 1 },
    { id: "RB-ROUTE-004", says: "If local AI is down, personal data waits — it never falls back to a cloud model.", applies: "all bots", dc: "personal", action: "block", laws: "GDPR · DPDP", status: "enforced", v: 1 },
    { id: "RB-AGENT-003", says: "AI agents may not change running services; they prepare the change and a person applies it.", applies: "all AI coding agents", dc: "internal", action: "needs approval", laws: "EU AI Act (human oversight) · OWASP LLM06", status: "enforced", v: 2 },
    { id: "RB-AGENT-004", says: "Refunds above 2,000 need a person, valid once for that exact refund.", applies: "support bot", dc: "personal", action: "needs approval", laws: "OWASP LLM06", status: "draft", v: 1 } ],
  approvals: [
    { id: "PL-118", title: "Open port 443 on edge-01 for the booking site", kind: "plan", by: "Priya", rule: "RB-INFRA-EDGE-002", fp: "sha256:7f3a…c91e", state: "waiting" },
    { id: "RB-AGENT-004 v1", title: "New rule: refunds above 2,000 need a person", kind: "rule", by: "Kavya", rule: "rule book change", fp: "sha256:2b91…04ad", state: "waiting" } ] };

function renderPeople() {
  $("#people-table tbody").innerHTML = GOV.people.map((p) => `<tr><td><b>${esc(p.name)}</b></td><td>${esc(ROLES[p.role].name)}</td><td>${esc(p.login)}</td><td class="muted">${esc(p.last)}</td>
    <td>${can("assign roles") && p.role !== "owner" ? `<button class="btn ghost small" data-role-of="${esc(p.name)}">Change role</button>` : ""}</td></tr>`).join("");
  $$("[data-role-of]").forEach((b) => (b.onclick = () => { b.outerHTML = '<span class="muted">Role change sent to the person and recorded</span>'; }));
  const cols = Object.keys(ROLES);
  $("#role-matrix").innerHTML = `<thead><tr><th>Action</th>${cols.map((c) => `<th>${esc(ROLES[c].name.split(" (")[0])}</th>`).join("")}</tr></thead><tbody>` +
    ACTIONS.map((a) => `<tr><td>${esc(a)}</td>${cols.map((c) => (ROLES[c].can.includes(a) || (c === "owner" && a === "read audit")) ? '<td class="y">✓</td>' : '<td class="n">—</td>').join("")}</tr>`).join("") + "</tbody>";
  $("#invite").disabled = !can("assign roles");
  $("#invite").title = can("assign roles") ? "" : "Only the owner assigns roles";
}
$("#invite").onclick = () => { $("#invite-box").hidden = false; $("#inv-msg").textContent = ""; };
$("#inv-cancel").onclick = () => ($("#invite-box").hidden = true);
$("#inv-send").onclick = () => {
  if (!can("assign roles")) { $("#inv-msg").textContent = "Only the owner can invite and assign roles."; return; }
  const code = Math.random().toString(36).slice(2, 5).toUpperCase() + "-" + Math.random().toString(36).slice(2, 5).toUpperCase();
  GOV.people.push({ name: $("#inv-name").value, role: $("#inv-role").value, login: "invite pending", last: "—" });
  $("#inv-msg").textContent = `Invite created: one-time code ${code}, valid 24 hours, single use. Recorded in the audit trail.`;
  renderPeople();
};

let selRule = null;
function renderRules() {
  $("#rule-table tbody").innerHTML = GOV.rules.map((r) => `<tr data-rule="${esc(r.id)}" class="${r.id === selRule ? "sel" : ""}"><td class="mono">${esc(r.id)}<div class="muted">v${r.v}</div></td><td>${esc(r.says)}</td>
    <td>${esc(r.action)}</td><td><span class="pill ${r.status === "enforced" ? "ok" : "warn"}">${r.status === "enforced" ? "Enforced" : "Draft"}</span></td></tr>`).join("");
  $$("[data-rule]").forEach((tr) => (tr.onclick = () => { selRule = tr.dataset.rule; renderRules(); editRule(); }));
  $("#rule-new").disabled = !can("edit rule book");
}
function editRule(isNew) {
  const r = isNew ? { id: "RB-NEW-" + (GOV.rules.length + 1), says: "", applies: "all bots", dc: "personal", action: "mask", laws: "", status: "draft", v: 0 } : GOV.rules.find((x) => x.id === selRule);
  if (!r) return;
  const ro = !can("edit rule book");
  $("#rule-editor").innerHTML = `<div class="card-h"><h2 class="mono">${esc(r.id)}</h2><span class="muted">version ${r.v}</span></div>
    <div class="editor">
      <label>What the rule says (plain words)<textarea id="re-says" ${ro ? "disabled" : ""}>${esc(r.says)}</textarea></label>
      <div class="formgrid"><label>Applies to<input id="re-applies" value="${esc(r.applies)}" ${ro ? "disabled" : ""}></label>
      <label>Data class<select id="re-dc" ${ro ? "disabled" : ""}>${["public", "internal", "confidential", "personal"].map((d) => `<option ${d === r.dc ? "selected" : ""}>${d}</option>`).join("")}</select></label>
      <label>Then<select id="re-action" ${ro ? "disabled" : ""}>${["allow", "mask", "local only", "needs approval", "block"].map((d) => `<option ${d === r.action ? "selected" : ""}>${d}</option>`).join("")}</select></label></div>
      <label>Laws and standards it supports<input id="re-laws" value="${esc(r.laws)}" ${ro ? "disabled" : ""}></label>
      <label>Test it — a sample message<input id="re-test" value="My card is 4111 1111 1111 1111, please refund 2,500"></label>
      <div class="row"><button class="btn ghost" id="re-run">Test</button>${ro ? `<span class="denied">${esc(ROLES[$("#viewas").value].name)}: read only — the governance officer edits rules</span>` : `<button class="btn" id="re-propose">Propose change</button>`}</div>
      <div id="re-out"></div></div>`;
  $("#re-run").onclick = async () => {
    const d = await api("scan", { text: $("#re-test").value });
    const found = Object.keys(d.counts);
    const act = $("#re-action").value, dc = $("#re-dc").value;
    const hit = dc === "personal" ? found.length > 0 : true;
    const cls = !hit ? "ok" : act === "block" ? "crit" : act === "allow" ? "ok" : "warn";
    $("#re-out").innerHTML = `<div class="verdict ${cls}">${hit ? `Rule applies → ${esc(act)}` : "Rule does not apply → allowed"}${found.length ? " · found " + esc(found.join(", ")) : ""}</div>`;
  };
  if (!ro) $("#re-propose").onclick = () => {
    const nr = { ...r, says: $("#re-says").value, applies: $("#re-applies").value, dc: $("#re-dc").value, action: $("#re-action").value, laws: $("#re-laws").value };
    GOV.approvals.unshift({ id: `${nr.id} v${r.v + 1}`, title: `Rule change: ${nr.says.slice(0, 70)}`, kind: "rule", by: who(), rule: "rule book change", fp: "sha256:" + Math.random().toString(16).slice(2, 6) + "…", state: "waiting", next: nr });
    $("#re-out").innerHTML = `<div class="verdict warn">Proposed by ${esc(who())}. It waits in Approvals for a second person; the current version stays enforced until then.</div>`;
  };
}
$("#rule-new").onclick = () => { selRule = null; editRule(true); };

function renderApprovals() {
  $("#approval-list").innerHTML = GOV.approvals.map((a, i) => {
    const own = a.by === who(), allowed = a.kind === "rule" ? can("approve rule book") : can("approve plans");
    const why = own ? "You requested this — someone else must approve it." : !allowed ? `${ROLES[$("#viewas").value].name} cannot approve ${a.kind === "rule" ? "rule book changes" : "plans"}.` : "";
    const done = a.state !== "waiting";
    return `<div class="card"><div class="card-h"><h2>${esc(a.title)}</h2><span class="pill ${done ? (a.state === "approved" ? "ok" : "crit") : "warn"}">${done ? esc(a.state[0].toUpperCase() + a.state.slice(1)) : "Waiting"}</span></div>
      <p>Requested by <b>${esc(a.by)}</b> · ${esc(a.rule)} · <code>${esc(a.fp)}</code></p>
      ${done ? `<p class="muted">${esc(a.note || "")}</p>` : `<div class="row"><button class="btn" data-ap="${i}" ${why ? "disabled" : ""}>Approve</button><button class="btn ghost" data-rj="${i}" ${why ? "disabled" : ""}>Reject</button>${why ? `<span class="denied">${esc(why)}</span>` : ""}</div>`}</div>`;
  }).join("");
  $$("[data-ap]").forEach((b) => (b.onclick = () => { const a = GOV.approvals[+b.dataset.ap]; a.state = "approved"; a.note = `Approved by ${who()} · recorded in the audit chain`;
    if (a.next) { const r = GOV.rules.find((x) => x.id === a.next.id); if (r) Object.assign(r, a.next, { v: r.v + 1, status: "enforced" }); else GOV.rules.push({ ...a.next, v: 1, status: "enforced" }); }
    renderApprovals(); }));
  $$("[data-rj]").forEach((b) => (b.onclick = () => { const a = GOV.approvals[+b.dataset.rj]; a.state = "rejected"; a.note = `Rejected by ${who()} · reason required in the full product`; renderApprovals(); }));
}
$("#viewas").onchange = () => {
  $("#host").textContent = "signed in as " + who();
  const id = (location.hash || "#overview").slice(1);
  if (id === "people") renderPeople(); if (id === "rules") { renderRules(); if (selRule) editRule(); } if (id === "approvals") renderApprovals();
};
$("#act-reset").onclick = () => { ACT.filter = null; drawActivity(); };
addEventListener("resize", () => { Object.values(state.charts).forEach((c) => c.resize()); ["c1", "c2", "c3", "c4"].forEach((k) => ACT[k] && ACT[k].resize()); });

/* ── Pro screens, live: when a panel plugin (the commercial core) is installed, GET api/capabilities marks a screen
   live and the screen talks to api/pro/* instead of showing the preview. The plugin keeps its own sign-in. ──────── */
let CAPS = { screens: {} };
const isLive = (id) => !!(CAPS.screens && CAPS.screens[id] && CAPS.screens[id].live);
function applyCaps() {
  const ed = document.querySelector(".edition");                 // sidebar footer follows the running edition
  if (ed && CAPS.edition && CAPS.edition !== "free") ed.textContent = (CAPS.edition === "pro" ? "Pro" : CAPS.edition) + " edition";
  Object.keys(CAPS.screens || {}).forEach((id) => {
    const live = isLive(id), sec = document.getElementById(id), box = document.getElementById("live-" + id);
    const btn = document.querySelector(`.rail button[data-p="${id}"]`);
    if (live && btn) { const l = btn.querySelector(".lock"); if (l) l.remove(); }
    if (!sec || !box) return;
    [...sec.children].forEach((c) => { if (c !== box) c.hidden = live; });
    box.hidden = !live;
  });
  if (Object.keys(CAPS.screens || {}).some(isLive)) $("label.viewas").hidden = true;   // roles come from sign-in now
}
async function pro(path, body) {      // -> { ok, status, data }; never throws
  try {
    const r = await fetch("api/pro/" + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    let d = {}; try { d = await r.json(); } catch (e) {}
    return { ok: r.ok, status: r.status, data: d };
  } catch (e) { return { ok: false, status: 0, data: { error: "The panel could not be reached.", degraded: true } }; }
}
const notice = (r) => r.data && r.data.degraded
  ? `<div class="card"><div class="verdict crit">The Pro module had a problem with this request (degraded). The rest of the panel keeps running.</div><p class="muted">${esc(r.data.error || "")}</p></div>`
  : `<div class="verdict crit">${esc((r.data && r.data.error) || "Request failed (" + r.status + ")")}</div>`;
const PRO = { me: null };
async function proSession() {
  const r = await pro("session");
  PRO.me = r.ok && r.data.signed_in ? r.data.user : null;
  $("#host").textContent = PRO.me ? `signed in as ${PRO.me.name} (${PRO.me.roles.join(", ")})` : "";
  return r;
}
function signInCard(box, s) {
  const setup = s.ok && s.data.setup_needed;
  box.innerHTML = `<div class="grid2"><div class="card"><h2>${setup ? "Set up the owner" : "Sign in"}</h2>
    <p class="muted">${setup ? "No one is set up yet. The first person becomes the owner." : "The Pro screens use their own sign-in and your role."}</p>
    <div class="formgrid">${setup ? '<label>Name<input id="pl-name"></label><label>Email<input id="pl-email"></label>' : '<label>User<input id="pl-user" autocomplete="username"></label>'}
    <label>Password<input id="pl-pass" type="password" autocomplete="${setup ? "new-password" : "current-password"}"></label>
    ${setup ? "" : '<label>Code from your authenticator (if turned on)<input id="pl-totp" inputmode="numeric"></label>'}</div>
    <div class="row"><button class="btn" id="pl-go">${setup ? "Create owner" : "Sign in"}</button></div><div id="pl-msg"></div></div>
    ${setup ? "" : `<div class="card"><h2>Accept an invite</h2><div class="formgrid"><label>Invite code<input id="pa-code"></label><label>Choose a password<input id="pa-pass" type="password" autocomplete="new-password"></label></div>
    <div class="row"><button class="btn ghost" id="pa-go">Accept</button></div><div id="pa-msg"></div></div>`}</div>`;
  $("#pl-go").onclick = async () => {
    const r = setup ? await pro("session/setup", { name: $("#pl-name").value, email: $("#pl-email").value, password: $("#pl-pass").value })
      : await pro("session/login", { username: $("#pl-user").value, password: $("#pl-pass").value, totp: $("#pl-totp").value });
    if (!r.ok) { $("#pl-msg").innerHTML = notice(r); return; }
    renderLive(currentScreen());
  };
  if (!setup) $("#pa-go").onclick = async () => {
    const r = await pro("people/accept", { code: $("#pa-code").value.trim(), password: $("#pa-pass").value });
    if (!r.ok) { $("#pa-msg").innerHTML = notice(r); return; }
    renderLive(currentScreen());
  };
}
const currentScreen = () => (location.hash || "#overview").slice(1);
const signOutBar = () => `<div class="row between"><span class="muted">Live · ${esc(PRO.me.name)} · ${esc(PRO.me.roles.join(", "))}</span><button class="btn ghost small" data-pro-logout>Sign out</button></div>`;
document.addEventListener("click", async (e) => {
  if (e.target.closest("[data-pro-logout]")) { await pro("session/logout", {}); renderLive(currentScreen()); }
});

async function renderLive(id) {
  const box = document.getElementById("live-" + id);
  if (!box) return;
  box.innerHTML = '<p class="muted">Loading…</p>';
  const s = await proSession();
  if (!s.ok) { box.innerHTML = notice(s); return; }
  if (!PRO.me) return signInCard(box, s);
  const fn = { approvals: liveApprovals, rules: liveRules, people: livePeople, audit: liveAudit, compliance: liveCompliance }[id];
  if (!fn) { box.innerHTML = signOutBar() + '<p class="muted">This screen is live, but has no view in this panel version yet.</p>'; return; }
  await fn(box);
}

async function livePeople(box) {
  const r = await pro("people");
  if (!r.ok) { box.innerHTML = signOutBar() + notice(r); return; }
  const d = r.data, owner = PRO.me.roles.includes("owner"), roles = Object.keys(d.roles || {});
  const opts = (sel) => roles.map((k) => `<option value="${esc(k)}" ${k === sel ? "selected" : ""}>${esc(d.roles[k].name)}</option>`).join("");
  const editable = (p) => owner && p.status === "active" && p.id !== PRO.me.id;
  box.innerHTML = signOutBar() + `<div class="card"><table class="people"><thead><tr><th>Person</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody>
    ${d.people.map((p) => `<tr><td><b>${esc(p.name)}</b><div class="muted mono">${esc(p.id)}</div></td><td>${editable(p) ? `<select data-role="${esc(p.id)}">${opts(p.roles[0])}</select>` : esc(p.roles.map((x) => (d.roles[x] || {}).name || x).join(", "))}</td>
      <td><span class="pill ${p.status === "active" ? "ok" : "warn"}">${esc(p.status)}</span></td>
      <td>${editable(p) ? `<button class="btn ghost small" data-off="${esc(p.id)}">Offboard</button>` : ""}</td></tr>`).join("")}
    ${(d.invites || []).map((i) => `<tr><td>${esc(i.name)}<div class="muted">${esc(i.email)}</div></td><td>${esc((d.roles[i.role] || {}).name || i.role)}</td><td><span class="pill warn">invited</span></td><td class="muted">until ${esc(i.expires)}</td></tr>`).join("")}
    </tbody></table>${d.solo ? '<p class="muted">Solo mode: one active person; every decision is flagged in the evidence.</p>' : ""}
    ${(d.conflicts || []).map((c) => `<div class="verdict warn">${esc(c.person)}: ${esc(c.flag)}</div>`).join("")}</div>
    ${owner ? `<div class="card"><h2>Invite someone</h2><div class="formgrid"><label>Name<input id="lv-name"></label><label>Email<input id="lv-email"></label><label>Role<select id="lv-role">${opts("approver")}</select></label></div>
      <div class="row"><button class="btn" id="lv-inv">Create invite</button></div><div id="lv-msg"></div></div>` : ""}
    <div class="card"><h2>My SSH public key (signs plan approvals)</h2><p class="muted">Paste your public key line (ssh-ed25519 …). Approvals of machine plans are signed with the matching private key, which never leaves your machine.</p>
      <label>Public key<input id="lv-key"></label><div class="row"><button class="btn ghost" id="lv-keygo">Register key</button></div><div id="lv-keymsg"></div></div>`;
  if (owner) $("#lv-inv").onclick = async () => {
    const x = await pro("people/invite", { name: $("#lv-name").value, email: $("#lv-email").value, role: $("#lv-role").value });
    $("#lv-msg").innerHTML = x.ok ? `<div class="verdict ok">Invite for <b>${esc(x.data.id)}</b>: one-time code <code>${esc(x.data.code)}</code> — shown once, valid 24 hours.</div>` : notice(x);
  };
  $$("[data-role]").forEach((s) => (s.onchange = async () => { const x = await pro(`people/${s.dataset.role}/role`, { role: s.value }); if (!x.ok) alert(x.data.error || "refused"); livePeople(box); }));
  $$("[data-off]").forEach((b) => (b.onclick = async () => { if (!confirm(`Offboard ${b.dataset.off}? Their access is revoked everywhere.`)) return;
    const x = await pro(`people/${b.dataset.off}/offboard`, {}); if (!x.ok) alert(x.data.error || "refused"); livePeople(box); }));
  $("#lv-keygo").onclick = async () => { const x = await pro("people/me/ssh-key", { key: $("#lv-key").value.trim() });
    $("#lv-keymsg").innerHTML = x.ok ? '<div class="verdict ok">Key registered.</div>' : notice(x); };
}

async function liveApprovals(box) {
  const r = await pro("approvals");
  if (!r.ok) { box.innerHTML = signOutBar() + notice(r); return; }
  const items = r.data.items || [];
  box.innerHTML = signOutBar() + (items.length ? "" : '<div class="card"><p class="muted">Nothing waits for approval.</p></div>') + items.map((a) => `<div class="card" data-item="${esc(a.id)}">
    <div class="card-h"><h2>${esc(a.title)}</h2><span class="pill ${a.state === "approved" ? "ok" : a.state === "rejected" ? "crit" : "warn"}">${esc(a.state)}</span></div>
    <p>Requested by <b>${esc(a.requested_by)}</b> · ${esc(a.kind === "plan" ? "machine plan" : "rule book change")} · <code>${esc((a.fingerprint || "").slice(0, 16))}…</code></p>
    <ul>${(a.changes || []).map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
    ${a.state !== "waiting" ? `<p class="muted">${esc(a.note || "")}</p>` : a.why_not ? `<p class="denied">${esc(a.why_not)}</p>` : `
      ${a.kind === "plan" ? `<details><summary>Sign this approval with your SSH key</summary><p class="muted">Save the text below as approval.json, then run <code>${esc(a.to_sign ? a.to_sign.command : "")}</code> and paste the contents of approval.json.sig.</p>
        <pre class="mono">${esc(a.to_sign ? a.to_sign.message : "")}</pre><label>Signature<textarea data-sig></textarea></label></details>` : ""}
      <label>Reason (needed to reject)<input data-reason></label>
      <div class="row"><button class="btn" data-approve>Approve</button><button class="btn ghost" data-reject>Reject</button></div>`}
    <div data-out></div></div>`).join("");
  $$("[data-item]").forEach((card) => {
    const a = items.find((x) => x.id === card.dataset.item), out = card.querySelector("[data-out]");
    const send = async (verb) => {
      const body = { reason: (card.querySelector("[data-reason]") || {}).value || "" };
      if (a.kind === "plan" && a.to_sign) Object.assign(body, { signature: (card.querySelector("[data-sig]") || {}).value || "", nonce: a.to_sign.nonce, expires_at: a.to_sign.expires_at });
      const x = await pro(`approvals/${encodeURIComponent(a.id)}/${verb}`, body);
      if (!x.ok) { out.innerHTML = notice(x); return; }
      liveApprovals(box);
    };
    const ap = card.querySelector("[data-approve]"), rj = card.querySelector("[data-reject]");
    if (ap) ap.onclick = () => send("approve");
    if (rj) rj.onclick = () => send("reject");
  });
}

async function liveRules(box) {
  const r = await pro("rules");
  if (!r.ok) { box.innerHTML = signOutBar() + notice(r); return; }
  const d = r.data, edit = d.can_edit;
  if (!d.rules || !d.rules.length) { box.innerHTML = signOutBar() + '<div class="card"><p class="muted">No rule book yet. Set NIYANTRAK_PRO_RULEBOOK to your rule book file and restart the panel.</p></div>'; return; }
  box.innerHTML = signOutBar() + `<p class="muted">${esc(d.name)} · version ${esc(d.version)}</p><div class="rulegrid">
    <div class="card"><table class="rules"><thead><tr><th>Rule</th><th>Says</th><th>Then</th><th>Status</th></tr></thead><tbody>
    ${d.rules.map((x) => `<tr data-lr="${esc(x.id)}"><td class="mono">${esc(x.id)}</td><td>${esc(x.says)}</td><td>${esc(x.then)}</td><td><span class="pill ${x.status === "enforced" ? "ok" : "warn"}">${esc(x.status)}</span></td></tr>`).join("")}</tbody></table></div>
    <div class="card"><h2>Test on a sample message</h2><label>Sample<input id="lr-text" value="My card is 4111 1111 1111 1111, please refund 2,500"></label>
      <div class="row"><button class="btn ghost" id="lr-test">Test</button></div><div id="lr-out"></div><div id="lr-edit"></div></div></div>`;
  $("#lr-test").onclick = async () => {
    const x = await pro("rules/test", { text: $("#lr-text").value });
    $("#lr-out").innerHTML = x.ok ? `<div class="verdict ${x.data.decision === "allow" ? "ok" : x.data.decision === "deny" ? "crit" : "warn"}">Decision: ${esc(x.data.decision)}${x.data.rule_ids.length ? " · by " + esc(x.data.rule_ids.join(", ")) : ""}${x.data.entities.length ? " · found " + esc(x.data.entities.join(", ")) : ""}</div>` : notice(x);
  };
  $$("[data-lr]").forEach((tr) => (tr.onclick = () => {
    const x = d.rules.find((y) => y.id === tr.dataset.lr);
    $("#lr-edit").innerHTML = `<h2 class="mono">${esc(x.id)}</h2>${edit ? `<label>Says<textarea id="le-says">${esc(x.says)}</textarea></label>
      <label>Then<select id="le-then">${(d.actions || []).map((a) => `<option ${a === x.then ? "selected" : ""}>${esc(a)}</option>`).join("")}</select></label>
      <div class="row"><button class="btn" id="le-go">Propose change</button></div><div id="le-out"></div>` : '<p class="denied">Read only — the governance officer proposes rule changes.</p>'}`;
    if (edit) $("#le-go").onclick = async () => {
      const y = await pro("rules/propose", { rule: { ...x.source, says: $("#le-says").value, then: $("#le-then").value } });
      $("#le-out").innerHTML = y.ok ? `<div class="verdict warn">Proposed as ${esc(y.data.id)} (version ${esc(y.data.version)}). It waits in Approvals for a second person.</div><ul>${y.data.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : notice(y);
    };
  }));
}

async function liveAudit(box) {
  const r = await pro("audit");
  if (!r.ok) { box.innerHTML = signOutBar() + notice(r); return; }
  const d = r.data;
  box.innerHTML = signOutBar() + `<div class="grid2">${d.chains.map((c) => `<div class="card"><h2>${esc(c.name)}</h2>
      <div class="verdict ${c.ok ? "ok" : "crit"}">${c.ok ? "Chain verifies" : "Chain broken at line " + esc(c.first_bad_line) + ": " + esc(c.reason)} · ${esc(c.records)} records</div></div>`).join("")}</div>
    <div class="card"><h2>Recent actions</h2>${(d.recent || []).map((e) => `<div class="arow"><code>${esc((e.ts || "").slice(0, 16))}</code><span class="ring"></span><div><b>${esc(e.who)}</b> ${esc(e.action)} ${esc(e.target || "")}</div><span class="route ${e.outcome === "refused" ? "block" : ""}">${esc(e.outcome || "")}</span></div>`).join("") || '<p class="muted">No actions recorded yet.</p>'}</div>
    <div class="card"><h2>Evidence pack</h2><div class="formgrid"><label>From<input id="ae-since" type="date"></label><label>Until<input id="ae-until" type="date"></label></div>
      <div class="row"><button class="btn" id="ae-go">Export summary</button></div><pre id="ae-out" class="mono"></pre></div>`;
  $("#ae-go").onclick = async () => {
    const x = await pro("audit/export", { since: $("#ae-since").value || null, until: $("#ae-until").value || null });
    $("#ae-out").textContent = x.ok ? JSON.stringify(x.data, null, 2) : (x.data.error || "refused");
  };
}

async function liveCompliance(box) {
  const r = await pro("compliance");
  if (!r.ok) { box.innerHTML = signOutBar() + notice(r); return; }
  const d = r.data;
  box.innerHTML = signOutBar() + `<div class="grid3">${(d.frameworks || []).map((f) => `<div class="card"><h2>${esc(f.name)}</h2><p>${esc(f.rules)} rule(s) cite it · ${esc(f.enforced)} enforced</p><p class="muted mono">${esc(f.citations.join(", "))}</p></div>`).join("") || '<div class="card"><p class="muted">No rule cites a law or standard yet.</p></div>'}</div>`;
}

/* ── Boot ───────────────────────────────────────────────────────────────────────────────────────────── */
function loadDemo() {
  if (BUNDLE) {
    state.node = BUNDLE.node; state.peers = BUNDLE.peers; state.joins = BUNDLE.joins; state.counts = BUNDLE.counts;
    $("#t-found").textContent = Object.values(state.counts).reduce((a, b) => a + b, 0).toLocaleString();
    $("#host").textContent = "on " + BUNDLE.node.hostname; $("#demo-badge").hidden = false;
    $("#demo-badge").title = BUNDLE.label;
    return;
  }
  const ok = (name) => ({ name, ok: true });
  state.node = { hostname: "control-01", node_id: "nyk-3fa91c2d7e10", role: "control", os: "ubuntu 24.04", bootstrapped: true,
    ipv4: ["192.0.2.10"], ipv6: ["fe80::a1%eth0"],
    checks: [ok("Audit rules record sensitive changes"), ok("Remote login hardened (keys only, no root)"), ok("Secrets folder private"), ok("Login status page installed")] };
  state.peers = {
    "nyk-7b20e4c1a9f3": { node_id: "nyk-7b20e4c1a9f3", hostname: "ai-node-01", role: "GPU worker", os: "ubuntu 24.04 · RTX 5090", ipv4: ["192.0.2.14"], ipv6: ["fe80::b2%eth0"], verified: true, seen_at: "just now" },
    "nyk-c04d19ee2b77": { node_id: "nyk-c04d19ee2b77", hostname: "edge-01", role: "edge", os: "ubuntu 24.04", ipv4: ["198.51.100.20"], ipv6: [], verified: true, seen_at: "1 min ago" },
    "nyk-9e5512ab03c8": { node_id: "nyk-9e5512ab03c8", hostname: "laptop-07", role: "developer laptop", os: "windows 11", ipv4: [], ipv6: ["fe80::c7%Ethernet"], verified: false, seen_at: "2 min ago" } };
  state.counts = { PHONE: 412, EMAIL: 268, AADHAAR: 131, CARD: 94, IBAN: 57, PAN: 49, US_SSN: 22 };
  $("#t-found").textContent = Object.values(state.counts).reduce((a, b) => a + b, 0).toLocaleString();
  $("#host").textContent = "on control-01"; $("#demo-badge").hidden = false;
}

(async function boot() {
  try {
    const n = await api("node");
    state.node = n;
    $("#host").textContent = n.hostname ? "on " + n.hostname : "";
  } catch (e) {}
  try { state.peers = (await api("peers")).peers || {}; } catch (e) {}
  if (DEMO) loadDemo();
  else { try { CAPS = await api("capabilities"); } catch (e) { CAPS = { screens: {} }; } applyCaps(); }
  refreshCounts();
  if (DEMO) { const c = state.counts; await scan(); state.counts = c; $("#t-found").textContent = Object.values(c).reduce((a, b) => a + b, 0).toLocaleString(); }
  else scan();
  const start = (location.hash || "#overview").slice(1);
  show(TITLES[start] ? start : "overview");
  setTimeout(() => window.scrollTo(0, 0), 0);
  addEventListener("load", () => window.scrollTo(0, 0), { once: true });
  addEventListener("load", redrawOpenScreen);
})();
function redrawOpenScreen() {         // the chart library may arrive after the open screen was first drawn
  const id = currentScreen();
  if (id === "overview") drawCharts();
  if (id === "activity") drawActivity();
}
