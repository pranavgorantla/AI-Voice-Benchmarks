"""
Abstract base class for platform adapters.

Each concrete adapter (VapiAdapter, RetellAdapter, …) implements the four
methods below.  The split between run_trial (raw event capture) and
normalize_events (translation to the canonical schema) is intentional: it lets
us re-process stored raw events if the canonical schema changes without re-
running trials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ── Canonical event schema ────────────────────────────────────────────────────

CANONICAL_EVENT_TYPES = frozenset(
    {
        "user_speech_started",
        "user_speech_ended",
        "agent_speech_started",
        "agent_speech_ended",
        "tool_call_dispatched",
        "tool_call_completed",
        "call_ended",
    }
)


@dataclass
class CanonicalEvent:
    """
    A single event in the canonical timeline for one trial.

    ``timestamp`` is seconds since the platform-reported call start, measured
    using the platform's own clock.  All comparisons happen within the same
    event stream, so absolute wall-clock offsets don't matter.
    """

    type: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in CANONICAL_EVENT_TYPES:
            raise ValueError(
                f"Unknown canonical event type {self.type!r}. "
                f"Valid types: {sorted(CANONICAL_EVENT_TYPES)}"
            )


# ── Call handles and trial results ───────────────────────────────────────────

@dataclass
class AgentHandle:
    """Opaque reference to an agent/assistant created on the platform."""

    platform: str
    agent_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrialResult:
    """Raw output of one trial run, before metric computation."""

    trial_id: str
    platform: str
    scenario_id: str
    trial_num: int
    raw_events: list[dict[str, Any]]
    canonical_events: list[CanonicalEvent]
    error: str | None = None


# ── Abstract adapter ──────────────────────────────────────────────────────────

class PlatformAdapter(ABC):
    """
    Abstract base class for platform adapters.

    Implementers must:
    - Set ``name`` to the platform slug ("vapi", "retell", …).
    - Implement all four abstract methods.
    - Document the event-translation rules in a block comment at the top of
      the concrete adapter module.
    """

    name: str

    @abstractmethod
    async def setup_agent(self, scenario: Any) -> AgentHandle:
        """
        Create or configure the test agent on the platform for this scenario.

        Called once per (platform, scenario) pair before any trials run.
        Should be idempotent if the agent already exists.
        """

    @abstractmethod
    async def run_trial(
        self,
        handle: AgentHandle,
        scenario: Any,
        trial_num: int,
        webhook_base_url: str,
    ) -> TrialResult:
        """
        Execute a single trial.

        Steps:
        1. Register a webhook URL for this trial (``webhook_base_url/webhooks/<platform>/<trial_id>``).
        2. Initiate the call via the platform API.
        3. Play synthetic user audio at the scripted points, triggered by
           platform-reported ``agent_speech_ended`` events.
        4. Collect events until ``call_ended`` or a timeout.
        5. Return the raw event list; normalization happens separately.
        """

    @abstractmethod
    async def teardown_agent(self, handle: AgentHandle) -> None:
        """
        Clean up resources created on the platform during setup_agent.

        Called once after all trials for a (platform, scenario) pair complete.
        Must not raise if the agent was never created or has already been deleted.
        """

    @abstractmethod
    def normalize_events(self, raw_events: list[dict[str, Any]]) -> list[CanonicalEvent]:
        """
        Translate platform-native event payloads to the canonical schema.

        This is where most platform-specific complexity lives.  See each
        concrete adapter for the translation table and caveats.

        The returned list must be sorted ascending by ``timestamp``.
        """
