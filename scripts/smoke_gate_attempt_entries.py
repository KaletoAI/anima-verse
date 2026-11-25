#!/usr/bin/env python3
"""Smoke: every quality-gated image loop runs attempt 2 on the SECOND entry of its occasion's chain
(docs/edit-prompts.md §7, C11/C12: ``routing.gate_attempts``), the route meta says so, and nothing is marked
``fallback_from``.

Usage:
    ./.venv/bin/python scripts/smoke_gate_attempt_entries.py

Throwaway world + instance (with a copy of the repo's ``human`` package for the base body), no real world, no hub,
no server, no network. The code under test is each REAL loop; below it ``expression_regen.render_character_image``
is replaced by a render that resolves the occasion through the REAL ``routing.run_routed`` on a ``BackendPool`` of
fake backends (the chain rules stubbed per occasion) and writes a small RGBA picture plus its sidecar (the sidecar
keys it was given + ``route_meta`` + ``service`` = the backend). Gates are stubbed per site to refuse attempt 1 and
pass attempt 2 — except the base-body hand gate, which is the real one on drawn figures. Footwear goes one level
deeper: its ``_edit`` and ``run_routed`` are real and the fakes' ``generate`` is the real ``ImageBackend.generate``
(with the edit-prompt normaliser), so the dialect of the second entry is checked too.

Chains (two entries each, all fake backends cost 1, 1 slot, img2img):
    garment_view  [gv-1, gv-2]      outfit_back_draft [obd-1, obd-2]   outfit_back_turn [obt-1, obt-2]
    base_front    [bf-1, bf-2]      base_view         [bv-1, bv-2]     outfit_front     [of-1, of-2]
    footwear_empty [fw-1 (model "Qwen2.1-Turbo" -> dialect image_tag), fw-2 (model "P-H3-Image" -> picture_edit)]

Expected, by hand (``attempt_order``: attempt k aims at usable entry min(k, n); ``route_meta`` writes
``attempt_entry {attempt, aimed_position, position}`` only for attempt > 1, ``fallback_from`` only when the render
ran behind the AIMED entry):

[0] gate_attempts alone: outside any attempt it sets 1, 2 (yields 1, 2); inside ``retry_attempt(2)`` it sets 2, 3
    (yields 1, 2 — the nested count continues; on f1851bf09 it set 1, 2) and after the loop the attempt is 2
    again, outside 1.
[1] garment ghost edit (``garment_images._render_edit_step``): renders gv-1, gv-2; attempt 2's sidecar
    ``attempt_entry`` {2, 2, 2}, no ``fallback_from``; published with attempt 2.
[2] garment drafted back (``garment_images._drafted_back``, no stored draft): drafts on obd-1, obd-2 (occasion
    outfit_back_draft via ``base_body.render_draft``), attempt 2 {2, 2, 2}; published with attempt 2.
[3] beard-free HairDeck input (``garment_beard.beard_free_input``): gv-1, gv-2; record accepted, attempt 2,
    backend gv-2, routing.position 2.
[4] piece-only template view (``garment_template_views.generate``): gv-1, gv-2; published from attempt 2.
[5] shell base view (``shell_base_views.ensure``): gv-1, gv-2; the variant's sidecar names attempt 2.
[6] base-body front hand gate (``base_body.generate_base_images``, force): figure hand widths 39 then 23 px of
    H = 600 (score 0.065 > 0.050 refused, 0.038 passes) -> base_front on bf-1, bf-2, attempt 2 {2, 2, 2}; then
    the three edit views back/left/right each on bv-1 (attempt 1 again after the loop), no attempt_entry.
[7] dressed back draft (``base_body._dress_view``):
    a) no stored draft, composite of draft 1 refused, draft 2 passes: turns obt-1, obt-2 and drafts obd-1, obd-2.
    b) a stored draft whose composite is refused (attempt 1, no render) -> ONE new draft as attempt 2: turn obt-2,
       draft obd-2, both {2, 2, 2} (the stored draft keeps its attempt number, Ruling C2).
[8] view guard (``base_body._guard_dressed_views``):
    a) back fails its check, ``rerender`` = the REAL ``_dress_view`` (draft 1 passes): the re-render's turn and
       draft run on obt-2 / obd-2 with {2, 2, 2} — the guard's ``retry_attempt(2)`` is continued by the draft
       loop. On f1851bf09 (before this change) the draft loop set attempt 1 again: obt-1 / obd-1.
    b) front fails, no ``rerender``, a manifest: ``generate_dressed_images`` re-renders under attempt 2 -> of-2,
       {2, 2, 2}; the second check passes, the view is kept.
[9] footwear empty shoe (``footwear_source._step_empty``, seed 0):
    a) chain [fw-1, fw-2], ``empty_gate`` refuses attempt 1: fw-1 with seed 0*1000+1 = 1, prompt without the
       picture_edit prefix (image_tag, no picture named: unchanged); fw-2 with seed 2, prompt starting
       "Edit <Picture 1>. " (picture_edit prefix). empty.try2.json: backend fw-2, routing.position 2,
       attempt_entry {2, 2, 2}, no fallback_from; the step record accepted, backend fw-2, routing.position 2.
    b) chain [fw-1] only: both attempts on fw-1 (seeds 1, 2); try2 attempt_entry {2, 1, 1} (clamped), no
       fallback_from.
    On f1851bf09 [9a] rendered both attempts on fw-1 (seeds 1, 2): the attempt number changed only the seed.
[10] no fake backend outside the two entries of each chain was ever asked; no socket was opened.
"""
import contextlib
import io
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

FAILS = []
CONNECTS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def _no_connect(*a, **k):
    CONNECTS.append(a)
    raise OSError("network disabled in this smoke")


socket.create_connection = _no_connect

CHAINS = {
    "garment_view": ["gv-1", "gv-2"],
    "outfit_back_draft": ["obd-1", "obd-2"],
    "outfit_back_turn": ["obt-1", "obt-2"],
    "base_front": ["bf-1", "bf-2"],
    "base_view": ["bv-1", "bv-2"],
    "outfit_front": ["of-1", "of-2"],
    "footwear_empty": ["fw-1", "fw-2"],
}
MODELS = {"fw-1": "Qwen2.1-Turbo", "fw-2": "P-H3-Image"}
ROUTES = []        # one row per routed render: occasion, backend, position, attempt_entry, fallback
FRONT_HANDS = []   # hand widths of the base_front figures, popped per base_front render


def png(path: Path, size=(64, 64)) -> Path:
    """An RGBA picture with an opaque block in the middle (cut-outs find a figure)."""
    w, h = size
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    im.paste((150, 120, 90, 255), (w // 4, h // 8, 3 * w // 4, 7 * h // 8))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def fig(hand: int, arm: int = 21) -> np.ndarray:
    """The hand-gate figure of smoke_base_body_hand_gate (torso 600 px tall, hands ``hand`` px wide)."""
    a = np.zeros((640, 640), np.uint8)
    a[10:611, 250:350] = 255
    cy = 300
    a[cy - arm // 2:cy + arm // 2 + 1, 100:250] = 255
    a[cy - arm // 2:cy + arm // 2 + 1, 350:500] = 255
    a[cy - hand // 2:cy + hand // 2 + 1, 40:100] = 255
    a[cy - hand // 2:cy + hand // 2 + 1, 500:560] = 255
    return a


def routed_row(occasion, name, route):
    from app.imagegen import routing
    meta = routing.route_meta(route)
    row = {"occasion": occasion, "backend": name, "position": route.position,
           "entry": meta.get("attempt_entry"), "fallback": "fallback_from" in meta, "meta": meta}
    ROUTES.append(row)
    return row


def fake_render(character_name, *, output_stem, occasion="", sidecar_extra=None, override_width=None,
                override_height=None, crop_back_to=None, **_kw):
    """``render_character_image`` stand-in: the REAL ``run_routed`` picks the backend, a picture is written."""
    from app.imagegen import routing
    name, route = routing.run_routed(occasion, lambda b: b.name, character=character_name, pool=POOL[0])
    row = routed_row(occasion, name, route)
    path = Path(output_stem).with_suffix(".png")
    if occasion == "base_front":
        alpha = fig(FRONT_HANDS.pop(0))
        rgba = np.zeros(alpha.shape + (4,), np.uint8)
        rgba[..., :3] = 180
        rgba[..., 3] = alpha
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgba, "RGBA").save(path)
    else:
        png(path, (override_width or 64, override_height or 64))
    if crop_back_to:
        from app.core.garment_images import crop_back
        side, offset, size = crop_back_to
        path = crop_back(path, path, side, offset, size)
    sidecar = {**(sidecar_extra or {}), **row["meta"], "service": name}
    path.with_suffix(".json").write_text(json.dumps(sidecar, default=str))
    return path


POOL = [None]


def taken(since, occasion=None):
    rows = ROUTES[since:]
    return [(r["backend"], r["entry"], r["fallback"]) for r in rows if occasion is None or r["occasion"] == occasion]


E2 = {"attempt": 2, "aimed_position": 2, "position": 2}


class Counter:
    """A stub gate that refuses its first call and passes from the second on."""

    def __init__(self):
        self.n = 0

    def ok(self) -> bool:
        self.n += 1
        return self.n >= 2


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="smoke-gate-entries-"))
    try:
        return run(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run(root: Path) -> int:
    os.environ["STORAGE_DIR"] = str(root / "world")
    os.environ["INSTANCE_DIR"] = str(root / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"},
                                                   "base_body": {"skin_detail_step": False}}))
    from app.core import config
    config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
    from app.core import db
    db.init_schema()
    shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
    from app.plugins.loader import discover_packages
    discover_packages(root / "plugins", force=True)

    from app.core import base_body, expression_regen, garment_beard, garment_images as gi, garment_store
    from app.core import garment_template_views as tv, model_refs, shell_base_views as sbv, view_composite
    from app.imagegen import base as _base
    from app.imagegen import routing
    from app.imagegen.base import ImageBackend
    from app.imagegen.selection import BackendPool
    from app.models.character import get_character_images_dir, get_character_profile, save_character_profile

    class Fake(ImageBackend):
        def __init__(self, name):
            super().__init__(name, "http://localhost", 1.0, "fake", "FAKE_GATE_ENTRIES_")
            self.model = MODELS.get(name, "fake-model")
            self.category, self.ref_slot_count, self.MEDIA_TYPE = "img2img", 1, "image"
            self.instance_enabled, self._available = True, True
            self.prompt_char_limit = 100000
            self.calls = []

        def check_availability(self):
            return True

        def _generate(self, prompt, negative_prompt, params):
            self.calls.append({"prompt": prompt, "seed": params.get("seed")})
            buf = io.BytesIO()
            im = Image.new("RGB", (256, 128), (255, 255, 255))
            im.paste((30, 30, 30), (20, 40, 236, 100))
            im.save(buf, format="PNG")
            return [buf.getvalue()]

    names = sorted({n for chain in CHAINS.values() for n in chain} | {"cloud"})
    fakes = {n: Fake(n) for n in names}
    POOL[0] = BackendPool(list(fakes.values()))
    rules = {k: list(v) for k, v in CHAINS.items()}
    routing._rules = lambda occasion: list(rules.get(occasion, []))
    routing._character_spec = lambda occ_def, character, overrides=None: ""
    _base.image_overflow_after_seconds = lambda: 0
    expression_regen.render_character_image = fake_render

    work = root / "work"
    refs_dir = work / "refs"
    refs_dir.mkdir(parents=True)
    model_refs.get_model_refs_dir = lambda c: refs_dir
    human = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
             "body_slots": {"skin": {"tone": "olive"}, "build": {"type": "athletic"}}}
    check("create Demo", save_character_profile("Demo", human, create_new=True), True)
    png(get_character_images_dir("Demo") / "Demo_1.png", (8, 8))
    stored = get_character_profile("Demo")
    stored["profile_image"] = "Demo_1.png"
    save_character_profile("Demo", stored)

    print("[0] gate_attempts alone")
    seen = [(a, routing.current_attempt()) for a in routing.gate_attempts(2)]
    check("[0] outside: yields / sets", seen, [(1, 1), (2, 2)])
    with routing.retry_attempt(2):
        seen = [(a, routing.current_attempt()) for a in routing.gate_attempts(2)]
        check("[0] nested in attempt 2: yields / sets", seen, [(1, 2), (2, 3)])
        for a in routing.gate_attempts(2):
            break
        check("[0] after a break in the nested loop", routing.current_attempt(), 2)
    check("[0] outside again", routing.current_attempt(), 1)

    base_png = png(work / "base.png", (64, 96))
    source_png = png(work / "source.png", (64, 96))

    class Kind:
        GATE_VERSIONS = {}
        REGATE_ACCEPTED_STEPS = {}

        def __init__(self):
            self.gate_counter = Counter()

        def edit_prompt(self, *a, **k):
            return "edit the piece", "blurry"

        def draft_prompt(self, *a, **k):
            return "draft the back", "blurry"

        def gate(self, *a, **k):
            ok = self.gate_counter.ok()
            return {"ok": ok, "reasons": [] if ok else ["stub refusal"]}

        def back_reasons(self, front_gate, record):
            return []

    def gpath(character_name, item_id, fsig, what, step="", view="", attempt=None):
        return work / "garment" / f"{step}_{view}_{attempt}.png"

    garment_store.garment_path = gpath
    gi._publish = lambda c, i, f, step, view, kind, target, final, records, attempt, follow=None: ("published", attempt)
    gi._accepted = lambda final: True
    gi._variant_sha = lambda base, variant: ""

    print("[1] garment ghost edit")
    mark = len(ROUTES)
    counter = Counter()
    gi._gate_inputs = lambda kind, step, base, source, refs, item: ((64, 96), {"source_rgb": None}, None)
    gi._source_sha = lambda kind, step, source: ""
    gi.jobs_left = lambda *a, **k: 2
    gi._capped = lambda kind, step: False
    gi._gate_attempt = lambda *a, **k: {"ok": counter.ok(), "reasons": []}
    gi._with_pair = lambda record, pair_check, extra=None: record
    out = gi._render_edit_step("Demo", "item_x", "f1", "ghost", "back", Kind(), profile={}, base=base_png,
                               source=source_png, refs_dir=refs_dir, final=work / "final.png", pair_check=None,
                               prompt_hints=None)
    check("[1] renders", taken(mark), [("gv-1", None, False), ("gv-2", E2, False)])
    check("[1] published attempt", out, ("published", 2))
    check("[1] attempt 2 sidecar entry",
          json.loads(gpath("", "", "", "", "ghost", "back", 2).with_suffix(".json").read_text()).get("attempt_entry"),
          E2)

    print("[2] garment drafted back")
    mark = len(ROUTES)
    front = png(gpath("", "", "", "", "draft", "front", None), (64, 96))
    gi.accepted_record = lambda path: {"ok": True}
    gi._follows_front = lambda *a, **k: True
    gi.draft_path = lambda c, i, f, step, view: work / "drafts" / f"{step}_{view}.png"
    base_body._dress_common = lambda view, **k: {}
    def compose(base, draft, target, **k):
        png(Path(target), (64, 96))
        return {"ok": True}

    view_composite.compose = compose
    view_composite.is_empty = lambda composite: False
    view_composite.read_support = lambda *a, **k: None
    view_composite.summary = lambda composite: "stub"
    view_composite.sidecar_fields = lambda composite: {}
    out = gi._drafted_back("Demo", "item_x", "f1", "draft", Kind(), profile={}, base=base_png, refs_dir=refs_dir,
                           final=work / "final_back.png")
    check("[2] drafts", taken(mark), [("obd-1", None, False), ("obd-2", E2, False)])
    check("[2] published attempt", out, ("published", 2))

    print("[3] beard-free HairDeck input")
    mark = len(ROUTES)
    counter = Counter()
    garment_beard.beard_gate = lambda *a, **k: {"ok": counter.ok(), "reasons": []}
    folder = work / "beard"
    target, record = garment_beard.beard_free_input("Demo", source_png, folder)
    check("[3] renders", taken(mark), [("gv-1", None, False), ("gv-2", E2, False)])
    check("[3] record", (record.get("accepted"), record.get("attempt"), record.get("backend"),
                         (record.get("routing") or {}).get("position")), (True, 2, "gv-2", 2))

    print("[4] piece-only template view")
    mark = len(ROUTES)
    counter = Counter()
    import app.models.inventory as inventory
    inventory.get_item = lambda iid: {"id": iid}
    inventory.get_item_image_path = lambda iid: str(source_png)
    tv.prompt_for = lambda item, view: ("the piece alone", "blurry")
    tv.views_dir = lambda c: work / "views"
    tv.check_file = lambda c, item, target, cut: {"ok": counter.ok(), "reasons": []}
    published = []
    tv._publish = lambda c, i, view, cut, record: published.append(record["attempt"]) or cut
    tv.generate("Demo", "item_x", "back")
    check("[4] renders", taken(mark), [("gv-1", None, False), ("gv-2", E2, False)])
    check("[4] published attempt", published, [2])

    print("[5] shell base view")
    mark = len(ROUTES)
    counter = Counter()
    sbv.current = lambda *a, **k: None
    sbv.edit_text = lambda variant: ("arms a little away", "blurry")
    sbv.path_of = lambda c, view, bsig, variant: work / "shell" / f"{view}_{variant}.png"
    sbv.attempt_path = lambda c, view, bsig, variant, n: work / "shell" / f"{view}_{variant}.try{n}.png"
    sbv._clear_attempts = lambda *a, **k: None
    sbv._write_attempts = lambda *a, **k: None
    sbv._gate = lambda c, bsig, variant, path, size: {"ok": counter.ok(), "reasons": []}
    base_body.cut_out = lambda p: Image.open(p).convert("RGBA")
    out = sbv.ensure("Demo", "back", "bsig", "arms", base_png)
    check("[5] renders", taken(mark), [("gv-1", None, False), ("gv-2", E2, False)])
    check("[5] variant sidecar attempt", json.loads(out.with_suffix(".json").read_text()).get("attempt"), 2)

    print("[6] base-body front hand gate")
    mark = len(ROUTES)
    FRONT_HANDS[:] = [39, 23]
    real_refs_dir = model_refs.get_model_refs_dir
    from app.models.character import get_character_dir
    model_refs.get_model_refs_dir = lambda c: get_character_dir(c) / "model_refs"
    (get_character_dir("Demo") / "model_refs").mkdir(parents=True, exist_ok=True)
    out = base_body.generate_base_images("Demo", force=True)
    model_refs.get_model_refs_dir = real_refs_dir
    check("[6] fronts", taken(mark, "base_front"), [("bf-1", None, False), ("bf-2", E2, False)])
    check("[6] views back to attempt 1", taken(mark, "base_view"), [("bv-1", None, False)] * 3)
    check("[6] rendered", sorted(k for k, v in out.items() if v), ["back", "front", "left", "right"])

    print("[7] dressed back draft")
    counter = Counter()
    base_body.composite_outdated = lambda record: False
    base_body.turned_cutout = lambda c, view, *, stem, front, refs_dir, common, sidecar_extra: fake_render(
        c, output_stem=stem, occasion="outfit_back_turn", sidecar_extra=sidecar_extra)
    base_body.render_view_edit = lambda c, view, *, stem, occasion, **k: fake_render(
        c, output_stem=stem, occasion=occasion)
    base_body.picture_edit_prompt = lambda *a, **k: ("dress the base view", "blurry")
    base_body._composite_extra = lambda *a, **k: {}

    def composite_attempt(c, view, *, stem, draft, base_views, extra, front=None, front_region=None):
        path = png(Path(stem).with_suffix(".png"), (64, 96))
        return path, {"ok": counter.ok(), "composite": {"ok": True}, "guard": {"best": view},
                      "noise": {"score": 0.0}}

    base_body._composite_attempt = composite_attempt
    base_body.best_fit_attempt = lambda results: next(
        ((i, True) for i, r in enumerate(results) if r["ok"]), (len(results) - 1, False))
    base_body.fit_gate_warning = lambda *a, **k: "stub warning"
    base_body._publish_staged = lambda staged, final_stem, record, key="hand_gate": Path(staged)
    base_body.clear_view_refusals = lambda *a, **k: None
    base_body.record_view_refusal = lambda *a, **k: None
    dress_refs = work / "dress"
    (dress_refs / "drafts").mkdir(parents=True, exist_ok=True)
    dressed_front = png(work / "dressed_front.png", (64, 96))
    stored_draft = [None]
    base_body.stored_draft = lambda c, view, signature, front: stored_draft[0]

    def dress_back():
        return base_body._dress_view("Demo", "back", signature="sig1", bsig="bsig", pieces={}, items=[], profile={},
                                     front=dressed_front, base_views={"back": base_png, "front": base_png},
                                     refs_dir=dress_refs, size=(64, 96))

    mark = len(ROUTES)
    dress_back()
    check("[7a] turns", taken(mark, "outfit_back_turn"), [("obt-1", None, False), ("obt-2", E2, False)])
    check("[7a] drafts", taken(mark, "outfit_back_draft"), [("obd-1", None, False), ("obd-2", E2, False)])
    mark = len(ROUTES)
    counter = Counter()
    stored_draft[0] = png(work / "stored_draft.png", (64, 96))
    dress_back()
    check("[7b] stored draft refused -> one new draft as attempt 2",
          (taken(mark, "outfit_back_turn"), taken(mark, "outfit_back_draft")),
          ([("obt-2", E2, False)], [("obd-2", E2, False)]))
    stored_draft[0] = None

    print("[8] view guard re-render")
    import app.core.model3d as model3d
    base_body._ref_sidecar = lambda path: {}
    base_body.orientation_retried = lambda *a, **k: 0
    base_body._guard_message = lambda view, result: f"{view} stub"
    checks = Counter()
    base_body.dressed_view_check = lambda v, path, registrations, front=None: {
        "ok": v == "front" or checks.ok(), "reasons": [], "framing": {"ok": True}}
    model3d._ref_manifest = lambda path: None
    mark = len(ROUTES)
    counter = Counter()
    counter.n = 1                      # the re-render's first draft passes its composite

    def rerender(v):
        return dress_back()[0]

    record, warnings = base_body._guard_dressed_views(
        "Demo", "sig1", "bsig", {"front": dressed_front, "back": base_png},
        {"front": base_png, "back": base_png}, rerender=rerender)
    check("[8a] front passes first, back re-rendered on entry 2",
          (taken(mark, "outfit_back_turn"), taken(mark, "outfit_back_draft")),
          ([("obt-2", E2, False)], [("obd-2", E2, False)]))
    check("[8a] front kept as it was, back kept after its re-render",
          (record["front"].get("rerendered"), record["back"]["ok"], record["back"].get("rerendered")),
          (None, True, True))

    mark = len(ROUTES)
    checks = Counter()
    base_body.dressed_view_check = lambda v, path, registrations, front=None: {
        "ok": checks.ok(), "reasons": [], "framing": {"ok": True}}
    model3d._ref_manifest = lambda path: {"pieces": {}, "items": []}
    base_body.generate_dressed_images = lambda c, **k: fake_render(
        c, output_stem=work / "rerender_front", occasion="outfit_front")
    base_body.dressed_image = lambda c, v, signature, bsig, fig=None: work / "rerender_front.png"
    record, warnings = base_body._guard_dressed_views(
        "Demo", "sig1", "bsig", {"front": dressed_front}, {"front": base_png}, rerender=None)
    check("[8b] manifest re-render on entry 2", taken(mark), [("of-2", E2, False)])
    check("[8b] front kept", (record["front"]["ok"], record["front"].get("rerendered")), (True, True))

    print("[9] footwear empty shoe")
    from app.core import footwear_gates, footwear_source as fs
    import app.models.character as character_mod
    import app.imagegen.service as service_mod

    class Service:
        def __init__(self, pool):
            self.pool = pool

        def run_on_backend(self, b, op):
            return self.pool.run_on_backend(b, op=op)

        def run_on_backend_channel(self, b, fn, **k):
            return fn()

    def fake_rembg(data, model="u2net", only_mask=False, **_kw):
        with Image.open(io.BytesIO(data)) as im:
            arr = np.asarray(im.convert("RGB"))
        mask = Image.fromarray(np.where(arr.min(-1) < 200, 255, 0).astype(np.uint8), "L")
        buf = io.BytesIO()
        mask.save(buf, format="PNG")
        return buf.getvalue()

    service_mod.get_image_service = lambda: Service(POOL[0])
    character_mod.run_rembg = fake_rembg

    def footwear(chain):
        rules["footwear_empty"] = list(chain)
        for n in ("fw-1", "fw-2"):
            fakes[n].calls.clear()
        d = work / f"shoe_{len(chain)}"
        d.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGB", (1024, 512), (255, 255, 255))
        im.paste((30, 30, 30), (100, 200, 900, 400))
        im.save(d / "upscaled.png")
        gate = Counter()
        footwear_gates.empty_gate = lambda matte, item_matte=None: {
            "ok": gate.ok(), "reasons": [] if gate.n >= 2 else ["stub refusal"]}
        fs._step_empty("item_shoe", "abcdef012345", 0, d)
        return d

    d = footwear(["fw-1", "fw-2"])
    c1, c2 = fakes["fw-1"].calls, fakes["fw-2"].calls
    check("[9a] seeds per backend", ([c["seed"] for c in c1], [c["seed"] for c in c2]), ([1], [2]))
    check("[9a] fw-1 prompt unprefixed (image_tag)", c1[0]["prompt"].startswith("Edit <Picture"), False)
    check("[9a] fw-2 prompt picture_edit prefix", c2[0]["prompt"].startswith("Edit <Picture 1>. "), True)
    try2 = json.loads((d / "empty.try2.json").read_text())
    check("[9a] try2 meta", (try2.get("backend"), (try2.get("routing") or {}).get("position"),
                             try2.get("attempt_entry"), "fallback_from" in try2), ("fw-2", 2, E2, False))
    step = fs._read(d)["steps"]["empty"]
    check("[9a] step record", (step.get("accepted"), step.get("backend"), (step.get("routing") or {}).get("position")),
          (True, "fw-2", 2))
    d = footwear(["fw-1"])
    c1, c2 = fakes["fw-1"].calls, fakes["fw-2"].calls
    check("[9b] single entry: both on fw-1", ([c["seed"] for c in c1], len(c2)), ([1, 2], 0))
    try2 = json.loads((d / "empty.try2.json").read_text())
    check("[9b] clamped entry", (try2.get("attempt_entry"), "fallback_from" in try2),
          ({"attempt": 2, "aimed_position": 1, "position": 1}, False))

    print("[10] nothing outside the chains, no network")
    allowed = {n for chain in CHAINS.values() for n in chain}
    check("[10] backends asked", sorted({r["backend"] for r in ROUTES} - allowed), [])
    check("[10] cloud never asked", fakes["cloud"].calls, [])
    check("[10] sockets", CONNECTS, [])

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
