"""5W activity telemetry: who · whom · where · what · why (+ agent, route, rule ids, outcome, entity counts).

    schema  validate one event; reject fields outside the allow-list, free text and identifier values
    sink    OTLP/HTTP JSON logs (POST /v1/logs) and plain JSON events (POST /v1/events) -> 5W events
    store   append-only Parquet segments per writer + hash-chained manifest; materialize, compact, DuckDB queries

The schema module is standard library only. The store and the sink's writer need the optional extra
`pip install niyantrak[telemetry]` (pyarrow + duckdb); without it the panel shows sample activity.
See docs/5W.md.
"""
