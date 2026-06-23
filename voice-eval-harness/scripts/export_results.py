"""
Export the current leaderboard to /docs/ for static GitHub Pages hosting.

Copies the frontend and writes a pre-fetched results.json so the leaderboard
can be served as a fully static site without a running backend.

Usage:
  python -m scripts.export_results

Output:
  docs/
    index.html
    leaderboard.js
    style.css
    results.json
    trials.json
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.harness.storage import SessionLocal, ScenarioResult, TrialResult, init_db
from src.api.routes import _serialize_scenario_result, _serialize_trial_summary

FRONTEND_DIR = pathlib.Path(__file__).parent.parent / "src" / "frontend"
DOCS_DIR = pathlib.Path(__file__).parent.parent / "docs"


def main() -> None:
    init_db()
    db = SessionLocal()

    try:
        results = [
            _serialize_scenario_result(r)
            for r in db.query(ScenarioResult).all()
        ]
        trials = [
            _serialize_trial_summary(t)
            for t in db.query(TrialResult)
            .order_by(TrialResult.started_at.desc())
            .limit(500)
            .all()
        ]
    finally:
        db.close()

    DOCS_DIR.mkdir(exist_ok=True)

    # Copy static assets
    for f in ["index.html", "leaderboard.js", "style.css"]:
        src = FRONTEND_DIR / f
        if src.exists():
            shutil.copy(src, DOCS_DIR / f)

    # Patch leaderboard.js to use static JSON instead of /api/results
    lb_js = (DOCS_DIR / "leaderboard.js").read_text()
    lb_js = lb_js.replace(
        'fetchJSON("/api/results")',
        'fetchJSON("results.json")',
    ).replace(
        'fetchJSON("/api/trials")',
        'fetchJSON("trials.json")',
    ).replace(
        'fetchJSON(`/api/trials/${trialId}`)',
        # Static export can't serve per-trial detail; fall back gracefully
        'Promise.reject(new Error("Per-trial detail not available in static export"))',
    )
    (DOCS_DIR / "leaderboard.js").write_text(lb_js)

    # Write JSON data files
    (DOCS_DIR / "results.json").write_text(json.dumps(results, indent=2))
    (DOCS_DIR / "trials.json").write_text(json.dumps(trials, indent=2))

    print(f"Exported {len(results)} scenario results and {len(trials)} trials to {DOCS_DIR}/")
    print("Push the docs/ directory to enable GitHub Pages static hosting.")


if __name__ == "__main__":
    main()
