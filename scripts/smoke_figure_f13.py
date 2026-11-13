#!/usr/bin/env python3
"""Fix round T12-F1 of the unified worn pieces (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``; rulings F13 a–f,
F14 g–h of the ledger): the interim hair, the closed mesh standing in for a
missing open one, the estimate, the single garment step, the unreadable
profile, the memoised Figure answer, the square canvas of the dressed views
and their framing check.

Usage:
    ./.venv/bin/python scripts/smoke_figure_f13.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no world, no hub, no GPU, no server. Images, fits
and sidecars are written by hand; renders are stubs that record their
arguments.

Stubs (all sections): ``base_body.is_base_pipeline`` -> True,
``base_signature`` -> BSIG, ``current_base`` -> (BSIG, "basesha"),
``base_model_sha256`` -> "basesha", ``garment_assembly.schedule`` -> False,
``model3d.face_before_rig_planned`` -> True and ``face_retexture.runnable``
-> not ok (counted, [f]) — so ``mesh_hub_stages`` is ["mesh", "rig"],
``base_body.dressed_views`` -> ("front", "back").

Fixture: "Demo" (human, on the pipeline) holds and wears jacket
``{slots: [outer], covers: [top], own_mesh, closable}`` "Black Jacket".

Expected, derived by hand from the rulings:

[a] Hair in the body on a bald plain body (F13 a). ``stored_base_haired`` on a
    front whose sidecar prompt says "…, completely bald, smooth clean-shaven
    head, …" (the OLDER bald wording) -> False; "… long brown hair …" -> True.
    Then (stubbed: haired False, prompts not current, hair item "hairitem"
    worn with an accepted HairDeck fit on "basesha", refresh = views
    front/back/left/right + model, ``base_rebuild_steps`` = 4 views of 1 +
    mesh 1 + rig 1): ``delivered.hair`` == "hairdeck" (never "bald" while the
    fit exists), ``wanted.hair`` == "body"; ``pending_changes`` holds ONE
    hair entry ``{key hair, wanted body, delivered hairdeck, note "in the
    body → plain body rebuild"}`` and NO "body" entry (the hair's rebuild IS
    the plain body's); the plan's plain_body step label "Hair · in the body →
    plain body rebuild (views 4 + mesh + rig)", 6 jobs; ``figure_info``: the
    hair change ``jobs`` 6, hair row ``{state pending, rebuild True, jobs 6,
    note "Shown with its HairDeck hair until the plain body is rebuilt with
    the hair"}``, ``body.plain.state`` "older_prompts". The HairDeck fit
    removed -> delivered "bald", hair row note "Shown bald until …".
[b] The jacket worn open, only its CLOSED fit F_c (F13 b):
    ``accepted_fit`` (worn state) -> F_c, explicit ``state="open"`` -> None;
    delivered ``own`` ∋ jacket, ``shown_closed`` == (jacket,),
    ``notes[jacket]`` "Shown closed until its open mesh is built", not painted,
    no interim; ``pending_changes`` holds exactly ONE entry naming the jacket:
    ``{key "<jacket>:state", wanted open, delivered closed, note "worn open —
    open mesh missing"}``; the plan keeps Step("pieces", "Own mesh · Black
    Jacket (open)", 3) (worn 1 + ghost 1 + mesh 1: the closed chain's backs
    are copied, ruling F15 i-1 — its worn back follows its front);
    ``figure_info``: that change ``jobs`` 3, the worn row state "pending"
    with the SHOWN_CLOSED
    note. Without F_c too: still ONE entry, key and note as above (how the
    piece is shown then is the general interim — ruling A11, a follow-up
    task; not pinned here).
[c] Estimate (F13 c), front + back dressed: ``dressed_view_jobs()`` 2 (1 + 1:
    the back is one draft, its composite is CPU since Task 11g).
    ``dressed_view_estimate`` of a figure with texture TSIG and both views
    missing: no store -> 2; the store's front made from the current base
    front -> 1 (front copied, back draft); + the store's back
    following that front -> 0; the back's draft made from another front -> 1;
    the outfit's front STORED with other content and only the back missing
    -> 1 (a copy follows only the store's front); no texture -> 0. ``cost``
    of steps 3 + 6 -> note "9 hub jobs (estimate, retries extra)".
[d] One step (F13 d): with nothing built, ``run_garment(jacket,
    steps="worn", only=True)`` runs ONLY worn (front, back) — the cut-out is
    never called, ``ran`` == ["worn"]; without ``only`` the same call runs
    worn, ghost and stops at the stubbed cut-out ("stop here — smoke").
    The route: body ``{step: "ghost"}`` -> ``start_garment(only=True)``,
    ``{step: "ghost", chain: true}`` -> only False, ``{}`` -> only False.
    ``start_garment(steps="worn", only=True)`` and ``(steps="worn")`` are two
    different waiting jobs.
[e] Unreadable profile (F13 e): ``get_character_profile(strict=True)``
    raising "db locked" -> ``start`` == ``{status: failed, reason: "The
    character's profile could not be read — nothing was judged or built: db
    locked"}`` and ``state()["failed"]["profile"]["error"]`` that text;
    ``request`` -> False with the same record; ``_run`` -> the same record
    (never "nothing to build").
[f] Memo (F13 f): ``figure_info`` twice -> ``_figure_info`` computed ONCE;
    after ``figure.invalidate()`` -> computed again; after a profile change
    -> again; with the memo emptied, a write (``figure.invalidate``) DURING
    the computation -> not stored (the next call computes: 5 in all).
    ``mesh_hub_stages`` of two signatures -> ["mesh", "rig"], the face
    route probed ONCE (``model3d._face_route_ok``); after
    ``figure.invalidate()`` probed again.
[g] Square canvas (F14 g). ``square_frame((686, 1536))`` == (1536, (425, 0))
    (side = max rounded up to 16: 1536 already is; dx = (1536-686)//2).
    ``crop_back`` of the square reference returned as is -> the source
    exactly; returned at 3072² -> the source's red top-left block (0..50) and
    blue bottom-right block (636..686, 1486..1536) at the same place; a
    render at the SOURCE's aspect 1376×3072 (MiniMax / P-H3) -> scaled to
    686×1536, blocks in place (box (0,0,686,1536)); another aspect 2048×1536
    -> scaled to height 1536 (unchanged), box x0 = (2048-1536)//2 + 425 =
    681. The dressed front (``_render_views``) and the draft
    (``render_draft``) go out as a 1536² reference (grey at (0, 0), the
    source's pixel at (425 + 30, 30)) with ``override_width`` ==
    ``override_height`` == 1536 and ``crop_back_to`` == (1536, (425, 0),
    (686, 1536)). Fails on b6476661: its ``_crop_back`` stretched the
    1376×3072 render onto 1536² (x × 1.116) and cut 425..1111 — the red
    block's centre (25, 25) is grey there.
[h] Framing (F14 h), frame height 1000, base rows 24..967 (0.024–0.968):
    0544's dressed rows 36..998 -> top +0.012, bottom +0.031 -> refused
    (> 0.03), warning set, no ``cut``; rows 36..999 -> bottom +0.032, ``cut``;
    rows 29..972 (+0.005, the square canvas) -> ok, no warning; rows 44..987
    (+0.02) -> ok with a warning; no matte -> ok, skipped.
    ``dressed_view_check`` with a passing guard and 0544's drift -> ok False,
    ``_guard_message`` "back view: the figure moved: its bottom edge shifted
    +3.1 % of the height (limit 3 %)". ``best_fit_attempt`` of [guard ok,
    framing refused, noise 1.0] and [guard ok, framing ok, noise 1.9 refused]
    -> index 1 (a kept frame before noise), not passed; its warning for the
    framing-refused record names "re-framed".
[i] The open state's views (ruling F15, hub job c9e10d2b: the back split
    open). ``OPEN_IMAGE_WORDS`` == "worn open at the front (unzipped /
    unbuttoned), its front edges apart so the body or the layer underneath
    shows between them"; the open worn FRONT prompt contains it, the closed
    one has no state word (``outfit_options._STATE_WORDS_RE``, A7). The
    closed chain with both backs: ``run_estimate(state="open")`` -> 3, note
    "worn 1 + ghost 1 + mesh 1 (backs from the closed state)" (HUB_JOBS 2 /
    2 / 1 minus ``BACK_JOBS`` worn 1, ghost 1 — the worn back is one draft,
    its composite is CPU since Task 11g). ``run_edit_step(worn, back,
    state="open")`` renders NOTHING (a render stub would raise): the open
    group's worn back is the closed one byte for byte, its record
    ``copied_from`` == {fsig_c, closed, sha256}, and it follows
    (``_follows_front``); a changed closed back -> it no longer follows.
    The ghost back (not drafted) copies the same way and follows while the
    closed ghost back is unchanged; once that is gone the copy is rendered
    again (below).
    The closed backs removed: the estimate -> 5 (nothing to copy); the open
    worn back's draft prompt and the open ghost back's prompt carry NO state
    word (rendered from the closed texts); with a composite stub that fails
    its checks the worn back drafts twice (draft, composite, draft,
    composite) and is refused.
[j] Ruling F16 (the Pose tab's Regenerate during a running Build looked
    dropped: the render thread waited behind the Build's garment chains).
    ``figure_build._active`` holds Demo -> ``POST …/model-refs/generate
    {kinds: [tpose]}`` raises 409 ``VIEWS_BUILD_RUNNING`` and fires nothing;
    ``get_model_refs_info(Demo)["build"]`` == {running True, step ""} (no
    step in flight). Without the Build: {"status": "generating"}, fired once
    with kinds ("tpose",); build {running False, step ""}. Plan vs Pose tab:
    wanted == delivered == built (no texture, no interim, no chains, no
    refits, plain body current) — ``dressed_image`` None -> [Step("texture",
    "Views: copied from the body's views", 0), Step("assemble", …, 0)];
    ``dressed_image`` a path -> []. At 52f9c3aa the route answers 200 and
    fires while the Build runs, and the stale case plans [] (built ==
    delivered, nothing runnable).

Fails on b6476661 (this script copied into a worktree at that commit):
[a] "older bald wording -> bald" (True), "delivered hair" ('bald'), "one
hair change" (a "body" entry, no note) and "plain body step" ("Plain body:
…") fail, then it stops — ``figure_build`` has no ``_info_memo`` ([f]).
[g] proves its point on today's code: the BASE ``_crop_back`` (``git show
b6476661:app/core/garment_images.py``) loses the red block.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "b6476661"
BSIG = "base0123abcd"
TSIG = "tex0123456789ab"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def base_module(path: str, name: str) -> types.ModuleType:
    """The module ``path`` as it was at BASE (its absolute ``app.*`` imports resolve to today's modules)."""
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:{path}"], check=True,
                            capture_output=True, text=True).stdout
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    exec(compile(source, f"{BASE}:{path}", "exec"), module.__dict__)
    return module


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-f13-") as tmp:
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

        import numpy as np
        from PIL import Image
        from app.core import base_body, base_body_gates, figure, figure_build, garment_assembly, garments, model3d
        from app.core import garment_hair, garment_images, model_refs
        from app.core import garment_store as gs
        from app.core import outfit_options as oo
        from app.models import inventory
        from app.models import character as character_mod
        from app.models.character import get_character_profile, save_character_profile
        garment_assembly.schedule = lambda *a, **k: False
        base_body.is_base_pipeline = lambda *_a, **_kw: True
        base_body.base_signature = lambda *_a, **_kw: BSIG
        base_body.current_base = lambda *_a, **_kw: (BSIG, "basesha")
        base_body.base_model_sha256 = lambda *_a, **_kw: "basesha"
        base_body.dressed_views = lambda: ("front", "back")
        base_body.side_views_dressed = lambda: False
        stage_calls = []

        def route_probe(character_name):
            stage_calls.append(character_name)
            return {"ok": False, "problems": [{}]}
        from app.core import face_retexture
        face_retexture.runnable = route_probe
        model3d.face_before_rig_planned = lambda *_a, **_kw: True

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}, "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        jacket = inventory.add_item(name="Black Jacket", category="outfit_piece", prompt_fragment="black jacket",
                                    outfit_piece={"slots": ["outer"], "outfit_types": ["casual"],
                                                  "mesh_mode": "own_mesh", "covers": ["top"],
                                                  "closable": True})["id"]
        check("inventory jacket", inventory.add_to_inventory("Demo", jacket), True)
        prof = lambda: get_character_profile("Demo")  # noqa: E731
        refs = model_refs.get_model_refs_dir("Demo")
        refs.mkdir(parents=True, exist_ok=True)

        def image(path: Path, size=(686, 1536), colour=(200, 180, 160), meta=None) -> Path:
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", size, colour).save(path)
            if meta is not None:
                path.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
            return path

        def put_fit(item_id, fsig, state=None, method="edit_chain"):
            path = gs.garment_path("Demo", item_id, fsig, "fit")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"glb {item_id} {fsig}".encode())
            record = {"accepted": True, "base_model_sha256": "basesha", "method": method}
            if state:
                record["state"] = state
            gs.write_record(path.with_suffix(".json"), record)
            return path

        # The plain body's views (front, back) — real files: find_ref_image / file_sha256 read them.
        base_front = image(refs / f"tpose_{BSIG}.png", colour=(120, 110, 100),
                           meta={"prompt": "a woman, long brown hair, standing"})
        base_back = image(refs / f"tpose_back_{BSIG}.png", colour=(110, 100, 90), meta={})

        # --- [a] interim hair --------------------------------------------------------------------------------
        print("[a] hair in the body on a bald plain body")
        check("haired prompt", base_body.stored_base_haired("Demo", BSIG), True)
        base_front.with_suffix(".json").write_text(json.dumps(
            {"prompt": "a woman, completely bald, smooth clean-shaven head, standing"}), encoding="utf-8")
        check("older bald wording -> bald", base_body.stored_base_haired("Demo", BSIG), False)
        p = prof()
        p["hair_method"] = "body"
        check("hair in the body", save_character_profile("Demo", p), True)
        fit_h = put_fit("hairitem", "a1b2c3d4e5f6", method=gs.HAIRDECK)
        rebuild = [("view front", 1), ("view back", 1), ("view left", 1), ("view right", 1), ("mesh", 1),
                   ("rig", 1)]
        with patch.object(base_body, "stored_base_haired", lambda *_a, **_k: False), \
                patch.object(base_body, "prompts_current", lambda *_a, **_k: False), \
                patch.object(base_body, "base_refresh_plan", lambda *_a, **_k: {
                    "signature": BSIG, "views": ["front", "back", "left", "right"], "model": True,
                    "reason": "older prompts"}), \
                patch.object(base_body, "base_rebuild_steps", lambda *_a, **_k: list(rebuild)), \
                patch.object(garment_hair, "worn_hair_id", lambda *_a, **_k: "hairitem"):
            wanted, delivered = figure._delivered("Demo", profile=prof())
            check("wanted hair", wanted.hair, figure.HAIR_BODY)
            check("delivered hair: the HairDeck hair stays", delivered.hair, figure.HAIR_HAIRDECK)
            changes = figure.pending_changes("Demo", profile=prof())
            check("one hair change, no body change",
                  [c for c in changes if c["key"] in (figure.HAIR_KEY, figure.BODY_KEY)],
                  [{"key": "hair", "name": "Hair", "wanted": "body", "delivered": "hairdeck",
                    "note": "in the body → plain body rebuild"}])
            plain = [s for s in figure_build.plan("Demo", profile=prof()) if s.name == "plain_body"]
            check("plain body step", [(s.label, s.jobs) for s in plain],
                  [("Hair · in the body → plain body rebuild (views 4 + mesh + rig)", 6)])
            figure_build._info_memo.clear()
            info = figure_build.figure_info("Demo")
            check("hair change jobs", [c.get("jobs") for c in info["changes"] if c["key"] == "hair"], [6])
            check("hair row", {k: info["hair"].get(k) for k in ("state", "rebuild", "jobs", "note")},
                  {"state": "pending", "rebuild": True, "jobs": 6,
                   "note": "Shown with its HairDeck hair until the plain body is rebuilt with the hair"})
            check("plain body older prompts", info["body"]["plain"]["state"], "older_prompts")
            fit_h.unlink()
            figure.invalidate()
            wanted, delivered = figure._delivered("Demo", profile=prof())
            check("no HairDeck fit -> bald", delivered.hair, figure.HAIR_BALD)
            info = figure_build.figure_info("Demo")
            check("hair row bald", info["hair"]["note"], "Shown bald until the plain body is rebuilt with the hair")
        p = prof()
        p.pop("hair_method", None)
        p["hair_method"] = ""
        save_character_profile("Demo", p)
        base_front.with_suffix(".json").write_text(json.dumps({"prompt": "a woman, long brown hair"}),
                                                   encoding="utf-8")

        # --- [b] closed mesh stands in -----------------------------------------------------------------------
        print("[b] worn open, only the closed mesh")
        check("wear jacket", inventory.equip_piece("Demo", jacket, source="smoke")["status"], "ok")
        fsig_c = gs.garment_fsig("Demo", jacket)

        def build_chain(fsig, state=None):
            """The whole chain of one state built: images, prepared mesh, the fit of that mesh."""
            from app.core.garment_fit import FIT_VERSION
            for step in ("worn", "ghost", "cutout"):
                for view in gs.GARMENT_VIEWS:
                    path = gs.garment_path("Demo", jacket, fsig, "image", step=step, view=view)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"png")
                    gs.write_record(path.with_suffix(".json"), {"accepted": True, "attempt": 1,
                                                                "gates": {"first": {"ok": True, "hem_t": 0.65}}})
            # The worn back follows its front (drafted): the open state can reuse it (ruling F15 i-1). It is a
            # composite (``fit``): a model fit of before Task 11g is stale (Ruling C2, fix round 2).
            worn_back = gs.garment_path("Demo", jacket, fsig, "image", step="worn", view="back")
            gs.write_record(worn_back.with_suffix(".json"), {
                **gs.read_record(worn_back.with_suffix(".json")), "fit": "composite",
                "front_sha256": base_body.file_sha256(gs.garment_path("Demo", jacket, fsig, "image", step="worn",
                                                                      view="front"))})
            prepared = gs.garment_path("Demo", jacket, fsig, "prepared")
            prepared.parent.mkdir(parents=True, exist_ok=True)
            prepared.write_bytes(b"glb")
            gs.write_record(prepared.with_suffix(".json"), {"accepted": True})
            fit = put_fit(jacket, fsig, state)
            gs.write_record(fit.with_suffix(".json"), {
                **gs.read_record(fit.with_suffix(".json")), "kind": "clothing",
                "fit_version": FIT_VERSION["clothing"], "inputs": {"prepared_sha256": garments._sha(prepared)}})
            return fit

        f_c = build_chain(fsig_c)
        oo.set_piece_state("Demo", jacket, "open")
        check("served open -> F_c", (gs.accepted_fit("Demo", jacket, base_model_sha="basesha") or (None,))[0], f_c)
        check("explicit open -> None", gs.accepted_fit("Demo", jacket, base_model_sha="basesha", state="open"), None)

        def dress_text(character_name, view, *, pieces, items, profile=None, mesh_items=(), **_kw):
            meshed = {str(i) for i in mesh_items or ()}
            visible = sorted({str(i) for i in (pieces or {}).values() if i and str(i) not in meshed})
            return ("wear:" + "+".join(visible)) if visible else ""

        base_body.dress_text = dress_text
        base_body.shape_view_shas = lambda *_a, **_kw: {}
        with patch.object(base_body, "stored_base_haired", lambda *_a, **_k: True), \
                patch.object(base_body, "prompts_current", lambda *_a, **_k: True), \
                patch.object(base_body, "base_refresh_plan", lambda *_a, **_k: {
                    "signature": BSIG, "views": [], "model": False, "reason": ""}), \
                patch.object(base_body, "dressed_image", lambda *_a, **_kw: Path("v")):
            figure.invalidate()
            got = figure.delivered_figure("Demo", profile=prof())
            check("own ∋ jacket", jacket in got.own, True)
            check("shown_closed", got.shown_closed, (jacket,))
            check("note", got.notes.get(jacket), "Shown closed until its open mesh is built")
            check("not painted, no interim", (jacket in got.painted, got.interim.get(jacket)), (False, None))
            mine = [c for c in figure.pending_changes("Demo", profile=prof()) if jacket in c["key"]]
            check("ONE change", mine, [{"key": f"{jacket}:state", "name": "Black Jacket", "wanted": "open",
                                        "delivered": "closed", "note": "worn open — open mesh missing"}])
            steps = [s for s in figure_build.plan("Demo", profile=prof()) if s.name == "pieces"]
            check("pieces step", [(s.label, s.jobs, s.item_id) for s in steps],
                  [("Own mesh · Black Jacket (open)", 3, jacket)])
            figure_build._info_memo.clear()
            info = figure_build.figure_info("Demo")
            check("change jobs", [c.get("jobs") for c in info["changes"] if jacket in c["key"]], [3])
            row = next(r for r in info["worn"] if r["item_id"] == jacket)
            check("worn row", (row["state"], row["note"]), ("pending", "Shown closed until its open mesh is built"))
            for path in (f_c, f_c.with_suffix(".json")):
                path.unlink()
            figure.invalidate()
            # Without any mesh of the piece the general interim decides (ruling A11's follow-up, not pinned here).
            mine = [c for c in figure.pending_changes("Demo", profile=prof()) if jacket in c["key"]]
            check("no mesh: still ONE change", [(c["key"], c.get("note")) for c in mine],
                  [(f"{jacket}:state", "worn open — open mesh missing")])
        oo.set_piece_state("Demo", jacket, "closed")

        # --- [c] estimate ------------------------------------------------------------------------------------
        print("[c] estimate")
        check("one set", base_body.dressed_view_jobs(), 2)
        fig = figure.Figure(signature="sig1", bsig=BSIG, shape=BSIG, texture=TSIG, in_body=(), painted=(), own=())
        outfit_views = {}
        sha = base_body.file_sha256
        with patch.object(base_body, "dressed_image",
                          lambda _c, v, *_a, **_k: outfit_views.get(v)):
            check("no store: 2", base_body.dressed_view_estimate("Demo", fig, "sig1", profile=prof()), 2)
            store = base_body.texture_refs_dir("Demo")
            s_front = image(store / f"tpose_{TSIG}.png", colour=(1, 2, 3), meta={
                "base_signature": BSIG, "base_image_sha256": sha(base_front), "dressed": True})
            check("store front: 1", base_body.dressed_view_estimate("Demo", fig, "sig1", profile=prof()), 1)
            draft = image(store / base_body.DRAFT_DIR / f"tpose_back_{TSIG}.png", colour=(4, 5, 6),
                          meta={"front_sha256": sha(s_front)})
            image(store / f"tpose_back_{TSIG}.png", colour=(7, 8, 9), meta={
                "base_signature": BSIG, "base_image_sha256": sha(base_back), "back_draft_sha256": sha(draft)})
            check("store front + back: 0", base_body.dressed_view_estimate("Demo", fig, "sig1", profile=prof()), 0)
            draft.with_suffix(".json").write_text(json.dumps({"front_sha256": "other"}), encoding="utf-8")
            check("back from another front: 1",
                  base_body.dressed_view_estimate("Demo", fig, "sig1", profile=prof()), 1)
            draft.with_suffix(".json").write_text(json.dumps({"front_sha256": sha(s_front)}), encoding="utf-8")
            outfit_views["front"] = image(refs / "tpose_sig1.png", colour=(9, 9, 9), meta={})
            check("own other front stored, back missing: 1",
                  base_body.dressed_view_estimate("Demo", fig, "sig1", profile=prof()), 1)
            outfit_views.clear()
            from dataclasses import replace
            check("no texture: 0",
                  base_body.dressed_view_estimate("Demo", replace(fig, texture=""), "sig1", profile=prof()), 0)
        Step = figure_build.Step
        check("cost note", figure_build.cost("Demo", [Step("interim", "x", 3), Step("pieces", "y", 6)])["note"],
              "9 hub jobs (estimate, retries extra)")

        # --- [d] one step ------------------------------------------------------------------------------------
        print("[d] one step")
        seen = []
        cut = []

        def edit_step(character_name, item_id, fsig, step, view, *, force=False, pair_check=None,
                      prompt_hints=None, state=None, before_composite=None):
            seen.append((step, view))
            path = gs.garment_path(character_name, item_id, fsig, "image", step=step, view=view)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"png")
            gs.write_record(path.with_suffix(".json"),
                            {"accepted": True, "attempt": 1, "gates": {"first": {"ok": True, "hem_t": 0.65}}})
            return path

        def cut_out(*_a, **_kw):
            cut.append(1)
            raise garments._Refused("cutout", "stop here — smoke", None)

        def clear_group():
            for path in gs.stored_groups("Demo").get((jacket, fsig_c), []):
                path.unlink(missing_ok=True)
                path.with_suffix(".json").unlink(missing_ok=True)
            gs.clear_failure("Demo", jacket, fsig_c)

        clear_group()
        with patch.object(garment_images, "run_edit_step", edit_step), patch.object(garment_images, "cut_out", cut_out):
            result = garments.run_garment("Demo", jacket, steps="worn", only=True)
            check("only: worn alone", sorted({s for s, _v in seen}), ["worn"])
            check("only: no cut-out", (len(cut), result.get("ran"), result.get("error")), (0, ["worn"], None))
            seen.clear()
            clear_group()
            result = garments.run_garment("Demo", jacket, steps="worn")
            check("chain: worn, ghost, then the cut-out", (sorted({s for s, _v in seen}), len(cut), result.get("step")),
                  (["ghost", "worn"], 1, "cutout"))
        from app.routes import characters as routes
        calls = []
        with patch.object(garments, "check_run", lambda *a, **k: None), \
                patch.object(garments, "start_garment", lambda *a, **k: calls.append(k.get("only")) or {}):
            for body in ({"step": "ghost"}, {"step": "ghost", "chain": True}, {}):
                routes.run_character_garment("Demo", jacket, routes.GarmentRunRequest(**body), {})
        check("route only", calls, [True, False, False])
        check("job keys differ", garments._Job(jacket, "worn", None, False, only=True).key()
              != garments._Job(jacket, "worn", None, False).key(), True)

        # --- [e] unreadable profile --------------------------------------------------------------------------
        print("[e] unreadable profile")
        real_get = character_mod.get_character_profile

        def broken(name, *, strict=False):
            if strict:
                raise RuntimeError("db locked")
            return real_get(name)
        text = "The character's profile could not be read — nothing was judged or built: db locked"
        with patch.object(character_mod, "get_character_profile", broken):
            check("start failed", figure_build.start("Demo", reason="smoke"), {"status": "failed", "reason": text})
            check("recorded", figure_build.state("Demo")["failed"].get("profile", {}).get("error"), text)
            figure_build._last.pop("Demo", None)
            check("request -> False", figure_build.request("Demo", "outfit"), False)
            check("request recorded", figure_build.state("Demo")["failed"].get("profile", {}).get("error"), text)
            figure_build._last.pop("Demo", None)
            figure_build._run("Demo", "smoke")
            check("run recorded", figure_build.state("Demo")["failed"].get("profile", {}).get("error"), text)
        figure_build._last.pop("Demo", None)

        # --- [f] memo ----------------------------------------------------------------------------------------
        print("[f] memo")
        computed = []
        real_info = figure_build._figure_info

        def counted(character_name, **kw):
            computed.append(1)
            return real_info(character_name, **kw)
        with patch.object(figure_build, "_figure_info", counted):
            figure_build._info_memo.clear()
            figure_build.figure_info("Demo")
            figure_build.figure_info("Demo")
            check("twice -> once", len(computed), 1)
            figure.invalidate()
            figure_build.figure_info("Demo")
            check("after invalidate -> again", len(computed), 2)
            p = prof()
            p["character_appearance"] = "slender, freckles"
            save_character_profile("Demo", p)
            figure_build.figure_info("Demo")
            check("after a profile change -> again", len(computed), 3)

            def racing(character_name, **kw):
                computed.append(1)
                figure.invalidate()   # a write lands while it computes
                return real_info(character_name, **kw)
            figure_build._info_memo.clear()
            with patch.object(figure_build, "_figure_info", racing):
                figure_build.figure_info("Demo")
            figure_build.figure_info("Demo")
            check("a write during it -> not stored", len(computed), 5)
        stage_calls.clear()
        figure.invalidate()
        check("stages", model3d.mesh_hub_stages("Demo", "zz1"), ["mesh", "rig"])
        model3d.mesh_hub_stages("Demo", "zz2")
        check("route probed once", stage_calls, ["Demo"])
        figure.invalidate()
        model3d.mesh_hub_stages("Demo", "zz1")
        check("probed again after invalidate", stage_calls, ["Demo", "Demo"])

        # --- [g] square canvas -------------------------------------------------------------------------------
        print("[g] square canvas")
        check("square frame", garment_images.square_frame((686, 1536)), (1536, (425, 0)))
        src = Image.new("RGB", (686, 1536), (128, 128, 128))
        src.paste((255, 0, 0), (0, 0, 50, 50))
        src.paste((0, 0, 255), (636, 1486, 686, 1536))
        src.paste((0, 200, 0), (30, 30, 31, 31))
        src_path = refs / "src.png"
        src.save(src_path)
        work = root / "work"
        work.mkdir()

        def blocks(path):
            with Image.open(path) as im:
                rgb = im.convert("RGB")
            return rgb.size, rgb.getpixel((25, 25)), rgb.getpixel((661, 1511))

        def near(px, want, tol=40):
            return all(abs(a - b) <= tol for a, b in zip(px, want))

        with garment_images.square_reference(src_path, refs) as (ref, side, offset, size):
            with Image.open(ref) as im:
                square = im.convert("RGB")
        check("reference", (square.size, square.getpixel((0, 0)), square.getpixel((425 + 30, 30))),
              ((1536, 1536), (128, 128, 128), (0, 200, 0)))
        for label, render in (("as is", square), ("3072²", square.resize((3072, 3072), Image.NEAREST)),
                              ("source aspect 1376×3072", src.resize((1376, 3072), Image.NEAREST))):
            path = work / f"{label[:4].strip()}.png"
            render.save(path)
            out = garment_images.crop_back(path, work / "out.png", side, offset, size)
            got_size, red, blue = blocks(out)
            check(f"crop back {label}", (got_size, near(red, (255, 0, 0)), near(blue, (0, 0, 255))),
                  ((686, 1536), True, True))
        check("exact as is", np.array_equal(np.asarray(Image.open(garment_images.crop_back(
            (lambda p: (square.save(p), p)[1])(work / "again.png"), work / "out2.png", side, offset, size)).convert(
            "RGB")), np.asarray(src)), True)
        check("box: source aspect", garment_images.crop_back_box((1376, 3072), 1536, (425, 0), (686, 1536)),
              ((686, 1536), (0, 0, 686, 1536)))
        check("box: other aspect", garment_images.crop_back_box((2048, 1536), 1536, (425, 0), (686, 1536)),
              ((2048, 1536), (681, 0, 1367, 1536)))
        base_gi = base_module("app/core/garment_images.py", "base_garment_images")
        path = work / "old.png"
        src.resize((1376, 3072), Image.NEAREST).save(path)
        old = base_gi._crop_back(path, work / "old_out.png", 1536, (425, 0), (686, 1536))
        check("BASE stretched it (red block lost)", near(blocks(old)[1], (255, 0, 0)), False)

        captured = []
        from app.core import expression_regen

        def render(character_name, **kw):
            with Image.open(kw["reference_image"]) as im:
                ref_img = im.convert("RGB")
            captured.append({"size": ref_img.size, "corner": ref_img.getpixel((0, 0)),
                             "mark": ref_img.getpixel((425 + 30, 30)),
                             **{k: kw.get(k) for k in ("override_width", "override_height", "crop_back_to")}})
            return None
        want = {"size": (1536, 1536), "corner": (128, 128, 128), "mark": (0, 200, 0), "override_width": 1536,
                "override_height": 1536, "crop_back_to": (1536, (425, 0), (686, 1536))}
        with patch.object(expression_regen, "render_character_image", render), \
                patch.object(base_body, "dress_prompt", lambda *a, **k: ("dress", "neg")):
            base_body._render_views("Demo", signature="sigq", pieces={}, items=[], todo=["front"], force=True,
                                    on=BSIG, registrations={"front": src_path, "back": None}, texts={"front": "x"},
                                    tsig="", mesh={}, dressed=True, bald=False, profile=prof(), raise_load=False,
                                    current=lambda v: None)
            check("dressed front", captured[-1:], [want])
            common = base_body._dress_common("back", pieces={}, items=[], profile=prof(), size=(1024, 1024))
            base_body.render_draft("Demo", "back", stem=refs / "drafts" / "d", front=src_path, refs_dir=refs,
                                   prompt=("t", "n"), profile=prof(), common=common, sidecar_extra={})
            check("draft", captured[-1:], [want])

        # --- [h] framing -------------------------------------------------------------------------------------
        print("[h] framing")

        def alpha(top, last):
            a = np.zeros((1000, 400), np.uint8)
            a[top:last + 1, 150:250] = 255
            return a
        base_a = alpha(24, 967)
        r = base_body_gates.framing_arrays(alpha(36, 998), base_a)
        check("json-safe", json.loads(json.dumps(r)) == r, True)
        check("0544 refused", (r["ok"], r["top"], r["bottom"], "warning" in r, "cut" in r),
              (False, 0.012, 0.031, True, False))
        r = base_body_gates.framing_arrays(alpha(36, 999), base_a)
        check("cut at the frame", (r["ok"], r["bottom"], r.get("cut")), (False, 0.032, True))
        r = base_body_gates.framing_arrays(alpha(29, 972), base_a)
        check("square canvas drift", (r["ok"], r["top"], r["bottom"], "warning" in r), (True, 0.005, 0.005, False))
        r = base_body_gates.framing_arrays(alpha(44, 987), base_a)
        check("2 % drift: warning", (r["ok"], r["bottom"], "warning" in r), (True, 0.02, True))
        r = base_body_gates.framing_arrays(np.full((1000, 400), 255, np.uint8), base_a)
        check("no matte", (r["ok"], "skipped" in r), (True, True))

        def rgba(path, a):
            img = Image.new("RGBA", (a.shape[1], a.shape[0]), (90, 90, 90, 0))
            img.putalpha(Image.fromarray(a))
            img.save(path)
            return path
        base_view = rgba(work / "base_back.png", base_a)
        dressed = rgba(work / "dressed_back.png", alpha(36, 998))
        with patch.object(base_body, "view_guard", lambda *_a, **_k: {"ok": True, "scores": {"back": 1.0},
                                                                      "best": "back"}):
            result = base_body.dressed_view_check("back", dressed, {"back": base_view})
        check("check refused", result["ok"], False)
        check("message", base_body._guard_message("back", result),
              "back view: the figure moved: its bottom edge shifted +3.1 % of the height (limit 3 %)")
        attempts = [{"ok": False, "guard": {"ok": True}, "framing": {"ok": False}, "noise": {"ok": True, "score": 1.0}},
                    {"ok": False, "guard": {"ok": True}, "framing": {"ok": True}, "noise": {"ok": False, "score": 1.9}}]
        check("best attempt", base_body.best_fit_attempt(attempts), (1, False))
        check("warning names re-framed", "re-framed" in base_body.fit_gate_warning(2, attempts[0]), True)

        # --- [i] the open state's views (F15) ----------------------------------------------------------------
        print("[i] open state: front phrase, backs from the closed state")
        from app.core import garment_clothing
        words = oo._STATE_WORDS_RE
        check("phrase", oo.OPEN_IMAGE_WORDS, "worn open at the front (unzipped / unbuttoned), its front edges apart "
                                             "so the body or the layer underneath shows between them")
        open_prof = oo.with_item_state(prof(), jacket, "open")
        front_open = garment_clothing.edit_prompt("Demo", "worn", "front", profile=open_prof, item_id=jacket)[0]
        front_closed = garment_clothing.edit_prompt("Demo", "worn", "front", profile=prof(), item_id=jacket)[0]
        check("open front says it", oo.OPEN_IMAGE_WORDS in front_open, True)
        check("closed front silent", bool(words.search(front_closed)), False)
        clear_group()
        fsig_o = gs.garment_fsig("Demo", jacket, state="open")
        build_chain(fsig_c)
        est = garments.run_estimate("Demo", jacket, state="open")
        check("open estimate", (est["hub_jobs"], est["note"]),
              (3, "worn 1 + ghost 1 + mesh 1 (backs from the closed state)"))
        oo.set_piece_state("Demo", jacket, "open")
        closed_worn_back = gs.garment_path("Demo", jacket, fsig_c, "image", step="worn", view="back")
        # The open worn front accepted (the back's own front); the closed back is reused, nothing renders.
        open_front = gs.garment_path("Demo", jacket, fsig_o, "image", step="worn", view="front")
        open_front.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), (1, 1, 1)).save(open_front)
        gs.write_record(open_front.with_suffix(".json"), {"accepted": True, "attempt": 1, "gates": {"first": {}}})

        def no_render(*_a, **_k):
            raise AssertionError("rendered")
        with patch.object(expression_regen, "render_character_image", no_render), \
                patch.object(base_body, "render_draft", no_render):
            got = garment_images.run_edit_step("Demo", jacket, fsig_o, "worn", "back", state="open")
        check("copied, byte for byte", got.read_bytes() == closed_worn_back.read_bytes(), True)
        check("copied_from", gs.read_record(got.with_suffix(".json")).get("copied_from"),
              {"fsig": fsig_c, "state": "closed", "sha256": base_body.file_sha256(closed_worn_back)})
        check("follows", garment_images._follows_front("Demo", jacket, fsig_o, "worn", got), True)
        closed_worn_back.write_bytes(b"another back")
        check("closed changed -> no longer follows",
              garment_images._follows_front("Demo", jacket, fsig_o, "worn", got), False)
        with patch.object(expression_regen, "render_character_image", no_render):
            ghost_copy = garment_images.run_edit_step("Demo", jacket, fsig_o, "ghost", "back", state="open")
        check("ghost back copied + follows (not drafted)",
              garment_images._follows_front("Demo", jacket, fsig_o, "ghost", ghost_copy), True)
        for step in ("worn", "ghost"):
            back = gs.garment_path("Demo", jacket, fsig_c, "image", step=step, view="back")
            back.unlink()
            back.with_suffix(".json").unlink()
        for path in (got, got.with_suffix(".json")):
            path.unlink()
        check("no closed backs: 5", garments.run_estimate("Demo", jacket, state="open")["hub_jobs"], 5)
        prompts = []

        def draft(*_a, prompt, **_k):
            prompts.append(("draft", prompt[0]))
            return image(refs / "draft_stub.png", meta={})

        def composite(*_a, **_k):
            prompts.append(("composite", ""))
            return {"ok": False, "reasons": ["stub"], "iou": 0.0, "coverage": {"score": 0.0}}
        # Masks without the BiRefNet model (the prompts are what is checked here).
        whole = lambda _path, size: np.ones((size[1], size[0]), bool)  # noqa: E731
        from app.core import view_composite
        with patch.object(base_body, "render_draft", draft), patch.object(view_composite, "compose", composite), \
                patch.object(garment_images, "_mask", whole):
            try:
                garment_images.run_edit_step("Demo", jacket, fsig_o, "worn", "back", state="open")
            except Exception:  # noqa: BLE001 — the stub composite fails its checks: GateRefused
                pass
        check("worn back: draft, composite, re-draft, composite", [k for k, _p in prompts],
              ["draft", "composite", "draft", "composite"])
        check("worn back: no state word", [k for k, p in prompts if words.search(p)], [])
        # The ghost back: its source (the open worn back) accepted; the prompt captured at the render.
        worn_back_o = gs.garment_path("Demo", jacket, fsig_o, "image", step="worn", view="back")
        Image.new("RGB", (8, 8), (2, 2, 2)).save(worn_back_o)
        gs.write_record(worn_back_o.with_suffix(".json"), {"accepted": True, "attempt": 1, "gates": {"first": {}}})
        ghost = []

        def render_ghost(character_name, **kw):
            ghost.append(kw.get("bare_prompt") or "")
            return None
        with patch.object(expression_regen, "render_character_image", render_ghost), \
                patch.object(garment_images, "_mask", whole):
            try:
                garment_images.run_edit_step("Demo", jacket, fsig_o, "ghost", "back", state="open")
            except Exception:  # noqa: BLE001 — nothing rendered: GateRefused
                pass
        check("ghost back rendered from the closed text", (len(ghost) > 0, [p for p in ghost if words.search(p)]),
              (True, []))

        # --- [j] manual render while a Build runs (F16) -----------------------------------------------------
        print("[j] manual render of the dressed views while a Build runs")
        import asyncio
        import dataclasses
        from fastapi import HTTPException
        for side in ("left", "right"):
            image(refs / f"tpose_{side}_{BSIG}.png", colour=(100, 90, 80), meta={})

        class _Req:
            async def json(self):
                return {"kinds": ["tpose"]}
        fired = []

        def generate():
            try:
                return asyncio.run(routes.generate_character_model_refs("Demo", _Req()))
            except HTTPException as e:
                return (e.status_code, e.detail)
        with patch.object(model_refs, "trigger_now", lambda *a, **k: fired.append(k.get("kinds"))):
            with figure_build._lock:
                figure_build._active.add("Demo")
            try:
                check("Build runs: 409, nothing fired", (generate(), fired),
                      ((409, figure_build.VIEWS_BUILD_RUNNING), []))
                check("Pose tab sees the Build", model_refs.get_model_refs_info("Demo").get("build"),
                      {"running": True, "step": ""})
            finally:
                with figure_build._lock:
                    figure_build._active.discard("Demo")
            check("no Build: 200 + fired", (generate(), fired), ({"status": "generating"}, [("tpose",)]))
            check("Pose tab: no Build", model_refs.get_model_refs_info("Demo").get("build"),
                  {"running": False, "step": ""})
        # The plan and the Pose tab judge the views alike (base_body.dressed_image): a delivered figure whose model
        # is built and that has no texture / interim -> "Views" step while a view is not current, nothing else.
        _w, d = figure._delivered("Demo", profile=prof())
        bare = dataclasses.replace(d, texture="", interim={})
        with patch.object(figure, "_delivered", lambda *a, **k: (bare, bare)), \
                patch.object(figure_build, "_model_figure", lambda *a, **k: bare), \
                patch.object(base_body, "base_refresh_plan", lambda *a, **k: {}), \
                patch.object(figure_build, "_chain_step", lambda *a, **k: None), \
                patch.object(figure_build, "_hair_step", lambda *a, **k: None):
            from app.core import garment_refit
            with patch.object(garment_refit, "work_count", lambda *a, **k: 0):
                with patch.object(base_body, "dressed_image", lambda *a, **k: None):
                    check("stale view -> Views step", [(s.name, s.label, s.jobs) for s in figure_build.plan("Demo")],
                          [("texture", "Views: copied from the body's views", 0),
                           ("assemble", "Assemble the figure", 0)])
                with patch.object(base_body, "dressed_image", lambda *a, **k: base_front):
                    check("current views -> nothing", figure_build.plan("Demo"), [])

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
