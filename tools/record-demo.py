#!/usr/bin/env python3
"""record-demo — screenshots, a walkthrough video and a GIF preview of the panel with the sample team's data.

    python3 tools/demo-data.py --out dist/demo --end 2026-10-23
    python3 tools/build-demo.py dist/demo/demo.html --bundle dist/demo/bundle.json
    python3 tools/record-demo.py dist/demo/demo.html --out docs/media

Writes <out>/screens/<page>.png, <out>/niyantrak-walkthrough.mp4 (and .webm) and <out>/niyantrak-walkthrough.gif.
Needs Playwright (`pip install playwright`) and a Chromium: the installed google-chrome is used when present, else
Playwright's own (`python -m playwright install chromium`). ffmpeg turns the recording into MP4 and GIF. Headless;
nothing is sent anywhere except the chart library loaded from jsDelivr by the page itself.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

PAGES = ["try", "overview", "fleet", "activity", "decisions", "rules", "proof"]
SIZE = {"width": 1440, "height": 900}
TRY_TEXT = ("Hi, I am Ramesh. My Aadhaar is 2345 6789 0124 and PAN ABCPE1234F. "
            "Please refund Rs 1,200 to ramesh@okhdfc and confirm on +91 98450 12345.")
CAPTION_JS = """(t) => { let c = document.getElementById('rec-caption');
  if (!c) { c = document.createElement('div'); c.id = 'rec-caption'; document.body.appendChild(c);
    Object.assign(c.style, {position: 'fixed', left: '50%', bottom: '28px', transform: 'translateX(-50%)', zIndex: 9999,
      background: 'rgba(17,24,39,.92)', color: '#fff', font: '600 20px Inter, system-ui, sans-serif',
      padding: '12px 22px', borderRadius: '10px', maxWidth: '80%', textAlign: 'center', boxShadow: '0 6px 24px rgba(0,0,0,.25)'}); }
  c.textContent = t; c.hidden = !t; }"""


def browser(pw):
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    return pw.chromium.launch(headless=True, executable_path=chrome) if chrome else pw.chromium.launch(headless=True)


def settle(page, ms=1800, screen=None):
    """Wait for the page and the chart library, then draw the screen again (charts drawn before it loaded are empty)."""
    page.wait_for_load_state("networkidle")
    page.wait_for_function("() => !!window.echarts", timeout=20000)
    if screen:
        page.evaluate("(p) => show(p)", screen)
    page.wait_for_timeout(ms)


def screenshots(pw, url, out):
    os.makedirs(os.path.join(out, "screens"), exist_ok=True)
    b = browser(pw)
    shots = []
    for p in PAGES:
        page = b.new_page(viewport=SIZE)
        page.goto(f"{url}#{p}")
        settle(page, screen=p)
        path = os.path.join(out, "screens", f"{p}.png")
        page.screenshot(path=path)
        shots.append(path)
        page.close()
    b.close()
    return shots


def walkthrough(pw, url, tmp):
    b = browser(pw)
    ctx = b.new_context(viewport=SIZE, record_video_dir=tmp, record_video_size=SIZE)
    page = ctx.new_page()
    cap = lambda t: page.evaluate(CAPTION_JS, t)
    go = lambda p: page.evaluate("(p) => show(p)", p)
    page.goto(f"{url}#try")
    settle(page, 800)
    cap("Niyantrak — enterprise AI governance, open evaluation edition (sample data, fictional team)")
    page.wait_for_timeout(3500)
    cap("Try it: paste a customer message — this is what a model would receive")
    page.fill("#msg", "")
    page.type("#msg", TRY_TEXT, delay=18)
    page.click("#go")
    page.wait_for_timeout(5000)
    cap("Identifiers are checksum-validated: Aadhaar (Verhoeff), card (Luhn), PAN, UPI, phone")
    page.wait_for_timeout(4500)
    for step, text, wait in (
            ("overview", "Overview: this machine's governance checks and what was found", 7000),
            ("fleet", "Fleet: machines join with a signed card over pinned TLS; the operator approves", 7000),
            ("activity", "Activity (6W): who · which agent · which project · what · where · why — labels and counts only", 8000)):
        go(step)
        page.wait_for_timeout(600)
        cap(text)
        page.wait_for_timeout(wait)
    cap("Click to filter: everything Codex did this week")
    page.evaluate("() => { ACT.filter = { k: 'agent', v: 'Codex' }; drawActivity(); }")
    page.wait_for_timeout(6500)
    cap("Hard stops: force-push, rm -r, credential files and production changes are blocked or need approval")
    page.evaluate("() => { ACT.filter = { k: 'what', v: 'Read file' }; drawActivity(); }")
    page.wait_for_timeout(5500)
    page.evaluate("() => { ACT.filter = null; drawActivity(); }")
    for step, text, wait in (
            ("decisions", "Decisions: an append-only log — status is derived, never edited in place", 8000),
            ("rules", "Rule book: what the gateway and the agent gate enforce", 6000),
            ("proof", "Proof: every test, coverage and the leak scan, kept in the repository", 7000)):
        go(step)
        page.wait_for_timeout(600)
        cap(text)
        page.wait_for_timeout(wait)
    cap("Ask the 6W store in SQL: niyantrak telemetry ask \"who ran destructive commands this week\"")
    page.wait_for_timeout(5000)
    cap("Open evaluation edition, Apache-2.0 · github.com/vigyanbytes/niyantrak")
    page.wait_for_timeout(3500)
    video = page.video.path()
    ctx.close()
    b.close()
    return video


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("html", help="demo page from tools/build-demo.py --bundle")
    ap.add_argument("--out", default="docs/media")
    ap.add_argument("--no-video", action="store_true")
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright
    url = "file://" + os.path.abspath(a.html)
    os.makedirs(a.out, exist_ok=True)
    with sync_playwright() as pw:
        for s in screenshots(pw, url, a.out):
            print("wrote", s)
        if a.no_video:
            return 0
        tmp = tempfile.mkdtemp(prefix="niyantrak-rec-")
        try:
            raw = walkthrough(pw, url, tmp)
            webm, mp4, gif = (os.path.join(a.out, f"niyantrak-walkthrough.{x}") for x in ("webm", "mp4", "gif"))
            ffmpeg("-i", raw, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "42", "-row-mt", "1", webm)
            ffmpeg("-i", raw, "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p",
                   "-movflags", "+faststart", mp4)
            pal = os.path.join(tmp, "palette.png")
            vf = "fps=6,setpts=0.4*PTS,scale=800:-1:flags=lanczos"         # 2.5x speed, small enough for a README
            ffmpeg("-i", mp4, "-vf", f"{vf},palettegen=max_colors=96:stats_mode=diff", pal)    # from the MP4: less
            ffmpeg("-i", mp4, "-i", pal, "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", gif)   # noise, smaller GIF
            for f in (webm, mp4, gif):
                print(f"wrote {f} ({os.path.getsize(f) // 1024} KB)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
