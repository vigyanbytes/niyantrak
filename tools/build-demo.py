#!/usr/bin/env python3
"""Build a single-file, offline-capable demo of the Niyantrak panel (sample data, in-page masking).

    python3 tools/build-demo.py [out.html] [--bundle dist/demo/bundle.json]    # default: dist/niyantrak-demo.html

Inlines app.css, standalone-shim.js and app.js into index.html and forces sample-data mode. Charts load ECharts from
jsDelivr when online; everything else works offline. The Proof screen shows real numbers: proof/latest/summary.json and
the last 30 lines of proof/history.jsonl are embedded as they are at build time. With --bundle (written by
tools/demo-data.py) the Overview, Fleet, Activity (5W) and Decisions screens show that fictional team's data, computed
by the real 5W store and decision log, labelled "Sample data".
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB = os.path.join(ROOT, "niyantrak", "web")
sys.path.insert(0, ROOT)
from niyantrak import proof  # noqa: E402


def proof_script(proof_dir):
    """window.NIYANTRAK_PROOF = {summary, history} | null — safe to inline in a <script> ('<' escaped)."""
    d = proof.load_proof(proof_dir, 30)
    if d:
        d["source"] = "from the repository's latest proof run"
    return "window.NIYANTRAK_PROOF = " + json.dumps(d).replace("<", "\\u003c") + ";\n"


def bundle_script(path):
    """window.NIYANTRAK_DEMO_DATA = <bundle.json> — safe to inline ('<' escaped)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return "window.NIYANTRAK_DEMO_DATA = " + json.dumps(data, sort_keys=True).replace("<", "\\u003c") + ";\n"


def build(out, proof_dir=None, bundle=None):
    html = open(os.path.join(WEB, "index.html")).read()
    css = open(os.path.join(WEB, "app.css")).read()
    shim = (proof_script(proof_dir or os.path.join(ROOT, "proof")) + (bundle_script(bundle) if bundle else "")
            + open(os.path.join(WEB, "standalone-shim.js")).read())
    app = open(os.path.join(WEB, "app.js")).read()
    # the demo always runs on sample data and calls the in-page API
    app = app.replace("const DEMO = /[?&]demo=1/.test(location.search);", "const DEMO = true;")
    app = app.replace("async function api(path, body) {", "async function api(path, body) {\n  if (window.niyantrakApi) return window.niyantrakApi(path, body);")
    for bad in ("</script", "<!--"):
        assert bad not in css + shim + app, f"cannot inline: contains {bad}"
    html = html.replace('<link rel="stylesheet" href="static/app.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="static/app.js" defer></script>', "")
    html = html.replace("</body>", f"<script>\n{shim}\n</script>\n<script>\n{app}\n</script>\n</body>")
    html = html.replace("<title>Niyantrak Panel</title>", "<title>Niyantrak Panel — demo</title>")
    html = html.replace('<span class="pill ok" id="gate">Running on this machine</span>',
                        '<span class="pill info" id="gate">Demo · runs in your browser</span>')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, "w").write(html)
    return html


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "dist", "niyantrak-demo.html"))
    ap.add_argument("--bundle", help="bundle.json from tools/demo-data.py (sample team data for the screens)")
    a = ap.parse_args()
    target = a.out
    page = build(target, bundle=a.bundle)
    print(f"wrote {target} ({len(page) // 1024} KB)")
