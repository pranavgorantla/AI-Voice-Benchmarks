# Roadmap

## v1.5 — Ground-truth measurement

- **Ground-truth VAD on captured audio.** v1 trusts platform-reported events. v1.5 records the agent's audio stream and runs a local VAD (Silero or WebRTC VAD) to measure latency against a ground-truth signal rather than vendor-reported events. This addresses the known v1 limitation where vendors with more aggressive VAD appear faster.
- **ElevenLabs Conversational AI adapter.** ElevenLabs released a standalone agent API in late 2024. Adding it as a third data point expands the leaderboard and stress-tests the adapter abstraction.
- **N=50 official leaderboard runs.** v1 publishes N=10 as a methodology-transparent estimate. v1.5 runs N=50 per scenario per platform before publishing any "official" ranking, consistent with the statistical methodology section of `methodology.md`.

## v2 — Expanded coverage

- **Forced alignment for first-content-word latency.** Use Montreal Forced Aligner or WhisperX to measure the delta from user_speech_ended to the first audible content word in the agent's response (not just the audio stream starting). This eliminates platforms gaming TTFR by starting a silent audio stream early.
- **OpenAI Realtime API adapter.** Direct WebSocket connection; no vendor telephony layer. Provides a baseline for what raw model latency looks like without additional infrastructure.
- **Concurrency / load benchmark.** Run N simultaneous trials and measure degradation curves. Requires careful methodology (vendor TOS review, opt-in flag, separate leaderboard section).
- **Additional scenarios.** Multi-tool chaining (two sequential tool calls in one call), mid-call error recovery, and a "hostile user" scenario testing robustness to off-topic inputs.

## v3 — Community and reproducibility

- **Hosted leaderboard with CI-triggered reruns.** Weekly scheduled GitHub Actions job re-runs all benchmarks and updates the public leaderboard automatically.
- **Contributed platform adapters.** Formal adapter contribution guide, review checklist, and CI gate that validates the normalized event schema.
- **Audio quality add-on module.** Subjective MOS scoring via crowdsourcing (separate from the latency harness; requires human raters).
