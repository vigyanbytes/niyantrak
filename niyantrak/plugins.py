"""Panel plugin host. Standard library only; never imports any plugin package by name.

A plugin is a callable `register(host)` found through the Python entry point group `niyantrak.panel_plugins`
(importlib.metadata), or — for tests and local trials — the environment variable NIYANTRAK_PLUGINS, a comma-separated
list of `module:attribute` specs (set but empty = no plugins). Inside register() a plugin may call:

    host.plugin(name=..., version=...)                       # how it is shown in GET /api/capabilities
    host.capability(screen, api="/api/pro/...", label=...)   # screen in PRO_SCREENS: switches it from preview to live
    host.route(method, "/api/pro/...", handler)              # handler(ctx) -> (status, dict[, headers])

Routes match by path prefix (longest first) and only under /api/pro/. `ctx` is a RequestContext: method, path, query,
body, headers (lower-case names), client, local. The free host passes mutating calls (POST/PUT/PATCH/DELETE) only
when they come from this machine; the plugin enforces its own sign-in and roles on top. The host never vouches for
who the user is. A plugin that fails to load contributes nothing (its partial registrations are dropped); a handler
that raises returns 500 {"degraded": true}. Both are logged and the panel keeps running.
"""
import logging
import os
import re
from dataclasses import dataclass, field
from importlib import import_module, metadata

GROUP = "niyantrak.panel_plugins"
ENV = "NIYANTRAK_PLUGINS"
PREFIX = "/api/pro/"
PRO_SCREENS = ("approvals", "rules", "people", "audit", "compliance", "access")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PATH_RE = re.compile(r"^/api/pro/[A-Za-z0-9_\-/]*$")
log = logging.getLogger("niyantrak.plugins")


class PluginError(Exception):
    pass


@dataclass
class RequestContext:
    method: str
    path: str
    query: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    client: str = ""
    local: bool = False

    @property
    def mutating(self):
        return self.method in MUTATING


class Registrar:
    """What register() sees. Collects routes and capabilities; the host takes them only if register() succeeds."""

    def __init__(self, spec):
        self.spec = spec
        self.info = {"name": spec, "version": None}
        self.routes, self.caps = [], {}

    def plugin(self, name=None, version=None):
        if name:
            self.info["name"] = str(name)
        if version is not None:
            self.info["version"] = str(version)

    def capability(self, screen, api=None, label=None, **extra):
        if screen not in PRO_SCREENS:
            raise PluginError(f"unknown Pro screen {screen!r} (one of {', '.join(PRO_SCREENS)})")
        if api is not None and not str(api).startswith(PREFIX):
            raise PluginError(f"capability api must be under {PREFIX}")
        cap = {"api": api, **({"label": str(label)} if label else {}), **extra}
        self.caps[screen] = cap

    def route(self, method, prefix, handler):
        method = str(method).upper()
        if method not in METHODS:
            raise PluginError(f"method {method!r} not allowed")
        prefix = str(prefix)
        if not (prefix + "/").startswith(PREFIX) or not PATH_RE.match(prefix if prefix.endswith("/") else prefix + "/") \
                or "/../" in prefix + "/" or "//" in prefix:
            raise PluginError(f"route {prefix!r} must be under {PREFIX}")
        if not callable(handler):
            raise PluginError("handler must be callable")
        self.routes.append((method, prefix.rstrip("/"), handler))


class PluginHost:
    def __init__(self):
        self.plugins, self.errors = [], []
        self._routes, self._caps = [], {}

    def registrar(self, spec):
        return Registrar(spec)

    def commit(self, reg):
        name = reg.info["name"]
        self.plugins.append(dict(reg.info))
        for screen, cap in reg.caps.items():
            self._caps[screen] = {"plugin": name, **cap}
        self._routes += [(m, p, h, name) for m, p, h in reg.routes]
        self._routes.sort(key=lambda r: -len(r[1]))

    def fail(self, spec, err):
        msg = f"{type(err).__name__}: {err}"[:300]
        log.warning("panel plugin %s not loaded: %s", spec, msg)
        self.errors.append({"plugin": spec, "error": msg})

    def add(self, spec, fn):
        reg = self.registrar(spec)
        try:
            if not callable(fn):
                raise PluginError(f"{spec} is not callable")
            fn(reg)
        except Exception as e:                                # noqa: BLE001 — a plugin must never stop the panel
            return self.fail(spec, e)
        self.commit(reg)

    def capabilities(self):
        screens = {}
        for s in PRO_SCREENS:
            c = self._caps.get(s)
            screens[s] = {"live": True, **c} if c else {"live": False, "plugin": None}
        return {"edition": "pro" if self.plugins else "free", "screens": screens,
                "plugins": [dict(p) for p in self.plugins], "errors": [dict(e) for e in self.errors]}

    def match(self, method, path):
        for m, prefix, handler, name in self._routes:
            if m == method and (path == prefix or path.startswith(prefix + "/")):
                return handler, name
        return None

    def dispatch(self, ctx):
        """-> (status, body dict, headers dict). Never raises."""
        hit = self.match(ctx.method, ctx.path)
        if hit is None:
            return 404, {"error": "not found", "preview": not self.plugins}, {}
        handler, name = hit
        try:
            out = handler(ctx)
            if not isinstance(out, tuple) or len(out) not in (2, 3) or not isinstance(out[0], int):
                raise PluginError(f"handler returned {type(out).__name__}, expected (status, body[, headers])")
            status, body = out[0], out[1]
            headers = dict(out[2]) if len(out) == 3 and out[2] else {}
            return status, body, headers
        except Exception:                                     # noqa: BLE001
            log.exception("panel plugin %s failed on %s %s", name, ctx.method, ctx.path)
            return 500, {"error": "The Pro module could not answer this request. The panel keeps running; "
                                  "the details are in the panel log.", "degraded": True, "plugin": name}, {}


def _entry_points(group):
    try:
        return list(metadata.entry_points(group=group))
    except TypeError:                                         # Python < 3.10 style API
        return list(metadata.entry_points().get(group, []))


def _resolve(spec):
    mod, sep, attr = spec.partition(":")
    if not sep or not mod or not attr:
        raise PluginError(f"plugin spec {spec!r} must be module:attribute")
    obj = import_module(mod)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def load(specs=None, env=None):
    """Build a host from explicit specs, else NIYANTRAK_PLUGINS (when set), else the entry point group."""
    host = PluginHost()
    env = os.environ if env is None else env
    if specs is None and ENV in env:
        specs = [s.strip() for s in env[ENV].split(",") if s.strip()]
    if specs is not None:
        for spec in specs:
            try:
                fn = _resolve(spec)
            except Exception as e:                            # noqa: BLE001
                host.fail(spec, e)
                continue
            host.add(spec, fn)
        return host
    try:
        eps = _entry_points(GROUP)
    except Exception as e:                                    # noqa: BLE001
        host.fail(GROUP, e)
        return host
    for ep in eps:
        try:
            fn = ep.load()
        except Exception as e:                                # noqa: BLE001
            host.fail(ep.name, e)
            continue
        host.add(ep.name, fn)
    return host
