"""
FastAPI application entry point.

Serves:
  /api/results          — aggregated leaderboard JSON
  /api/trials/{id}      — per-trial detail JSON
  /webhooks/vapi/{id}   — Vapi webhook receiver
  /webhooks/retell/{id} — Retell webhook receiver
  /                     — static leaderboard frontend
"""

from __future__ import annotations

import os
import pathlib

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..harness.storage import init_db
from .routes import router

FRONTEND_DIR = pathlib.Path(__file__).parent.parent / "frontend"

app = FastAPI(
    title="Voice AI Eval Harness",
    description="Benchmarking API for production voice AI platforms",
    version="0.1.0",
)

app.include_router(router)

# Serve the static frontend at /
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")


@app.on_event("startup")
async def startup() -> None:
    init_db()


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=port, reload=False)
