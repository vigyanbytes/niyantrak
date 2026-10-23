"""As-built docs: deterministic Markdown + HTML + SVG from node cards and the join store (golden files)."""
import copy
import json
import os
import pathlib

import pytest

from niyantrak import docs

FIX = pathlib.Path(__file__).parent / "fixtures" / "docs"
GOLDEN = FIX / "golden"


def inputs():
    d = json.loads((FIX / "input.json").read_text())
    return docs.collect(d["join"], local=d["local"])


def test_collect_merges_local_and_joined_nodes():
    nodes = inputs()["nodes"]
    assert [n["node_id"] for n in nodes] == ["nyk-aaaaaaaaaaa0", "nyk-aaaaaaaaaaa1", "nyk-aaaaaaaaaaa2", "nyk-aaaaaaaaaaa3"]
    local = nodes[0]
    assert local["source"] == "this machine" and local["state"] == "this machine" and len(local["checks"]) == 3
    assert nodes[1]["state"] == "approved" and len(nodes[1]["host_key_sha256"]) == 64


def test_render_page_set():
    pages = docs.render(inputs())
    assert set(pages) == {"index.md", "index.html", "network-map.svg", "manifest.json",
                          *(f"node-nyk-aaaaaaaaaaa{i}.{ext}" for i in range(4) for ext in ("md", "html"))}
    idx = pages["index.md"]
    for want in ("# Fleet as built", "| gpu-01 |", "approved", "pending", "rejected", "network-map.svg"):
        assert want in idx
    node = pages["node-nyk-aaaaaaaaaaa1.md"]
    for want in ("## Hardware", "## Operating system", "## Addresses", "## Roles", "## Governance checks",
                 "Example GPU 32GB", "192.0.2.14", "2001:db8::14", "worker", "card signature verified at join"):
        assert want in node, want
    ctl = pages["node-nyk-aaaaaaaaaaa0.md"]
    assert "Secrets folder private" in ctl and "FAIL" in ctl


def test_no_keys_or_token_hashes_in_output():
    blob = "".join(docs.render(inputs()).values())
    assert "FIXTUREKEY" not in blob and "tokenhash" not in blob and "ssh-ed25519" not in blob


def test_untrusted_card_text_is_escaped():
    pages = docs.render(inputs())
    assert "<b>7</b>" not in pages["node-nyk-aaaaaaaaaaa2.html"] and "&lt;b&gt;7&lt;/b&gt;" in pages["node-nyk-aaaaaaaaaaa2.html"]
    assert "<b>7</b>" not in pages["network-map.svg"] and "<b>" not in pages["index.html"]
    assert "laptop-&lt;b&gt;7&lt;/b&gt; \\| x" in pages["index.md"]    # Markdown: no raw HTML, pipe escaped
    assert "<b>" not in pages["node-nyk-aaaaaaaaaaa2.md"]


def test_svg_is_wellformed():
    import xml.etree.ElementTree as ET
    root = ET.fromstring(docs.render(inputs())["network-map.svg"])
    assert root.tag.endswith("svg")
    text = docs.render(inputs())["network-map.svg"]
    assert "192.0.2.0/24" in text and "198.51.100.0/24" in text and "IPv6 link-local only" in text


def test_deterministic_regardless_of_input_order():
    d = json.loads((FIX / "input.json").read_text())
    a = docs.render(docs.collect(d["join"], local=d["local"]))
    d2 = copy.deepcopy(d)
    d2["join"]["nodes"] = dict(reversed(list(d2["join"]["nodes"].items())))
    for n in d2["join"]["nodes"].values():
        n["card"]["addresses"]["ipv6"] = list(reversed(n["card"]["addresses"]["ipv6"]))
    b = docs.render(docs.collect(d2["join"], local=d2["local"]))
    assert a == b


def test_golden_output():
    pages = docs.render(inputs())
    if os.environ.get("NIYANTRAK_UPDATE_GOLDEN"):
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for f, body in pages.items():
            (GOLDEN / f).write_bytes(body.encode())
    golden = {p.name: p.read_bytes() for p in GOLDEN.iterdir()}
    assert {f: b.encode() for f, b in pages.items()} == golden


def test_write_is_byte_identical_and_removes_stale(tmp_path):
    out = tmp_path / "docs"
    changed = docs.write(str(out), docs.render(inputs()))
    assert len(changed) == 12
    snap = {p.name: p.read_bytes() for p in out.iterdir()}
    assert docs.write(str(out), docs.render(inputs())) == []          # same input → nothing rewritten
    assert {p.name: p.read_bytes() for p in out.iterdir()} == snap
    (out / "notes-by-hand.txt").write_text("keep me")
    d = json.loads((FIX / "input.json").read_text())
    del d["join"]["nodes"]["nyk-aaaaaaaaaaa3"]
    docs.write(str(out), docs.render(docs.collect(d["join"], local=d["local"])))
    names = {p.name for p in out.iterdir()}
    assert "node-nyk-aaaaaaaaaaa3.md" not in names and "notes-by-hand.txt" in names


def test_list_pages(tmp_path):
    out = tmp_path / "docs"
    assert docs.list_pages(str(out)) == []
    docs.write(str(out), docs.render(inputs()))
    pages = docs.list_pages(str(out))
    assert pages[0] == {"file": "index.html", "md": "index.md", "title": "Fleet as built", "kind": "fleet"}
    assert {"file": "network-map.svg", "md": None, "title": "Network map", "kind": "map"} in pages
    assert any(p["title"] == "gpu-01" and p["kind"] == "node" for p in pages)


def test_empty_fleet_renders():
    pages = docs.render(docs.collect({}, local=None))
    assert "No machines recorded yet" in pages["index.md"] and "<svg" in pages["network-map.svg"]


def test_cli_docs_generate(tmp_path, capsys):
    from niyantrak.cli import main
    store = tmp_path / "join.json"
    store.write_text(json.dumps(json.loads((FIX / "input.json").read_text())["join"]))
    out = tmp_path / "docs"
    assert main(["docs", "generate", "--out", str(out), "--join-store", str(store), "--no-local"]) == 0
    assert (out / "node-nyk-aaaaaaaaaaa1.html").exists() and "wrote" in capsys.readouterr().out
    assert main(["docs", "generate", "--out", str(out), "--join-store", str(store), "--no-local"]) == 0
    assert "unchanged" in capsys.readouterr().out
