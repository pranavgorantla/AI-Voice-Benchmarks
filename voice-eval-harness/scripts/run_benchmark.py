"""
CLI entry point for running benchmarks.

Usage:
  python -m scripts.run_benchmark --platform vapi --scenario booking-simple --trials 3
  python -m scripts.run_benchmark --platform retell --scenario booking-interrupted
  python -m scripts.run_benchmark --platform all --scenario all   # run everything
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# Allow running from the voice-eval-harness directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.harness.adapters.vapi import VapiAdapter
from src.harness.adapters.retell import RetellAdapter
from src.harness.config import settings
from src.harness.runner import BenchmarkRunner
from src.harness.scenarios import list_scenario_ids
from src.harness.storage import SessionLocal, init_db


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_benchmark")

ADAPTERS = {
    "vapi": VapiAdapter,
    "retell": RetellAdapter,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the Voice AI Eval Harness benchmark.")
    p.add_argument(
        "--platform",
        required=True,
        choices=[*ADAPTERS.keys(), "all"],
        help="Platform to benchmark, or 'all' to run every registered platform.",
    )
    p.add_argument(
        "--scenario",
        default="all",
        help="Scenario ID (e.g. booking-simple), or 'all' to run every scenario.",
    )
    p.add_argument(
        "--trials",
        type=int,
        default=None,
        help=f"Number of trials per scenario (default: {settings.trials} from env).",
    )
    p.add_argument(
        "--rate-limit-rpm",
        type=int,
        default=None,
        dest="rate_limit_rpm",
        help=f"Max requests/minute to the platform API (default: {settings.rate_limit_rpm}).",
    )
    p.add_argument(
        "--webhook-base-url",
        default="",
        dest="webhook_base_url",
        help="Public base URL for webhook receiver (default: HARNESS_PUBLIC_URL env var).",
    )
    return p.parse_args()


async def run(args: argparse.Namespace) -> None:
    init_db()

    platforms = list(ADAPTERS.keys()) if args.platform == "all" else [args.platform]
    scenarios = list_scenario_ids() if args.scenario == "all" else [args.scenario]

    all_summaries = []

    for platform in platforms:
        adapter = ADAPTERS[platform]()
        db = SessionLocal()

        try:
            runner = BenchmarkRunner(
                adapter=adapter,
                db=db,
                trials=args.trials,
                rate_limit_rpm=args.rate_limit_rpm,
                webhook_base_url=args.webhook_base_url,
            )

            for scenario_id in scenarios:
                logger.info("═══ %s / %s ═══", platform.upper(), scenario_id)
                try:
                    summary = await runner.run_scenario(scenario_id)
                    all_summaries.append(summary)
                except Exception:
                    logger.exception("Fatal error in scenario %s", scenario_id)
        finally:
            db.close()

    # Print a compact results table
    print("\n\n══ RESULTS ══════════════════════════════════════════════════════")
    print(f"{'PLATFORM':<10} {'SCENARIO':<22} {'TTFR med':>10} {'TTFR p95':>10} {'TOOL%':>7} {'TURNS%':>7}")
    print("─" * 72)
    for s in all_summaries:
        def _ms(v):
            return f"{round(v*1000)} ms" if v is not None else "—"
        def _pct(v):
            return f"{round(v*100)}%" if v is not None else "—"
        print(
            f"{s['platform']:<10} {s['scenario_id']:<22} "
            f"{_ms(s['ttfr_median_s']):>10} {_ms(s['ttfr_p95_s']):>10} "
            f"{_pct(s['tool_call_accuracy_rate']):>7} {_pct(s['turn_completion_rate']):>7}"
        )
    print("═" * 72)


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
