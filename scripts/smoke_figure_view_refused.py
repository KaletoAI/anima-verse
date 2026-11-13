"""A dressed view whose composite was refused is a cached failure keyed by its
inputs (Ruling FR-I3 of the final review of plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``;
``app/core/base_body.py`` "Refused views"). The plan side — an automatic Build
skips the failed view step, a manual one clears the records and retries once —
is checked in ``scripts/smoke_figure_fit_refused.py`` [5].

Usage:
    ./.venv/bin/python scripts/smoke_figure_view_refused.py

Runs in a temp world (``paths.init(<tmp>)`` before any world-DB import), one
character "Demo", no server, no hub, no network. ``base_body.dressed_views`` is
narrowed to (front, back); ``shape_view`` / ``stored_draft`` are tables for [2].

The rule, derived by hand: the record of view V of signature S holds while V
is not current and its inputs are the same — the sha256 of the dressed front
``tpose_<S>``, the sha256 of the view V of the shape it is composited onto
(``tpose_<V>_<on>``) and ``view_composite.VERSION``. It lives at
``model_refs/drafts/refused/tpose_<V>_<S>.json``.

Files: front ``tpose_S`` = b"front-1", base back ``tpose_back_ON`` = b"back-1".
[1] record_view_refusal(back, S, error "E1") -> refused_views(S, ON) ==
    {back: E1}; the record path is ``drafts/refused/tpose_back_S.json``; with
    the view current -> {}; the front rewritten to b"front-2" -> {} (restored
    -> {back: E1}); the base back rewritten -> {}; restored, VERSION + 1 ->
    {}; restored -> {back: E1}; clear_view_refusals(S) -> {} and the file is
    gone.
[2] The estimate counts a refused view as ONE draft: shape SH with its front
    stored and the back missing, its stored draft following the front
    (``stored_draft`` stub) -> ``shape_view_jobs(SH, ON)`` == 0 (composited
    again, Ruling C2); with a refusal recorded for SH's back -> 1; cleared ->
    0.
[3] The record goes with its signature: ``outfit_cache_gc._ref_files`` lists
    ``drafts/refused/tpose_back_S.json`` under S.
[4] Fails on the old code: at commit 5eab1741 ``base_body.py`` has no
    ``record_view_refusal`` (a refused view was rendered again by every
    automatic Build).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "5eab1741"
S, ON, SH = "aaaabbbbcccc", "base0123abcd", "ob0123456789"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


_TICK = [1_700_000_000_000_000_000]


def write(path: Path, data: bytes) -> None:
    """Write ``data`` with a fresh mtime: the sha256 memo keys on the file's stat, and two writes of the same
    size inside one clock tick would look alike."""
    path.write_bytes(data)
    _TICK[0] += 1_000_000_000
    os.utime(path, ns=(_TICK[0], _TICK[0]))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-view-refused-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config, db
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
        db.init_schema()
        from app.models.character import save_character_profile
        check("create Demo", save_character_profile("Demo", {"template": "human-roleplay", "gender": "female",
                                                             "age": 30, "height": 168}, create_new=True), True)
        from app.core import base_body, outfit_cache_gc, view_composite
        from app.core.model_refs import get_model_refs_dir
        refs = get_model_refs_dir("Demo")
        base_body.dressed_views = lambda: ("front", "back")
        front, base_back = refs / f"tpose_{S}.png", refs / f"tpose_back_{ON}.png"
        write(front, b"front-1")
        write(base_back, b"back-1")
        none = lambda _v: None  # noqa: E731

        print("[1] the record holds for the same inputs only")
        base_body.record_view_refusal("Demo", "back", S, front=front, base_view=base_back, error="E1")
        record = refs / "drafts" / "refused" / f"tpose_back_{S}.json"
        check("record path", record.is_file(), True)
        check("same inputs", base_body.refused_views("Demo", S, ON, current=none), {"back": "E1"})
        check("view current", base_body.refused_views("Demo", S, ON, current=lambda v: front), {})
        write(front, b"front-2")
        check("another front", base_body.refused_views("Demo", S, ON, current=none), {})
        write(front, b"front-1")
        check("front restored", base_body.refused_views("Demo", S, ON, current=none), {"back": "E1"})
        write(base_back, b"back-2")
        check("another base view", base_body.refused_views("Demo", S, ON, current=none), {})
        write(base_back, b"back-1")
        version = view_composite.VERSION
        view_composite.VERSION = version + 1
        try:
            check("another composite version", base_body.refused_views("Demo", S, ON, current=none), {})
        finally:
            view_composite.VERSION = version
        check("all restored", base_body.refused_views("Demo", S, ON, current=none), {"back": "E1"})

        print("[3] the record goes with its signature")
        listed = [p.relative_to(refs).as_posix() for p in outfit_cache_gc._ref_files("Demo").get(S, [])]
        check("listed under S", f"drafts/refused/tpose_back_{S}.json" in listed, True)

        base_body.clear_view_refusals("Demo", S)
        check("cleared", (base_body.refused_views("Demo", S, ON, current=none), record.exists()), ({}, False))

        print("[2] the estimate counts a refused view as one draft")
        shape_front = refs / f"tpose_{SH}.png"
        write(shape_front, b"shape-front")
        base_body.shape_view = lambda _c, view, *_a, **_kw: shape_front if view == "front" else None
        base_body.stored_draft = lambda *_a, **_kw: refs / "drafts" / f"tpose_back_{SH}.png"
        check("draft follows the front: 0", base_body.shape_view_jobs("Demo", SH, ON), 0)
        base_body.record_view_refusal("Demo", "back", SH, front=shape_front, base_view=base_back, error="E2")
        check("refused: 1", base_body.shape_view_jobs("Demo", SH, ON), 1)
        base_body.clear_view_refusals("Demo", SH)
        check("cleared: 0", base_body.shape_view_jobs("Demo", SH, ON), 0)

    print("[4] fails on the old code")
    old = subprocess.run(["git", "show", f"{OLD}:app/core/base_body.py"], cwd=ROOT, capture_output=True, text=True)
    check(f"old code readable at {OLD}", old.returncode, 0)
    check(f"no record_view_refusal at {OLD}", "def record_view_refusal" in old.stdout, False)

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
