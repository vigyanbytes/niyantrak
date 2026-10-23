"""Web panel: serves the page, scans without echoing values, reports node status."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from niyantrak.panel import Handler


def start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_page_and_scan():
    srv, url = start()
    try:
        page = urllib.request.urlopen(url + "/").read().decode()
        assert "Try it" in page and "Niyantrak" in page and "Add machine" in page
        assert b"function show" in urllib.request.urlopen(url + "/static/app.js").read()
        assert json.load(urllib.request.urlopen(url + "/api/peers"))["peers"] is not None
        req = urllib.request.Request(url + "/api/scan", data=json.dumps({"text": "PAN ABCPE1234F, call +91 98450 12345"}).encode(),
                                     headers={"Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req))
        assert "<PAN_1>" in d["masked"] and "ABCPE1234F" not in json.dumps(d) and d["session_counts"]["PAN"] >= 1
        assert json.load(urllib.request.urlopen(url + "/api/node"))["bootstrapped"] in (True, False)
    finally:
        srv.shutdown()
