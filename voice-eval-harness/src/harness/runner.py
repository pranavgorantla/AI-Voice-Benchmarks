"""
Benchmark runner orchestrator.

Usage (via CLI wrapper):
  python -m scripts.run_benchmark --platform vapi --scenario booking-simple --trials 3

The runner:
  1. Loads the scenario from YAML.
  2. Calls adapter.setup_agent() once.
  3. Runs N trials sequentially with inter-trial backoff to respect rate limits.
  4. For each trial, calls adapter.run_trial(), computes metrics, and persists.
  5. After all trials, recomputes the aggregated ScenarioResult.
  6. Calls adapter.teardown_agent() in a finally block.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from .adapters.base import CanonicalEvent, PlatformAdapter, TrialResult
from .config import settings
from .metrics import (
    aggregate,
    compute_barge_in_response_time,
    compute_time_to_first_response,
    compute_tool_call_accuracy,
    compute_turn_completion_rate,
)
from .scenarios import Scenario, load_scenario
from .storage import (
    Session,
    recompute_scenario_result,
    save_trial,
)

logger = logging.getLogger(__name__)


def _canonical_to_dicts(events: list[CanonicalEvent]) -> list[dict[str, Any]]:
    return [
        {"type": e.type, "timestamp": e.timestamp, "payload": e.payload}
        for e in events
    ]


class BenchmarkRunner:
    def __init__(
        self,
        adapter: PlatformAdapter,
        db: Session,
        *,
        trials: int | None = None,
        rate_limit_rpm: int | None = None,
        webhook_base_url: str = "",
    ) -> None:
        self.adapter = adapter
        self.db = db
        self.trials = trials or settings.trials
        self.rate_limit_rpm = rate_limit_rpm or settings.rate_limit_rpm
        self.webhook_base_url = webhook_base_url or settings.harness_public_url
        self._min_inter_trial_s = 60.0 / max(self.rate_limit_rpm, 1)

    async def run_scenario(self, scenario_id: str) -> dict[str, Any]:
        """
        Run all trials for one scenario on the configured platform.

        Returns a summary dict with per-metric aggregates.
        """
        scenario = load_scenario(scenario_id)
        platform = self.adapter.name

        logger.info(
            "Starting benchmark: platform=%s scenario=%s trials=%d",
            platform,
            scenario_id,
            self.trials,
        )

        handle = await self.adapter.setup_agent(scenario)
        successes = 0
        errors = 0

        try:
            for trial_num in range(1, self.trials + 1):
                logger.info("  Trial %d/%d …", trial_num, self.trials)
                trial_start = time.monotonic()

                result = await self._run_trial_with_retry(handle, scenario, trial_num)
                self._persist_trial(result)

                if result.error:
                    errors += 1
                    logger.warning("  Trial %d failed: %s", trial_num, result.error)
                else:
                    successes += 1

                # Rate-limit inter-trial pause
                elapsed = time.monotonic() - trial_start
                sleep_for = max(0.0, self._min_inter_trial_s - elapsed)
                if sleep_for > 0 and trial_num < self.trials:
                    logger.debug("  Rate-limit pause %.1fs", sleep_for)
                    await asyncio.sleep(sleep_for)

        finally:
            await self.adapter.teardown_agent(handle)

        scenario_result = recompute_scenario_result(
            self.db, platform=platform, scenario_id=scenario_id
        )

        summary = {
            "platform": platform,
            "scenario_id": scenario_id,
            "trials_run": self.trials,
            "successes": successes,
            "errors": errors,
            "ttfr_median_s": scenario_result.ttfr_median,
            "ttfr_p95_s": scenario_result.ttfr_p95,
            "barge_in_median_s": scenario_result.barge_in_median,
            "barge_in_p95_s": scenario_result.barge_in_p95,
            "tool_call_accuracy_rate": scenario_result.tool_call_accuracy_rate,
            "turn_completion_rate": scenario_result.turn_completion_rate,
        }
        logger.info("Scenario complete: %s", summary)
        return summary

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _run_trial_with_retry(
        self,
        handle: Any,
        scenario: Scenario,
        trial_num: int,
    ) -> TrialResult:
        return await self.adapter.run_trial(
            handle, scenario, trial_num, self.webhook_base_url
        )

    def _persist_trial(self, result: TrialResult) -> None:
        ttfr = compute_time_to_first_response(result.canonical_events)
        barge = compute_barge_in_response_time(result.canonical_events)

        # Build a dummy success_criteria from the scenario for accuracy metrics
        scenario = load_scenario(result.scenario_id)
        tool_acc = compute_tool_call_accuracy(
            result.canonical_events, scenario.success_criteria
        )
        turn_comp = compute_turn_completion_rate(
            result.canonical_events, scenario.success_criteria
        )

        save_trial(
            self.db,
            trial_id=result.trial_id,
            platform=result.platform,
            scenario_id=result.scenario_id,
            trial_num=result.trial_num,
            raw_events=result.raw_events,
            canonical_events_dicts=_canonical_to_dicts(result.canonical_events),
            ttfr_measurements=ttfr,
            barge_in_measurements=barge,
            tool_call_accuracy=tool_acc,
            turn_completion=turn_comp,
            error=result.error,
        )
