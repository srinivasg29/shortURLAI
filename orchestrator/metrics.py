from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings

Event = dict[str, Any]


def load_events(path: str | Path | None = None) -> list[Event]:
    """Reads the JSONL audit log into memory. This is the single source of
    truth every metric below is computed from - no separate in-process
    counters to keep in sync with it."""
    audit_path = Path(path) if path is not None else Path(get_settings().audit_log_path)
    if not audit_path.exists():
        return []

    events: list[Event] = []
    with audit_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def group_by_run(events: list[Event]) -> dict[str, list[Event]]:
    runs: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        run_id = event.get("run_id")
        if run_id:
            runs[run_id].append(event)
    return dict(runs)


def success_rate(events: list[Event]) -> float:
    """Fraction of runs that did not end in a safe-stop."""
    runs = group_by_run(events)
    if not runs:
        return 0.0
    safe_stopped = sum(
        1 for evts in runs.values() if any(e["type"] == "safe_stop" for e in evts)
    )
    return (len(runs) - safe_stopped) / len(runs)


def retry_frequency_by_node(events: list[Event]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        if event["type"] == "llm_retry":
            counts[event.get("node", "unknown")] += 1
    return dict(counts)


def rollback_stats(events: list[Event]) -> dict[str, float]:
    safe_stops = [e for e in events if e["type"] == "safe_stop"]
    rollbacks = [e for e in safe_stops if e.get("rollback")]
    rate = len(rollbacks) / len(safe_stops) if safe_stops else 0.0
    return {
        "safe_stop_count": len(safe_stops),
        "rollback_count": len(rollbacks),
        "rollback_rate": rate,
    }


def mean_time_to_resolution_seconds(events: list[Event]) -> float | None:
    """Average time between a safe_stop event and the next gate_resume in
    the same run - how long a run sat halted before a human continued it.
    None if no safe-stop has ever been resumed."""
    runs = group_by_run(events)
    durations: list[float] = []
    for evts in runs.values():
        evts_sorted = sorted(evts, key=lambda e: e["timestamp"])
        pending_since: datetime | None = None
        for event in evts_sorted:
            if event["type"] == "safe_stop":
                pending_since = _parse_ts(event["timestamp"])
            elif event["type"] == "gate_resume" and pending_since is not None:
                durations.append((_parse_ts(event["timestamp"]) - pending_since).total_seconds())
                pending_since = None
    return sum(durations) / len(durations) if durations else None


def latency_breakdown_by_run(events: list[Event]) -> dict[str, dict[str, float]]:
    """Per-run end-to-end duration split into human-approval wait time
    (the gap between the last event before a gate_resume and the resume
    itself - i.e. while the graph sat interrupted) vs. automated time."""
    runs = group_by_run(events)
    result: dict[str, dict[str, float]] = {}
    for run_id, evts in runs.items():
        evts_sorted = sorted(evts, key=lambda e: e["timestamp"])
        if len(evts_sorted) < 2:
            continue

        total_seconds = (
            _parse_ts(evts_sorted[-1]["timestamp"]) - _parse_ts(evts_sorted[0]["timestamp"])
        ).total_seconds()

        human_wait_seconds = 0.0
        for i in range(1, len(evts_sorted)):
            if evts_sorted[i]["type"] == "gate_resume":
                prev_ts = _parse_ts(evts_sorted[i - 1]["timestamp"])
                cur_ts = _parse_ts(evts_sorted[i]["timestamp"])
                human_wait_seconds += (cur_ts - prev_ts).total_seconds()

        result[run_id] = {
            "total_seconds": total_seconds,
            "human_wait_seconds": human_wait_seconds,
            "automated_seconds": max(total_seconds - human_wait_seconds, 0.0),
        }
    return result


def llm_latency_by_node(events: list[Event]) -> dict[str, dict[str, float]]:
    by_node: dict[str, list[float]] = defaultdict(list)
    for event in events:
        if event["type"] == "llm_call" and event.get("success") and event.get("latency_ms"):
            by_node[event.get("node", "unknown")].append(event["latency_ms"])
    return {
        node: {"count": len(values), "avg_latency_ms": sum(values) / len(values)}
        for node, values in by_node.items()
    }


def run_timeline(run_id: str, events: list[Event] | None = None) -> list[Event]:
    """All audit events for one run, in chronological order - the
    human-readable reconstruction of a single run's decision lineage from
    the durable audit trail, independent of whether the in-memory
    OrchestratorState for that run still exists."""
    events = events if events is not None else load_events()
    return sorted(
        (e for e in events if e.get("run_id") == run_id),
        key=lambda e: e["timestamp"],
    )


def compute_reliability_metrics(events: list[Event] | None = None) -> dict[str, Any]:
    """The plan's Section 8 metrics (success rate, retry/rollback frequency,
    MTTR, end-to-end latency split), plus Section 7's per-node LLM latency,
    all in one place. Recomputed fresh from the audit log every call rather
    than tracked incrementally in-process, so it's always consistent with
    what actually happened, including across process restarts."""
    events = events if events is not None else load_events()

    latencies = latency_breakdown_by_run(events)
    n = len(latencies)
    avg_total = sum(v["total_seconds"] for v in latencies.values()) / n if n else 0.0
    avg_human = sum(v["human_wait_seconds"] for v in latencies.values()) / n if n else 0.0
    avg_automated = sum(v["automated_seconds"] for v in latencies.values()) / n if n else 0.0

    return {
        "run_count": len(group_by_run(events)),
        "success_rate": success_rate(events),
        "retry_frequency_by_node": retry_frequency_by_node(events),
        "rollback": rollback_stats(events),
        "mean_time_to_resolution_seconds": mean_time_to_resolution_seconds(events),
        "avg_end_to_end_seconds": avg_total,
        "avg_human_wait_seconds": avg_human,
        "avg_automated_seconds": avg_automated,
        "llm_latency_ms_by_node": llm_latency_by_node(events),
    }
