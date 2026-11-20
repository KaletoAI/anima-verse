"""Usage: ./.venv/bin/python scripts/suitability_exclude_model_load.py            # dry run: before/after table
          ./.venv/bin/python scripts/suitability_exclude_model_load.py --apply    # write (SERVER STOPPED)

One-time repair of stored model-test results from before a888da62e. Until then
a test sent its first requests to a model the server still had to load, and
that load time sat in the answer time of the FIRST case's requests without
thinking (2026-11-20). Scores are untouched — only time figures change.

What counts as a load: a request of the first case's pass without thinking
that took more than 3x the median of the other cases' off-stage durations AND
at least 5 s longer than it. Only the first case is looked at (nothing else is
sent before it); a slow first vision case may be a projector load as well, but
that cannot be told from a slow image and stays as measured.

What is corrected, in the shared result (current and history entries) and in
the local sidecar run it names (diagnostic_run_id):
- the load requests lose their duration (duration_s 0, the original value kept
  as load_excluded_s) — the same marking a request without a valid time has;
- the first case's off-stage duration (and, when that stage decided the case,
  its duration and tok/s) from the remaining requests, 0 = no clean sample;
- the group's tok/s and median latency, the projected turn, speed_ok — by the
  formulas of model_suitability._summarize, from the sidecar's runs.
Self-check: the same formulas must reproduce the STORED figures from the
unmodified runs first; a result where they do not is reported and left alone.
A verdict that only speed decided is not rewritten here: the row is reported
as "retest" instead.
"""
import argparse
import copy
import json
import shutil
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
FACTOR, MARGIN_S = 3.0, 5.0
TURN_TASKS = ("thought", "extraction_chat_state", "extraction")


def timed(runs):
    return [r for r in runs if float(r.get("duration_s") or 0) > 0 and not r.get("error")]


def figures(checks, recommended):
    """speed per group, projected turn — as model_suitability._summarize."""
    eligible = [c for c in checks if c.get("recommended_ok", c.get("ok")) is not None]
    speed = {}
    for group in ("tools", "helpers", "vision"):
        runs = timed([r for c in eligible if c.get("group") == group for r in recommended.get(c["id"], [])])
        durations = [r["duration_s"] for r in runs]
        tokens = sum(int((r.get("usage") or {}).get("completion_tokens") or 0) for r in runs)
        speed[group] = {"median_latency_s": round(median(durations), 2) if durations else None,
                        "tok_s": round(tokens / sum(durations), 1) if durations else None}
    medians = []
    for task in TURN_TASKS:
        runs = timed([r for c in eligible if c.get("task") == task for r in recommended.get(c["id"], [])])
        medians.append(median([r["duration_s"] for r in runs]) if runs else None)
    projected = sum(medians) if all(v is not None for v in medians) else None
    return speed, projected


def stored_figures(ts):
    speed = {g: {k: (v or {}).get(k) for k in ("median_latency_s", "tok_s")}
             for g, v in (ts.get("speed") or {}).items()}
    return speed, ts.get("projected_turn_s")


def same(a, b):
    (speed_a, proj_a), (speed_b, proj_b) = a, b
    close = lambda x, y: x == y or (x is not None and y is not None and abs(x - y) < 1e-6)
    return (all(close(speed_a.get(g, {}).get(k), speed_b.get(g, {}).get(k))
                for g in ("tools", "helpers", "vision") if g in speed_b for k in ("median_latency_s", "tok_s"))
            and close(proj_a, proj_b))


def sidecar_run(outputs, key, run_id):
    latest = outputs.get("outputs", {}).get(key) or {}
    if run_id and latest.get("run_id") == run_id:
        return latest
    return next((item for item in reversed(outputs.get("history", {}).get(key, []))
                 if run_id and item.get("run_id") == run_id), None)


def repair(key, record, outputs):
    """Returns a report row, or None when the result carries no model load.
    Mutates record and the sidecar run in place (the caller works on copies
    in a dry run)."""
    ts = record.get("tested_suitability") or {}
    checks = ts.get("checks") or []
    if not checks or "load_excluded_s" in ts:
        return None
    first = checks[0]
    stages = first.get("stages") or []
    others = [(c.get("stages") or [{}])[0].get("duration_s") for c in checks[1:]]
    others = [d for d in others if d]
    if not stages or not others or not stages[0].get("duration_s"):
        return None
    limit = max(FACTOR * median(others), median(others) + MARGIN_S)
    off_mean = stages[0]["duration_s"]
    side = sidecar_run(outputs, key, ts.get("diagnostic_run_id"))
    row = {"model": key, "off_before": off_mean, "tok_before": (ts["speed"].get(first["group"]) or {}).get("tok_s"),
           "median_before": (ts["speed"].get(first["group"]) or {}).get("median_latency_s"),
           "projected_before": ts.get("projected_turn_s"), "speed_ok_before": ts.get("speed_ok"),
           "verdict": ts.get("verdict")}
    if side is None:
        if off_mean <= limit:
            return None
        return {**row, "status": "no sidecar run — left alone"}
    recommended = side.get("recommended_cases") or {}
    if not same(figures(checks, recommended), stored_figures(ts)):
        if off_mean <= limit:
            return None
        return {**row, "status": "self-check failed — left alone"}
    group_budget = first.get("recommended_budget") or 0
    lists = []
    if first.get("stage") == 0:
        lists.append((side.get("cases") or {}).get(first["id"]) or [])
    if group_budget == 0:
        lists.append(recommended.get(first["id"]) or [])
    off_runs = lists[0] if lists else None
    if off_runs is not None:
        cold = [r for r in off_runs if float(r.get("duration_s") or 0) > limit]
        if not cold:
            return None
        load = max(r["duration_s"] for r in cold)
        for runs in lists:
            for run in runs:
                if float(run.get("duration_s") or 0) > limit:
                    run["load_excluded_s"] = run["duration_s"]
                    run["duration_s"] = 0
        clean = timed(off_runs)
        off_after = round(sum(r["duration_s"] for r in clean) / len(clean), 2) if clean else 0.0
        tokens = sum(int((r.get("usage") or {}).get("completion_tokens") or 0) for r in clean)
        tok_after = round(tokens / sum(r["duration_s"] for r in clean), 1) if clean else 0.0
    else:
        # The off runs were replaced by a later stage's in the sidecar: only
        # the stored mean is left, and it holds the load.
        if off_mean <= limit:
            return None
        load, off_after, tok_after = off_mean, 0.0, None
    stages[0]["duration_s"] = off_after
    if first.get("stage") == 0:
        first["duration_s"] = off_after
        if tok_after is not None:
            first["tok_s"] = tok_after
    first["load_excluded_s"] = round(load, 2)
    speed, projected = figures(checks, recommended)
    for group, values in speed.items():
        if group in (ts.get("speed") or {}) and ts["speed"][group] is not None:
            ts["speed"][group].update(values)
    ts["projected_turn_s"] = projected
    speed_ok = projected is not None and projected <= (ts.get("max_turn_seconds") or 20)
    status = "corrected"
    if speed_ok != bool(ts.get("speed_ok")):
        status = "corrected — speed verdict changes, RETEST for the verdict"
    ts["speed_ok"] = speed_ok
    ts["load_excluded_s"] = round(load, 2)
    if "tested_speed" in record:
        record["tested_speed"] = copy.deepcopy(ts["speed"])
    thinking = (ts.get("thinking") or {}).get(first["group"]) or {}
    if thinking.get("median_latency_s_recommended") == row["median_before"]:
        thinking["median_latency_s_recommended"] = speed[first["group"]]["median_latency_s"]
    return {**row, "status": status, "load": round(load, 1), "off_after": off_after,
            "tok_after": speed[first["group"]]["tok_s"], "median_after": speed[first["group"]]["median_latency_s"],
            "projected_after": projected, "speed_ok_after": speed_ok}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--capabilities", default=str(ROOT / "shared/config/model_capabilities.json"))
    parser.add_argument("--outputs", default=str(ROOT / "shared/config/model_capabilities_outputs.json"))
    parser.add_argument("--apply", action="store_true", help="write both files (stop the server first)")
    parser.add_argument("--backup-dir", default="", help="where --apply copies both files first (required)")
    args = parser.parse_args()
    caps_path, outs_path = Path(args.capabilities), Path(args.outputs)
    caps = json.loads(caps_path.read_text(encoding="utf-8"))
    outs = json.loads(outs_path.read_text(encoding="utf-8"))
    rows = []
    for key, record in caps.get("suitability", {}).items():
        row = repair(key, record, outs)
        if row:
            rows.append({**row, "entry": "current"})
    for key, records in caps.get("suitability_history", {}).items():
        for index, record in enumerate(records):
            row = repair(key, record, outs)
            if row:
                rows.append({**row, "entry": f"history {index}"})
    num = lambda v: "-" if v is None else f"{v:.1f}"
    print(f"{'model':58} {'entry':10} {'load s':>7} {'case 1 off s':>14} {'tok/s':>12} {'median s':>12} {'turn s':>12}  status")
    for r in rows:
        if "load" not in r:
            print(f"{r['model'][:58]:58} {r['entry']:10} {'?':>7} {num(r['off_before']):>14} {'':>12} {'':>12} {'':>12}  {r['status']}")
            continue
        pair = lambda a, b: f"{num(a)}>{num(b)}"
        print(f"{r['model'][:58]:58} {r['entry']:10} {r['load']:>7} {pair(r['off_before'], r['off_after']):>14} "
              f"{pair(r['tok_before'], r['tok_after']):>12} {pair(r['median_before'], r['median_after']):>12} "
              f"{pair(r['projected_before'], r['projected_after']):>12}  {r['status']}")
    print(f"{len(rows)} result(s) with a model load in the first case")
    if not args.apply:
        print("dry run — nothing written (use --apply with the server stopped)")
        return 0
    if not args.backup_dir:
        print("--apply needs --backup-dir", file=sys.stderr)
        return 2
    backup = Path(args.backup_dir)
    backup.mkdir(parents=True, exist_ok=True)
    for path in (caps_path, outs_path):
        shutil.copy2(path, backup / path.name)
    caps_path.write_text(json.dumps(caps, indent=2, ensure_ascii=False), encoding="utf-8")
    outs_path.write_text(json.dumps(outs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"written; backups in {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
