"""
Vapi platform adapter — push (webhook) model.

Event translation table
-----------------------
Vapi fires webhooks as HTTP POST to the serverUrl you configure.
Each payload has a ``message.type`` field:

  Vapi event                         Canonical event
  ─────────────────────────────────  ──────────────────────────
  speech-update (role=user, started) user_speech_started
  speech-update (role=user, stopped) user_speech_ended
  speech-update (role=ass., started) agent_speech_started
  speech-update (role=ass., stopped) agent_speech_ended
  function-call                      tool_call_dispatched
  function-call-result               tool_call_completed
  end-of-call-report / hang          call_ended

Timestamp source
----------------
Vapi does not currently include per-event monotonic timestamps in webhook
payloads.  We record the harness-local ``time.monotonic()`` at the moment
the webhook is received.  This introduces a small network-round-trip
jitter (~1–5 ms on Replit), which is documented as a v1 limitation in
methodology.md.

Call initiation
---------------
We create a Vapi web call via POST /call/web.  The call is connected to
our webhook URL for event delivery.  Audio injection uses Vapi's
transientToolResult mechanism: the harness plays the next user-turn WAV
through the OS default audio output (or stdin pipe in headless mode).
For v1 the harness delegates audio playback to an external process
(ffplay/afplay); see runner.py for the inter-process handoff.

Source: https://docs.vapi.ai
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx

from .base import AgentHandle, CanonicalEvent, PlatformAdapter, TrialResult
from ..config import settings
from ..scenarios import Scenario


VAPI_BASE_URL = "https://api.vapi.ai"
CALL_TIMEOUT_S = 120


class VapiAdapter(PlatformAdapter):
    name = "vapi"

    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.vapi_api_key}",
            "Content-Type": "application/json",
        }

    # ── Adapter lifecycle ─────────────────────────────────────────────────────

    async def setup_agent(self, scenario: Scenario) -> AgentHandle:
        """
        Create a Vapi assistant configured for this scenario.

        Vapi assistants are reusable across calls.  We create one per
        (platform, scenario) run and reuse it across trials.
        """
        agent_cfg = scenario.agent_config
        payload = {
            "name": f"eval-harness-{scenario.id}",
            "model": {
                "provider": "openai",
                "model": agent_cfg.model,
                "temperature": agent_cfg.temperature,
                "systemPrompt": agent_cfg.system_prompt,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters.model_dump(),
                        },
                    }
                    for t in agent_cfg.tools
                ],
            },
            "voice": {
                "provider": "openai",
                "voiceId": agent_cfg.voice,
            },
        }

        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.post(f"{VAPI_BASE_URL}/assistant", json=payload)
            resp.raise_for_status()
            data = resp.json()

        return AgentHandle(
            platform=self.name,
            agent_id=data["id"],
            extra={"assistant_data": data},
        )

    async def teardown_agent(self, handle: AgentHandle) -> None:
        """Delete the Vapi assistant created during setup."""
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.delete(
                f"{VAPI_BASE_URL}/assistant/{handle.agent_id}"
            )
            # 404 is acceptable — already deleted or never created
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()

    # ── Trial execution ───────────────────────────────────────────────────────

    async def run_trial(
        self,
        handle: AgentHandle,
        scenario: Scenario,
        trial_num: int,
        webhook_base_url: str,
    ) -> TrialResult:
        """
        Execute one trial against the Vapi API.

        Event collection strategy:
        1. We create a web call with serverUrl pointing to our webhook receiver.
        2. The harness webhook receiver (api/routes.py) accumulates events in an
           in-memory queue keyed by trial_id.
        3. run_trial polls that queue until call_ended arrives or CALL_TIMEOUT_S
           elapses.
        4. Audio playback between turns is triggered by agent_speech_ended events
           arriving in the queue.
        """
        from ..webhook_store import WebhookStore

        trial_id = str(uuid.uuid4())
        webhook_url = f"{webhook_base_url}/webhooks/vapi/{trial_id}"
        store = WebhookStore.instance()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        store.register(trial_id, queue)

        raw_events: list[dict[str, Any]] = []
        error: str | None = None

        try:
            call_id = await self._create_web_call(
                assistant_id=handle.agent_id,
                server_url=webhook_url,
            )

            call_started_at = time.monotonic()
            await self._collect_events(
                trial_id=trial_id,
                scenario=scenario,
                queue=queue,
                raw_events=raw_events,
                call_started_at=call_started_at,
            )

        except Exception as exc:
            error = str(exc)
        finally:
            store.unregister(trial_id)

        canonical = self.normalize_events(raw_events)
        return TrialResult(
            trial_id=trial_id,
            platform=self.name,
            scenario_id=scenario.id,
            trial_num=trial_num,
            raw_events=raw_events,
            canonical_events=canonical,
            error=error,
        )

    async def _create_web_call(
        self,
        assistant_id: str,
        server_url: str,
    ) -> str:
        payload = {
            "assistantId": assistant_id,
            "serverUrl": server_url,
        }
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.post(f"{VAPI_BASE_URL}/call/web", json=payload)
            resp.raise_for_status()
            return resp.json()["id"]

    async def _collect_events(
        self,
        *,
        trial_id: str,
        scenario: Scenario,
        queue: asyncio.Queue[dict[str, Any]],
        raw_events: list[dict[str, Any]],
        call_started_at: float,
    ) -> None:
        """
        Drain the webhook queue until call_ended or timeout.

        Audio turns are played when agent_speech_ended fires for the turn index
        that matches the next scripted user turn.
        """
        import pathlib
        from ..audio_player import play_audio_async

        audio_dir = pathlib.Path(__file__).parents[4] / "scenarios" / "audio"
        turn_index = 0
        agent_turn_count = 0

        deadline = time.monotonic() + CALL_TIMEOUT_S

        while time.monotonic() < deadline:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

            event["_harness_offset_s"] = time.monotonic() - call_started_at
            raw_events.append(event)

            msg_type = (event.get("message") or {}).get("type", "")

            if msg_type == "speech-update":
                msg = event["message"]
                if msg.get("role") == "assistant" and msg.get("status") == "stopped":
                    agent_turn_count += 1
                    # Play next user turn if one exists
                    if turn_index < len(scenario.turns):
                        turn = scenario.turns[turn_index]
                        audio_path = audio_dir / turn.audio
                        await play_audio_async(str(audio_path))
                        turn_index += 1

            elif msg_type in ("end-of-call-report", "hang"):
                break

    # ── Event normalisation ───────────────────────────────────────────────────

    def normalize_events(
        self, raw_events: list[dict[str, Any]]
    ) -> list[CanonicalEvent]:
        """
        Translate Vapi webhook payloads to canonical events.

        Translation table:
          speech-update {role=user, status=started}  → user_speech_started
          speech-update {role=user, status=stopped}  → user_speech_ended
          speech-update {role=assistant, status=started} → agent_speech_started
          speech-update {role=assistant, status=stopped} → agent_speech_ended
          function-call                              → tool_call_dispatched
          function-call-result                       → tool_call_completed
          end-of-call-report / hang                  → call_ended
        """
        canonical: list[CanonicalEvent] = []

        for raw in raw_events:
            ts: float = raw.get("_harness_offset_s", 0.0)
            msg: dict[str, Any] = raw.get("message") or {}
            msg_type: str = msg.get("type", "")

            if msg_type == "speech-update":
                role = msg.get("role", "")
                status = msg.get("status", "")
                if role == "user" and status == "started":
                    canonical.append(CanonicalEvent("user_speech_started", ts))
                elif role == "user" and status == "stopped":
                    canonical.append(CanonicalEvent("user_speech_ended", ts))
                elif role == "assistant" and status == "started":
                    canonical.append(CanonicalEvent("agent_speech_started", ts))
                elif role == "assistant" and status == "stopped":
                    canonical.append(CanonicalEvent("agent_speech_ended", ts))

            elif msg_type == "function-call":
                fn = msg.get("functionCall") or {}
                canonical.append(
                    CanonicalEvent(
                        "tool_call_dispatched",
                        ts,
                        payload={"name": fn.get("name"), "args": fn.get("parameters", {})},
                    )
                )

            elif msg_type == "function-call-result":
                canonical.append(
                    CanonicalEvent(
                        "tool_call_completed",
                        ts,
                        payload={"result": msg.get("result")},
                    )
                )

            elif msg_type in ("end-of-call-report", "hang"):
                canonical.append(CanonicalEvent("call_ended", ts))

        return sorted(canonical, key=lambda e: e.timestamp)
