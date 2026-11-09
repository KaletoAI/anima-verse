#!/usr/bin/env python3
"""Base body: the hand-pose gate of the front render (app/core/base_body_gates.py,
base_body.generate_base_images).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_hand_gate.py

Runs against a THROWAWAY world + instance with a copy of the repo's ``human``
package — no real world, no image backend, no GPU, no server. Synthetic
masks only; the expected numbers are derived by hand below.

Synthetic figure ``fig(hand, arm=21)`` on a 640x640 alpha canvas: a torso
column x 250..349, rows 10..610 (body height H = 600 px = WORK_HEIGHT, so
no resampling); per side a horizontal arm of ``arm`` rows centred on row
300 (left x 100..249, right x 350..499) ending in a hand block of ``hand``
rows, 60 px long (left x 40..99, right x 500..559). The hand tip is the
outermost column (x 40 / 559), its row the mean of that column = 300, the
same centre as the arm, so the arm axis is horizontal and a 0.01·H slice is
6 columns. Width of a slice = pixels / 6 px / H:

[1] gate on masks (values rounded to 4 places, ±0.0002 allowed):
    hand 23, arm 21: hand 23/600 = 0.0383, wrist 21/600 = 0.0350 (the first
        arm slice, at 60/600 = 0.10), ratio 23/21 = 1.095; score 0.0383 <=
        HAND_LIMIT 0.050 -> ok (palms toward the thighs: edge-on, narrow).
    hand 39, arm 21: hand 39/600 = 0.0650, ratio 39/21 = 1.857; score
        0.0650 > 0.050 -> not ok (palm to the camera: flat, wide).
    hand 45 left, 23 right: score = the wider hand 45/600 = 0.0750 -> not ok.
    The 39-figure scaled x2 (H = 1201 px, resampled to 600): the same
        fractions within ±0.002 (scale-free).
    Opaque canvas (alpha 255 everywhere) -> ok True, score None, reason "no
    cut-out (opaque image)"; an RGB file -> reason "no alpha channel"; an empty
    alpha -> "no figure".
[2] best_attempt: [fail .065, pass .038] -> (1, True); [.065, .075, .055]
    -> (2, False) (lowest score); [unmeasurable] -> (0, True).
[3] generate_base_images("Demo") with render_character_image stubbed (front
    calls draw the next hand width of a queue into a 640x640 synthetic
    figure plus a sidecar {"base_signature", "seed": n}; view calls write an
    8x8 PNG):
    a) queue [39, 23]: 2 front calls, each into its own
       model_refs/.handgate_*/attemptN/ stem; the stored front is attempt 2
       (sidecar seed 2) with hand_gate {ok True, chosen 2, limit 0.05,
       attempts [ok False, ok True]}; the 3 views edit it (reference named
       tpose_<bsig>.png); status front: failed False, warning None; no
       staging dir left in model_refs.
    b) force, queue [39, 45, 33]: 3 front calls; none passes; the stored
       front is attempt 3 (33/600 = 0.055, the lowest) with hand_gate.ok
       False, chosen 3; status front: failed False, error None, warning
       "Palms may face the camera (hand check failed after 3 attempts)";
       back/left/right are still rendered (3 view calls).
    c) force, queue [23]: 1 front call, warning cleared.
    d) force, queue [39, None]: attempt 2 renders nothing -> attempt 1 is
       kept (seed 1), warning "... after 1 attempt)", views rendered.
    e) force, queue [raise]: the first attempt raises -> front failed with
       that error, no view call, nothing published over the old front.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r} ±{tol}"))
    if not ok:
        FAILS.append(label)


def fig(hand_left: int, hand_right: int = None, arm: int = 21) -> np.ndarray:
    hand_right = hand_left if hand_right is None else hand_right
    a = np.zeros((640, 640), np.uint8)
    a[10:611, 250:350] = 255
    cy = 300
    a[cy - arm // 2:cy + arm // 2 + 1, 100:250] = 255
    a[cy - arm // 2:cy + arm // 2 + 1, 350:500] = 255
    a[cy - hand_left // 2:cy + hand_left // 2 + 1, 40:100] = 255
    a[cy - hand_right // 2:cy + hand_right // 2 + 1, 500:560] = 255
    return a


def save_rgba(alpha: np.ndarray, path: Path) -> None:
    from PIL import Image
    rgba = np.zeros(alpha.shape + (4,), np.uint8)
    rgba[..., :3] = 180
    rgba[..., 3] = alpha
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(path)


def tiny_png(path: Path) -> None:
    from PIL import Image
    im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    im.putpixel((4, 4), (200, 100, 50, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


QUEUE = []
CALLS = []


def stub(character_name, *, output_stem, **kw):
    from app.core import base_body
    CALLS.append({"stem": output_stem, "occasion": kw.get("occasion"), "ref": kw.get("reference_image")})
    path = output_stem.with_suffix(".png")
    if kw.get("occasion") != "base_front":
        tiny_png(path)
        return path
    item = QUEUE.pop(0)
    if item == "raise":
        raise RuntimeError("backend down")
    if item is None:
        return None
    save_rgba(fig(item), path)
    seed = sum(1 for c in CALLS if c["occasion"] == "base_front")
    path.with_suffix(".json").write_text(json.dumps({"base_signature": base_body.base_signature(character_name),
                                                     "seed": seed}))
    return path


def gate_section() -> None:
    from PIL import Image
    from app.core import base_body_gates as g
    print("[1] gate on synthetic masks")
    r = g.hand_pose_gate_mask(fig(23))
    check("narrow ok", r["ok"], True)
    near("narrow score", r["score"], 23 / 600, 2e-4)
    for side in ("left", "right"):
        near(f"narrow {side} hand", r[side]["hand"], 23 / 600, 2e-4)
        near(f"narrow {side} wrist", r[side]["wrist"], 21 / 600, 2e-4)
        near(f"narrow {side} wrist_at", r[side]["wrist_at"], 0.10, 1e-9)
        near(f"narrow {side} ratio", r[side]["ratio"], 23 / 21, 2e-3)
    r = g.hand_pose_gate_mask(fig(39))
    check("wide not ok", r["ok"], False)
    near("wide score", r["score"], 39 / 600, 2e-4)
    near("wide ratio", r["left"]["ratio"], 39 / 21, 2e-3)
    check("limit", r["limit"], 0.050)
    r = g.hand_pose_gate_mask(fig(45, 23))
    check("mixed not ok", r["ok"], False)
    near("mixed score = wider hand", r["score"], 45 / 600, 2e-4)
    near("mixed right hand", r["right"]["hand"], 23 / 600, 2e-4)
    big = np.kron(fig(39), np.ones((2, 2), np.uint8))
    r = g.hand_pose_gate_mask(big)
    near("scaled x2 hand", r["left"]["hand"], 39 / 600, 2e-3)
    near("scaled x2 wrist", r["left"]["wrist"], 21 / 600, 2e-3)
    check("scaled x2 not ok", r["ok"], False)
    r = g.hand_pose_gate_mask(np.full((640, 640), 255, np.uint8))
    check("opaque", (r["ok"], r["score"], r.get("reason")), (True, None, "no cut-out (opaque image)"))
    r = g.hand_pose_gate_mask(np.zeros((640, 640), np.uint8))
    check("empty", (r["ok"], r["score"], r.get("reason")), (True, None, "no figure"))
    with tempfile.TemporaryDirectory() as tmp:
        rgb = Path(tmp) / "rgb.png"
        Image.new("RGB", (64, 64), (200, 200, 200)).save(rgb)
        r = g.hand_pose_gate(rgb)
        check("rgb file", (r["ok"], r.get("reason")), (True, "no alpha channel"))
        rgba = Path(tmp) / "f.png"
        save_rgba(fig(39), rgba)
        near("file path", g.hand_pose_gate(rgba)["score"], 39 / 600, 2e-4)

    print("[2] best_attempt")
    fail, ok = {"ok": False, "score": 0.065}, {"ok": True, "score": 0.038}
    check("pass on 2", g.best_attempt([fail, ok]), (1, True))
    check("lowest kept", g.best_attempt([fail, {"ok": False, "score": 0.075}, {"ok": False, "score": 0.055}]),
          (2, False))
    check("unmeasurable passes", g.best_attempt([{"ok": True, "score": None}]), (0, True))


def main() -> int:
    gate_section()
    with tempfile.TemporaryDirectory(prefix="base-body-hand-gate-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, expression_regen
        from app.models.character import (get_character_dir, get_character_images_dir,
                                          get_character_profile, save_character_profile)
        human = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"skin": {"tone": "olive"}, "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        tiny_png(get_character_images_dir("Demo") / "Demo_1.png")
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        check("profile image", save_character_profile("Demo", stored), True)
        refs = get_character_dir("Demo") / "model_refs"
        bsig = base_body.base_signature("Demo")
        front_png, front_json = refs / f"tpose_{bsig}.png", refs / f"tpose_{bsig}.json"

        def run(queue, **kw):
            QUEUE[:] = queue
            CALLS.clear()
            out = base_body.generate_base_images("Demo", **kw)
            fronts = [c for c in CALLS if c["occasion"] == "base_front"]
            views = [c for c in CALLS if c["occasion"] != "base_front"]
            return out, fronts, views

        def sidecar():
            return json.loads(front_json.read_text())

        def staging_left():
            return [p.name for p in refs.iterdir() if p.is_dir()]

        real = expression_regen.render_character_image
        expression_regen.render_character_image = stub
        try:
            print("[3a] fail, then pass")
            out, fronts, views = run([39, 23])
            check("front calls", len(fronts), 2)
            check("attempt stems", [(c["stem"].parent.name, c["stem"].name, c["stem"].parent.parent.parent)
                                    for c in fronts],
                  [("attempt1", f"tpose_{bsig}", refs), ("attempt2", f"tpose_{bsig}", refs)])
            check("staging prefix", {c["stem"].parent.parent.name.startswith(".handgate_") for c in fronts}, {True})
            check("stored front", out.get("front"), str(front_png))
            meta = sidecar()
            check("kept attempt 2", meta.get("seed"), 2)
            check("sidecar keeps base_signature", meta.get("base_signature"), bsig)
            gate = meta.get("hand_gate") or {}
            check("hand_gate", (gate.get("ok"), gate.get("chosen"), gate.get("limit"),
                                [a["ok"] for a in gate.get("attempts", [])]), (True, 2, 0.05, [False, True]))
            near("attempt 1 score", gate["attempts"][0]["score"], 39 / 600, 2e-4)
            check("views edit the chosen front", [c["ref"].name for c in views], [f"tpose_{bsig}.png"] * 3)
            st = base_body.base_status("Demo")["front"]
            check("status clean", (st["failed"], st["error"], st["warning"]), (False, None, None))
            check("no staging left", staging_left(), [])

            print("[3b] never passes: lowest kept + warning")
            out, fronts, views = run([39, 45, 33], force=True)
            check("front calls", len(fronts), 3)
            meta = sidecar()
            check("kept attempt 3", meta.get("seed"), 3)
            gate = meta["hand_gate"]
            check("hand_gate", (gate["ok"], gate["chosen"], len(gate["attempts"])), (False, 3, 3))
            near("kept score", gate["attempts"][2]["score"], 33 / 600, 2e-4)
            st = base_body.base_status("Demo")["front"]
            check("status warning", (st["failed"], st["error"], st["warning"]),
                  (False, None, "Palms may face the camera (hand check failed after 3 attempts)"))
            check("views still rendered", len(views), 3)
            check("result", sorted(k for k, v in out.items() if v), ["back", "front", "left", "right"])
            check("no staging left", staging_left(), [])
            info = base_body.base_info("Demo")
            check("base_info carries the warning", info["status"]["front"]["warning"],
                  base_body.hand_gate_warning(3))

            print("[3c] pass at once clears the warning")
            out, fronts, views = run([23], force=True)
            check("front calls", len(fronts), 1)
            check("warning cleared", base_body.base_status("Demo")["front"]["warning"], None)
            check("kept attempt 1", sidecar()["hand_gate"]["chosen"], 1)

            print("[3d] a later attempt renders nothing")
            out, fronts, views = run([39, None], force=True)
            check("front calls", len(fronts), 2)
            check("kept attempt 1", (sidecar().get("seed"), sidecar()["hand_gate"]["chosen"]), (1, 1))
            check("warning", base_body.base_status("Demo")["front"]["warning"], base_body.hand_gate_warning(1))
            check("warning text", base_body.hand_gate_warning(1),
                  "Palms may face the camera (hand check failed after 1 attempt)")
            check("views rendered", len(views), 3)

            print("[3e] the first attempt raises")
            before = front_png.read_bytes()
            out, fronts, views = run(["raise"], force=True)
            check("result", out, {"front": None})
            st = base_body.base_status("Demo")["front"]
            check("front failed", (st["failed"], st["error"], st["warning"]), (True, "backend down", None))
            check("no view call", len(views), 0)
            check("old front untouched", front_png.read_bytes() == before, True)
            check("no staging left", staging_left(), [])
        finally:
            expression_regen.render_character_image = real

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
