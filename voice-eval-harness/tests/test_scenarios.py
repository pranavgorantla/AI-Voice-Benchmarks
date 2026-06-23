"""
Tests for scenario loading and schema validation.

Does not require audio files to be present (validate_audio=False).
"""

from __future__ import annotations

import pytest

from src.harness.scenarios import list_scenario_ids, load_all_scenarios, load_scenario


class TestScenarioLoading:
    def test_list_scenario_ids_returns_both_scenarios(self):
        ids = list_scenario_ids()
        assert "booking-simple" in ids
        assert "booking-interrupted" in ids

    def test_load_booking_simple(self):
        scenario = load_scenario("booking-simple", validate_audio=False)
        assert scenario.id == "booking-simple"

    def test_load_booking_interrupted(self):
        scenario = load_scenario("booking-interrupted", validate_audio=False)
        assert scenario.id == "booking-interrupted"

    def test_unknown_scenario_raises(self):
        with pytest.raises(FileNotFoundError):
            load_scenario("does-not-exist", validate_audio=False)

    def test_load_all_scenarios(self):
        scenarios = load_all_scenarios(validate_audio=False)
        assert len(scenarios) >= 2


class TestBookingSimpleSchema:
    @pytest.fixture(autouse=True)
    def scenario(self):
        self.s = load_scenario("booking-simple", validate_audio=False)

    def test_has_two_turns(self):
        assert len(self.s.turns) == 2

    def test_turns_are_user_role(self):
        for turn in self.s.turns:
            assert turn.role == "user"

    def test_no_interrupt_turns(self):
        for turn in self.s.turns:
            assert turn.interrupt is False

    def test_agent_config_has_tool(self):
        assert len(self.s.agent_config.tools) == 1
        assert self.s.agent_config.tools[0].name == "book_appointment"

    def test_success_criteria_tool_call(self):
        assert len(self.s.success_criteria.tool_calls) == 1
        assert self.s.success_criteria.tool_calls[0].name == "book_appointment"

    def test_success_criteria_patient_name(self):
        args = self.s.success_criteria.tool_calls[0].args_match
        assert args.get("patient_name") == "Alex Chen"

    def test_success_criteria_time(self):
        args = self.s.success_criteria.tool_calls[0].args_match
        assert "T14:00" in args.get("appointment_datetime_contains", "")

    def test_min_turns_completed(self):
        assert self.s.success_criteria.min_turns_completed == 2

    def test_expected_response_within_ms(self):
        for turn in self.s.turns:
            assert turn.expected_response_within_ms > 0


class TestBookingInterruptedSchema:
    @pytest.fixture(autouse=True)
    def scenario(self):
        self.s = load_scenario("booking-interrupted", validate_audio=False)

    def test_has_three_turns(self):
        assert len(self.s.turns) == 3

    def test_first_two_turns_are_interrupts(self):
        assert self.s.turns[0].interrupt is True
        assert self.s.turns[1].interrupt is True

    def test_third_turn_is_not_interrupt(self):
        assert self.s.turns[2].interrupt is False

    def test_success_criteria_uses_3pm(self):
        args = self.s.success_criteria.tool_calls[0].args_match
        assert "T15:00" in args.get("appointment_datetime_contains", "")

    def test_min_turns_completed(self):
        assert self.s.success_criteria.min_turns_completed == 3

    def test_interrupt_turns_have_faster_expected_response(self):
        """Interrupt turns should have a tighter latency budget than confirmation turns."""
        interrupt_budget = self.s.turns[0].expected_response_within_ms
        confirm_budget = self.s.turns[2].expected_response_within_ms
        assert interrupt_budget < confirm_budget
