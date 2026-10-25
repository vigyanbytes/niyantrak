/* Standalone demo: replaces the panel's server API with in-page logic and sample data.
   Detection is the same checksum-validated rules as niyantrak/recognizers.py, ported to JavaScript. Nothing leaves the page. */
(function () {
  const VD = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],
    [5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]];
  const VP = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],
    [4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]];
  const digits = (s) => s.replace(/\D/g, "");
  const verhoeff = (n) => { let c = 0; [...n].reverse().forEach((ch, i) => { c = VD[c][VP[i % 8][+ch]]; }); return c === 0; };
  const aadhaar = (s) => { const d = digits(s); return d.length === 12 && !"01".includes(d[0]) && verhoeff(d); };
  const luhn = (s) => { const d = digits(s); if (d.length < 13 || d.length > 19) return false; let t = 0;
    [...d].reverse().forEach((ch, i) => { let n = +ch; if (i % 2) { n *= 2; if (n > 9) n -= 9; } t += n; }); return t % 10 === 0; };
  const B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const gstin = (s) => { s = s.toUpperCase(); if (s.length !== 15) return false; let t = 0;
    for (let i = 0; i < 14; i++) { const p = B36.indexOf(s[i]) * (i % 2 ? 2 : 1); t += Math.floor(p / 36) + (p % 36); }
    return B36[(36 - (t % 36)) % 36] === s[14]; };
  const iban = (s) => { s = s.replace(/\s/g, "").toUpperCase(); if (s.length < 15 || s.length > 34) return false;
    const r = s.slice(4) + s.slice(0, 4); let num = ""; for (const c of r) num += B36.indexOf(c);
    return BigInt(num) % 97n === 1n; };
  const pan = (s) => "PCHFATBLJG".includes(s[3].toUpperCase());
  const ssn = (s) => { const d = digits(s); return d.length === 9 && !["000", "666"].includes(d.slice(0, 3)) && d[0] !== "9" && d.slice(3, 5) !== "00" && d.slice(5) !== "0000"; };
  const B = "(?<![\\w@.])", E = "(?![\\w@])";
  const RULES = [
    ["AADHAAR", B + "[2-9]\\d{3}[\\s-]?\\d{4}[\\s-]?\\d{4}" + E, aadhaar],
    ["PAN", B + "[A-Za-z]{5}\\d{4}[A-Za-z]" + E, pan],
    ["GSTIN", B + "\\d{2}[A-Za-z]{5}\\d{4}[A-Za-z][1-9A-Za-z][Zz][0-9A-Za-z]" + E, gstin],
    ["IFSC", B + "[A-Z]{4}0[A-Z0-9]{6}" + E, null],
    ["UPI_ID", B + "[a-zA-Z0-9][a-zA-Z0-9._-]{1,255}@[a-zA-Z]{2,64}(?![\\w.@])", null],
    ["IN_PHONE", "(?<![\\w+])(?:\\+91[\\s-]?|0)?[6-9]\\d{4}[\\s-]?\\d{5}" + E, null],
    ["IBAN", B + "[A-Z]{2}\\d{2}(?:\\s?[A-Z0-9]{4}){2,7}(?:\\s?[A-Z0-9]{1,4})?" + E, iban],
    ["UK_NINO", B + "(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z]{2}\\s?\\d{2}\\s?\\d{2}\\s?\\d{2}\\s?[A-D]" + E, null],
    ["US_SSN", B + "\\d{3}-\\d{2}-\\d{4}" + E, ssn],
    ["EMAIL", B + "[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}" + E, null],
    ["CARD", B + "\\d{4}(?:[\\s-]?\\d{4}){2}[\\s-]?\\d{1,7}" + E, luhn],
    ["PHONE", "(?<![\\w+])\\+(?:[1-9]\\d{0,2})[\\s-]?\\d{2,4}(?:[\\s-]?\\d{2,4}){2,3}" + E, null],
  ].map(([e, rx, ok]) => [e, new RegExp(rx, "g"), ok]);
  function scan(text) {
    let spans = [];
    for (const [e, rx, ok] of RULES) { rx.lastIndex = 0; let m; while ((m = rx.exec(text))) { if (!ok || ok(m[0])) spans.push([m.index, m.index + m[0].length, e]); } }
    spans.sort((a, b) => a[0] - b[0] || (b[1] - b[0]) - (a[1] - a[0]));
    const keep = []; let end = -1; for (const s of spans) if (s[0] >= end) { keep.push(s); end = s[1]; }
    const n = {}; let out = "", pos = 0;
    for (const [s, t, e] of keep) { n[e] = (n[e] || 0) + 1; out += text.slice(pos, s) + `<${e}_${n[e]}>`; pos = t; }
    return { masked: out + text.slice(pos), counts: n };
  }
  // Sample decision log (made up): two decisions, one replacing the other, and open work.
  const N = (id, kind, status, ts, title, extra) => ({ id, kind, status, ts, title, text: null, user: null, agent: null, product: null, session: null, auto_closed: null, ...extra });
  const DEMO_DECISIONS = { empty: false,
    nodes: [N("DEC-101", "DECISION", "superseded", "2026-03-02", "Bots may send masked text to any cloud model"),
      N("DEC-114", "DECISION", "in force", "2026-04-11", "Card and health details stay on the local GPU", { agent: "officer-assistant", product: "support-bot" }),
      N("DEC-120", "DECISION", "pending", "2026-05-06", "Keep chat transcripts 90 days, then erase"),
      N("WORK-31", "WORK", "in progress", "2026-05-08", "Route health questions to the local model"),
      N("WORK-32", "WORK", "blocked", "2026-05-09", "Second GPU for the support bot", { text: "Waiting for budget approval" }),
      N("WORK-33", "WORK", "proposed", "2026-05-10", "Weekly evidence pack for the auditor"),
      N("WORK-29", "WORK", "done", "2026-04-20", "Mask UPI ids in WhatsApp replies"),
      N("support-bot", "THING", null, null, "Support bot")],
    links: [{ source: "DEC-101", target: "DEC-114", kind: "SUPERSEDED_BY" }, { source: "DEC-114", target: "support-bot", kind: "ABOUT" },
      { source: "WORK-31", target: "DEC-114", kind: "REFERENCES" }, { source: "WORK-32", target: "WORK-31", kind: "REFERENCES" },
      { source: "DEC-120", target: "support-bot", kind: "ABOUT" }, { source: "WORK-29", target: "support-bot", kind: "ABOUT" }],
    counts: { "d:in force": 1, "d:pending": 1, "d:superseded": 1, "w:blocked": 1, "w:done": 1, "w:in progress": 1, "w:proposed": 1, THING: 1 },
    open: [{ key: "d:pending", label: "Decisions waiting for sign-off", items: [{ id: "DEC-120", ts: "2026-05-06", title: "Keep chat transcripts 90 days, then erase" }] },
      { key: "w:blocked", label: "Blocked / on hold", items: [{ id: "WORK-32", ts: "2026-05-09", title: "Second GPU for the support bot" }] },
      { key: "w:in progress", label: "In progress", items: [{ id: "WORK-31", ts: "2026-05-08", title: "Route health questions to the local model" }] },
      { key: "w:proposed", label: "Proposed — waiting for a yes", items: [{ id: "WORK-33", ts: "2026-05-10", title: "Weekly evidence pack for the auditor" }] }] };
  const BUNDLE = window.NIYANTRAK_DEMO_DATA || null;     // tools/demo-data.py --> build-demo.py --bundle (sample team)
  function bundleActivity(path) {
    const q = new URLSearchParams(path.split("?")[1] || ""), k = q.get("k"), v = q.get("v");
    if (!k) return BUNDLE.activity;
    return BUNDLE.activity_by[k + "=" + v] || { empty: true, reason: "No sample events for this filter." };
  }
  window.NIYANTRAK_STANDALONE = true;
  window.niyantrakApi = async function (path, body) {
    if (path === "scan") { const r = scan(String(body.text || "").slice(0, 20000)); return { ...r, session_counts: r.counts }; }
    if (BUNDLE && path === "node") return BUNDLE.node;
    if (BUNDLE && path === "peers") return { peers: BUNDLE.peers };
    if (BUNDLE && path === "nodes") return { nodes: BUNDLE.joins };
    if (BUNDLE && path.split("?")[0] === "activity") return bundleActivity(path);
    if (BUNDLE && path === "decisions") return BUNDLE.decisions;
    if (path === "node") return { hostname: "control-01", node_id: "nyk-3fa91c2d7e10", bootstrapped: false, checks: [] };
    if (path === "peers") return { peers: {} };
    if (path === "nodes") return { nodes: {} };
    if (path === "proof") { if (window.NIYANTRAK_PROOF) return window.NIYANTRAK_PROOF; throw new Error("No proof run yet — run tools/prove.py"); }
    if (path.split("?")[0] === "activity") return { empty: true, reason: "This is the offline demo: activity comes from the 6W store in the installed panel." };
    if (path === "decisions") return DEMO_DECISIONS;
    if (path === "docs") return { pages: [], empty: true };
    if (path === "docs/regenerate") throw new Error("This is the offline demo: documents are generated by the installed panel.");
    if (path === "discover") return { peers: {}, message: "This is the offline demo: discovery runs in the installed panel." };
    throw new Error("not available in the demo");
  };
})();
