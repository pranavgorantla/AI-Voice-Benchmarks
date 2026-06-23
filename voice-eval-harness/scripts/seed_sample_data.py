"""
Seed the local SQLite database with realistic sample data.

Use this to verify the leaderboard renders correctly before running live trials.
Data is clearly labeled [example data] in the UI context — see README.

Usage:
  python -m scripts.seed_sample_data
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.harness.storage import (
    ScenarioResult,
    SessionLocal,
    TrialResult,
    init_db,
)

# Realistic-but-fictional sample data based on vendor marketing claims
# vs. typical production observations. Labeled [example data].
SAMPLE_RESULTS = [
    {
        "platform": "vapi",
        "scenario_id": "booking-simple",
        "trial_count": 10,
        "ttfr_median": 0.48,
        "ttfr_p95": 0.72,
        "ttfr_n": 20,
        "barge_in_median": None,
        "barge_in_p95": None,
        "barge_in_n": 0,
        "tool_call_accuracy_rate": 1.0,
        "turn_completion_rate": 1.0,
    },
    {
        "platform": "vapi",
        "scenario_id": "booking-interrupted",
        "trial_count": 10,
        "ttfr_median": 0.51,
        "ttfr_p95": 0.89,
        "ttfr_n": 30,
        "barge_in_median": 0.21,
        "barge_in_p95": 0.38,
        "barge_in_n": 20,
        "tool_call_accuracy_rate": 0.9,
        "turn_completion_rate": 0.9,
    },
    {
        "platform": "retell",
        "scenario_id": "booking-simple",
        "trial_count": 10,
        "ttfr_median": 0.44,
        "ttfr_p95": 0.61,
        "ttfr_n": 20,
        "barge_in_median": None,
        "barge_in_p95": None,
        "barge_in_n": 0,
        "tool_call_accuracy_rate": 1.0,
        "turn_completion_rate": 1.0,
    },
    {
        "platform": "retell",
        "scenario_id": "booking-interrupted",
        "trial_count": 10,
        "ttfr_median": 0.46,
        "ttfr_p95": 0.70,
        "ttfr_n": 30,
        "barge_in_median": 0.18,
        "barge_in_p95": 0.31,
        "barge_in_n": 20,
        "tool_call_accuracy_rate": 1.0,
        "turn_completion_rate": 1.0,
    },
]


def seed() -> None:
    init_db()
    db = SessionLocal()

    try:
        # Clear existing sample data
        db.query(ScenarioResult).delete()
        db.query(TrialResult).delete()
        db.commit()

        # Insert scenario results
        for s in SAMPLE_RESULTS:
            row = ScenarioResult(
                platform=s["platform"],
                scenario_id=s["scenario_id"],
                trial_count=s["trial_count"],
                updated_at=datetime.utcnow(),
                ttfr_median=s["ttfr_median"],
                ttfr_p95=s["ttfr_p95"],
                ttfr_n=s["ttfr_n"],
                barge_in_median=s["barge_in_median"],
                barge_in_p95=s["barge_in_p95"],
                barge_in_n=s["barge_in_n"],
                tool_call_accuracy_rate=s["tool_call_accuracy_rate"],
                turn_completion_rate=s["turn_completion_rate"],
            )
            db.add(row)

        # Insert a handful of representative trial rows
        for platform in ["vapi", "retell"]:
            for scenario_id in ["booking-simple", "booking-interrupted"]:
                for trial_num in range(1, 4):
                    import json
                    ttfr = [0.45 + trial_num * 0.02, 0.38 + trial_num * 0.01]
                    barge = [0.20 + trial_num * 0.01] if "interrupted" in scenario_id else []
                    tool_acc = 1.0
                    turn_comp = 1.0
                    row = TrialResult(
                        trial_id=str(uuid.uuid4()),
                        platform=platform,
                        scenario_id=scenario_id,
                        trial_num=trial_num,
                        started_at=datetime.utcnow(),
                        raw_events_json="[]",
                        canonical_events_json=json.dumps([
                            {"type": "user_speech_started", "timestamp": 0.0, "payload": {}},
                            {"type": "user_speech_ended", "timestamp": 3.2, "payload": {}},
                            {"type": "agent_speech_started", "timestamp": 3.2 + ttfr[0], "payload": {}},
                            {"type": "agent_speech_ended", "timestamp": 6.1, "payload": {}},
                            {"type": "user_speech_ended", "timestamp": 7.8, "payload": {}},
                            {"type": "tool_call_dispatched", "timestamp": 7.8 + ttfr[1], "payload": {
                                "name": "book_appointment",
                                "args": {
                                    "patient_name": "Alex Chen",
                                    "appointment_datetime": "2025-01-14T14:00:00" if "simple" in scenario_id else "2025-01-14T15:00:00",
                                },
                            }},
                            {"type": "tool_call_completed", "timestamp": 8.3, "payload": {"result": "success"}},
                            {"type": "agent_speech_started", "timestamp": 8.4, "payload": {}},
                            {"type": "agent_speech_ended", "timestamp": 10.2, "payload": {}},
                            {"type": "call_ended", "timestamp": 10.5, "payload": {}},
                        ]),
                        ttfr_measurements_json=json.dumps(ttfr),
                        barge_in_measurements_json=json.dumps(barge),
                        tool_call_accuracy=tool_acc,
                        turn_completion=turn_comp,
                    )
                    db.add(row)

        db.commit()
        print(f"Seeded {len(SAMPLE_RESULTS)} scenario results and sample trial rows.")
        print("Note: this is [example data]. Run the benchmark to replace it with real results.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
