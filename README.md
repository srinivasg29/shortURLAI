# Agentic URL Shortener

A production-grade URL Shortener service, built alongside a LangGraph-based agentic SDLC
orchestrator that coordinates requirement understanding, planning, architecture, coding, testing,
review, and documentation for changes to this same codebase — with human approval gates, bounded
re-planning, and audit-grade traceability.

> Status: under active build-out. This README is filled in incrementally per phase; see
> [docs/workflow_gate_reference.md](docs/workflow_gate_reference.md) and
> [FINAL_ENGINEERING_SUMMARY.md](FINAL_ENGINEERING_SUMMARY.md) once those phases land.

## Project Overview

- `app/` — the FastAPI URL Shortener service (create, redirect, analytics).
- `orchestrator/` — the LangGraph agentic orchestration layer that plans and implements changes
  to `app/`, gated by automated checks and human approval.
- `scenarios/` — three end-to-end orchestrator runs (greenfield, brownfield, ambiguous) with
  committed transcripts under `scenarios/transcripts/`.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv\Scripts\Activate.ps1 in PowerShell
pip install -e ".[dev]"
cp .env.example .env
```

## Running the Service

```bash
uvicorn app.main:app --reload
```

- `POST /api/shorten` — create a short URL (`{"target_url": "https://..."}`).
- `GET /{code}` — 302 redirect to the target URL; records a click asynchronously.
- `GET /api/urls/{code}/stats` — click count and metadata for a short code.
- `GET /health` — liveness check.
- `GET /metrics` — Prometheus metrics.
- `GET /docs` — interactive OpenAPI docs (`/openapi.json` for the raw schema).

By default the service uses a local SQLite file (`data/shortener.db`) and an in-process TTL
cache for the redirect hot path. Set `REDIS_URL` in `.env` to use Redis instead.

## Running the Agentic Orchestrator

_Filled in during Phase 5+._
