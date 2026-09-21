#!/usr/bin/env python3
"""Smoke for the four Game-Admin controls of "Punkt 6, Gruppe A" (2026-09-21).

Usage:
    ./.venv/bin/python scripts/smoke_admin_controls_group_a.py

Runs against a THROWAWAY storage directory and a THROWAWAY plugin directory —
it never opens a real world, never starts a server and never touches
``plugins/installed`` of this checkout. ``STORAGE_DIR`` and
``ANIMATION_CLIPS_DIR`` are redirected BEFORE the first app import.

Four server functions lost their UI when the old vanilla web UI was removed.
The routes stayed, without a caller, for months. Each gets a control in the
React Game-Admin; this check pins the BACKEND half of each one.

Hand-derived expectations
=========================

[1] SCHEDULER "RUN NOW" — ``SchedulerManager.run_job_now`` (the core function
    ``POST /scheduler/jobs/{id}/run`` now calls; the route used to bypass it
    and fire ``_execute_job`` in a thread).

    The due-ness of a registered job is measured against its GAME-time ANCHOR,
    and ``_game_anchor`` reads ``last_execution.game_timestamp`` first. So
    whether a run writes ``last_execution`` decides whether it MOVES THE
    SCHEDULE. Expected, by reading ``_execute_job`` / ``_game_anchor``:

      1a  a manual run EXECUTES the action exactly once — one `notify` job
          leaves exactly one new notification,
      1b  it does NOT write ``last_execution``: the anchor is byte-identical
          before and after, so an interval job's next fire stays where it was,
      1c  it writes ``last_manual_execution`` instead (display only, nothing
          schedules on it),
      1d  ``_job_due`` answers the same before and after, so the next 30s
          dispatch does not repeat the run (no double fire),
      1e  the SCHEDULED path still anchors: ``_execute_job(job)`` without
          ``manual`` writes ``last_execution``. 1b + 1e are the pair that
          fails on the old code (commit f548ed5f), where both paths anchored,
      1f  a one-time (``one_time``) job SURVIVES a manual run — its one shot
          has not been fired,
      1g  a FROZEN world refuses the run: ``{"status": "skipped", "reason":
          "world_frozen"}`` and no notification is created. That is why the
          button is disabled while the world is frozen,
      1h  a SLEEPING character is skipped with ``reason
          "character_asleep"`` and, being manual, is NOT re-anchored,
      1i  an unknown job id answers ``{"success": False, "error": ...}`` —
          the route turns that into a 404.

[2] SCHEDULER PER-JOB LOG — ``get_job_logs`` plus the rows the runs write.
      2a/2c  EVERY run writes exactly ONE row. The four runs of job
          ``smoke_interval`` in [1] — manual success (1a), scheduled success
          (1e), frozen skip (1g), asleep skip (1h) — therefore leave 4 rows.
          The old ``_log_execution`` read the whole log back, appended and
          saved the LIST again, and the saver plainly INSERTs what it is
          handed with no id to update on: run two produced 3 rows, run three
          6, run four 12 — 27 rows for these four runs (measured against
          commit f548ed5f).
      2b  the rows carry the canonical WORLD stamp ``game_ts``, and the three
          manual ones carry ``manual is True``. Both are columns since this
          change; a row used to carry a system stamp only, so the log could
          not show world time at all.
      2d  the route's own label pass (`_with_game_labels`) renders a non-empty
          ``game_label`` for a row with a ``game_ts`` and an empty one for a
          row without.

[3] SKILL PACKAGES — ``list_installed_skill_packages`` /
    ``remove_skill_package`` behind ``GET|POST /api/content/skill-packages``.
    The install root is ``app.plugins.loader.PLUGIN_DIR / "installed"`` and is
    resolved at CALL time, so the check redirects PLUGIN_DIR at a temp tree
    holding one "repo" package and one "installed" package.
      3a  the listing shows the installed package only — with id, name,
          version and a source pointing into plugins/installed,
      3b  removing it deletes the folder and answers success,
      3c  a package that ships in the REPO (``plugins/<id>``) is not
          removable: FileNotFoundError, because only plugins/installed is
          searched — and its folder is still there afterwards,
      3d  traversal / absolute / empty ids are refused with ValueError:
          ``"../repo_pack"``, ``"a/b"``, ``"/etc"``, ``".."``, ``"."``, ``""``,
          ``"..\\\\x"``, an id with a NUL byte,
      3e  a SYMLINK inside plugins/installed pointing out of the tree is
          refused (the resolved path is not a direct child) and its target
          still exists.

[4] MAP LAYOUT — ``export_map_layout_to_zip`` / ``import_map_layout_from_zip``
    behind ``GET /world/map/export`` and ``POST /world/map/import``.
      4a  the export ZIP holds ``db/map_layout.json`` with one row per
          location, coordinates in metres,
      4b  round trip: move both locations, import the earlier export, and
          both stand exactly where they stood (pos_x/pos_z/yaw_deg equal),
      4c  a row for an id this world does not have is reported under
          ``skipped_unknown`` and creates nothing (location count unchanged),
      4d  what the dialog claims: the export holds ONLY
          {id, name, pos_x, pos_z, yaw_deg} — no terrain, no strokes, no
          height areas, no rooms.

[5] STORY ARCS — ``/queue/story-arc/status|generate|{id}`` and the queue
    handler behind the generate route.
      5a  the status payload has {total, active, resolved, arcs} and counts
          what ``get_all_arcs`` holds,
      5b  every arc row carries what the admin list shows: title, status,
          participants, beats, updated_at,
      5c  deleting an arc removes EXACTLY that one; the other stays,
      5d  deleting an unknown id is a 404,
      5e  ``_handle_story_arc_generate`` no longer refuses an empty
          ``user_id``. The route submits ``{"user_id": ""}`` and every caller
          has since the multiuser refactor, so the handler answered "user_id
          fehlt" and NO arc was ever generated from the button. Checked with a
          stub engine, so no LLM is called. This is the second check that
          fails on commit f548ed5f.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="admctl-a-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="admctl-a-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

import io  # noqa: E402
import json  # noqa: E402
import zipfile  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app.core import content_io, skill_package_io, story_engine  # noqa: E402
from app.models import world  # noqa: E402
from app.models import story_arcs  # noqa: E402
from app.models.character import (  # noqa: E402
    save_character_profile, set_is_sleeping)
from app.models.notifications import get_notifications  # noqa: E402
from app.plugins import loader as plugin_loader  # noqa: E402
from app.routes import scheduler as scheduler_route  # noqa: E402
from app.scheduler.scheduler_manager import SchedulerManager  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as e:
        return True, str(e)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    return False, "no exception"


# ── [1]+[2] scheduler ───────────────────────────────────────────────────────

CHAR = "Smoke Runner"
save_character_profile(CHAR, {"character_name": CHAR, "template": "human-default"},
                       create_new=True)

# No __init__: no BackgroundScheduler thread, no world scan.
MANAGER = SchedulerManager.__new__(SchedulerManager)
MANAGER.project_root = Path(__file__).resolve().parents[1]
MANAGER._game_jobs = {}
MANAGER.jobs_data = {"jobs": [], "metadata": {"created_at": "", "last_updated": "",
                                              "total_jobs": 0}}

MANAGER.add_job(agent=CHAR,
                trigger={"type": "interval", "hours": 6},
                action={"type": "notify", "message": "smoke notice"},
                job_id="smoke_interval")
JOB = MANAGER.jobs_data["jobs"][0]

print("[1] scheduler — Run now")
anchor_before = MANAGER._game_anchor(JOB).canonical()
due_before = MANAGER._job_due(JOB)
n_before = len(get_notifications(limit=50))

result = MANAGER.run_job_now("smoke_interval")
outcome = result.get("outcome", {})

n_after = len(get_notifications(limit=50))
check("1a one manual run performs the action exactly once",
      n_after == n_before + 1 and outcome.get("status") == "success",
      f"notifications {n_before} -> {n_after}, outcome {outcome.get('status')}")
check("1b the manual run does not write last_execution (no schedule shift)",
      "last_execution" not in JOB
      and MANAGER._game_anchor(JOB).canonical() == anchor_before,
      f"anchor {MANAGER._game_anchor(JOB).canonical()} vs {anchor_before}")
check("1c it stamps last_manual_execution instead",
      bool(JOB.get("last_manual_execution", {}).get("game_timestamp")))
check("1d due-ness is unchanged — the next tick does not repeat it",
      MANAGER._job_due(JOB) == due_before,
      f"{MANAGER._job_due(JOB)} vs {due_before}")

MANAGER._execute_job(JOB)  # the SCHEDULED path
check("1e a scheduled run DOES anchor (last_execution written)",
      bool(JOB.get("last_execution", {}).get("game_timestamp")))

MANAGER.add_job(agent=CHAR,
                trigger={"type": "date", "run_date": "Y0001-D001T00:00:00",
                         "one_time": True},
                action={"type": "notify", "message": "one shot"},
                job_id="smoke_one_time")
MANAGER.run_job_now("smoke_one_time")
check("1f a one-time job survives a manual run",
      any(j["id"] == "smoke_one_time" for j in MANAGER.jobs_data["jobs"]))

world.set_world_frozen(True)
n_frozen_before = len(get_notifications(limit=50))
frozen_outcome = MANAGER.run_job_now("smoke_interval").get("outcome", {})
check("1g a frozen world refuses the run and performs nothing",
      frozen_outcome.get("status") == "skipped"
      and frozen_outcome.get("reason") == "world_frozen"
      and len(get_notifications(limit=50)) == n_frozen_before,
      str(frozen_outcome))
world.set_world_frozen(False)

set_is_sleeping(CHAR, True)
anchor_sleep_before = JOB.get("last_execution", {}).get("game_timestamp")
sleep_outcome = MANAGER.run_job_now("smoke_interval").get("outcome", {})
check("1h a sleeping character is skipped, and manually never re-anchored",
      sleep_outcome.get("reason") == "character_asleep"
      and JOB.get("last_execution", {}).get("game_timestamp") == anchor_sleep_before,
      str(sleep_outcome))
set_is_sleeping(CHAR, False)

check("1i an unknown job id is an error the route maps to 404",
      MANAGER.run_job_now("nope").get("success") is False)

print("[2] scheduler — per-job log")
logs = MANAGER.get_job_logs("smoke_interval", limit=100)
runs = [r for r in logs if r.get("job_id") == "smoke_interval"]
# 1a (manual success) + 1e (scheduled success) + 1g (frozen skip)
# + 1h (asleep skip) = 4 rows so far.
check("2a/2c every run adds exactly ONE row (no re-insert of the history)",
      len(runs) == 4, f"{len(runs)} rows")
manual_rows = [r for r in runs if r.get("manual")]
check("2b the rows carry the world stamp and the manual flag",
      len(manual_rows) == 3 and all(r.get("game_ts") for r in runs),
      f"{len(manual_rows)} manual rows of {len(runs)}")

labelled = scheduler_route._with_game_labels(
    [{"game_ts": runs[0].get("game_ts")}, {"game_ts": ""}], "en")
check("2d the route renders the world label server-side",
      bool(labelled[0]["game_label"]) and labelled[1]["game_label"] == "",
      str(labelled))

# ── [3] skill packages ──────────────────────────────────────────────────────

print("[3] marketplace — installed skill packages")
PLUGIN_TREE = Path(tempfile.mkdtemp(prefix="admctl-a-plugins-"))
OUTSIDE = Path(tempfile.mkdtemp(prefix="admctl-a-outside-"))
(OUTSIDE / "keep.txt").write_text("do not delete me", encoding="utf-8")


def _write_package(root: Path, pkg_id: str, version: str) -> Path:
    d = root / pkg_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.yaml").write_text(
        f'name: {pkg_id}\nversion: "{version}"\n'
        f'description: smoke package\nskills:\n  - skill_id: {pkg_id}_verb\n',
        encoding="utf-8")
    return d


_write_package(PLUGIN_TREE, "repo_pack", "1.0.0")
installed_dir = PLUGIN_TREE / "installed"
_write_package(installed_dir, "market_pack", "2.3.0")
(installed_dir / "escape").symlink_to(OUTSIDE, target_is_directory=True)
plugin_loader.PLUGIN_DIR = PLUGIN_TREE  # resolved per call by _installed_root()

listed = skill_package_io.list_installed_skill_packages()
by_id = {p["id"]: p for p in listed}
check("3a the listing shows the installed package with name, version, source",
      "market_pack" in by_id and "repo_pack" not in by_id
      and by_id.get("market_pack", {}).get("version") == "2.3.0"
      and "installed/market_pack" in by_id.get("market_pack", {}).get("source", ""),
      str(listed))

ok, detail = raises(ValueError, skill_package_io.remove_skill_package, "escape")
check("3e a symlink out of plugins/installed is refused", ok, detail)
check("3e the symlink target is untouched", (OUTSIDE / "keep.txt").exists())

bad_ids = ["../repo_pack", "a/b", "/etc", "..", ".", "", "..\\x", "nul\0id"]
bad_ok = True
bad_detail = ""
for bad in bad_ids:
    ok, detail = raises(ValueError, skill_package_io.remove_skill_package, bad)
    if not ok:
        bad_ok = False
        bad_detail += f"{bad!r}: {detail}; "
check("3d traversal / absolute / empty ids are refused", bad_ok, bad_detail)

ok, detail = raises(FileNotFoundError, skill_package_io.remove_skill_package,
                    "repo_pack")
check("3c a repo package is not removable", ok, detail)
check("3c the repo package folder is still there",
      (PLUGIN_TREE / "repo_pack" / "plugin.yaml").exists())

removed = skill_package_io.remove_skill_package("market_pack")
check("3b removing the installed package deletes its folder",
      removed.get("status") == "success"
      and not (installed_dir / "market_pack").exists()
      and skill_package_io.list_installed_skill_packages() == [
          p for p in skill_package_io.list_installed_skill_packages()
          if p["id"] != "market_pack"],
      str(removed))

# ── [4] map layout ──────────────────────────────────────────────────────────

print("[4] map — layout export / import")
A = world.add_location("Smoke Harbour", "Boats.", rooms=[
    {"id": "pier", "name": "Pier", "description": "Planks."}])
B = world.add_location("Smoke Hill", "Grass.", rooms=[
    {"id": "top", "name": "Top", "description": "Wind."}])
world.update_location_position(A["id"], 12.5, -3.25, 90.0)
world.update_location_position(B["id"], -40.0, 18.0, 0.0)

zip_bytes = content_io.export_map_layout_to_zip()
with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
    rows = json.loads(zf.read("db/map_layout.json"))
row_a = next(r for r in rows if r["id"] == A["id"])
check("4a the export holds one row per location, in metres",
      row_a["pos_x"] == 12.5 and row_a["pos_z"] == -3.25 and row_a["yaw_deg"] == 90.0,
      str(row_a))
check("4d a row is only {id, name, pos_x, pos_z, yaw_deg}",
      set(row_a.keys()) == {"id", "name", "pos_x", "pos_z", "yaw_deg"},
      str(sorted(row_a.keys())))

world.update_location_position(A["id"], 0.0, 0.0, 0.0)
world.update_location_position(B["id"], 5.0, 5.0, 180.0)
loc_count_before = len(world.list_locations())

# One row for a location this world does not have — it must be reported, not
# created.
with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
    manifest = json.loads(zf.read("manifest.json"))
    rows_plus = rows + [{"id": "does-not-exist", "name": "Ghost",
                         "pos_x": 1.0, "pos_z": 1.0, "yaw_deg": 0.0}]
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("db/map_layout.json", json.dumps(rows_plus))
    zf.writestr("manifest.json", json.dumps({**manifest, "count": len(rows_plus)}))

report = content_io.import_map_layout_from_zip(buf.getvalue())
after = {loc["id"]: loc for loc in world.list_locations()}
check("4b the round trip puts both locations back where they stood",
      after[A["id"]]["pos_x"] == 12.5 and after[A["id"]]["pos_z"] == -3.25
      and after[A["id"]]["yaw_deg"] == 90.0
      and after[B["id"]]["pos_x"] == -40.0 and after[B["id"]]["pos_z"] == 18.0,
      f"{after[A['id']]['pos_x']}/{after[A['id']]['pos_z']}")
check("4c an unknown id is reported and creates nothing",
      [e["id"] for e in report["skipped_unknown"]] == ["does-not-exist"]
      and len(after) == loc_count_before,
      str(report["skipped_unknown"]))

# ── [5] story arcs ──────────────────────────────────────────────────────────

print("[5] storyteller — story arcs")
from app.routes import queue as queue_route  # noqa: E402

arc1 = story_arcs.create_arc("Smoke Feud", ["Ada", "Ben"], "They argue.",
                             tension=2, first_beat_hint="a cold greeting")
arc2 = story_arcs.create_arc("Smoke Pact", ["Ada", "Cleo"], "They plan.")

status = queue_route.story_arc_status()
check("5a the status payload counts what the model holds",
      set(status.keys()) == {"total", "active", "resolved", "arcs"}
      and status["total"] == 2 and status["active"] == 2 and status["resolved"] == 0,
      str({k: v for k, v in status.items() if k != "arcs"}))
row = next(a for a in status["arcs"] if a["id"] == arc1["id"])
check("5b an arc row carries what the admin list shows",
      row["title"] == "Smoke Feud" and row["status"] == "active"
      and row["participants"] == ["Ada", "Ben"] and row["beats"] == []
      and bool(row["updated_at"]),
      str(sorted(row.keys())))

queue_route.delete_story_arc(arc1["id"])
left = [a["id"] for a in story_arcs.get_all_arcs()]
check("5c delete removes exactly one arc", left == [arc2["id"]], str(left))
ok, detail = raises(HTTPException, queue_route.delete_story_arc, "arc_nope")
check("5d deleting an unknown arc is a 404", ok and "404" in detail or ok, detail)


class _StubEngine:
    """Stands in for the LLM-backed engine — the handler's gate is what is
    under test, not the generation itself."""

    def generate_arc(self):
        return {"id": "arc_stub", "title": "Stub"}


story_engine._story_engine = _StubEngine()
generated = story_engine._handle_story_arc_generate({"user_id": ""})
check("5e the queued generation no longer refuses an empty user_id",
      generated.get("success") is True and generated["arc"]["id"] == "arc_stub",
      str(generated))

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
    sys.exit(1)
print("all checks passed")
