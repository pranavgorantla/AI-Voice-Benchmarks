"""
Retell platform adapter — push (webhook) model.

Event translation table
-----------------------
Retell fires webhooks as HTTP POST to the webhook URL you provide when
creating a web call.  Each payload has a ``event`` (string) field:

  Retell event           Canonical event
  ─────────────────────  ──────────────────────────
  call_started           (harness internal; start clock)
  user_speech_started    user_speech_started
  user_speech_ended      user_speech_ended
  agent_speech_started   agent_speech_started
  agent_speech_ended     agent_speech_ended
  tool_call_invocation   tool_call_dispatched
  tool_call_result       tool_call_completed
  call_ended             call_ended

Timestamp source
----------------
Retell includes a ``timestamp`` field (epoch milliseconds) in each
webhook payload.  We convert this to seconds-since-call-start using the
timestamp of the ``call_started`` event as the origin.  This is more
accurate than Vapi's harness-local clock approach and is noted in
methodology.md.

Call initiation
---------------
We create a Retell web call via POST /v2/create-web-call, then pass the
returned ``access_token`` to the Retell Web SDK (or WebSocket directly)
to connect and stream audio.  For v1 audio injection details see
runner.py.

Source: https://docs.retellai.com
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


RETELL_BASE_URL = "https://api.retellai.com"
CALL_TIMEOUT_S = 120


class RetellAdapter(PlatformAdapter):
    name = "retell"

    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.retell_api_key}",
            "Content-Type": "application/json",
        }

    # ── Adapter lifecycle ─────────────────────────────────────────────────────

    async def setup_agent(self, scenario: Scenario) -> AgentHandle:
        """
        Create a Retell LLM + Agent configured for this scenario.

        Retell separates "LLM" (the AI model config) from "Agent" (the voice/
        telephony config).  We create both and store the agent_id.
        """
        agent_cfg = scenario.agent_config

        # 1. Create the LLM
        llm_payload = {
            "model": agent_cfg.model,
            "general_prompt": agent_cfg.system_prompt,
            "tools": [
                {
                    "type": "custom",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters.model_dump(),
                    "url": "",  # harness returns a canned success response
                    "speak_during_execution": False,
                    "speak_after_execution": False,
                }
                for t in agent_cfg.tools
            ],
        }

        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            llm_resp = await client.post(f"{RETELL_BASE_URL}/create-retell-llm", json=llm_payload)
            llm_resp.raise_for_status()
            llm_id = llm_resp.json()["llm_id"]

            # 2. Create the Agent
            agent_payload = {
                "llm_websocket_url": f"wss://api.retellai.com/llm-websocket/{llm_id}",
                "voice_id": agent_cfg.voice,
                "agent_name": f"eval-harness-{scenario.id}",
            }
            agent_resp = await client.post(f"{RETELL_BASE_URL}/create-agent", json=agent_payload)
            agent_resp.raise_for_status()
            agent_id = agent_resp.json()["agent_id"]

        return AgentHandle(
            platform=self.name,
            agent_id=agent_id,
            extra={"llm_id": llm_id},
        )

    async def teardown_agent(self, handle: AgentHandle) -> None:
        """Delete the Retell agent and LLM created during setup."""
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            for url in [
                f"{RETELL_BASE_URL}/delete-agent/{handle.agent_id}",
                f"{RETELL_BASE_URL}/delete-retell-llm/{handle.extra.get('llm_id', '')}",
            ]:
                if not url.endswith("/"):
                    resp = await client.delete(url)
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
        from ..webhook_store import WebhookStore

        trial_id = str(uuid.uuid4())
        webhook_url = f"{webhook_base_url}/webhooks/retell/{trial_id}"
        store = WebhookStore.instance()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        store.register(trial_id, queue)

        raw_events: list[dict[str, Any]] = []
        error: str | None = None

        try:
            await self._create_web_call(
                agent_id=handle.agent_id,
                webhook_url=webhook_url,
            )

            await self._collect_events(
                trial_id=trial_id,
                scenario=scenario,
                queue=queue,
                raw_events=raw_events,
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

    async def _create_web_call(self, agent_id: str, webhook_url: str) -> dict[str, Any]:
        payload = {
            "agent_id": agent_id,
            "metadata": {},
            "webhook_url": webhook_url,
        }
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.post(f"{RETELL_BASE_URL}/v2/create-web-call", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def _collect_events(
        self,
        *,
        trial_id: str,
        scenario: Scenario,
        queue: asyncio.Queue[dict[str, Any]],
        raw_events: list[dict[str, Any]],
    ) -> None:
        import pathlib
        from ..audio_player import play_audio_async

        audio_dir = pathlib.Path(__file__).parents[4] / "scenarios" / "audio"
        turn_index = 0
        call_start_ms: float | None = None
        deadline = time.monotonic() + CALL_TIMEOUT_S

        while time.monotonic() < deadline:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

            event_type: str = event.get("event", "")
            event_ts_ms: float = float(event.get("timestamp", 0))

            if event_type == "call_started":
                call_start_ms = event_ts_ms

            # Attach offset in seconds for normalize_events
            event["_call_start_ms"] = call_start_ms or event_ts_ms
            raw_events.append(event)

            if event_type == "agent_speech_ended":
                if turn_index < len(scenario.turns):
                    turn = scenario.turns[turn_index]
                    audio_path = audio_dir / turn.audio
                    await play_audio_async(str(audio_path))
                    turn_index += 1

            elif event_type == "call_ended":
                break

    # ── Event normalisation ───────────────────────────────────────────────────

    def normalize_events(
        self, raw_events: list[dict[str, Any]]
    ) -> list[CanonicalEvent]:
        """
        Translate Retell webhook payloads to canonical events.

        Retell's events map almost 1:1 to the canonical schema, making this
        the simpler of the two v1 adapters.

        Timestamp is derived from the Retell-provided epoch-ms field, offset
        by the call_started timestamp for a monotonic-since-call-start reading.
        """
        start_ms: float = 0.0
        for raw in raw_events:
            if raw.get("event") == "call_started":
                start_ms = float(raw.get("timestamp", 0))
                break

        mapping = {
            "user_speech_started": "user_speech_started",
            "user_speech_ended": "user_speech_ended",
            "agent_speech_started": "agent_speech_started",
            "agent_speech_ended": "agent_speech_ended",
            "call_ended": "call_ended",
        }

        canonical: list[CanonicalEvent] = []

        for raw in raw_events:
            event_type: str = raw.get("event", "")
            ts_s: float = (float(raw.get("timestamp", 0)) - start_ms) / 1000.0

            if event_type in mapping:
                canonical.append(CanonicalEvent(mapping[event_type], ts_s))

            elif event_type == "tool_call_invocation":
                canonical.append(
                    CanonicalEvent(
                        "tool_call_dispatched",
                        ts_s,
                        payload={
                            "name": raw.get("name"),
                            "args": raw.get("arguments", {}),
                        },
                    )
                )

            elif event_type == "tool_call_result":
                canonical.append(
                    CanonicalEvent(
                        "tool_call_completed",
                        ts_s,
                        payload={"result": raw.get("result")},
                    )
                )

        return sorted(canonical, key=lambda e: e.timestamp)
