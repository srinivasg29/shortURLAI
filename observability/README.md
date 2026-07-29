# Observability

Two Prometheus scrape targets, both served by the running FastAPI app (`app/main.py`):

| Endpoint | Source | What it covers |
|---|---|---|
| `GET /metrics` | `prometheus-fastapi-instrumentator` | HTTP-level service metrics: request rate, latency, status codes for the URL shortener API. |
| `GET /orchestrator/metrics` | `app/routers/observability.py` → `orchestrator/metrics.py` | Section 8's reliability metrics — success rate, retry/rollback frequency by node, MTTR, end-to-end latency split into automated vs. human-approval wait time — computed fresh from the audit log (`AUDIT_LOG_PATH`) on every scrape. |

`GET /orchestrator/runs/{run_id}` (not a Prometheus endpoint) returns one run's full audit
timeline as JSON — the human-readable reconstruction of a single run's decision lineage,
independent of whether that run's in-memory `OrchestratorState` still exists.

## Wiring it up locally

```bash
# 1. Run the app (writes/reads the audit log at AUDIT_LOG_PATH, default ./audit_log.jsonl)
uvicorn app.main:app

# 2. Point Prometheus at it
docker run -p 9090:9090 \
  -v "$(pwd)/observability/prometheus.yml:/etc/prometheus/prometheus.yml" \
  prom/prometheus

# 3. Point Grafana at Prometheus, then import grafana-dashboard.json
docker run -p 3000:3000 grafana/grafana
```

`prometheus.yml` scrapes `host.docker.internal:8000` — adjust if the app runs elsewhere.
`grafana-dashboard.json` is a real, importable Grafana dashboard (Dashboards → Import → Upload
JSON) with panels for every metric above, plus one panel driven by the plain `/metrics` endpoint
to show request throughput isn't invisible just because this doc focuses on the orchestrator.

## Tracing

`app/tracing.py` configures an OpenTelemetry `TracerProvider` with a `ConsoleSpanExporter` —
every orchestrator node execution (`orchestrator/graph.py`) and every FastAPI request
(`FastAPIInstrumentor`, wired in `app/main.py`) emits a span to stdout. Each run gets a parent
`run` (or `run_resume`) span; every node it executes nests under that span with `run_id` and
(when applicable) `gate_id`/`gate_passed` attributes — so a single run's trace tree is
reconstructable from stdout alone, no external collector required for local development.

Swapping the Console exporter for a real OTLP exporter (Jaeger, Tempo, a vendor backend) is a
one-line change in `app/tracing.py`'s `_provider()` — nothing else in the codebase references the
exporter directly, every caller goes through `get_tracer()`.

## Where the underlying data comes from

Nothing here is tracked incrementally in-process. `orchestrator/metrics.py` recomputes every
metric from the JSONL audit log (`orchestrator/audit.py`) on each request, which is also the
audit trail `state["gate_log"]`/`state["replan_log"]` mirror to durable storage. That means the
Prometheus numbers are always consistent with what the audit log actually recorded — including
after a process restart — rather than a separate set of counters that could drift from it.
