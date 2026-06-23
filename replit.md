# Voice AI Eval Harness

Open-source benchmarking harness for production voice AI agent platforms (Vapi, Retell, and beyond) — measures end-of-turn latency, barge-in response time, and tool-call accuracy across platforms running identical scenarios.

## Run & Operate

### Voice Eval Harness (Python / FastAPI)
- `cd voice-eval-harness && DATABASE_URL=sqlite:///./results.db PORT=8000 python -m src.api.main` — leaderboard server (port 8000)
- `cd voice-eval-harness && python -m pytest tests/` — run all unit tests (45 tests, no live API calls)
- `cd voice-eval-harness && python -m scripts.seed_audio` — generate WAV fixtures (needs `OPENAI_API_KEY`, creates silent placeholders if not set)
- `cd voice-eval-harness && DATABASE_URL=sqlite:///./results.db python -m scripts.seed_sample_data` — seed example leaderboard data
- `cd voice-eval-harness && python -m scripts.run_benchmark --platform vapi --scenario booking-simple --trials 3` — run a live benchmark
- `cd voice-eval-harness && DATABASE_URL=sqlite:///./results.db python -m scripts.export_results` — export static docs/ for GitHub Pages

### pnpm workspace (Node.js / TypeScript)
- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages

## Stack

### Voice Eval Harness
- Python 3.11+, FastAPI, Uvicorn
- SQLite via SQLAlchemy (default), Pydantic Settings
- Adapter pattern: `PlatformAdapter` ABC → `VapiAdapter`, `RetellAdapter`
- Event model: push/webhook — adapters receive events via local FastAPI webhook routes
- Metrics: pure functions in `src/harness/metrics.py`, fully unit-tested
- Frontend: vanilla JS + Chart.js (CDN), no build step

### pnpm workspace
- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5, DB: PostgreSQL + Drizzle ORM

## Where things live

```
voice-eval-harness/
├── methodology.md          ← THE most important file; credibility document
├── README.md               ← marketing asset + reproduction steps
├── ROADMAP.md
├── scenarios/
│   ├── booking-simple.yaml
│   ├── booking-interrupted.yaml
│   └── audio/*.wav         ← committed WAV fixtures; regenerate with seed_audio.py
├── src/harness/
│   ├── adapters/base.py    ← PlatformAdapter ABC + CanonicalEvent schema
│   ├── adapters/vapi.py    ← Vapi webhook push adapter
│   ├── adapters/retell.py  ← Retell webhook push adapter
│   ├── metrics.py          ← pure metric computation functions
│   ├── scenarios.py        ← YAML loader + Pydantic schema
│   ├── storage.py          ← SQLAlchemy models (trial_results, scenario_results)
│   ├── runner.py           ← BenchmarkRunner orchestrator
│   ├── webhook_store.py    ← in-process trial event queue
│   └── audio_player.py     ← async WAV playback (ffplay/afplay/aplay)
├── src/api/
│   ├── main.py             ← FastAPI app + static file mount
│   └── routes.py           ← /api/results, /api/trials, /webhooks/{platform}/{id}
└── src/frontend/
    ├── index.html          ← leaderboard UI
    ├── leaderboard.js      ← vanilla JS, Chart.js charts, trial detail panel
    └── style.css           ← dark theme
```

## Architecture decisions

- **Push/webhook event model**: Both Vapi and Retell fire webhook events; harness receives them via in-process queue (`webhook_store.py`). Pull polling was rejected — it introduces artificial latency and defeats latency measurement.
- **Platform-reported events only (v1)**: We trust each vendor's `user_speech_ended` as ground truth. This is documented as a v1 limitation in `methodology.md`; ground-truth VAD is planned for v1.5.
- **Audio playback triggered by `agent_speech_ended`**: More realistic than fixed schedule; consistent with using platform events throughout.
- **SQLite default**: Zero-dependency local storage. SQLAlchemy makes swapping to Postgres trivial. Postgres migration path noted in `ROADMAP.md`.
- **Built-in rate-limit backoff via tenacity**: `--rate-limit-rpm` flag (default 10); prevents silent mid-run failures.

## Product

- **Leaderboard** at `localhost:8000`: median + p95 per metric, both platforms, both scenarios, distribution bar charts.
- **Per-trial drill-down**: click any trial row to see the full canonical event timeline in a slide-in panel.
- **Benchmark CLI**: `scripts/run_benchmark.py --platform vapi|retell|all --scenario <id>|all --trials N`
- **Static export**: `scripts/export_results.py` dumps docs/ for GitHub Pages hosting.

## User preferences

_Populate as you build._

## Gotchas

- **Run tests from `voice-eval-harness/` directory**, not the repo root. `pytest` reads `pyproject.toml` from that directory.
- **DATABASE_URL** — the monorepo sets `DATABASE_URL` to PostgreSQL. Always pass `DATABASE_URL=sqlite:///./results.db` explicitly when running harness scripts from bash, or set it in `voice-eval-harness/.env`.
- **SCENARIOS_DIR** in `scenarios.py` is computed from `__file__` using `parents[2]` — one level above `src/`. If you move the file, update the path.
- **Audio fixture paths** in adapters use `parents[3]` from the adapter file (which is inside `src/harness/adapters/`).
- `tests/conftest.py` overrides `DATABASE_URL` to SQLite in-memory so tests never need psycopg2.
- `seed_audio.py` creates silent placeholder WAVs if `OPENAI_API_KEY` is not set. These are valid WAV files but contain silence — live trials will receive silence.
- **Workflow**: `Voice Eval Harness: Leaderboard` runs on port 8000.

## Pointers

- See `methodology.md` for the credibility document (vendor dispute process, event translation tables, statistical methodology)
- See `ROADMAP.md` for v1.5 (ground-truth VAD) and v2 (forced alignment, OpenAI Realtime) plans
- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
