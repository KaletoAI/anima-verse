#!/usr/bin/env python3
"""Smoke run for the outfit batch job (app/core/outfit_batch.py).

No test framework, no GPU, no LLM, no queue DB: the inventory store, the mesh
cache probe, the queue peek and the two render calls are monkeypatched, so the
run exercises the REAL enumeration, signing, coherence, counting and worker
code against canned data.

What a batch is today (commit "outfit batch renders COMBINATIONS"): saved
outfit SETS play no role any more. Every outfit piece in the inventory is an
option in the slot it declares FIRST; per slot one piece or nothing, and the
combinations are the cartesian product over the slots. The all-empty
combination is skipped. That is why this file checks ``combo_options`` /
``count_combos`` / ``combo_stats`` / ``_handle_outfit_combos`` and no longer a
per-saved-outfit ``plan()``.

Canned inventory (hand-built, so every number below is derived from it):

    id      first slot         outfit_types          covers
    ------  -----------------  --------------------  -----------------
    blouse  top                business              —
    shirt   top                casual                —
    jeans   bottom             casual                underwear_bottom
    boots   feet               casual, business      —
    cloak   outer (of outer+top)  — (untagged)       —
    boxers  underwear_bottom   intimate              —

Hand-derived expectations
=========================

[1] combo_options groups by FIRST slot, slots sorted, pieces sorted by name:
    bottom [jeans] · feet [boots] · outer [cloak] · top [blouse, shirt] ·
    underwear_bottom [boxers]. ``cloak`` declares outer+top and appears under
    ``outer`` ONLY — the same first-slot rule the wardrobe uses.

[2] count_combos is ARITHMETIC. Unfiltered every slot gets [None, *pieces],
    so 2 * 2 * 2 * 3 * 2 = 48; every slot may stay empty, so the all-empty
    combination is reachable and subtracted: 47.
    With top pinned to ["shirt"] (no None) it is 2 * 2 * 2 * 1 * 2 = 16 and
    nothing is subtracted — 16.

[3] The signature is md5(…)[:12] over the VISIBLE pieces, slots sorted.
    Therefore: order-independent, and jeans+boxers signs IDENTICALLY to jeans
    alone, because jeans ``covers`` underwear_bottom and a piece nobody sees
    cannot change the render. That collapse is the whole point of the cache.
    It is ONE rule with the worn state (``model_refs.outfit_signature``), and
    the empty combination is where that matters: a character dressed by prose
    only (``outfit_description``, a temporary NPC) is NOT naked, so its empty
    combination must key on that text, not on md5(""). Hand-derived for the
    line "a grey linen apron": ``render_outfit(...)["full"]`` reads
    "wearing: a grey linen apron", md5 of which is
    3bdb2ee2463ced85c866bb4320b425ad -> "3bdb2ee2463c", and that is exactly
    what ``current_outfit_state`` reports for the worn state. Keyed the old
    way the batch would file the pre-warmed render under md5("")[:12] =
    "d41d8cd98f00" while the world looks for "3bdb2ee2463c" — cache miss,
    second render, and the GC calls the batch's own entry stale. A character
    with no outfit text at all keeps "d41d8cd98f00".

[4] Coherence (visible pieces must share a tag; untagged = wildcard;
    underwear only judges itself when nothing else is visible):
        shirt + jeans        casual ∩ casual        -> coherent
        blouse + jeans       business ∩ casual = ∅  -> INCOHERENT
        blouse + boots       business ∩ {c,b}       -> coherent
        blouse + jeans + cloak  cloak is a wildcard, business ∩ casual = ∅
                                                    -> INCOHERENT
        jeans + boxers       boxers is covered      -> coherent
        boxers alone         underwear judges itself-> coherent
        cloak alone          nothing tagged         -> coherent

[5] combo_stats, filter A = feet/outer/underwear_bottom pinned empty:
        choices bottom[None,jeans] top[None,blouse,shirt] -> 2*3 = 6, -1 = 5
        the five: {blouse} {shirt} {jeans} {jeans,blouse} {jeans,shirt}
        {jeans,blouse} is incoherent -> 4 survive, all 4 signatures distinct
        coherent_only=True  -> total 4, missing 4
        coherent_only=False -> total 5 (arithmetic), missing 5

[6] combo_stats, filter B = feet/outer/top pinned empty (the collapse case):
        choices bottom[None,jeans] underwear_bottom[None,boxers] -> 4, -1 = 3
        the three: {boxers} {jeans} {jeans,boxers}
        all three are coherent, but {jeans,boxers} signs as {jeans}
        -> only 2 UNIQUE signatures
        coherent_only=True  -> total 2, missing 2
        coherent_only=False -> total 3 (arithmetic!), missing 2
        with the jeans mesh already cached -> missing 1
        force=True ignores the cache      -> missing 2

[7] est_seconds = missing * (average of the last mesh durations + 60 s
    T-pose allowance); with no history at all the fallback is 240 s/combo.
        durations [] -> 240.0        -> 2 missing = 480.0
        durations [100, 140] -> 120 + 60 = 180.0 -> 2 missing = 360.0

[8] Above MAX_EXACT_COMBOS nothing is enumerated: the arithmetic total is
    reported as an upper bound, missing == total, and both _exact flags say
    so (total_exact is False only because the coherence filter is on).

[9] The worker on filter B, empty cache, coherent_only=True:
        product order is bottom-outermost, so the combinations arrive as
        {boxers} -> {jeans} -> {jeans,boxers}
        the third one signs like the second, which is cached BY THEN
        -> total 3, rendered 2, skipped 1, failed 0
    Every render gets kinds=("tpose",) and items=[] — carried items are
    deliberately out of scope.
    The skip is driven by what actually LANDED in the cache, so when the
    jeans mesh FAILS the collapsed twin is attempted rather than skipped:
    3 rendered, 2 failed, 0 skipped. A cache hit that does not exist must
    never hide a failure.

Usage:  ./.venv/bin/python scripts/smoke_outfit_batch.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="outfit-batch-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import model3d, model_refs, outfit_batch, task_queue  # noqa: E402
from app.core.outfit_coherence import is_coherent  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

CHAR = "demo"
#: A second character, dressed by free text instead of by wardrobe pieces.
DRESSED = "npc-in-prose"
#: md5("")[:12] — the key of a character wearing nothing at all.
EMPTY_MD5 = "d41d8cd98f00"
FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def eq(label: str, actual, expected) -> None:
    check(label, actual == expected,
          f"{actual!r}" if actual == expected else f"{actual!r} != {expected!r}")


# ── Canned stores ───────────────────────────────────────────────────────

ITEMS = {
    "blouse": {"name": "Blouse", "slots": ["top"],
               "types": ["business"], "covers": []},
    "shirt":  {"name": "Shirt", "slots": ["top"],
               "types": ["casual"], "covers": []},
    # Trousers swallow the underwear slot — that is what makes two different
    # combinations one render.
    "jeans":  {"name": "Jeans", "slots": ["bottom"],
               "types": ["casual"], "covers": ["underwear_bottom"]},
    "boots":  {"name": "Boots", "slots": ["feet"],
               "types": ["casual", "business"], "covers": []},
    # Multi-slot: declared outer+top, offered under "outer" only. Untagged,
    # so it is a coherence wildcard.
    "cloak":  {"name": "Cloak", "slots": ["outer", "top"],
               "types": [], "covers": []},
    "boxers": {"name": "Boxers", "slots": ["underwear_bottom"],
               "types": ["intimate"], "covers": []},
}

#: Set to {} to play "this character owns nothing".
OWNED = dict(ITEMS)


def _item(item_id: str):
    spec = ITEMS.get(item_id)
    if not spec:
        return None
    return {"id": item_id, "item_name": spec["name"],
            "outfit_piece": {"slots": list(spec["slots"]),
                             "outfit_types": list(spec["types"]),
                             "covers": list(spec["covers"])}}


def install_stores() -> None:
    inventory.get_item = _item
    inventory.get_character_inventory = lambda name: {
        "inventory": [
            {"item_id": iid, "item_name": spec["name"],
             "item_category": "outfit_piece",
             "outfit_piece": {"slots": list(spec["slots"])}}
            for iid, spec in sorted(OWNED.items())
        ] if name == CHAR else []}


# Signatures that already have a mesh / a T-pose render.
HAVE_MESH: set = set()
HAVE_REF: set = set()

# What the patched queue peek answers with.
QUEUE_ROWS: list = []
DURATIONS: list = []


def fake_query_tasks(sql, params=()):
    if "duration_s" in sql:
        return [{"duration_s": v} for v in DURATIONS]
    return list(QUEUE_ROWS)


class FakeQueue:
    """The queue the worker and start() see — no DB behind it."""

    def __init__(self):
        self.submitted = []
        self.cancelled = []
        self.submit_result = "task-42"
        self.cancel_after = -1   # -1 = never cancel
        self.cancel_calls = 0

    def submit(self, **kw):
        self.submitted.append(kw)
        return self.submit_result

    def cancel_task(self, task_id):
        self.cancelled.append(task_id)
        return True

    def is_task_cancelled(self, task_id):
        self.cancel_calls += 1
        return 0 <= self.cancel_after < self.cancel_calls


QUEUE = FakeQueue()


def install_patches() -> None:
    outfit_batch._query_tasks = fake_query_tasks
    outfit_batch._mesh_signatures = lambda name: set(HAVE_MESH)
    task_queue.get_task_queue = lambda: QUEUE


def sig(pieces: dict, character_name: str = CHAR) -> str:
    return outfit_batch._signature(pieces, character_name)


ALL_EMPTY = {"bottom": [None], "feet": [None], "outer": [None],
             "top": [None], "underwear_bottom": [None]}
# feet / outer / underwear_bottom pinned empty — only bottom and top vary.
FILTER_A = {"feet": [None], "outer": [None], "underwear_bottom": [None]}
# feet / outer / top pinned empty — bottom and underwear_bottom vary.
FILTER_B = {"feet": [None], "outer": [None], "top": [None]}
# Only the multi-slot piece, in its first slot.
FILTER_CLOAK = {"bottom": [None], "feet": [None], "top": [None],
                "underwear_bottom": [None], "outer": ["cloak"]}


# ── 1. Options ──────────────────────────────────────────────────────────

def test_options() -> None:
    print("\n[1] combo_options(): every piece in the slot it declares FIRST")
    opts = outfit_batch.combo_options(CHAR)
    eq("slots are sorted", list(opts),
       ["bottom", "feet", "outer", "top", "underwear_bottom"])
    eq("pieces are sorted by name", [p["item_id"] for p in opts["top"]],
       ["blouse", "shirt"])
    eq("the multi-slot piece sits in its first slot",
       [p["item_id"] for p in opts["outer"]], ["cloak"])
    check("...and nowhere else",
          "cloak" not in [p["item_id"] for p in opts["top"]])
    eq("names travel with the ids", opts["bottom"][0],
       {"item_id": "jeans", "name": "Jeans"})

    global OWNED
    OWNED = {}
    eq("an empty inventory has no options", outfit_batch.combo_options(CHAR), {})
    OWNED = dict(ITEMS)


# ── 2. Filter resolution and counting ───────────────────────────────────

def test_counting() -> None:
    print("\n[2] _resolve_filter() + count_combos(): arithmetic, never a list")
    opts = outfit_batch.combo_options(CHAR)

    choices, err = outfit_batch._resolve_filter(opts, None)
    eq("no filter -> no error", err, "")
    eq("every slot keeps 'empty' plus its pieces",
       {s: len(v) for s, v in choices.items()},
       {"bottom": 2, "feet": 2, "outer": 2, "top": 3, "underwear_bottom": 2})
    check("'empty' comes first", all(v[0] is None for v in choices.values()))
    eq("2*2*2*3*2 = 48, minus the all-empty one",
       outfit_batch.count_combos(choices), 47)

    pinned, err = outfit_batch._resolve_filter(opts, {"top": ["shirt"]})
    eq("a pinned slot loses its 'empty' option", pinned["top"], ["shirt"])
    eq("2*2*2*1*2 = 16, nothing subtracted",
       outfit_batch.count_combos(pinned), 16)

    empty, _ = outfit_batch._resolve_filter(opts, ALL_EMPTY)
    eq("every slot empty leaves no combination at all",
       outfit_batch.count_combos(empty), 0)
    eq("no choices at all is zero", outfit_batch.count_combos({}), 0)

    print("\n[2b] a filter that cannot be honoured is REFUSED, not trimmed")
    eq("an empty option list",
       outfit_batch._resolve_filter(opts, {"top": []})[1],
       "slot 'top': at least one option must stay selected")
    eq("an unknown piece",
       outfit_batch._resolve_filter(opts, {"top": ["hat"]})[1],
       "slot 'top': unknown piece 'hat'")
    eq("an unknown slot",
       outfit_batch._resolve_filter(opts, {"hat": ["cloak"]})[1],
       "unknown slot 'hat'")
    eq("a wrong-typed entry",
       outfit_batch._resolve_filter(opts, {"top": "shirt"})[1],
       "slot 'top': at least one option must stay selected")


# ── 3. Signature ────────────────────────────────────────────────────────

def test_signature() -> None:
    print("\n[3] _signature(): the cache key of a combination")
    s = sig({"top": "shirt", "bottom": "jeans"})
    eq("12 hex characters", (len(s), all(c in "0123456789abcdef" for c in s)),
       (12, True))
    eq("slot order does not matter", sig({"bottom": "jeans", "top": "shirt"}), s)
    eq("stable across calls", sig({"top": "shirt", "bottom": "jeans"}), s)
    check("different pieces, different key", sig({"top": "blouse"}) != sig({"top": "shirt"}))
    check("different slots, different key",
          len({sig({"top": "shirt"}), sig({"bottom": "jeans"}),
               sig({"feet": "boots"})}) == 3)

    print("  a covered piece cannot change the picture:")
    eq("jeans + boxers signs exactly like jeans",
       sig({"bottom": "jeans", "underwear_bottom": "boxers"}),
       sig({"bottom": "jeans"}))
    check("...but boxers on their own do not",
          sig({"underwear_bottom": "boxers"}) != sig({"bottom": "jeans"}))

    print("  the empty combination of a free-text character:")
    # A character dressed by prose only (a temporary NPC): the batch must key
    # its empty combination the way the WORN state keys it, or the pre-warmed
    # entry and the entry the world looks for are two different files —
    # cache miss, second render, and a GC that reports the batch's own entry
    # stale (warm/purge/warm, one GPU render per cycle).
    save_character_profile(DRESSED, {"character_name": DRESSED,
                                     "template": "npc-temporary",
                                     "outfit_description": "a grey linen apron",
                                     "outfit_worn": True}, create_new=True)
    worn = model_refs.current_outfit_state(DRESSED)[2]
    eq("the empty combination keys exactly like the worn state",
       sig({}, DRESSED), worn)
    # By hand: md5("wearing: a grey linen apron")[:12] — NOT md5("")[:12].
    eq("and that key is the outfit LINE, not the naked default",
       (worn, worn == EMPTY_MD5), ("3bdb2ee2463c", False))
    eq("a character with no outfit text keeps the historical naked key",
       sig({}, "nobody-at-all"), EMPTY_MD5)


# ── 4. Coherence ────────────────────────────────────────────────────────

def test_coherence() -> None:
    print("\n[4] the coherence filter the enumeration applies")
    check("shirt + jeans (casual ∩ casual)",
          is_coherent({"top": "shirt", "bottom": "jeans"}))
    check("blouse + jeans (business ∩ casual = ∅) is refused",
          not is_coherent({"top": "blouse", "bottom": "jeans"}))
    check("blouse + boots (boots are both)",
          is_coherent({"top": "blouse", "feet": "boots"}))
    check("an untagged wildcard rescues nothing",
          not is_coherent({"top": "blouse", "bottom": "jeans",
                           "outer": "cloak"}))
    check("the cloak alone is fine (nothing tagged to judge by)",
          is_coherent({"outer": "cloak"}))
    check("jeans + boxers — the covered piece cannot clash",
          is_coherent({"bottom": "jeans", "underwear_bottom": "boxers"}))
    check("boxers alone judge themselves",
          is_coherent({"underwear_bottom": "boxers"}))

    print("\n[4b] _iter_combos() honours it, lazily")
    opts = outfit_batch.combo_options(CHAR)
    choices, _ = outfit_batch._resolve_filter(opts, FILTER_A)
    raw = list(outfit_batch._iter_combos(choices))
    kept = list(outfit_batch._iter_combos(choices, coherent_only=True))
    eq("five non-empty combinations", len(raw), 5)
    eq("the incoherent one is dropped", len(kept), 4)
    check("...and it is exactly blouse+jeans",
          {"top": "blouse", "bottom": "jeans"} in raw
          and {"top": "blouse", "bottom": "jeans"} not in kept)
    check("the all-empty combination is never yielded",
          all(c for c in raw))
    check("it is a generator, not a list",
          hasattr(outfit_batch._iter_combos(choices), "__next__"))

    print("\n[4c] _combo_label(): slot-sorted, empty slots absent")
    names = {p["item_id"]: p["name"]
             for bucket in opts.values() for p in bucket}
    eq("two pieces", outfit_batch._combo_label(
        {"top": "shirt", "bottom": "jeans"}, names), "bottom: Jeans · top: Shirt")
    eq("nothing at all", outfit_batch._combo_label({}, names), "(nothing)")


# ── 5./6./7./8. Stats ───────────────────────────────────────────────────

def test_stats() -> None:
    global DURATIONS
    DURATIONS = []
    HAVE_MESH.clear()

    print("\n[5] combo_stats() on filter A — coherence changes the total")
    st = outfit_batch.combo_stats(CHAR, FILTER_A, coherent_only=True)
    eq("4 coherent combinations", st["total"], 4)
    eq("all 4 are missing", st["missing"], 4)
    eq("both counts are exact", (st["total_exact"], st["missing_exact"]),
       (True, True))
    eq("no error", st["error"], "")
    raw = outfit_batch.combo_stats(CHAR, FILTER_A, coherent_only=False)
    eq("without the filter the arithmetic total is 5", raw["total"], 5)
    eq("...and all 5 are missing", raw["missing"], 5)

    print("\n[6] combo_stats() on filter B — the covered piece collapses")
    st = outfit_batch.combo_stats(CHAR, FILTER_B, coherent_only=True)
    eq("3 combinations, 2 renders", (st["total"], st["missing"]), (2, 2))
    raw = outfit_batch.combo_stats(CHAR, FILTER_B, coherent_only=False)
    eq("the arithmetic total still counts 3", raw["total"], 3)
    eq("...but 'missing' counts SIGNATURES, so 2", raw["missing"], 2)

    HAVE_MESH.add(sig({"bottom": "jeans"}))
    cached = outfit_batch.combo_stats(CHAR, FILTER_B, coherent_only=True)
    eq("a cached mesh removes its combination", cached["missing"], 1)
    forced = outfit_batch.combo_stats(CHAR, FILTER_B, force=True,
                                      coherent_only=True)
    eq("force ignores the cache", forced["missing"], 2)
    HAVE_MESH.clear()

    print("\n[7] est_seconds = missing * (mesh average + 60 s T-pose)")
    eq("no history -> the 240 s fallback",
       outfit_batch.estimate_seconds_per_combo(), 240.0)
    eq("2 missing * 240 s",
       outfit_batch.combo_stats(CHAR, FILTER_B,
                                coherent_only=True)["est_seconds"], 480.0)
    DURATIONS = [100.0, 140.0]
    eq("avg 120 + 60", outfit_batch.estimate_seconds_per_combo(), 180.0)
    eq("2 missing * 180 s",
       outfit_batch.combo_stats(CHAR, FILTER_B,
                                coherent_only=True)["est_seconds"], 360.0)
    DURATIONS = []

    print("\n[8] above MAX_EXACT_COMBOS nothing is enumerated")
    original = outfit_batch.MAX_EXACT_COMBOS
    try:
        outfit_batch.MAX_EXACT_COMBOS = 2
        big = outfit_batch.combo_stats(CHAR, FILTER_B, coherent_only=True)
        eq("the arithmetic total is the upper bound", big["total"], 3)
        eq("missing == total by assumption", big["missing"], 3)
        eq("and it says so", (big["total_exact"], big["missing_exact"]),
           (False, False))
    finally:
        outfit_batch.MAX_EXACT_COMBOS = original

    print("\n[8b] a refused filter comes back as an error, not as zero work")
    bad = outfit_batch.combo_stats(CHAR, {"top": ["hat"]})
    eq("the message travels", bad["error"], "slot 'top': unknown piece 'hat'")
    eq("...with everything zeroed", (bad["total"], bad["missing"]), (0, 0))


# ── 9. The worker ───────────────────────────────────────────────────────

def run_worker(slots, coherent_only=True, force=False, ref_fails=(),
               mesh_fails=(), cancel_after=-1):
    """Runs _handle_outfit_combos with stubbed renders.

    Returns (result, ref_calls, mesh_calls).
    """
    ref_calls, mesh_calls = [], []

    def fake_refs(name, kinds=None, force=False, *, pieces=None, items=None,
                  signature=None):
        ref_calls.append({"character": name, "signature": signature,
                          "pieces": dict(pieces or {}), "items": list(items or []),
                          "kinds": kinds, "force": force})
        if signature not in ref_fails:
            HAVE_REF.add(signature)
        return {}

    def fake_find_ref(name, kind, signature=None):
        return Path(f"/fake/{kind}_{signature}.png") if signature in HAVE_REF else None

    def fake_mesh(name, *, force=False, signature=None, **kw):
        mesh_calls.append({"signature": signature, "force": force})
        if signature in mesh_fails:
            return {"ok": False, "error": "backend exploded"}
        HAVE_MESH.add(signature)
        return {"ok": True, "cached": False, "path": f"/fake/{signature}.glb"}

    model_refs.generate_model_ref_images = fake_refs
    model_refs.find_ref_image = fake_find_ref
    model3d.generate_for_current_outfit = fake_mesh
    QUEUE.cancel_after = cancel_after
    QUEUE.cancel_calls = 0

    opts = outfit_batch.combo_options(CHAR)
    choices, err = outfit_batch._resolve_filter(opts, slots)
    if err:
        raise AssertionError(err)
    res = outfit_batch._handle_outfit_combos({
        "character": CHAR,
        "slots": {s: list(v) for s, v in choices.items()},
        "force": force, "coherent_only": coherent_only,
        "_task_id": "task-42"})
    HAVE_REF.clear()
    return res, ref_calls, mesh_calls


def test_worker() -> None:
    HAVE_MESH.clear()

    print("\n[9] the worker on filter B: render, then skip the collapse")
    res, refs, meshes = run_worker(FILTER_B)
    eq("total counts combinations, not renders", res["total"], 3)
    eq("two were rendered", res["rendered"], 2)
    eq("the third one was already cached by its twin", res["skipped"], 1)
    eq("nothing failed", res["failed"], 0)
    eq("not cancelled", res["cancelled"], False)
    eq("the order is boxers, then jeans",
       [m["signature"] for m in meshes],
       [sig({"underwear_bottom": "boxers"}), sig({"bottom": "jeans"})])
    eq("reference and mesh always share the signature",
       [r["signature"] for r in refs], [m["signature"] for m in meshes])
    check("only the T-pose is rendered",
          all(r["kinds"] == ("tpose",) for r in refs), str(refs[0]["kinds"]))
    check("carried items stay out of it", all(r["items"] == [] for r in refs))
    eq("the pieces arrive slot-mapped", refs[1]["pieces"], {"bottom": "jeans"})

    print("\n[9b] a second run finds everything cached")
    res, refs, meshes = run_worker(FILTER_B)
    eq("nothing rendered", res["rendered"], 0)
    eq("everything skipped", res["skipped"], 3)
    check("no render was even attempted", not refs and not meshes)
    HAVE_MESH.clear()

    print("\n[9c] force re-renders regardless of the cache")
    HAVE_MESH.update({sig({"bottom": "jeans"}),
                      sig({"underwear_bottom": "boxers"})})
    res, refs, meshes = run_worker(FILTER_B, force=True)
    eq("all three combinations run", res["rendered"], 3)
    eq("nothing is skipped", res["skipped"], 0)
    check("force is passed down to both stages",
          all(r["force"] for r in refs) and all(m["force"] for m in meshes))
    HAVE_MESH.clear()

    print("\n[10] the multi-slot piece renders in its FIRST slot")
    res, refs, _ = run_worker(FILTER_CLOAK)
    eq("exactly one combination", res["total"], 1)
    eq("cloak lands in 'outer', not 'top'", refs[0]["pieces"], {"outer": "cloak"})
    HAVE_MESH.clear()

    print("\n[11] a broken combination does not end the batch")
    boxers_sig = sig({"underwear_bottom": "boxers"})
    jeans_sig = sig({"bottom": "jeans"})
    res, refs, meshes = run_worker(FILTER_B, ref_fails=(boxers_sig,))
    eq("both were attempted", res["rendered"], 2)
    eq("one of them failed", res["failed"], 1)
    check("no mesh ran without its T-pose input",
          boxers_sig not in [m["signature"] for m in meshes])
    check("the one after it still ran", jeans_sig in [m["signature"] for m in meshes])
    status = outfit_batch.get_status(CHAR)
    results = {r["signature"]: r for r in status["results"]}
    eq("the missing T-pose is reported",
       results[boxers_sig]["error"], "T-pose render failed")
    check("the good one is marked ok", results[jeans_sig]["ok"])
    HAVE_MESH.clear()

    # A FAILED mesh is not added to the cache set, so the combination that
    # collapses onto the same signature ({jeans, boxers}) is not skipped —
    # it gets its own attempt and fails as well. Both are reported: 3
    # rendered, 2 failed, nothing skipped. That is the honest behaviour;
    # skipping the twin would hide a failure behind a cache hit that does
    # not exist.
    res, _, meshes = run_worker(FILTER_B, mesh_fails=(jeans_sig,))
    eq("the twin of a FAILED render is attempted, not skipped",
       (res["rendered"], res["skipped"]), (3, 0))
    eq("both attempts are counted as failures", res["failed"], 2)
    eq("...and both hit the same signature",
       [m["signature"] for m in meshes].count(jeans_sig), 2)
    status = outfit_batch.get_status(CHAR)
    results = {r["signature"]: r for r in status["results"]}
    check("...and the message travels",
          "exploded" in results[jeans_sig]["error"], results[jeans_sig]["error"])
    HAVE_MESH.clear()

    print("\n[12] cancellation stops BETWEEN combinations")
    res, _, meshes = run_worker(FILTER_B, cancel_after=1)
    eq("the batch reports itself cancelled", res["cancelled"], True)
    eq("the running combination finished", res["rendered"], 1)
    eq("nothing after it started", len(meshes), 1)
    check("the job is not running any more",
          not outfit_batch.get_status(CHAR)["running"])
    HAVE_MESH.clear()

    print("\n[13] the status record")
    run_worker(FILTER_B)
    st = outfit_batch.get_status(CHAR)
    eq("total / done / skipped survive the run",
       (st["total"], st["done"], st["skipped"]), (3, 2, 1))
    check("it carries a start and an end stamp",
          bool(st["started_at"]) and bool(st["finished_at"]))
    check("nothing is 'current' any more", st["current"] is None)
    eq("a character that never ran is idle",
       outfit_batch.get_status("nobody")["running"], False)
    check("a snapshot cannot be mutated from outside",
          outfit_batch.get_status(CHAR)["results"]
          is not outfit_batch.get_status(CHAR)["results"])
    HAVE_MESH.clear()

    print("\n[13b] a filter the payload cannot honour raises, it does not run")
    try:
        outfit_batch._handle_outfit_combos({"character": CHAR,
                                            "slots": {"hat": ["cloak"]}})
        check("a bad payload filter raises", False, "no exception")
    except ValueError as e:
        eq("a bad payload filter raises", str(e), "unknown slot 'hat'")


# ── 14. start() / stop() ────────────────────────────────────────────────

def test_start_stop() -> None:
    global OWNED
    HAVE_MESH.clear()
    QUEUE_ROWS.clear()

    print("\n[14] start(): one low-priority queue task, guarded")
    QUEUE.submitted.clear()
    res = outfit_batch.start(CHAR, FILTER_B, coherent_only=True)
    eq("it is accepted", res["ok"], True)
    eq("the task id comes back", res["task_id"], "task-42")
    eq("with the numbers the dialog showed",
       (res["total"], res["missing"]), (2, 2))
    job = QUEUE.submitted[0]
    eq("one persistent task of the batch type", job["task_type"], "outfit_combos")
    eq("at the low priority", job["priority"], outfit_batch.PRIORITY_LOW)
    eq("never retried", job["max_retries"], 0)
    eq("owned by the character", job["agent_name"], CHAR)
    eq("the resolved filter travels IN the payload",
       job["payload"]["slots"]["underwear_bottom"], [None, "boxers"])
    eq("...and so does the coherence flag",
       job["payload"]["coherent_only"], True)

    print("\n[14b] the guards")
    eq("a filter that yields nothing",
       outfit_batch.start(CHAR, ALL_EMPTY),
       {"ok": False, "error": "the filter yields no combination"})
    eq("a refused filter",
       outfit_batch.start(CHAR, {"top": []}),
       {"ok": False, "error": "slot 'top': at least one option must stay selected"})

    QUEUE_ROWS.append({"task_id": "t-1", "status": "pending"})
    eq("a second start while one is queued",
       outfit_batch.start(CHAR, FILTER_B),
       {"ok": False, "error": "already running"})
    QUEUE_ROWS.clear()

    QUEUE.submit_result = ""
    eq("a queue that refuses the task",
       outfit_batch.start(CHAR, FILTER_B),
       {"ok": False, "error": "queue rejected the task"})
    QUEUE.submit_result = "task-42"

    OWNED = {}
    eq("a character with no outfit pieces at all",
       outfit_batch.start(CHAR, None),
       {"ok": False, "error": "no outfit pieces in this inventory"})
    OWNED = dict(ITEMS)

    print("\n[15] queue_state() / stop() read the QUEUE, not memory")
    eq("nothing queued", outfit_batch.queue_state(CHAR),
       {"state": "none", "task_id": ""})
    check("stopping an idle character is a no-op",
          outfit_batch.stop(CHAR) is False)
    QUEUE_ROWS.append({"task_id": "t-7", "status": "running"})
    eq("a running batch is visible", outfit_batch.queue_state(CHAR),
       {"state": "running", "task_id": "t-7"})
    QUEUE.cancelled.clear()
    check("stop() cancels exactly that task",
          outfit_batch.stop(CHAR) is True and QUEUE.cancelled == ["t-7"],
          str(QUEUE.cancelled))
    QUEUE_ROWS.clear()


def main() -> int:
    install_stores()
    install_patches()
    test_options()
    test_counting()
    test_signature()
    test_coherence()
    test_stats()
    test_worker()
    test_start_stop()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
