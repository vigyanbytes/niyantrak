"""Charts drawn before the chart library (ECharts, loaded from a CDN) arrived are drawn again once it has loaded."""
import re
from pathlib import Path

JS = (Path(__file__).resolve().parents[2] / "niyantrak" / "web" / "app.js").read_text()


def test_open_screen_is_redrawn_when_the_chart_library_loads():
    # opening the panel straight at #activity (a bookmark or a reload) drew empty charts before this
    assert 'addEventListener("load", redrawOpenScreen)' in JS
    body = re.search(r"function redrawOpenScreen\(\) \{(.*?)\n\}", JS, re.S).group(1)
    for fn in ("drawCharts()", "drawActivity()"):
        assert fn in body
    assert 'addEventListener("load", drawCharts)' not in JS
