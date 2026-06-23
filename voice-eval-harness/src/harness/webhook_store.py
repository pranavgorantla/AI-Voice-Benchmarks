"""
In-process webhook event store.

The FastAPI webhook receivers in api/routes.py push raw events into queues
here; the adapter's run_trial() drains those queues.

One WebhookStore singleton lives for the lifetime of the FastAPI process.
Trial IDs are UUIDs, so collisions are not a concern.
"""

from __future__ import annotations

import asyncio
from typing import Any


class WebhookStore:
    _instance: "WebhookStore | None" = None

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    @classmethod
    def instance(cls) -> "WebhookStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, trial_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._queues[trial_id] = queue

    def unregister(self, trial_id: str) -> None:
        self._queues.pop(trial_id, None)

    async def push(self, trial_id: str, event: dict[str, Any]) -> bool:
        """
        Push an event to the queue for trial_id.

        Returns True if the queue exists (trial is active), False otherwise.
        Stale webhooks (arriving after unregister) are silently dropped.
        """
        queue = self._queues.get(trial_id)
        if queue is None:
            return False
        await queue.put(event)
        return True
