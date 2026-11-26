# Client execution — E0 baseline

Purpose: the baseline of spec `docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md` § 7
(measurement and success), taken **before** any client-execution change (E0). The same measurement is
repeated after every stage with the same scenario, so the numbers compare.

What it measures (read-only, `scripts/measure_client_execution.py`): server CPU per minute
(`utime+stime` of the uvicorn process), the client-execution routes `/play/pos`, `/play/worldmap`,
`/play/orders` (from the once-a-minute `hot_path client_exec_routes` lines in `logs/main.log`), the
travel-ticker beats and the prop-action `advance()` / `_advance_run` / `_validate` steps
(`hot_path client_exec_ticker`), and the native client's first step from click to the avatar's first
centimetre (`[native] first_step` lines of the client log).

## Preconditions

- The server runs with the commits of tasks 1–2 (route counters and ticker counters), restarted by the user.
- The world is a **clone** — never the play world.
- The native client is built with task 4 (first-step probe).
- The server must **not restart** during the measuring window; the script aborts when a log shrinks.

## Scenario checklist (the same every run)

1. [ ] The avatar walks freely for 60 s, then takes an armchair by click.
2. [ ] Three NPCs are sent to bed, one after another.
3. [ ] An overland journey is started and keeps running.

## Command

Run from the repo root while the scenario plays (window 420 s):

```bash
./.venv/bin/python scripts/measure_client_execution.py record --seconds 420 --pid $(cat .pids/main.pid) --client-log <export folder>/logs/native-<time>.log --label "E0 baseline" --out docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e0-baseline.md
```

- The PID comes from the PID file written by `start.sh` (`.pids/main.pid`), never from `pgrep -f`: under
  `sg render` that would hit the wrapper. The script additionally checks the process command line and
  aborts otherwise.
- `--client-log` is the current `native-*.log` of the running native client.
- The script appends its section (`## E0 baseline — <ISO time>`) with the filled-in table to this file.

## Result

Empty until the user's run appends its section below. Columns as written by the script:

| Metric | Value | Raw sum | Log line span s | Measured s |
|---|---|---|---|---|
| Server CPU s/min | | | | |
| `/play/pos`/s | | | | |
| `/play/pos`/min | | | | |
| `/play/worldmap`/min | | | | |
| `/play/orders`/min | | | | |
| Ticker beats/min | | | | |
| `advance()`/min | | | | |
| `_advance_run`/min | | | | |
| `_validate` in advance/min | | | | |
| First step median | | n/a | n/a | |

## E0 baseline — 2026-11-25T11:54:42+01:00

| Metric | Value | Raw sum | Log line span s | Measured s |
|---|---|---|---|---|
| Server CPU s/min | 136.4 | 955.0 | n/a | 420 |
| `/play/pos`/s | 0.0 | 0 | 369 | 420 |
| `/play/pos`/min | 0.0 | 0 | 369 | 420 |
| `/play/worldmap`/min | 8.8 | 54 | 369 | 420 |
| `/play/orders`/min | 0.0 | 0 | 369 | 420 |
| Ticker beats/min | 9.6 | 59 | 369 | 420 |
| `advance()`/min | 0.0 | 0 | 369 | 420 |
| `_advance_run`/min | 0.0 | 0 | 369 | 420 |
| `_validate` in advance/min | 0.0 | 0 | 369 | 420 |
| First step median | n/a | n/a | n/a | 420 |

## E0 baseline — 2026-11-25T13:12:19+01:00

| Metric | Value | Raw sum | Log line span s | Measured s |
|---|---|---|---|---|
| Server CPU s/min | 60.5 | 423.2 | n/a | 420 |
| `/play/pos`/s | 0.0 | 4 | 364 | 420 |
| `/play/pos`/min | 0.7 | 4 | 364 | 420 |
| `/play/worldmap`/min | 19.1 | 116 | 364 | 420 |
| `/play/orders`/min | 0.0 | 0 | 364 | 420 |
| Ticker beats/min | 11.5 | 70 | 364 | 420 |
| `advance()`/min | 5.3 | 32 | 364 | 420 |
| `_advance_run`/min | 37.3 | 226 | 364 | 420 |
| `_validate` in advance/min | 37.3 | 226 | 364 | 420 |
| First step median | n/a | n/a | n/a | 420 |

## E3 run

Same instructions as above, repeated after stage E3 (plan `docs/superpowers/plans/2026-11-25-client-ausfuehrung-e3.md`):

- Preconditions as above, plus: the server runs the E3 state (orders landed in `5b45e09a4`, tasks 12–14 on top),
  restarted by the user; the native client is the E3 AppImage (`~/claude-out/AnimaNative-latest.AppImage`).
- Same world clone, same scenario checklist (free walk 60 s then armchair by click; three NPCs to bed one after
  another; one overland journey running), same 420 s window.
- Command (only the label differs; the script appends its section below this one):

```bash
./.venv/bin/python scripts/measure_client_execution.py record --seconds 420 --pid $(cat .pids/main.pid) --client-log <export folder>/logs/native-<time>.log --label "E3 run" --out docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e0-baseline.md
```

Expected change against the second E0 baseline (2026-11-25T13:12:19):

- `_validate` in advance/min clearly below 37.3: the ticker now advances only due runs (`advance(due_only=True)`),
  and a furniture approach flips on its estimate timer instead of being validated every beat.
- `/play/orders`/min > 0 only after a push: the native client fetches `/play/orders` when the `orders` topic
  signals a change, never on a timer; a window without any order change shows 0.
- `/play/pos` and `/play/worldmap` are not expected to change in E3 (the reporting rule is E4).
