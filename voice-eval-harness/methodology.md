# Methodology

This document is the credibility record for Voice AI Eval Harness results. If a vendor disputes a result, they should dispute the methodology here first — the maintainer commits to addressing objections within 7 days (see [Contesting a result](#contesting-a-result)).

---

## 1. What we measure and why

### 1.1 Time-to-First-Response (TTFR)

**Definition:** The delta (seconds) from the platform-reported `user_speech_ended` event to the platform-reported `agent_speech_started` event, measured per user turn.

**Aggregation:** Median and p95 across all turns across all trials for a given (platform, scenario) pair.

**Why this metric:** TTFR is the dominant contributor to perceived conversational naturalness. Every vendor claims sub-500ms; this provides a reproducible measurement.

**Unit:** Seconds (displayed as milliseconds in the UI).

---

### 1.2 Barge-in Response Time

**Definition:** When a user interrupts the agent mid-utterance, the delta (seconds) from `user_speech_started` (received while the agent is speaking) to `agent_speech_ended` (platform stops the agent).

**Aggregation:** Median and p95 across all detected barge-in events across all trials.

**Why this metric:** Barge-in handling is the second most-cited latency claim. A platform that can't stop its agent quickly feels unnatural and frustrating.

**Unit:** Seconds (displayed as milliseconds in the UI).

---

### 1.3 Tool-Call Accuracy

**Definition:** Whether the platform's agent dispatched the correct tool (`book_appointment`) with args that satisfy an exact-match check (case-insensitive string match for `patient_name`; substring match for `appointment_datetime` to allow flexible date resolution).

**Aggregation:** Pass rate across trials (e.g. 9/10 = 90%).

**Why this metric:** Voice agents are only useful if they take the right actions. Latency without accuracy is irrelevant.

---

### 1.4 Turn-Completion Rate

**Definition:** Whether the scenario reached its success state: the minimum number of agent turns completed AND all required tool calls satisfied.

**Aggregation:** Pass rate across trials.

**Why this metric:** Composite "did it work" signal. A scenario that times out or produces the wrong tool call gets 0.

---

## 2. What we don't measure in v1

| Not measured | Reason |
|---|---|
| Ground-truth VAD | Would require recording the agent's audio stream and running a local VAD. Planned for v1.5. |
| First-content-word latency | Requires forced alignment (WhisperX or MFA). Planned for v2. |
| Audio quality / MOS | Subjective; requires human raters. Not in scope for an automated harness. |
| Cost per call | Pricing varies by plan, region, and negotiated rates. Fair comparison is not possible without vendor cooperation. |
| Concurrency / load behavior | Different ethical and TOS considerations; planned for v2 with an opt-in flag. |
| Regional latency variation | We run from a single Replit region (US East). Results may differ in other regions. |

---

## 3. Event-stream methodology

**v1 uses platform-reported events.** We do not independently verify when speech started or ended. Specifically:

> We treat each vendor's `user_speech_ended` event as ground truth for v1.

**Trust assumption:** The platform's VAD is the source of truth for when the user finished speaking. This is the same signal the platform uses internally to trigger its response, so measuring TTFR from this event is internally consistent.

**Known limitation:** A platform with a more aggressive (hair-trigger) VAD will cut the user off sooner and thus appear to have a lower TTFR — not because its response is faster, but because it declared the user done speaking earlier. This will be addressed in v1.5 by running ground-truth VAD on the captured audio.

---

## 4. Per-platform event translation table

### 4.1 Vapi

Source: [Vapi webhook documentation](https://docs.vapi.ai/webhooks)

Timestamp source: Harness-local `time.monotonic()` at webhook receipt (network round-trip jitter: ~1–5 ms on co-located infra).

| Vapi event | Field | Canonical event |
|---|---|---|
| `speech-update` | `role=user, status=started` | `user_speech_started` |
| `speech-update` | `role=user, status=stopped` | `user_speech_ended` |
| `speech-update` | `role=assistant, status=started` | `agent_speech_started` |
| `speech-update` | `role=assistant, status=stopped` | `agent_speech_ended` |
| `function-call` | `functionCall.name`, `functionCall.parameters` | `tool_call_dispatched` |
| `function-call-result` | `result` | `tool_call_completed` |
| `end-of-call-report` | — | `call_ended` |
| `hang` | — | `call_ended` |

**Caveat:** Vapi does not include per-event timestamps in webhook payloads (as of v1 publication). We use harness wall-clock time. If Vapi adds event timestamps in a future API version, the adapter will be updated to use them.

---

### 4.2 Retell

Source: [Retell webhook documentation](https://docs.retellai.com/features/webhooks)

Timestamp source: Retell-provided `timestamp` field (epoch milliseconds), converted to seconds-since-call-start using the `call_started` event as origin. This is more accurate than Vapi's harness-clock approach.

| Retell event | Canonical event |
|---|---|
| `call_started` | (harness internal; sets call clock origin) |
| `user_speech_started` | `user_speech_started` |
| `user_speech_ended` | `user_speech_ended` |
| `agent_speech_started` | `agent_speech_started` |
| `agent_speech_ended` | `agent_speech_ended` |
| `tool_call_invocation` | `tool_call_dispatched` |
| `tool_call_result` | `tool_call_completed` |
| `call_ended` | `call_ended` |

Retell's event names map almost 1:1 to the canonical schema; the translation is minimal.

---

## 5. Statistical methodology

- **N = 10 trials** per (platform, scenario) in v1. This is a methodology-transparent estimate, not a definitive ranking. Before publishing an official leaderboard, we will run N = 50 (planned for v1.5).
- **Reported statistics:** Median (p50) and 95th percentile (p95). We do not report mean because latency distributions are right-skewed; the mean is distorted by occasional high-latency outliers.
- **Full distributions** are stored in the database and accessible in the per-trial detail drill-down.
- **Justification for N = 10:** Each trial involves a real telephony round-trip (~30–60 seconds). N = 10 per scenario per platform = ~20 minutes of benchmark time per run, which is practical for reproduction from a clean clone. N = 50 takes ~2 hours and is reserved for official publications.

---

## 6. Platform configuration choices

All runs use the same configuration across platforms to maximize comparability:

| Parameter | Value | Justification |
|---|---|---|
| Model | `gpt-4o` | Both platforms support it; it is each vendor's documented recommended model for booking/tool-use tasks |
| Voice | `alloy` (OpenAI TTS) | Available on both platforms; neutral, clearly intelligible |
| Temperature | `0` | Maximizes determinism for tool-call accuracy evaluation |
| System prompt | See `scenarios/*.yaml` | Identical across platforms |
| Tool schema | See `scenarios/*.yaml` | Identical across platforms |

---

## 7. Reproducibility checklist

- [x] All scenario definitions committed to `scenarios/*.yaml`
- [x] Synthetic user audio committed to `scenarios/audio/*.wav` (generated once via `scripts/seed_audio.py`, not regenerated per run)
- [x] Pinned Python dependencies in `pyproject.toml`
- [x] Dockerfile with pinned base image (`python:3.11-slim`)
- [x] `docker compose up` from a clean clone produces a working harness
- [ ] **Non-determinism acknowledgement:** LLM outputs (the agent's words, tool call argument formatting) are not fully deterministic even at temperature=0. Mitigation: N = 10 trials, robust success criteria (substring match for datetime, case-insensitive for name).

---

## 8. Known confounders

| Confounder | Effect | Mitigation |
|---|---|---|
| Network latency between Replit and vendor APIs | Inflates all TTFR measurements by the same amount; does not affect relative rankings unless vendors have different API endpoint geographies | Document Replit region; note in results |
| Time-of-day load on vendor infrastructure | Vendor infrastructure may be under different load at different times | Run benchmarks at consistent times; report run timestamp |
| LLM non-determinism | Tool call args may vary across trials | Robust substring matching; N = 10 trials |
| VAD aggressiveness (v1 limitation) | Platforms with hair-trigger VAD appear faster | Documented in section 3; addressed in v1.5 |
| Webhook delivery order | Webhooks are HTTP POST and may arrive slightly out of order under load | Events are sorted by timestamp before metric computation |

---

## Contesting a result

If you believe a result is incorrect — wrong configuration, a platform bug that has since been fixed, or a methodology error — please:

1. Open a GitHub issue with: the platform, scenario, specific metric, expected behavior, and observed behavior.
2. Include a reproducible config if the issue is configuration-related.
3. The maintainer commits to a re-run within **7 days** of a complete bug report.
4. If the re-run produces different results, the issue will be documented and the leaderboard updated.

We welcome vendor participation. If you work at Vapi, Retell, or another platform and want to provide a canonical test configuration, open a pull request against `scenarios/*.yaml`.
