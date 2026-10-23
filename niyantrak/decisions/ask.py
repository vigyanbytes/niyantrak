"""Optional: answer a question about the decision graph with a LOCAL model (OpenAI-compatible /chat/completions).

Decision data is internal. The endpoint must be this machine, a private/LAN/tailnet address, or an mDNS .local
name; anything else is refused before a byte is sent (pass allow_host=<exact host> for a machine you own whose name
is not recognisably local). Proxies from the environment are ignored and redirects are not followed, so the
request cannot be steered elsewhere. The model only gets the exact rows that match the question.
"""
import ipaddress
import json
import os
import re
import urllib.parse
import urllib.request

from .graph import all_nodes

DEFAULT_URL = "http://127.0.0.1:8000/v1"
LOCAL_NETS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10")]
STATUS_WORDS = {"pending": ("DECISION", "pending"), "sign-off": ("DECISION", "pending"), "signoff": ("DECISION", "pending"),
                "superseded": ("DECISION", "superseded"), "in force": ("DECISION", "in force"),
                "retired": ("DECISION", "retired"),
                "blocked": ("WORK", "blocked"), "on hold": ("WORK", "blocked"), "in progress": ("WORK", "in progress"),
                "proposed": ("WORK", "proposed"), "to do": ("WORK", "to do"), "todo": ("WORK", "to do"),
                "done": ("WORK", "done"), "dropped": ("WORK", "dropped"), "deferred": ("WORK", "dropped")}
STOP = {"what", "which", "when", "where", "about", "decisions", "decision", "work", "items", "show", "list", "with",
        "that", "this", "have", "does", "from", "why"}


class RefusedEndpoint(ValueError):
    """The model endpoint is not local; nothing was sent."""


def is_local_endpoint(url, allow_host=None):
    try:
        u = urllib.parse.urlsplit(str(url or ""))
        host = (u.hostname or "").lower()
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not host:
        return False
    if allow_host and host == str(allow_host).lower():
        return True
    if host == "localhost" or (host.endswith(".local") and host.count(".") >= 1 and len(host) > 6):
        return True
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return any(ip in n for n in LOCAL_NETS if n.version == ip.version)


def rows_for(g, question):
    """Exact rows for a question: status words select by status; otherwise words of 4+ letters match id/title/text."""
    ql = str(question or "").lower()
    picks = sorted({v for k, v in STATUS_WORDS.items() if k in ql})
    ns = [n for n in all_nodes(g) if n["kind"] in ("DECISION", "WORK")]
    newest = lambda rows: sorted(sorted(rows, key=lambda n: n["id"]), key=lambda n: str(n["ts"] or ""), reverse=True)
    out = []
    if picks:
        for kind, status in picks:
            out += newest([n for n in ns if n["kind"] == kind and n["status"] == status])
    else:
        words = [w for w in re.findall(r"[a-z0-9][a-z0-9-]{3,}", ql) if w not in STOP]
        if words:
            out = newest([n for n in ns if any(w in f"{n['id']} {n['title'] or ''} {n['text'] or ''}".lower() for w in words)])
    return [{"kind": n["kind"].lower(), "id": n["id"], "status": n["status"], "ts": n["ts"], "title": n["title"],
             "text": n["text"]} for n in out]


def _post(url, body, timeout=300):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=timeout) as r:
        return json.load(r)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def ask(g, question, endpoint=None, model=None, allow_host=None, list_only=False, max_tokens=900, post=None, env=None):
    """{"rows": exact matching rows, "answer": model text or None, "endpoint": url}. Raises RefusedEndpoint."""
    env = os.environ if env is None else env
    url = endpoint or env.get("NIYANTRAK_LLM_URL") or DEFAULT_URL
    if not is_local_endpoint(url, allow_host):
        host = urllib.parse.urlsplit(url).hostname if "://" in str(url) else url
        raise RefusedEndpoint(f"refusing {host!s}: decision data may only go to a local model "
                              "(this machine, a private or tailnet address, or a .local name)")
    rows = rows_for(g, question)
    out = {"rows": rows, "answer": None, "endpoint": url}
    if not rows or list_only:
        return out
    ids = {r["id"] for r in rows}
    lines = ["# Rows (kind | id | status | date | title | detail)"]
    lines += [f"{r['kind']} | {r['id']} | {r['status']} | {str(r['ts'] or '')[:10]} | {r['title'] or ''} | {(r['text'] or '')[:200]}"
              for r in rows]
    lines += ["", "# Links between these rows (from -> to : kind)"]
    lines += [f"{e['source']} -> {e['target']} : {e['kind']}" for e in g["edges"] if e["source"] in ids or e["target"] in ids]
    body = {"model": model or env.get("NIYANTRAK_LLM_MODEL") or "local-model", "temperature": 0.1, "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": "You answer questions about a decision log and work ledger. Use ONLY the data "
                 "given. Cite item ids in brackets. If the data does not say, answer 'not recorded'. Plain English, short."},
                {"role": "user", "content": "DATA\n" + "\n".join(lines) + f"\n\nQUESTION\n{question}"}]}
    resp = (post or _post)(url.rstrip("/") + "/chat/completions", body)
    out["answer"] = resp["choices"][0]["message"]["content"].strip()
    return out
