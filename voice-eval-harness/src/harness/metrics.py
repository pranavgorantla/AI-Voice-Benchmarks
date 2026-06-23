"""
Metric computation from canonical event streams.

All functions are pure — they take a list of CanonicalEvent objects and return
a float (seconds) or a boolean.  No I/O, no side effects.  This makes them
straightforward to unit-test with fixture event streams.

Metrics defined here:

  time_to_first_response
    user_speech_ended → agent_speech_started (first agent utterance in each turn)
    Unit: seconds.  Reported per-turn; aggregated as median + p95 across trials.

  barge_in_response_time
    user_speech_started (while agent is speaking) → agent_speech_ended
    Captures how quickly the platform stops the agent and begins processing the
    interruption.  Only meaningful for scenarios with interrupt=True turns.
    Unit: seconds.

  tool_call_accuracy
    Exact match of tool name + args against the canonical schema.
    A substring match is used for datetime fields annotated with
    ``appointment_datetime_contains`` to allow flexible date resolution.
    Returns 1.0 (pass) or 0.0 (fail) per trial.

  turn_completion_rate
    Did the scenario reach its success state (min_turns_completed + required
    tool calls)?  Returns 1.0 (pass) or 0.0 (fail) per trial.

Aggregation (across N trials per scenario per platform):
  - Median (p50)
  - 95th percentile (p95)
  - Full distribution stored in the DB for the per-trial drill-down view.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .adapters.base import CanonicalEvent
from .scenarios import SuccessCriteria


# ── Latency metrics ───────────────────────────────────────────────────────────

def compute_time_to_first_response(events: list[CanonicalEvent]) -> list[float]:
    """
    Returns one measurement per user turn: the delta (seconds) from
    ``user_speech_ended`` to the next ``agent_speech_started``.

    If no ``agent_speech_started`` follows a ``user_speech_ended`` (e.g. the
    call ended without a response) the turn is excluded from the list.
    """
    results: list[float] = []
    waiting_since: float | None = None

    for event in sorted(events, key=lambda e: e.timestamp):
        if event.type == "user_speech_ended":
            waiting_since = event.timestamp
        elif event.type == "agent_speech_started" and waiting_since is not None:
            results.append(event.timestamp - waiting_since)
            waiting_since = None  # consume; wait for the next user turn

    return results


def compute_barge_in_response_time(events: list[CanonicalEvent]) -> list[float]:
    """
    Returns one measurement per detected barge-in: the delta (seconds) from
    ``user_speech_started`` (while agent is speaking) to the next
    ``agent_speech_ended``.

    A barge-in is detected when ``user_speech_started`` falls between an
    ``agent_speech_started`` and its paired ``agent_speech_ended``.
    """
    results: list[float] = []
    sorted_events = sorted(events, key=lambda e: e.timestamp)

    agent_speaking = False
    barge_in_at: float | None = None

    for event in sorted_events:
        if event.type == "agent_speech_started":
            agent_speaking = True
            barge_in_at = None
        elif event.type == "user_speech_started" and agent_speaking:
            barge_in_at = event.timestamp
        elif event.type == "agent_speech_ended":
            if barge_in_at is not None:
                results.append(event.timestamp - barge_in_at)
                barge_in_at = None
            agent_speaking = False

    return results


# ── Tool-call accuracy ────────────────────────────────────────────────────────

def _args_match(actual_args: dict[str, Any], expected_match: dict[str, Any]) -> bool:
    """
    Check actual tool args against the ``args_match`` dict from success criteria.

    Rules:
    - Keys ending in ``_contains`` do a substring match on the corresponding
      field (without the ``_contains`` suffix).
    - All other keys require an exact string match (case-insensitive trim).
    """
    for key, expected_value in expected_match.items():
        if key.endswith("_contains"):
            field_name = key[: -len("_contains")]
            actual_value = str(actual_args.get(field_name, ""))
            if expected_value not in actual_value:
                return False
        else:
            actual_value = str(actual_args.get(key, "")).strip().lower()
            if actual_value != str(expected_value).strip().lower():
                return False
    return True


def compute_tool_call_accuracy(
    events: list[CanonicalEvent],
    criteria: SuccessCriteria,
) -> float:
    """
    Returns 1.0 if all required tool calls in ``criteria`` are satisfied by
    the ``tool_call_dispatched`` events in this trial, else 0.0.
    """
    dispatched = [
        e for e in events if e.type == "tool_call_dispatched"
    ]

    for required in criteria.tool_calls:
        matched = any(
            e.payload.get("name") == required.name
            and _args_match(e.payload.get("args", {}), required.args_match)
            for e in dispatched
        )
        if not matched:
            return 0.0

    return 1.0


# ── Turn completion rate ──────────────────────────────────────────────────────

def compute_turn_completion_rate(
    events: list[CanonicalEvent],
    criteria: SuccessCriteria,
) -> float:
    """
    Returns 1.0 if the scenario reached its success state, else 0.0.

    Success requires both:
    - At least ``criteria.min_turns_completed`` ``agent_speech_started`` events.
    - All required tool calls satisfied (delegates to compute_tool_call_accuracy).
    """
    agent_turns = sum(1 for e in events if e.type == "agent_speech_started")
    if agent_turns < criteria.min_turns_completed:
        return 0.0
    return compute_tool_call_accuracy(events, criteria)


# ── Aggregation ───────────────────────────────────────────────────────────────

def aggregate(values: list[float]) -> dict[str, float | None]:
    """
    Compute median and p95 for a list of measurements.

    Returns None for both stats when ``values`` is empty (e.g. no barge-ins in
    a non-interrupted scenario).
    """
    if not values:
        return {"median": None, "p95": None, "n": 0}
    arr = np.array(values, dtype=float)
    return {
        "median": float(np.median(arr)),
        "p95": float(np.percentile(arr, 95)),
        "n": len(arr),
    }
