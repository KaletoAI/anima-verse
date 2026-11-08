#!/usr/bin/env python3
"""Humanoid mesh-input renders ask for an A-pose, not a T-pose.

User decision 2026-11-08 (base-body programme, Task 1): the reference render
that feeds image-to-3D shows the humanoid in an A-pose — arms straight and
angled about 45 degrees down and away from the body. The rig chain binds an
A-pose mesh into the T-pose rig unchanged, so only texts move. Internal
`tpose*` identifiers (use cases, config keys, file kinds) stay as they are.

Expected values, derived by hand from that decision (no snapshot of output):

[1] Front pose text `get_tpose_prompt()` (no admin override in a fresh
    storage): contains "A-pose" and "45 degrees"; contains none of the
    T-pose words "T-pose", "letter T", "shoulder height".
[2] Extra views `get_tpose_view_prompt("back"|"left"|"right")`: contain
    "A-pose"; none of "T-pose", "shoulder height", "points at the camera"
    (the old profile asked the near arm to point AT the camera — in an
    A-pose it angles down and away instead).
[3] Shipped negatives of the use cases `tpose`, `tpose_back`, `tpose_side`
    in BOTH style families ("keywords" and "natural", resolved through
    `config.get_use_case_prompts` with no override): contain none of
    "A-pose", "arms lowered", "arms angled downward", "arms at sides" — a
    negative that forbids the pose the positive asks for cancels it. They DO
    contain "T-pose" and "arms raised to shoulder height" (the old pose moves
    into the negative so it cannot return).
[4] `shared/templates/character/base-character.json`: tab `tpose_tab` has
    label "Pose" / label_de "Pose"; section `model_refs` has label
    "Pose (image-to-3D input)".
[5] Animals are untouched: `ANIMAL_POSE_PROMPT_DEFAULT` names no A-pose.

Usage: ./.venv/bin/python scripts/smoke_apose_prompts.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

failures = []


def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        if detail:
            print("     ", detail[:200])
        failures.append(label)


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix="smoke-apose-") as tmp:
        paths.init(tmp)
        from app.core import config, model_refs as mr

        # [1] front
        front = mr.get_tpose_prompt()
        check("[1] front names the A-pose", "A-pose" in front, front)
        check("[1] front names 45 degrees", "45 degrees" in front, front)
        for word in ("T-pose", "letter T", "shoulder height"):
            check(f"[1] front has no {word!r}", word not in front, front)

        # [2] extra views
        for view in ("back", "left", "right"):
            text = mr.get_tpose_view_prompt(view)
            check(f"[2] {view} names the A-pose", "A-pose" in text, text)
            for word in ("T-pose", "shoulder height", "points at the camera"):
                check(f"[2] {view} has no {word!r}", word not in text, text)

        # [3] negatives, both families
        for uc in ("tpose", "tpose_back", "tpose_side"):
            for model in ("keywords", "natural"):
                neg = config.get_use_case_prompts(uc, image_model=model)["prompt_negative"]
                check(f"[3] {uc}/{model} negative is non-empty", bool(neg))
                for word in ("A-pose", "arms lowered", "arms angled downward", "arms at sides"):
                    check(f"[3] {uc}/{model} negative has no {word!r}", word not in neg, neg)
                for word in ("T-pose", "arms raised to shoulder height"):
                    check(f"[3] {uc}/{model} negative has {word!r}", word in neg, neg)

        # [4] template labels
        tpl = json.loads((ROOT / "shared/templates/character/base-character.json").read_text())
        blocks = {}
        for key in ("tabs", "sections"):
            for b in tpl.get(key, []) or []:
                if isinstance(b, dict) and b.get("id"):
                    blocks[b["id"]] = b
        tab = blocks.get("tpose_tab", {})
        check("[4] tpose_tab label == 'Pose'", tab.get("label") == "Pose", repr(tab))
        check("[4] tpose_tab label_de == 'Pose'", tab.get("label_de") == "Pose", repr(tab))
        sec = blocks.get("model_refs", {})
        check("[4] model_refs label == 'Pose (image-to-3D input)'",
              sec.get("label") == "Pose (image-to-3D input)", repr(sec))

        # [5] animals untouched
        check("[5] animal pose names no A-pose", "A-pose" not in mr.ANIMAL_POSE_PROMPT_DEFAULT)

    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
