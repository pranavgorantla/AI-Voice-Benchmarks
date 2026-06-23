"""
Async audio playback helper.

Plays a WAV file using a subprocess (ffplay or afplay depending on OS).
Falls back to a no-op if neither is available — this lets the test suite
run without audio hardware or media players installed.

In a real trial, the audio is played through the system's default output
device, which Vapi/Retell's WebRTC session captures and transmits to the
cloud-hosted agent.  If you're running in a headless environment without
a virtual audio device, you'll need to set up a loopback (e.g. PulseAudio
null-sink on Linux) before running live benchmarks.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)


def _find_player() -> list[str] | None:
    """Return the command list for the first available audio player, or None."""
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
    if shutil.which("afplay"):
        return ["afplay"]
    if shutil.which("aplay"):
        return ["aplay", "--quiet"]
    return None


async def play_audio_async(wav_path: str) -> None:
    """
    Play a WAV file asynchronously.

    Awaits completion before returning so that the caller's event loop can
    sequence multiple turns correctly.
    """
    player_cmd = _find_player()
    if player_cmd is None:
        logger.warning(
            "No audio player found (ffplay/afplay/aplay). "
            "Skipping playback of %s. Live trial results will be invalid.",
            wav_path,
        )
        return

    cmd = player_cmd + [wav_path]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception:
        logger.exception("Audio playback failed for %s", wav_path)
