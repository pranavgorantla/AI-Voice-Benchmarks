"""
Unit tests for metric computation functions.

All tests use fixture event streams — no live API calls.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.harness.adapters.base import CanonicalEvent
from src.harness.metrics import (
    aggregate,
    compute_barge_in_response_time,
    compute_time_to_first_response,
    compute_tool_call_accuracy,
    compute_turn_completion_rate,
)
from src.harness.scenarios import SuccessCriteria, ToolCallCriteria

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_events(filename: str) -> list[CanonicalEvent]:
    data = json.loads((FIXTURES / filename).read_text())
    return [
        CanonicalEvent(
            type=e["type"],
            timestamp=e["timestamp"],
            payload=e.get("payload", {}),
        )
        for e in data["canonical_events"]
    ]


def load_expected(filename: str) -> dict:
    return json.loads((FIXTURES / filename).read_text())["expected_metrics"]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def simple_events() -> list[CanonicalEvent]:
    return load_events("sample_event_stream.json")


@pytest.fixture
def interrupted_events() -> list[CanonicalEvent]:
    return load_events("sample_event_stream_interrupted.json")


@pytest.fixture
def simple_criteria() -> SuccessCriteria:
    return SuccessCriteria(
        tool_calls=[
            ToolCallCriteria(
                name="book_appointment",
                args_match={
                    "patient_name": "Alex Chen",
                    "appointment_datetime_contains": "T14:00",
                },
            )
        ],
        min_turns_completed=2,
    )


@pytest.fixture
def interrupted_criteria() -> SuccessCriteria:
    return SuccessCriteria(
        tool_calls=[
            ToolCallCriteria(
                name="book_appointment",
                args_match={
                    "patient_name": "Alex Chen",
                    "appointment_datetime_contains": "T15:00",
                },
            )
        ],
        min_turns_completed=3,
    )


# ── time_to_first_response ────────────────────────────────────────────────────

class TestTimeToFirstResponse:
    def test_simple_two_turns(self, simple_events):
        measurements = compute_time_to_first_response(simple_events)
        assert len(measurements) == 2

    def test_simple_values_are_positive(self, simple_events):
        measurements = compute_time_to_first_response(simple_events)
        assert all(m > 0 for m in measurements)

    def test_simple_first_ttfr(self, simple_events):
        """First TTFR = agent_speech_started(3.65) - user_speech_ended(3.20) = 0.45s"""
        measurements = compute_time_to_first_response(simple_events)
        assert abs(measurements[0] - 0.45) < 0.01

    def test_simple_second_ttfr(self, simple_events):
        """Second TTFR = agent_speech_started(8.40) - user_speech_ended(7.80) = 0.60s"""
        measurements = compute_time_to_first_response(simple_events)
        assert abs(measurements[1] - 0.60) < 0.01

    def test_interrupted_three_turns(self, interrupted_events):
        measurements = compute_time_to_first_response(interrupted_events)
        assert len(measurements) == 3

    def test_empty_stream_returns_empty(self):
        assert compute_time_to_first_response([]) == []

    def test_no_agent_response_returns_empty(self):
        events = [
            CanonicalEvent("user_speech_started", 0.0),
            CanonicalEvent("user_speech_ended", 2.0),
            CanonicalEvent("call_ended", 5.0),
        ]
        assert compute_time_to_first_response(events) == []


# ── barge_in_response_time ────────────────────────────────────────────────────

class TestBargeInResponseTime:
    def test_simple_no_barge_ins(self, simple_events):
        assert compute_barge_in_response_time(simple_events) == []

    def test_interrupted_two_barge_ins(self, interrupted_events):
        measurements = compute_barge_in_response_time(interrupted_events)
        assert len(measurements) == 2

    def test_interrupted_values_positive(self, interrupted_events):
        measurements = compute_barge_in_response_time(interrupted_events)
        assert all(m > 0 for m in measurements)

    def test_barge_in_only_when_agent_speaking(self):
        """user_speech_started OUTSIDE an agent turn should not be counted."""
        events = [
            CanonicalEvent("user_speech_started", 0.0),
            CanonicalEvent("user_speech_ended", 2.0),
            # No agent turn here
            CanonicalEvent("agent_speech_started", 2.5),
            CanonicalEvent("agent_speech_ended", 4.0),
        ]
        assert compute_barge_in_response_time(events) == []


# ── tool_call_accuracy ────────────────────────────────────────────────────────

class TestToolCallAccuracy:
    def test_simple_correct_tool_call(self, simple_events, simple_criteria):
        assert compute_tool_call_accuracy(simple_events, simple_criteria) == 1.0

    def test_interrupted_correct_tool_call_3pm(self, interrupted_events, interrupted_criteria):
        assert compute_tool_call_accuracy(interrupted_events, interrupted_criteria) == 1.0

    def test_wrong_time_fails(self, interrupted_events, simple_criteria):
        """booking-interrupted uses T15:00 but simple_criteria expects T14:00"""
        assert compute_tool_call_accuracy(interrupted_events, simple_criteria) == 0.0

    def test_wrong_patient_name_fails(self, simple_events):
        criteria = SuccessCriteria(
            tool_calls=[
                ToolCallCriteria(
                    name="book_appointment",
                    args_match={"patient_name": "Jordan Smith"},
                )
            ]
        )
        assert compute_tool_call_accuracy(simple_events, criteria) == 0.0

    def test_wrong_tool_name_fails(self, simple_events):
        criteria = SuccessCriteria(
            tool_calls=[ToolCallCriteria(name="cancel_appointment", args_match={})]
        )
        assert compute_tool_call_accuracy(simple_events, criteria) == 0.0

    def test_no_tool_calls_in_stream_fails(self, simple_criteria):
        events = [
            CanonicalEvent("user_speech_started", 0.0),
            CanonicalEvent("user_speech_ended", 2.0),
            CanonicalEvent("agent_speech_started", 2.5),
            CanonicalEvent("agent_speech_ended", 4.0),
            CanonicalEvent("call_ended", 5.0),
        ]
        assert compute_tool_call_accuracy(events, simple_criteria) == 0.0

    def test_no_required_tool_calls_always_passes(self, simple_events):
        criteria = SuccessCriteria(tool_calls=[], min_turns_completed=0)
        assert compute_tool_call_accuracy(simple_events, criteria) == 1.0

    def test_contains_substring_match(self):
        """appointment_datetime_contains should match any datetime containing the substr."""
        events = [
            CanonicalEvent(
                "tool_call_dispatched",
                1.0,
                payload={
                    "name": "book_appointment",
                    "args": {
                        "patient_name": "Alex Chen",
                        "appointment_datetime": "2025-06-17T14:00:00+05:30",
                    },
                },
            )
        ]
        criteria = SuccessCriteria(
            tool_calls=[
                ToolCallCriteria(
                    name="book_appointment",
                    args_match={
                        "patient_name": "Alex Chen",
                        "appointment_datetime_contains": "T14:00",
                    },
                )
            ]
        )
        assert compute_tool_call_accuracy(events, criteria) == 1.0


# ── turn_completion_rate ──────────────────────────────────────────────────────

class TestTurnCompletionRate:
    def test_simple_full_success(self, simple_events, simple_criteria):
        assert compute_turn_completion_rate(simple_events, simple_criteria) == 1.0

    def test_interrupted_full_success(self, interrupted_events, interrupted_criteria):
        assert compute_turn_completion_rate(interrupted_events, interrupted_criteria) == 1.0

    def test_not_enough_agent_turns(self, simple_criteria):
        events = [
            CanonicalEvent("user_speech_started", 0.0),
            CanonicalEvent("user_speech_ended", 2.0),
            CanonicalEvent("agent_speech_started", 2.5),  # only 1 agent turn
            CanonicalEvent(
                "tool_call_dispatched", 3.0,
                payload={"name": "book_appointment", "args": {"patient_name": "Alex Chen", "appointment_datetime": "2025-01-14T14:00:00"}},
            ),
            CanonicalEvent("tool_call_completed", 3.1, payload={"result": "success"}),
            CanonicalEvent("agent_speech_ended", 4.0),
            CanonicalEvent("call_ended", 4.5),
        ]
        # min_turns_completed=2 but only 1 agent_speech_started
        assert compute_turn_completion_rate(events, simple_criteria) == 0.0


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate:
    def test_empty_returns_none(self):
        result = aggregate([])
        assert result["median"] is None
        assert result["p95"] is None
        assert result["n"] == 0

    def test_single_value(self):
        result = aggregate([0.5])
        assert result["median"] == pytest.approx(0.5)
        assert result["p95"] == pytest.approx(0.5)
        assert result["n"] == 1

    def test_multiple_values(self):
        vals = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
        result = aggregate(vals)
        assert result["median"] == pytest.approx(0.75)
        assert result["p95"] > result["median"]
        assert result["n"] == 10
