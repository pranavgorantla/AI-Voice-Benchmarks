"""
SQLAlchemy models and DB session management.

Schema:
  trial_results   — one row per (platform, scenario, trial_num)
  scenario_results — one row per (platform, scenario); aggregated from trials

The DB is SQLite by default.  DATABASE_URL can be overridden in .env.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Generator

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class TrialResult(Base):
    """One row per trial execution."""

    __tablename__ = "trial_results"

    id = Column(Integer, primary_key=True, index=True)
    trial_id = Column(String, unique=True, index=True, nullable=False)
    platform = Column(String, nullable=False, index=True)
    scenario_id = Column(String, nullable=False, index=True)
    trial_num = Column(Integer, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    error = Column(Text, nullable=True)

    # Raw and canonical events stored as JSON strings
    raw_events_json = Column(Text, nullable=True)
    canonical_events_json = Column(Text, nullable=True)

    # Per-trial metric values (seconds)
    # time_to_first_response: list of measurements, one per user turn
    ttfr_measurements_json = Column(Text, nullable=True)
    # barge_in_response_time: list of measurements, one per barge-in
    barge_in_measurements_json = Column(Text, nullable=True)
    # Scalar pass/fail metrics
    tool_call_accuracy = Column(Float, nullable=True)   # 1.0 or 0.0
    turn_completion = Column(Float, nullable=True)      # 1.0 or 0.0

    @property
    def ttfr_measurements(self) -> list[float]:
        return json.loads(self.ttfr_measurements_json or "[]")

    @property
    def barge_in_measurements(self) -> list[float]:
        return json.loads(self.barge_in_measurements_json or "[]")

    @property
    def raw_events(self) -> list[dict[str, Any]]:
        return json.loads(self.raw_events_json or "[]")

    @property
    def canonical_events(self) -> list[dict[str, Any]]:
        return json.loads(self.canonical_events_json or "[]")


class ScenarioResult(Base):
    """
    Aggregated results for one (platform, scenario) pair.

    Re-computed from trial_results whenever new trials are added.
    """

    __tablename__ = "scenario_results"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, nullable=False, index=True)
    scenario_id = Column(String, nullable=False, index=True)
    trial_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # time_to_first_response aggregates (seconds)
    ttfr_median = Column(Float, nullable=True)
    ttfr_p95 = Column(Float, nullable=True)
    ttfr_n = Column(Integer, nullable=True)

    # barge_in_response_time aggregates (seconds)
    barge_in_median = Column(Float, nullable=True)
    barge_in_p95 = Column(Float, nullable=True)
    barge_in_n = Column(Integer, nullable=True)

    # tool_call_accuracy: rate across trials (0.0–1.0)
    tool_call_accuracy_rate = Column(Float, nullable=True)

    # turn_completion_rate: rate across trials (0.0–1.0)
    turn_completion_rate = Column(Float, nullable=True)


def init_db() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Write helpers ─────────────────────────────────────────────────────────────

def save_trial(
    db: Session,
    *,
    trial_id: str,
    platform: str,
    scenario_id: str,
    trial_num: int,
    raw_events: list[dict[str, Any]],
    canonical_events_dicts: list[dict[str, Any]],
    ttfr_measurements: list[float],
    barge_in_measurements: list[float],
    tool_call_accuracy: float,
    turn_completion: float,
    error: str | None = None,
) -> TrialResult:
    row = TrialResult(
        trial_id=trial_id,
        platform=platform,
        scenario_id=scenario_id,
        trial_num=trial_num,
        error=error,
        raw_events_json=json.dumps(raw_events),
        canonical_events_json=json.dumps(canonical_events_dicts),
        ttfr_measurements_json=json.dumps(ttfr_measurements),
        barge_in_measurements_json=json.dumps(barge_in_measurements),
        tool_call_accuracy=tool_call_accuracy,
        turn_completion=turn_completion,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def recompute_scenario_result(
    db: Session,
    *,
    platform: str,
    scenario_id: str,
) -> ScenarioResult:
    """
    Pull all trials for (platform, scenario_id) and recompute aggregates.
    Upserts a ScenarioResult row.
    """
    import numpy as np

    trials: list[TrialResult] = (
        db.query(TrialResult)
        .filter(
            TrialResult.platform == platform,
            TrialResult.scenario_id == scenario_id,
            TrialResult.error.is_(None),
        )
        .all()
    )

    all_ttfr: list[float] = []
    all_barge: list[float] = []
    tool_scores: list[float] = []
    turn_scores: list[float] = []

    for t in trials:
        all_ttfr.extend(t.ttfr_measurements)
        all_barge.extend(t.barge_in_measurements)
        if t.tool_call_accuracy is not None:
            tool_scores.append(t.tool_call_accuracy)
        if t.turn_completion is not None:
            turn_scores.append(t.turn_completion)

    def _median(vals: list[float]) -> float | None:
        return float(np.median(vals)) if vals else None

    def _p95(vals: list[float]) -> float | None:
        return float(np.percentile(vals, 95)) if vals else None

    existing = (
        db.query(ScenarioResult)
        .filter(
            ScenarioResult.platform == platform,
            ScenarioResult.scenario_id == scenario_id,
        )
        .first()
    )

    if existing is None:
        existing = ScenarioResult(platform=platform, scenario_id=scenario_id)
        db.add(existing)

    existing.trial_count = len(trials)
    existing.updated_at = datetime.utcnow()
    existing.ttfr_median = _median(all_ttfr)
    existing.ttfr_p95 = _p95(all_ttfr)
    existing.ttfr_n = len(all_ttfr)
    existing.barge_in_median = _median(all_barge)
    existing.barge_in_p95 = _p95(all_barge)
    existing.barge_in_n = len(all_barge)
    existing.tool_call_accuracy_rate = (
        float(np.mean(tool_scores)) if tool_scores else None
    )
    existing.turn_completion_rate = (
        float(np.mean(turn_scores)) if turn_scores else None
    )

    db.commit()
    db.refresh(existing)
    return existing
