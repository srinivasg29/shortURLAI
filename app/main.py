from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.database import init_db
from app.routers import analytics, redirect, shorten


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Agentic URL Shortener",
    description="Production-grade URL shortener with create, redirect, and analytics APIs.",
    version="0.1.0",
    lifespan=lifespan,
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(shorten.router)
app.include_router(analytics.router)
# Catch-all single-segment redirect route must be registered last so it
# doesn't shadow the static routes above (e.g. /health, /metrics).
app.include_router(redirect.router)
