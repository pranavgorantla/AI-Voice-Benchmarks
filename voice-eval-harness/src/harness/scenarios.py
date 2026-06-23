"""
Scenario loading and validation.

Scenarios are YAML files in the ``scenarios/`` directory.  Each file is
validated against the ScenarioConfig Pydantic model at load time so that bad
configs surface immediately rather than mid-run.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


SCENARIOS_DIR = pathlib.Path(__file__).parents[2] / "scenarios"


# ── Schema ────────────────────────────────────────────────────────────────────

class ToolParameter(BaseModel):
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ToolConfig(BaseModel):
    name: str
    description: str
    parameters: ToolParameter


class AgentConfig(BaseModel):
    system_prompt: str
    voice: str
    model: str
    temperature: float = 0.0
    tools: list[ToolConfig] = Field(default_factory=list)


class TurnConfig(BaseModel):
    role: str
    audio: str
    transcript: str
    interrupt: bool = False
    expected_response_within_ms: int


class ToolCallCriteria(BaseModel):
    name: str
    args_match: dict[str, Any] = Field(default_factory=dict)


class SuccessCriteria(BaseModel):
    tool_calls: list[ToolCallCriteria] = Field(default_factory=list)
    min_turns_completed: int = 0


class Scenario(BaseModel):
    id: str
    description: str
    agent_config: AgentConfig
    turns: list[TurnConfig]
    success_criteria: SuccessCriteria

    @model_validator(mode="after")
    def audio_files_exist(self) -> "Scenario":
        audio_dir = SCENARIOS_DIR / "audio"
        for turn in self.turns:
            audio_path = audio_dir / turn.audio
            if not audio_path.exists():
                raise ValueError(
                    f"Audio file not found: {audio_path}. "
                    "Run `python -m scripts.seed_audio` to generate audio fixtures."
                )
        return self


# ── Loader ────────────────────────────────────────────────────────────────────

def load_scenario(scenario_id: str, *, validate_audio: bool = True) -> Scenario:
    """
    Load and validate a scenario by its ID.

    Args:
        scenario_id: Matches the ``id`` field in the YAML and the filename stem.
        validate_audio: Set to False in tests to skip the audio-file existence check.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        ValidationError: If the YAML does not match the schema.
    """
    yaml_path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Scenario file not found: {yaml_path}. "
            f"Available scenarios: {list_scenario_ids()}"
        )

    with yaml_path.open() as fh:
        data = yaml.safe_load(fh)

    if not validate_audio:
        # Monkey-patch audio paths so Pydantic's validator doesn't raise.
        # Only used in tests where real WAV files are not present.
        for turn in data.get("turns", []):
            turn["audio"] = turn.get("audio", "")

        class _NoAudioScenario(Scenario):
            @model_validator(mode="after")
            def audio_files_exist(self) -> "_NoAudioScenario":  # type: ignore[override]
                return self

        return _NoAudioScenario.model_validate(data)

    return Scenario.model_validate(data)


def load_all_scenarios(*, validate_audio: bool = True) -> list[Scenario]:
    """Load all YAML files in the scenarios directory."""
    return [
        load_scenario(p.stem, validate_audio=validate_audio)
        for p in sorted(SCENARIOS_DIR.glob("*.yaml"))
    ]


def list_scenario_ids() -> list[str]:
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml"))
