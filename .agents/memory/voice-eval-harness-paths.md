---
name: Voice Eval Harness path computation
description: How SCENARIOS_DIR and audio directory paths are computed from __file__ in the harness; depths are different per file location.
---

# Path computation in voice-eval-harness

The harness uses `pathlib.Path(__file__).parents[N]` to locate the `scenarios/` directory relative to source files. The N varies by file depth:

- `src/harness/scenarios.py` → `parents[2]` = `voice-eval-harness/`
- `src/harness/adapters/vapi.py` and `retell.py` → `parents[3]` = `voice-eval-harness/`

**Why:** The project root (`voice-eval-harness/`) is the anchor for `scenarios/`, `scenarios/audio/`, etc. Each source file is at a different nesting depth, so the parent count differs.

**How to apply:** If you add a new adapter at a deeper nesting level, or move files, recount parents from the new `__file__` location. A wrong count gives a path that points outside the project (e.g., to `/home/runner/workspace/scenarios/` instead of `/home/runner/workspace/voice-eval-harness/scenarios/`) and silently fails with "file not found" rather than a clear import error.
