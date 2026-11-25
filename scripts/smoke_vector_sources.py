#!/usr/bin/env python3
"""Guard: every shared test vector names WHERE its numbers are derived.

Usage:
    ./.venv/bin/python scripts/smoke_vector_sources.py               # the guard ([V1]-[V3], [V5])
    ./.venv/bin/python scripts/smoke_vector_sources.py --verify-move # only [V4], the one-time move proof
    ./.venv/bin/python scripts/smoke_vector_sources.py --extract <old source>
        # prints the opening docstring of <old source> at PIN, unchanged

No server, no world, no storage: it reads shared/test-vectors/*.json and the
files they name, plus 'git show PIN:<path>' for [V4] and --extract.

Why. Every 'shared/test-vectors/<name>.json' carries a 'source': the file whose
docstring derives each expected number by hand. Until E1 (2026-11-25) almost
all of them pointed into client3d/scripts/, which E3 deletes together with the
browser scene. E1 moves every derivation out of client3d/ first:
  class A  - the smoke tests package code only (packages/scene-render) and
             moves as a whole: client3d/scripts/X -> scripts/X;
  class B  - the logic lives on only natively after E3: the derivation moves
             word for word into native/tests/Derivations/<smoke>.md, executed
             by the C# vector tests; the JS smoke keeps a pointer docstring;
  class C  - a Python smoke already replays the vector: the derivation moves
             word for word into that smoke's module docstring.

Checks
  [V1] 'source' is an existing repo file (relative to the repo root).
  [V2] no 'source' starts with 'client3d/'.
  [V3] the source file contains EXACTLY '<name>.json' (not preceded by a word
       character, so 'prop_water.json' does not prove 'water') or
       loadVectors('<name>') / loadVectors("<name>"). Checked only when [V1]
       and [V2] hold: a client3d/ source is already a violation, and several
       of the browser smokes load their vectors through a local helper, so
       [V3] would count the same vector twice. Every source outside client3d/
       (a moved smoke, a Python smoke, a native/tests/Derivations/*.md) must
       name its vector files literally.
  [V4] (only with --verify-move) for every MOVED entry,
       normalize(opening_docstring(git show PIN:<old>)) is a substring of
       normalize(<new file>). Not part of the standing guard: later stages
       (E2-E6) may correct a derivation legitimately; [V4] proves only that
       the move itself lost nothing.
  [V5] every MOVED old source that still exists (class B/C: the JS smoke stays
       until E3) has the sentence 'Derivation moved to <new source>' in its
       opening docstring.

normalize() strips comment markers at line start/end and drops ONLY the
whitespace-separated tokens that are repo paths with a code/doc extension,
optionally wrapped in inline-code backticks (they change legitimately with a
move: client3d/scripts/smoke_x.mjs -> scripts/smoke_x.mjs, and Task 8 turned
the backticked client3d/src/game/prefs.ts into hud/src/game/prefs.ts). Divisions and units ('(10 + 11) / 2', 'm/s',
'x=side/100*cos(yaw)') stay part of the comparison. Built-in self-test, run
before every check: normalize("a/b m/s client3d/src/game/prefs.ts,") == "a/b m/s".

Expected numbers, derived by hand
---------------------------------
There are 81 vector files. At PIN (011cd048aa3c) 70 of them have a 'source'
under client3d/scripts/, and clip_shift.json carries a formula text instead of
a path. Task 8 already moved graphics_prefs (client3d/scripts/ ->
scripts/smoke_graphics_prefs.mjs), so its MOVED entry is in the table from the
start.

  Before Task 9:  [V2] 70 - 1 (graphics_prefs, Task 8) = 69
                  [V1]  1 (clip_shift: a formula, not a file)
                  -> 70 violations.
  After Task 9:   class A moves 6 vectors (ground_polygons, hillshade,
                  role_turn, scene_place, scene_primitives, scene_verify),
                  class C 2 (group_role_points, prop_water), and clip_shift
                  gets native/tests/Derivations/clip_shift.md:
                  [V2] 69 - 6 - 2 = 61, [V1] 0 -> 61 violations, all of them
                  class B. Tasks 10-12 move those 61 derivations to
                  native/tests/Derivations/ (Task 10: 22, leaving 39;
                  Task 11: 20, leaving 19; Task 12: the last 19, leaving 0).
  After Task 12:  0 violations - the guard passes.

The guard is therefore deliberately RED between Task 9 and Task 12.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

PIN = "011cd048aa3cc2937186d7f35d2203af9491db8a"

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VECTOR_DIR = os.path.join(ROOT, "shared", "test-vectors")

# Vector name -> (old source at PIN, new source). Grows with Tasks 9-12.
MOVED: dict[str, tuple[str, str]] = {
    # Task 8: HUD-only smoke moved to scripts/.
    "graphics_prefs": ("client3d/scripts/smoke_graphics_prefs.mjs", "scripts/smoke_graphics_prefs.mjs"),
    # Task 9, class A: package-code smokes moved to scripts/.
    "ground_polygons": ("client3d/scripts/smoke_ground_math.mjs", "scripts/smoke_ground_math.mjs"),
    "hillshade": ("client3d/scripts/smoke_hillshade.mjs", "scripts/smoke_hillshade.mjs"),
    "role_turn": ("client3d/scripts/smoke_role_turn_vectors.mjs", "scripts/smoke_role_turn_vectors.mjs"),
    "scene_place": ("client3d/scripts/smoke_place_rotation.mjs", "scripts/smoke_place_rotation.mjs"),
    "scene_primitives": ("client3d/scripts/smoke_scene_primitives.mjs", "scripts/smoke_scene_primitives.mjs"),
    "scene_verify": ("client3d/scripts/smoke_scene_verify.mjs", "scripts/smoke_scene_verify.mjs"),
    # Task 9, class C: a Python smoke already replays the vector.
    "group_role_points": ("client3d/scripts/smoke_group_role_points.mjs", "scripts/smoke_group_role_points.py"),
    "prop_water": ("client3d/scripts/smoke_prop_water.mjs", "scripts/smoke_prop_water.py"),
    # Task 10, class B: figures, bridges, pairs, clips -> native/tests/Derivations/.
    "bridge_heading": ("client3d/scripts/smoke_bridge_heading.mjs", "native/tests/Derivations/bridge_heading.md"),
    "bridge_lift": ("client3d/scripts/smoke_bridge_lift.mjs", "native/tests/Derivations/bridge_lift.md"),
    "bridge_travel": ("client3d/scripts/smoke_bridge_root.mjs", "native/tests/Derivations/bridge_root.md"),
    "foot_lock": ("client3d/scripts/smoke_foot_lock_math.mjs", "native/tests/Derivations/foot_lock_math.md"),
    "foot_lock_measure": ("client3d/scripts/smoke_foot_lock_measure.mjs", "native/tests/Derivations/foot_lock_measure.md"),
    "leg_pin": ("client3d/scripts/smoke_leg_pin.mjs", "native/tests/Derivations/leg_pin.md"),
    "stand_settle": ("client3d/scripts/smoke_stand_settle.mjs", "native/tests/Derivations/stand_settle.md"),
    "hips_tracks": ("client3d/scripts/smoke_rig_stand_ref.mjs", "native/tests/Derivations/rig_stand_ref.md"),
    "clip_commit": ("client3d/scripts/smoke_clip_order.mjs", "native/tests/Derivations/clip_order.md"),
    "clip_coverage": ("client3d/scripts/smoke_clip_coverage.mjs", "native/tests/Derivations/clip_coverage.md"),
    "figure_clips": ("client3d/scripts/smoke_figure_clips.mjs", "native/tests/Derivations/figure_clips.md"),
    "figure_normalisation": ("client3d/scripts/smoke_figure_normalisation.mjs", "native/tests/Derivations/figure_normalisation.md"),
    "pair_blend": ("client3d/scripts/smoke_pair_blend.mjs", "native/tests/Derivations/pair_blend.md"),
    "pair_clip_geometry": ("client3d/scripts/smoke_clip_pair.mjs", "native/tests/Derivations/clip_pair.md"),
    "pair_clip_phase": ("client3d/scripts/smoke_pair_realtime.mjs", "native/tests/Derivations/pair_realtime.md"),
    "pair_height": ("client3d/scripts/smoke_pair_storey.mjs", "native/tests/Derivations/pair_storey.md"),
    "secondary_angle": ("client3d/scripts/smoke_secondary_motion.mjs", "native/tests/Derivations/secondary_motion.md"),
    "secondary_chain": ("client3d/scripts/smoke_secondary_motion.mjs", "native/tests/Derivations/secondary_motion.md"),
    "secondary_params": ("client3d/scripts/smoke_secondary_motion.mjs", "native/tests/Derivations/secondary_motion.md"),
    "secondary_particle": ("client3d/scripts/smoke_secondary_motion.mjs", "native/tests/Derivations/secondary_motion.md"),
    "animal_gait": ("client3d/scripts/smoke_animal_vectors.mjs", "native/tests/Derivations/animal_vectors.md"),
    "animal_legs": ("client3d/scripts/smoke_animal_vectors.mjs", "native/tests/Derivations/animal_vectors.md"),
    # Task 11, class B: walking, embody, travel, placement, overview -> native/tests/Derivations/.
    "collide": ("client3d/scripts/smoke_walk_math.mjs", "native/tests/Derivations/walk_math.md"),
    "figure_ground": ("client3d/scripts/smoke_walk_math.mjs", "native/tests/Derivations/walk_math.md"),
    "npc_ground": ("client3d/scripts/smoke_walk_math.mjs", "native/tests/Derivations/walk_math.md"),
    "overview_hud": ("client3d/scripts/smoke_walk_math.mjs", "native/tests/Derivations/walk_math.md"),
    "stairs": ("client3d/scripts/smoke_walk_math.mjs", "native/tests/Derivations/walk_math.md"),
    "walk_control": ("client3d/scripts/smoke_walk_math.mjs", "native/tests/Derivations/walk_math.md"),
    "embody": ("client3d/scripts/smoke_embody_vectors.mjs", "native/tests/Derivations/embody_vectors.md"),
    "enter": ("client3d/scripts/smoke_enter_math.mjs", "native/tests/Derivations/enter_math.md"),
    "npc_placement": ("client3d/scripts/smoke_npc_placement.mjs", "native/tests/Derivations/npc_placement.md"),
    "npc_walk": ("client3d/scripts/smoke_npc_walk.mjs", "native/tests/Derivations/npc_walk.md"),
    "place_poll": ("client3d/scripts/smoke_places_client.mjs", "native/tests/Derivations/places_client.md"),
    "room_spots": ("client3d/scripts/smoke_room_spots.mjs", "native/tests/Derivations/room_spots.md"),
    "travel": ("client3d/scripts/smoke_travel_math.mjs", "native/tests/Derivations/travel_math.md"),
    "prop_action_motion": ("client3d/scripts/smoke_prop_action_motion.mjs", "native/tests/Derivations/prop_action_motion.md"),
    "door_swing": ("client3d/scripts/smoke_door_swing.mjs", "native/tests/Derivations/door_swing.md"),
    "event_pins": ("client3d/scripts/smoke_event_pins.mjs", "native/tests/Derivations/event_pins.md"),
    "overview_labels": ("client3d/scripts/smoke_overview_labels.mjs", "native/tests/Derivations/overview_labels.md"),
    "camera": ("client3d/scripts/smoke_camera_math.mjs", "native/tests/Derivations/camera_math.md"),
    "view_shift": ("client3d/scripts/smoke_view_shift.mjs", "native/tests/Derivations/view_shift.md"),
    "bench_math": ("client3d/scripts/smoke_bench_math.mjs", "native/tests/Derivations/bench_math.md"),
    # Task 12, class B: terrain, scene, light, audio -> native/tests/Derivations/.
    "ambience": ("client3d/scripts/smoke_ambience.mjs", "native/tests/Derivations/ambience.md"),
    "audio": ("client3d/scripts/smoke_audio_math.mjs", "native/tests/Derivations/audio_math.md"),
    "backdrop": ("client3d/scripts/smoke_backdrop_math.mjs", "native/tests/Derivations/backdrop_math.md"),
    "fog_veil": ("client3d/scripts/smoke_fog_veil.mjs", "native/tests/Derivations/fog_veil.md"),
    "height_tiles": ("client3d/scripts/smoke_height_tiles.mjs", "native/tests/Derivations/height_tiles.md"),
    "impostors": ("client3d/scripts/smoke_impostors.mjs", "native/tests/Derivations/impostors.md"),
    "layer_ground": ("client3d/scripts/smoke_layer_cut.mjs", "native/tests/Derivations/layer_cut.md"),
    "light_pool": ("client3d/scripts/smoke_light_pool.mjs", "native/tests/Derivations/light_pool.md"),
    "occlusion": ("client3d/scripts/smoke_occlusion.mjs", "native/tests/Derivations/occlusion.md"),
    "scatter": ("client3d/scripts/smoke_scatter_math.mjs", "native/tests/Derivations/scatter_math.md"),
    "scatter_rows": ("client3d/scripts/smoke_scatter_math.mjs", "native/tests/Derivations/scatter_math.md"),
    "scene_models": ("client3d/scripts/smoke_scene_models.mjs", "native/tests/Derivations/scene_models.md"),
    "scene_view": ("client3d/scripts/smoke_scene_view.mjs", "native/tests/Derivations/scene_view.md"),
    "sky_light": ("client3d/scripts/smoke_shadow_snap.mjs", "native/tests/Derivations/shadow_snap.md"),
    "terrain_lod": ("client3d/scripts/smoke_terrain_lod.mjs", "native/tests/Derivations/terrain_lod.md"),
    "undergrowth": ("client3d/scripts/smoke_undergrowth.mjs", "native/tests/Derivations/undergrowth.md"),
    "water": ("client3d/scripts/smoke_water_shade.mjs", "native/tests/Derivations/water_shade.md"),
    "world_props": ("client3d/scripts/smoke_world_props.mjs", "native/tests/Derivations/world_props.md"),
    "residency": ("client3d/scripts/smoke_residency_gen.mjs", "native/tests/Derivations/residency_gen.md"),
    # clip_shift has no entry: at PIN its source was a formula, not a file; the
    # formula is native/tests/Derivations/clip_shift.md word for word.
}

# A repo path token; an inline-code backtick on either side belongs to the token
# ('`client3d/src/game/prefs.ts`' -> '`hud/src/game/prefs.ts`' is a legitimate move).
_PATH_TOKEN = re.compile(r"^`?[\w.@-]+(/[\w.@-]+)+\.(ts|tsx|mjs|js|py|json|cs|md)`?[,.;:)]*$")
_LEAD_MARKER = re.compile(r'^(/\*\*|/\*|\*/|\*|///|//|"""|#)')
_TRAIL_MARKER = re.compile(r'(\*/|""")$')


def opening_docstring(text: str) -> str:
    """The opening comment block of a source file, verbatim.

    Skips a shebang line; takes the first '/** ... */' or '/* ... */' block at
    the start of the file, otherwise the leading run of '//' lines; for Python
    the module docstring literal (including its quotes)."""
    lines = text.split("\n")
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    body = "\n".join(lines).lstrip()
    if body.startswith("/*"):
        end = body.find("*/")
        return body if end < 0 else body[: end + 2]
    m = re.match(r'(?:[rRuU]?)("""|\'\'\')', body)
    if m:
        quote = m.group(1)
        end = body.find(quote, m.end())
        return body if end < 0 else body[: end + 3]
    run = []
    for line in body.split("\n"):
        if line.lstrip().startswith("//"):
            run.append(line)
        else:
            break
    return "\n".join(run)


def normalize(text: str) -> str:
    """Comment markers off, repo-path tokens out, whitespace collapsed."""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        line = _LEAD_MARKER.sub("", line, count=1)
        line = _TRAIL_MARKER.sub("", line.rstrip(), count=1)
        out.extend(tok for tok in line.split() if not _PATH_TOKEN.match(tok))
    return " ".join(out).strip()


def _self_test() -> None:
    got = normalize("a/b m/s client3d/src/game/prefs.ts,")
    if got != "a/b m/s":
        sys.exit(f"normalize self-test FAILED: {got!r} != 'a/b m/s'")


def _git_show(path: str) -> str:
    return subprocess.run(["git", "show", f"{PIN}:{path}"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _names_vector(text: str, name: str) -> bool:
    n = re.escape(name)
    return bool(re.search(r"(?<![\w])" + n + r"\.json", text)
                or re.search(r"loadVectors\((['\"])" + n + r"\1\)", text))


def check_sources() -> list[str]:
    """[V1]-[V3] and [V5]; one line per violation."""
    bad = []
    files = sorted(f for f in os.listdir(VECTOR_DIR) if f.endswith(".json"))
    for fname in files:
        name = fname[:-5]
        with open(os.path.join(VECTOR_DIR, fname), encoding="utf-8") as fh:
            data = json.load(fh)
        src = data.get("source") if isinstance(data, dict) else None
        if not isinstance(src, str) or not os.path.isfile(os.path.join(ROOT, src)):
            bad.append(f"[V1] {name}: source {src!r} is not a repo file")
            continue
        if src.startswith("client3d/"):
            bad.append(f"[V2] {name}: source {src} lies under client3d/")
            continue
        if not _names_vector(_read(src), name):
            bad.append(f"[V3] {name}: {src} names neither {name}.json nor loadVectors('{name}')")
    for name, (old, new) in sorted(MOVED.items()):
        if os.path.isfile(os.path.join(ROOT, old)):
            if f"Derivation moved to {new}" not in opening_docstring(_read(old)):
                bad.append(f"[V5] {name}: {old} still exists without 'Derivation moved to {new}'")
    return bad


def verify_move() -> list[str]:
    """[V4]: the derivation at PIN survives, normalized, in the new file."""
    bad = []
    for name, (old, new) in sorted(MOVED.items()):
        before = normalize(opening_docstring(_git_show(old)))
        after = normalize(_read(new))
        if not before or before not in after:
            bad.append(f"[V4] {name}: docstring of {old} @ PIN is not contained in {new}")
    return bad


def main(argv: list[str]) -> int:
    _self_test()
    if len(argv) == 2 and argv[0] == "--extract":
        sys.stdout.write(opening_docstring(_git_show(argv[1])))
        sys.stdout.write("\n")
        return 0
    if argv == ["--verify-move"]:
        bad = verify_move()
        for line in bad:
            print(line)
        print(f"verify-move: {len(MOVED)} MOVED entries checked, {len(bad)} deviations")
        return 1 if bad else 0
    if argv:
        print(__doc__)
        return 2
    bad = check_sources()
    for line in bad:
        print(line)
    print(f"vector sources: {len(bad)} violations")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
