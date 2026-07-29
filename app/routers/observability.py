from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from orchestrator import metrics

router = APIRouter(prefix="/orchestrator", tags=["observability"])


@router.get("/metrics")
def orchestrator_metrics() -> PlainTextResponse:
    """Prometheus exposition of Section 8's reliability metrics, computed
    fresh from the audit log on every request (a Gauge snapshot of derived
    state, not an in-process Counter) - see orchestrator/metrics.py."""
    computed = metrics.compute_reliability_metrics()
    registry = CollectorRegistry()

    Gauge(
        "orchestrator_run_count", "Total orchestrator runs recorded in the audit log",
        registry=registry,
    ).set(computed["run_count"])
    Gauge(
        "orchestrator_success_rate", "Fraction of runs that completed without a safe-stop",
        registry=registry,
    ).set(computed["success_rate"])
    Gauge(
        "orchestrator_avg_end_to_end_seconds", "Average end-to-end run duration, in seconds",
        registry=registry,
    ).set(computed["avg_end_to_end_seconds"])
    Gauge(
        "orchestrator_avg_human_wait_seconds",
        "Average time per run spent waiting on human-approval gates, in seconds",
        registry=registry,
    ).set(computed["avg_human_wait_seconds"])
    Gauge(
        "orchestrator_avg_automated_seconds",
        "Average time per run spent in automated execution, in seconds",
        registry=registry,
    ).set(computed["avg_automated_seconds"])
    Gauge(
        "orchestrator_safe_stop_count", "Total safe-stop events across all runs",
        registry=registry,
    ).set(computed["rollback"]["safe_stop_count"])
    Gauge(
        "orchestrator_rollback_count", "Total rollback actions taken at safe-stop",
        registry=registry,
    ).set(computed["rollback"]["rollback_count"])
    Gauge(
        "orchestrator_rollback_rate", "Fraction of safe-stops that included a rollback",
        registry=registry,
    ).set(computed["rollback"]["rollback_rate"])

    mttr = computed["mean_time_to_resolution_seconds"]
    if mttr is not None:
        Gauge(
            "orchestrator_mean_time_to_resolution_seconds",
            "Average time from safe-stop to human-resumed continuation, in seconds",
            registry=registry,
        ).set(mttr)

    retry_gauge = Gauge(
        "orchestrator_llm_retry_count", "LLM call retries, by node", ["node"], registry=registry
    )
    for node, count in computed["retry_frequency_by_node"].items():
        retry_gauge.labels(node=node).set(count)

    latency_gauge = Gauge(
        "orchestrator_llm_latency_ms_avg",
        "Average successful LLM call latency in milliseconds, by node",
        ["node"],
        registry=registry,
    )
    call_gauge = Gauge(
        "orchestrator_llm_call_count", "Successful LLM calls, by node", ["node"], registry=registry
    )
    for node, stats in computed["llm_latency_ms_by_node"].items():
        latency_gauge.labels(node=node).set(stats["avg_latency_ms"])
        call_gauge.labels(node=node).set(stats["count"])

    return PlainTextResponse(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@router.get("/runs/{run_id}")
def orchestrator_run_timeline(run_id: str) -> list[dict]:
    """Human-readable reconstruction of one run's decision lineage from the
    durable audit trail - audit-grade traceability independent of whether
    the run's in-memory OrchestratorState still exists."""
    timeline = metrics.run_timeline(run_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="no audit events found for that run_id")
    return timeline
