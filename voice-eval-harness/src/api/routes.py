"""
API routes.

Endpoints:
  GET  /api/results                — leaderboard data (all platforms × scenarios)
  GET  /api/results/{platform}/{scenario_id}
                                   — single (platform, scenario) summary
  GET  /api/trials/{trial_id}      — per-trial detail with full event timeline
  GET  /api/docs/{name}            — serve raw markdown for README / methodology
  POST /webhooks/vapi/{trial_id}   — Vapi webhook receiver
  POST /webhooks/retell/{trial_id} — Retell webhook receiver
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

_HARNESS_ROOT = pathlib.Path(__file__).parents[2]   # src/api/ → src/ → voice-eval-harness/
_REPO_ROOT = _HARNESS_ROOT.parent                   # workspace root (where README lives on GitHub)
DOCS_FILES = {
    "readme": _REPO_ROOT / "README.md",
    "methodology": _HARNESS_ROOT / "methodology.md",
    "roadmap": _HARNESS_ROOT / "ROADMAP.md",
}

from ..harness.storage import ScenarioResult, TrialResult, get_db
from ..harness.webhook_store import WebhookStore

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Docs endpoints ────────────────────────────────────────────────────────────

@router.get("/api/docs/{name}")
def get_doc(name: str) -> Response:
    """Serve raw markdown text for README, methodology, or roadmap."""
    path = DOCS_FILES.get(name.lower())
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail=f"Doc {name!r} not found. Valid names: {list(DOCS_FILES)}")
    return Response(content=path.read_text(), media_type="text/plain; charset=utf-8")


# ── Leaderboard endpoints ─────────────────────────────────────────────────────

@router.get("/api/results")
def get_all_results(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return all scenario results for the leaderboard."""
    rows: list[ScenarioResult] = db.query(ScenarioResult).all()
    return [_serialize_scenario_result(r) for r in rows]


@router.get("/api/results/{platform}/{scenario_id}")
def get_scenario_result(
    platform: str,
    scenario_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = (
        db.query(ScenarioResult)
        .filter(
            ScenarioResult.platform == platform,
            ScenarioResult.scenario_id == scenario_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No results found")
    return _serialize_scenario_result(row)


@router.get("/api/trials")
def list_trials(
    platform: str | None = None,
    scenario_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    q = db.query(TrialResult)
    if platform:
        q = q.filter(TrialResult.platform == platform)
    if scenario_id:
        q = q.filter(TrialResult.scenario_id == scenario_id)
    rows = q.order_by(TrialResult.started_at.desc()).limit(200).all()
    return [_serialize_trial_summary(r) for r in rows]


@router.get("/api/trials/{trial_id}")
def get_trial_detail(trial_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    row: TrialResult | None = (
        db.query(TrialResult).filter(TrialResult.trial_id == trial_id).first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    return _serialize_trial_detail(row)


# ── Webhook receivers ─────────────────────────────────────────────────────────

@router.post("/webhooks/vapi/{trial_id}", status_code=200)
async def vapi_webhook(trial_id: str, request: Request) -> Response:
    """
    Receive Vapi webhook events and route them to the active trial queue.

    Vapi expects a 200 OK with an optional JSON response body.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    store = WebhookStore.instance()
    pushed = await store.push(trial_id, payload)

    if not pushed:
        logger.debug("Vapi webhook for unknown/expired trial %s (dropped)", trial_id)

    return Response(content=json.dumps({"status": "ok"}), media_type="application/json")


@router.post("/webhooks/retell/{trial_id}", status_code=200)
async def retell_webhook(trial_id: str, request: Request) -> Response:
    """
    Receive Retell webhook events and route them to the active trial queue.

    Retell expects a 200 OK.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    store = WebhookStore.instance()
    pushed = await store.push(trial_id, payload)

    if not pushed:
        logger.debug("Retell webhook for unknown/expired trial %s (dropped)", trial_id)

    return Response(content=json.dumps({"status": "ok"}), media_type="application/json")


# ── Serialisers ───────────────────────────────────────────────────────────────

def _serialize_scenario_result(r: ScenarioResult) -> dict[str, Any]:
    return {
        "platform": r.platform,
        "scenario_id": r.scenario_id,
        "trial_count": r.trial_count,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "ttfr": {
            "median_s": r.ttfr_median,
            "p95_s": r.ttfr_p95,
            "n": r.ttfr_n,
        },
        "barge_in": {
            "median_s": r.barge_in_median,
            "p95_s": r.barge_in_p95,
            "n": r.barge_in_n,
        },
        "tool_call_accuracy_rate": r.tool_call_accuracy_rate,
        "turn_completion_rate": r.turn_completion_rate,
    }


def _serialize_trial_summary(r: TrialResult) -> dict[str, Any]:
    return {
        "trial_id": r.trial_id,
        "platform": r.platform,
        "scenario_id": r.scenario_id,
        "trial_num": r.trial_num,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "error": r.error,
        "tool_call_accuracy": r.tool_call_accuracy,
        "turn_completion": r.turn_completion,
        "ttfr_measurements": r.ttfr_measurements,
        "barge_in_measurements": r.barge_in_measurements,
    }


def _serialize_trial_detail(r: TrialResult) -> dict[str, Any]:
    summary = _serialize_trial_summary(r)
    summary["canonical_events"] = r.canonical_events
    return summary
