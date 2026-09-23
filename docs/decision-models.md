# Decision models

Optional typed decisions from a fast non-generative model. Spec:
`development_instructions/plan-decision-models.md`.

## What it is

A decision model answers questions about a state — `noul` (yes/no), `choice` (one of up to 255
keys), `score` (a point on a scale) — with probabilities, in 10–500 ms, without generating text.
Laya (Apache 2.0), openjev (MIT) and TypeSafe Jev all speak the same protocol:

    POST <base-url>/v1/systemone
    {"model": "", "state": {...}, "questions": {"<name>": {"type": "choice", "instructions": "...",
      "criteria": {"<key>": "<description>", ...}}}}

Response: `{"answers": {"<name>": {"choice"|"noul"|"score": ..., "probabilities": {...}}}}`.

## The contract

`app.core.decision.decide()` returns `None` whenever the caller should take its usual path:
master switch off, point unknown or `off`, no usable endpoint, timeout/HTTP/JSON error, an answer
that does not fit, or mode `shadow`. It never raises. Nothing may depend on a decision model.

## Configuration — `/admin/settings → Decision models`

- **Endpoints:** master switch + list of `{name, url, api_key, model, enabled}`. With llama-swap
  the URL is `http://<host>:8080/upstream/<model>` (`POST /v1/systemone` directly on llama-swap is a
  404). Leave `model` empty: jev-serve then routes German text to Laya's multilingual checkpoint;
  `laya` would force the English one. **Test** sends one probe question (30-s timeout, warms a
  cold slot).
- **Points:** per decision point the mode (`off` / `shadow` / `on`), the endpoint list (the first
  decides in `on`; `shadow` asks all), `min_confidence`, `timeout_s`. Read live, no restart.
- **Shadow results:** per point × endpoint × question — calls, errors, latency p50/p95, answers,
  share below the minimum confidence, agreement with the usual path (confident answers only),
  no outcome, taken.

## Confidence

Computed by the client from `probabilities`, never taken from the server: `choice` → probability
of the chosen key, `score` → largest probability, `noul` → `max(p, 1 − p)`. Laya reports
`1 − normalised entropy` and openjev the largest probability as `confidence`; one threshold would
otherwise mean two things.

## Failures

No retry. Three failures in a row block an endpoint for 60 s (shown on the Endpoints page).
Warnings are throttled to one per endpoint and reason per 10 minutes. Shadow calls run in a
background pool (8 at most, further calls are skipped) and never add latency.

## Log and statistics

`logs/decisions.jsonl` (archived monthly like `llm_calls.jsonl`, joins on `trace_id`) and the
`decision_stats` table in `world.db`.

## Decision points of the core

| Point | Where | Question | `on` does |
|---|---|---|---|
| `thought_skip` | `AgentLoop._run_turn`, idle thought without perception, hint or unread inbox | `turn`: `act` / `idle` | `idle` → no LLM turn, outcome `decision_skip` |
| `pose_match` | `pose_catalog.resolve_to_catalog(axis="pose")` after the exact alias | `group`, then `entry` of that group (+ `none`) | confident key wins over the embedding; `none` → candidate list |
| `expression_match` | same, `axis="expression"` | `entry` (+ `none`) | same |

## Adding a point (core or plugin)

1. `register_point("my_point", label=..., description=..., origin="<package>")` — a plugin in its
   `on_load` module.
2. At the call site: `if decision.is_active("my_point"):` build state + questions, `key = …`,
   `d = decide(...)`; act only on `d.answers.get(...)`; otherwise run the usual path and
   `record_outcome("my_point", key, {...})`; after acting in `on`, `mark_taken("my_point", key)`.
3. The usual path stays complete — the point must work with the master switch off.
