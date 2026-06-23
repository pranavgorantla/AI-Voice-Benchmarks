"""
Generate synthetic user audio fixtures using OpenAI TTS.

The generated WAV files are committed to scenarios/audio/ so that benchmark
runs are deterministic — the same audio is sent to every platform in every
trial.

Run once (requires OPENAI_API_KEY):
  python -m scripts.seed_audio

The voice is "onyx" (deep, clear, natural pace) at the default 24000 Hz
sample rate.  Do not change the voice or text without re-running this script
and re-committing the WAV files, as that would break cross-run comparability.
"""

from __future__ import annotations

import os
import pathlib
import struct
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.harness.config import settings

AUDIO_DIR = pathlib.Path(__file__).parent.parent / "scenarios" / "audio"

# Each entry: (filename, transcript)
AUDIO_LINES = [
    (
        "booking-simple-turn-1.wav",
        "Hi, I'd like to book a cleaning for next Tuesday at 2pm. My name is Alex Chen.",
    ),
    (
        "booking-simple-turn-2.wav",
        "Yes, that works. Thanks!",
    ),
    (
        "booking-interrupted-turn-1.wav",
        "Hi, I want to book a—",
    ),
    (
        "booking-interrupted-turn-2.wav",
        "Sorry, I need Tuesday at 3pm, not 2pm. My name is Alex Chen.",
    ),
    (
        "booking-interrupted-turn-3.wav",
        "Yes, 3pm on Tuesday works. Thanks!",
    ),
]


def generate_silent_wav(path: pathlib.Path, duration_s: float = 0.5) -> None:
    """
    Write a silent WAV file as a placeholder.

    Used when OPENAI_API_KEY is not set.  Platforms will receive silence and
    the harness will still exercise the event-collection path.
    """
    sample_rate = 24000
    num_channels = 1
    sample_width = 2  # 16-bit
    num_frames = int(sample_rate * duration_s)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * num_frames * num_channels * sample_width)


def generate_with_openai(filename: str, text: str) -> None:
    try:
        import httpx
    except ImportError:
        print("httpx not installed; run `pip install httpx` and retry.")
        sys.exit(1)

    api_key = settings.openai_api_key
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment.")

    output_path = AUDIO_DIR / filename

    print(f"  Generating: {filename!r} ({len(text)} chars) …")
    resp = httpx.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "tts-1",
            "input": text,
            "voice": "onyx",
            "response_format": "wav",
        },
        timeout=60,
    )
    resp.raise_for_status()
    output_path.write_bytes(resp.content)
    print(f"  Saved: {output_path} ({len(resp.content):,} bytes)")


def main() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    api_key = settings.openai_api_key

    if not api_key:
        print(
            "OPENAI_API_KEY not set — generating silent placeholder WAV files.\n"
            "Set OPENAI_API_KEY and re-run to generate real speech audio.\n"
        )
        for filename, _ in AUDIO_LINES:
            path = AUDIO_DIR / filename
            generate_silent_wav(path)
            print(f"  Created placeholder: {path.name}")
        print("\nDone. Commit scenarios/audio/*.wav to the repo.")
        return

    print(f"Generating {len(AUDIO_LINES)} audio files via OpenAI TTS …\n")
    for filename, text in AUDIO_LINES:
        generate_with_openai(filename, text)

    print("\nDone. Commit scenarios/audio/*.wav to the repo.")
    print("These files are the ground-truth audio used in all benchmark runs.")
    print("Do NOT regenerate unless you're intentionally changing the scenarios.")


if __name__ == "__main__":
    main()
