#!/usr/bin/env python3
"""Opening a worn piece re-keys the Wardrobe's outfit preview (bug 2026-11-12 "open-not-stale"; plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Addendum A, rulings A1 / A7).

The bug: Glut's Schuppen-BH was switched to open in the Wardrobe (POST …/outfit-options/piece-state) and the
Wardrobe's pose preview ("Outfit image", ``FieldModelRefs kinds=['pose']``) kept showing the closed render with
the badge "current". The server side was right — an open piece is part of the outfit signature
(``_equipped_signature`` appends ``open:<ids>``), so the info for the open outfit has no pose render and the
debounced render is armed. The preview never asked: its ``refreshKey`` was ``JSON.stringify(data.equipped)``,
and a piece-state toggle changes no equipped slot, so the tile kept the info it had loaded before the toggle
(the closed file + its "current" badge). Same for the PromptPreview under it (still without "worn open").
Fix: both keys are ``outfitKey = JSON.stringify([data.equipped, garments?.piece_state || {}])`` —
``garments.piece_state`` is the Wardrobe payload's EFFECTIVE open map (``outfit_options.piece_states``).

Usage:
    ./.venv/bin/python scripts/smoke_wardrobe_open_preview.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before any world-DB import) — no real
world, no hub, no GPU, no server. Stubs: ``model_refs.schedule_outfit_render`` records its calls (no timer),
``sync_topics.changed_at`` no-op. The route function ``set_character_piece_state`` is called directly (the HTTP
gate is covered by smoke_auth_gate B).

Fixture (real ``add_item``, ids written as names): jacket ``{slots: [outer], covers: [top]}`` "black jacket"
(closable by kind default: outer); blouse ``{slots: [top]}`` "white blouse" (not closable). Character "Demo"
holds both and wears ``{outer: jacket, top: blouse}``. A stored pose render for the CLOSED outfit is written by
hand: ``model_refs/pose_<C>.png`` (fixed bytes) + sidecar, C = md5("outer=jacket")[:12] (the blouse is covered
by the closed jacket, so the visible pieces are the jacket alone — ``_equipped_signature``). No image modifiers
are active, so the pose reference signature is C itself (``pose_reference_signature`` adds ``-p`` only with a
state fingerprint). UI key K(state) = json [equipped, piece_state] as the Wardrobe builds it.

Expected, derived by hand from rulings A1 (closed = old key byte-identical, only open adds) and A7 (closed
text says nothing):

[0] Fails on the old code: ``git show 20ebbd27:frontend/src/tabs/characters/WardrobeTab.tsx`` passes
    ``refreshKey={JSON.stringify(data.equipped)}`` to FieldModelRefs and PromptPreview and never reads
    ``piece_state`` for them, so check [5] fails there.
[1] Closed (start). get_model_refs_info: signature C; pose.filename "pose_<C>.png", annotated freshness
    current; find_ref_image(Demo, "pose") is that file. Wardrobe piece_state {}. Pose text "black jacket".
[2] Open (route, jacket open). Response piece_state {jacket: open}; schedule_outfit_render called once for Demo
    (the render of the new outfit is DUE). Signature O = md5("outer=jacket|top=blouse|open:jacket")[:12] != C
    (the open jacket hides nothing, so the blouse counts; open:<id> last). get_model_refs_info pose None and
    find_ref_image None (no render for O — the tile says "No render yet" instead of the closed picture).
    Wardrobe piece_state {jacket: open} -> K differs from [1]'s K (the preview reloads). Pose text "white blouse
    underneath black jacket, worn open".
[3] Closed again (route). schedule called again (the timer's render then finds C stored and skips). Signature
    C; pose.filename "pose_<C>.png", freshness current, bytes == the [1] bytes and mtime unchanged (the stored
    closed image, no re-render). Wardrobe piece_state {} -> K == [1]'s K. Text "black jacket".
[4] Open, then "Can be worn open" OFF (update_item jacket closable False). The stored map still names the
    jacket (an item edit writes no profile) but piece_states drops it: Wardrobe piece_state {} -> K == [1]'s K;
    signature C; pose "pose_<C>.png" current, same bytes; text "black jacket" (closed again).
[5] UI source (WardrobeTab.tsx, this tree): an ``outfitKey`` built from ``data.equipped`` and
    ``garments?.piece_state``; FieldModelRefs kinds={['pose']} and PromptPreview both take
    ``refreshKey={outfitKey}``; no ``refreshKey={JSON.stringify(data.equipped)}`` is left.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "20ebbd27"
WARDROBE = "frontend/src/tabs/characters/WardrobeTab.tsx"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def md5_12(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def ui_source_ok(src: str) -> bool:
    """[5]: the preview keys follow the open pieces."""
    key = re.search(r"const outfitKey = JSON\.stringify\(\[data\.equipped, garments\?\.piece_state \|\| \{\}\]\)",
                    src)
    refs = re.search(r"<FieldModelRefs character=\{character\} kinds=\{\['pose'\]\}\s+refreshKey=\{outfitKey\}", src)
    prompt = re.search(r"<PromptPreview character=\{character\}\s+refreshKey=\{outfitKey\}", src)
    return bool(key and refs and prompt) and "refreshKey={JSON.stringify(data.equipped)}" not in src


def main() -> int:
    print("[0] fails on the old code")
    old = subprocess.run(["git", "show", f"{BASE}:{WARDROBE}"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    check(f"old preview key ignores piece_state at {BASE}", ui_source_ok(old), False)
    check(f"old key is the equipped state at {BASE}", old.count("refreshKey={JSON.stringify(data.equipped)}"), 2)

    with tempfile.TemporaryDirectory(prefix="wardrobe-open-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()

        from app.core import garment_set, model_refs, sync_topics
        from app.core.model_overview import annotate_model_refs_info
        from app.core.outfit_renderer import render_outfit
        from app.models import inventory
        from app.models.character import get_character_profile, save_character_profile
        scheduled = []
        model_refs.schedule_outfit_render = lambda name, *a, **k: scheduled.append(name)
        sync_topics.changed_at = lambda *a, **k: None
        from app.routes.characters import PieceStateRequest, set_character_piece_state

        def piece(name, slots, frag, **op):
            return inventory.add_item(name, category="outfit_piece", prompt_fragment=frag,
                                      outfit_piece={"slots": slots, **op})["id"]
        jacket = piece("Jacket", ["outer"], "black jacket", covers=["top"])
        blouse = piece("Blouse", ["top"], "white blouse")
        check("create Demo", save_character_profile("Demo", {"template": "human-roleplay", "gender": "female"},
                                                     create_new=True), True)
        for iid in (jacket, blouse):
            inventory.add_to_inventory("Demo", iid)
        prof = get_character_profile("Demo")
        prof["equipped_pieces"] = {"outer": jacket, "top": blouse}
        check("wear jacket + blouse", save_character_profile("Demo", prof), True)
        equipped = {"outer": jacket, "top": blouse}

        closed_sig = md5_12(f"outer={jacket}")
        open_sig = md5_12(f"outer={jacket}|top={blouse}|open:{jacket}")
        refs = model_refs.get_model_refs_dir("Demo")
        refs.mkdir(parents=True, exist_ok=True)
        stored_png = refs / f"pose_{closed_sig}.png"
        stored_bytes = b"\x89PNG\r\n\x1a\n" + b"closed-render" * 8
        stored_png.write_bytes(stored_bytes)
        (refs / f"pose_{closed_sig}.json").write_text(json.dumps({
            "created_at": "2026-11-12T20:00:00+00:00", "equipped_pieces": equipped, "equipped_items": []}))
        stored_mtime = stored_png.stat().st_mtime_ns

        def ui_key():
            ward = garment_set.wardrobe("Demo")
            return json.dumps([equipped, ward.get("piece_state") or {}]), ward.get("piece_state")

        def pose_view():
            info = annotate_model_refs_info("Demo", model_refs.get_model_refs_info("Demo"))
            pose = info.get("pose")
            return info.get("signature"), pose and pose.get("filename"), pose and (pose.get("freshness") or {}).get(
                "state")

        def pose_text():
            return render_outfit(character_name="Demo")["pieces"]

        def closed_view(tag):
            sig, fname, state = pose_view()
            check(f"{tag}: signature C", sig, closed_sig)
            check(f"{tag}: pose file = stored closed render", fname, f"pose_{closed_sig}.png")
            check(f"{tag}: pose freshness", state, "current")
            check(f"{tag}: served pose file", model_refs.find_ref_image("Demo", "pose"), stored_png)
            check(f"{tag}: same bytes", stored_png.read_bytes() == stored_bytes, True)
            check(f"{tag}: not re-written", stored_png.stat().st_mtime_ns, stored_mtime)
            check(f"{tag}: pose text closed", pose_text(), "black jacket")

        print("[1] closed")
        closed_view("[1]")
        key_closed, state = ui_key()
        check("[1] wardrobe piece_state", state, {})

        print("[2] open")
        res = set_character_piece_state("Demo", PieceStateRequest(item_id=jacket, state="open"))
        check("[2] route piece_state", res.get("piece_state"), {jacket: "open"})
        check("[2] render due (scheduled)", scheduled, ["Demo"])
        sig, fname, _ = pose_view()
        check("[2] signature O", sig, open_sig)
        check("[2] O != C", open_sig != closed_sig, True)
        check("[2] no pose render for the open outfit", fname, None)
        check("[2] served pose file", model_refs.find_ref_image("Demo", "pose"), None)
        key_open, state = ui_key()
        check("[2] wardrobe piece_state", state, {jacket: "open"})
        check("[2] preview key changes", key_open != key_closed, True)
        check("[2] pose text open", pose_text(), "white blouse underneath black jacket, worn open")

        print("[3] closed again")
        set_character_piece_state("Demo", PieceStateRequest(item_id=jacket, state="closed"))
        check("[3] scheduled again", scheduled, ["Demo", "Demo"])
        closed_view("[3]")
        key, state = ui_key()
        check("[3] wardrobe piece_state", state, {})
        check("[3] preview key = closed key", key, key_closed)

        print("[4] open, then closable off")
        set_character_piece_state("Demo", PieceStateRequest(item_id=jacket, state="open"))
        check("[4] open signature first", pose_view()[0], open_sig)
        inventory.update_item(jacket, {"outfit_piece": {"slots": ["outer"], "covers": ["top"], "closable": False}})
        stored_map = (get_character_profile("Demo").get("equipped_options") or {}).get("piece_state")
        check("[4] stored map untouched by the item edit", stored_map, {jacket: "open"})
        key, state = ui_key()
        check("[4] wardrobe piece_state (effective)", state, {})
        check("[4] preview key = closed key", key, key_closed)
        closed_view("[4]")

    print("[5] UI source")
    check("WardrobeTab preview keys follow piece_state", ui_source_ok((ROOT / WARDROBE).read_text()), True)

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
