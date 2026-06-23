# Voice AI Eval Harness

Reproducible latency benchmarks for production voice AI agent platforms (Vapi, Retell, and beyond).

---

## The headline finding [example data]

| Platform | Scenario | TTFR median | TTFR p95 | Barge-in median | Tool accuracy | Turn completion |
|---|---|---|---|---|---|---|
| **retell** | booking-simple | **440 ms** | 610 ms | — | 100% | 100% |
| **vapi** | booking-simple | 480 ms | 720 ms | — | 100% | 100% |
| **retell** | booking-interrupted | **460 ms** | 700 ms | **180 ms** | 100% | 100% |
| **vapi** | booking-interrupted | 510 ms | 890 ms | 210 ms | 90% | 90% |

*[example data] — run the benchmark yourself to get real results from your region and account tier.*

---

## Why this exists

Every voice AI vendor claims sub-500ms latency and "human-like" interruption handling. None of them publish a reproducible methodology. This project is that methodology and its reference implementation.

The harness runs identical scenarios against multiple platforms — same system prompt, same voice, same synthetic user audio — and measures timing from platform-reported events. Results are stored in SQLite and rendered on a static leaderboard. The benchmark is fully reproducible from a clean clone in under 5 commands.

---

## What it measures

- **Time-to-first-response (TTFR):** from `user_speech_ended` to `agent_speech_started`, per turn. The primary latency signal.
- **Barge-in response time:** from `user_speech_started` (during agent speech) to `agent_speech_ended`. How fast does the platform stop talking?
- **Tool-call accuracy:** did the agent call the right function with the right args?
- **Turn-completion rate:** did the scenario reach its success state (tool call + confirmation)?

Reported as **median + p95** across 10 trials per scenario per platform.

---

## What it doesn't measure (yet)

- **Ground-truth VAD** — v1 trusts platform-reported events. A platform with aggressive VAD appears faster because it declares the user done speaking earlier. Addressed in v1.5.
- **First-content-word latency** — requires forced alignment (WhisperX). Planned for v2.
- **Audio quality / MOS** — subjective; requires human raters.
- **Cost per call** — fair cross-platform comparison requires vendor cooperation.
- **Concurrency / load** — out of scope for v1.

See [methodology.md](methodology.md) for the full accounting.

---

## How to reproduce

```bash
# 1. Clone and install
git clone https://github.com/your-org/voice-eval-harness
cd voice-eval-harness
pip install ".[dev]"

# 2. Generate synthetic user audio (requires OPENAI_API_KEY, or creates silent placeholders)
python -m scripts.seed_audio

# 3. Seed sample data and start the leaderboard server
python -m scripts.seed_sample_data
PORT=8000 python -m src.api.main

# 4. Run a real benchmark (requires platform API keys in .env)
cp .env.example .env   # fill in VAPI_API_KEY, RETELL_API_KEY, HARNESS_PUBLIC_URL
python -m scripts.run_benchmark --platform vapi --scenario booking-simple --trials 3

# 5. Or run everything via Docker
docker compose up
```

The leaderboard is at `http://localhost:8000`. Results update in real time as trials complete.

---

## Methodology

Detailed in [methodology.md](methodology.md).

Summary: v1 uses platform-reported events with harness-local timestamps (Vapi) or vendor-provided timestamps (Retell). The known limitation is that platforms with more aggressive VAD appear faster; this will be corrected in v1.5 by ground-truth VAD on captured audio. N=10 trials for v1; N=50 for any official leaderboard publication.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full plan. Three highlights:

- **v1.5:** Ground-truth VAD, ElevenLabs adapter, N=50 official runs.
- **v2:** First-content-word latency (forced alignment), OpenAI Realtime API adapter, concurrency benchmarks.
- **v3:** CI-triggered weekly reruns, community adapter contributions, hosted leaderboard.

---

## How to add a platform

1. Create `src/harness/adapters/<platform>.py` implementing `PlatformAdapter`.
2. Add the translation table as a module-level comment block (see `vapi.py` and `retell.py` for the format).
3. Register the adapter in `scripts/run_benchmark.py`.
4. Add the platform to the per-platform section of `methodology.md`.
5. Open a pull request. The reviewer checklist is in `.github/CONTRIBUTING.md`.

The adapter interface is four methods: `setup_agent`, `run_trial`, `teardown_agent`, `normalize_events`. The hardest one is `normalize_events` — that's where all the platform-specific event translation lives, and it's the most important thing to get right.

---

## Running the tests

```bash
pytest                    # all tests (no live API calls)
pytest -v tests/test_metrics.py   # metric computation only
pytest -v tests/test_scenarios.py # schema validation only
```

Tests cover all metric computation functions with fixture event streams and all scenario YAML validation. No live API calls are made in the test suite.

---

## Citation

```bibtex
@misc{voice-eval-harness-2025,
  title        = {Voice {AI} Eval Harness: Reproducible Latency Benchmarks for Production Voice Agents},
  author       = {Voice AI Eval Harness Contributors},
  year         = {2025},
  howpublished = {\url{https://github.com/your-org/voice-eval-harness}},
  note         = {Open-source benchmarking harness for Vapi, Retell, and compatible platforms}
}
```

---

## License

MIT. See [LICENSE](LICENSE).
