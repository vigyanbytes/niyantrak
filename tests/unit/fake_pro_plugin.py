"""Test plugins for the panel plugin host (not shipped). Each `register*` is what an entry point would resolve to."""


def register(host):
    host.plugin(name="fake-pro", version="9.9")
    host.capability("approvals", api="/api/pro/approvals", label="Approvals (live)")
    host.capability("people", api="/api/pro/people")
    host.route("GET", "/api/pro/approvals", lambda ctx: (200, {"items": [{"id": "PL-1"}], "q": ctx.query}))
    host.route("POST", "/api/pro/approvals", lambda ctx: (200, {"echo": ctx.body, "local": ctx.local,
                                                               "path": ctx.path}))
    host.route("GET", "/api/pro/people", people)
    host.route("GET", "/api/pro/boom", boom)
    host.route("GET", "/api/pro/cookie", lambda ctx: (200, {"cookie": ctx.headers.get("cookie")},
                                                      {"Set-Cookie": "s=1; HttpOnly; Path=/api/pro"}))


def people(ctx):
    if ctx.headers.get("x-role") != "owner":                 # a plugin enforcing its own roles
        return 403, {"error": "owner only"}
    return 200, {"people": []}


def boom(ctx):
    raise RuntimeError("database exploded")


def register_broken(host):
    host.capability("audit", api="/api/pro/audit")
    host.route("GET", "/api/pro/audit", lambda ctx: (200, {}))
    raise RuntimeError("licence file missing")


def register_bad_route(host):
    host.route("GET", "/api/node", lambda ctx: (200, {"hijacked": True}))


def register_bad_screen(host):
    host.capability("fleet", api="/api/pro/fleet")


not_callable = 42
