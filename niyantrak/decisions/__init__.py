"""Decision graph: what was decided, what replaced it, and what work is open — as append-only events.

    from niyantrak.decisions import Store, graph
    s = Store()                                   # $NIYANTRAK_DECISIONS, else <state root>/decisions
    s.append([{"kind": "DECISION", "src": "DEC-1", "title": "..."}], writer="hook")
    g = graph.derive(s.events())                  # statuses derived, never stored
    graph.open_items(g); graph.export_graph(g); graph.materialize(s)

Standard library only; `pyarrow` (Parquet segments) and `duckdb` (SQL views) are used when installed.
CLI: python3 -m niyantrak.decisions --help
"""
from . import graph, schema  # noqa: F401
from .store import Store  # noqa: F401
