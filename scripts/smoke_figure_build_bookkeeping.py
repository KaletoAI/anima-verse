#!/usr/bin/env python3
"""Figure Build bookkeeping (bug round 2026-11-20, cluster 1): the assembly records the figure it delivered, a
piece that failed in this Build is never silently left off a published figure, the own-mesh pieces come before the
template drapes, and a worn-open template piece keeps its own change row.

Usage:
    ./.venv/bin/python scripts/smoke_figure_build_bookkeeping.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no Blender, no server. The planner and
the runner are driven with stubbed producers; [4] writes real sidecar files into the throwaway directory.

Fixture: character "Demo", outfit signature ``sig1``, plain body ``base1`` (shape = bsig, texture ``tex1``). Pieces:
``boots`` (own mesh), ``trousers`` (template), ``blazer`` (template, worn open).

Expected, by hand:

[1] ``plan`` with the boots' chain due (``_chain_step`` → a ``pieces`` step) and the trousers' drape due
    (``_template_step`` → a ``template`` step), nothing else due, the built figure == the delivered one:
    the order is ``STEP_ORDER``'s — pieces, template, then the fits (an own-mesh piece is worn and a pieces step
    is in the work → "Fits on the CPU") and assemble (work is planned) → names
    ``["pieces", "template", "fits", "assemble"]``. Before the fix the template loop ran first:
    ``["template", "pieces", "fits", "assemble"]`` (the trousers draped without the boot's fit, A237).
[2] ``_run_planned`` (manual unless said) over stubbed runners that record their calls. A failure is "recorded"
    when the re-judged step (``_chain_step`` / ``_template_step``, stubbed from the set ``recorded``) is "failed —
    Retry"; the runner's failure puts the piece into ``recorded`` unless the case says it records nothing:
    (a) steps pieces(boots), template(trousers), assemble; the boots' chain FAILS on its first try (``Step.failed``
        "") and records it → calls ``["pieces", "template"]``, ``skipped == ["assemble"]``, ``failed`` has
        ``pieces``.
    (b) the same, but the plan listed the boots' chain as a cached failure (``failed`` "mesh refused", a manual
        Build retries it) and it fails again → the figure is assembled without it: calls
        ``["pieces", "template", "assemble"]``, ``skipped == []``.
    (c) the trousers' drape fails on its first try (recorded) → calls ``["pieces", "template"]``, ``skipped ==
        ["assemble"]``.
    (e) review fix: a failure that records NOTHING — a drape left due (timeout / interrupted / no Blender), a drape
        held by the retry budget, a chain deferred by load or the media switch — never holds the assembly (it would
        hold every Build): the trousers' drape fails unrecorded → ``["pieces", "template", "assemble"]``,
        ``skipped == []``, ``failed`` ``["template"]``; the boots' chain deferred unrecorded → the same calls,
        ``failed`` ``["pieces"]``. Before the fix (9ae6530d8) both gave ``["pieces", "template"]`` with
        ``skipped == ["assemble"]``, on every Build.
    (f) review fix: an AUTOMATIC run never holds the assembly — nothing re-runs a recorded failure automatically
        (ruling 7a), so it assembles without the piece (Ruling A119): the trousers' drape fails on its first try
        and records it → ``["pieces", "template", "assemble"]``, ``skipped == []``. Before the fix (9ae6530d8):
        ``["pieces", "template"]``, ``skipped == ["assemble"]``.
    (d) steps pieces(boots), assemble; after the pieces the trousers' drape key moved (``_template_step`` now
        returns a step) → the run drapes it right after the pieces: calls ``["pieces", "template", "assemble"]``,
        the template call for ``trousers``. With nothing due (``_template_step`` None) → ``["pieces",
        "assemble"]``. In an AUTOMATIC run a drape that is a cached failure is not added (``_runnable``) →
        ``["pieces", "assemble"]``.
[3] ``figure._open_mesh_missing``: the blazer worn open, in ``own`` and ``template``, left out with
    "Drape failed: stretch_max 1.8 (limit 1.3)" → ``{}`` (its change row keeps the drape reason); the same piece
    as a plain own-mesh piece (not in ``template``) → ``{"blazer": "left_out"}``; an accessory worn open →
    ``{}``.
[4] ``base_body.record_delivered_figure`` on a stored outfit model ``sig1`` whose sidecar records the trousers
    left out ("Not draped yet") and ``mesh_items.intended`` [boots, trousers], with a current assembly
    (``bare_revision`` == the bare file's), ``figure_stale`` "" (same shape/texture): the delivered figure has
    both in ``own`` → ``{"rewritten": True, "intended_changed": False}`` (intended stays [boots, trousers]); the
    bare sidecar's ``figure`` == the delivered ``as_dict()``, its ``mesh_items`` == ``mesh_record``: intended =
    effective = unpainted = [boots, trousers], missing {}; the assembly sidecar carries the same ``figure`` and the
    NEW ``bare_revision`` (still current, no rebuild). A second call → ``rewritten`` False (already recorded).
    ``figure_stale`` "figure" → False and the sidecar unchanged. A figure of another signature → False.
    The bare sidecar's ``garment_warnings`` (``["Not fitted on this outfit body, served without: boots (fit
    refused)"]`` — a fact of the model and body, not of the record) are kept by the rewrite; before the review fix
    (9ae6530d8) they were removed while the assembly sidecar kept them, so the overview showed them as the
    assembly's own.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-build-bookkeeping-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import base_body, figure, figure_build as fb, garment_assembly, garment_refit, model3d

        def fig(**kw):
            base = dict(signature="sig1", bsig="base1", shape="base1", texture="tex1", in_body=(), own=(),
                        pieces={"feet": "boots", "bottom": "trousers"})
            base.update(kw)
            return figure.Figure(**base)

        wanted = fig(own=("boots", "trousers"), template=("trousers",))
        delivered = fig(own=("boots",), template=(), left_out={"trousers": "Not draped yet"})

        print("[1] plan order: own-mesh pieces before the template drapes")
        base_body.is_base_pipeline = lambda *_a, **_kw: True
        base_body.base_refresh_plan = lambda *_a, **_kw: {}
        base_body.dressed_view_jobs = lambda: 0
        figure.is_plain = lambda _shape: True
        fb._mesh_repair_due = fb._tip_smoothing_due = lambda *_a: False
        fb._model_figure = lambda *_a: delivered
        fb._template_step = lambda c, i, d, p: fb.Step("template", f"Template drape · {i}", 0, i)
        fb._chain_step = lambda c, n, i, label, p: fb.Step(n, label, 0, i)
        fb._assemble_held = lambda *_a: None
        fb._views_missing = lambda *_a: False
        fb._collision_due = lambda _c: False
        garment_refit.work_count = lambda *_a, **_kw: 0
        steps = fb.plan("Demo", profile={"x": 1}, resolved=(wanted, delivered))
        check("[1] step names", [s.name for s in steps], ["pieces", "template", "fits", "assemble"])
        check("[1] items", [s.item_id for s in steps[:2]], ["boots", "trousers"])

        print("[2] the run: a piece that failed in this Build holds the assembly; templates re-checked")
        calls = []
        outcome = {}

        def runner(name):
            def run(_c, step, _explicit=False):
                calls.append((name, step.item_id))
                error = outcome.get((name, step.item_id), "")
                if error and record_failure["on"]:
                    recorded.add(step.item_id)
                return error
            return run

        fb._RUNNERS.update({n: runner(n) for n in ("pieces", "template", "assemble", "fits")})
        fb.base_step_in_flight = lambda _c: ""
        fb._tracked = lambda *_a: (None, "")
        fb._base_snapshot = lambda _c: None
        fb._base_changed = lambda *_a: []
        fb._check_pin = lambda _c: None
        fb._pin = lambda *_a: None
        figure._delivered = lambda *_a, **_kw: (wanted, delivered)
        planned = []
        fb.plan = lambda *_a, **_kw: list(planned)
        due_after = {"step": None}
        fb._now = lambda _c: ({}, wanted, delivered, [])
        recorded = set()
        record_failure = {"on": True}

        def template_step(c, i, d, p):
            if i in recorded:
                return fb.Step("template", f"Template drape · {i}" + fb.FAILED_SUFFIX, 0, i, failed="stretch")
            return due_after["step"]

        def chain_step(c, n, i, label, p):
            if i in recorded:
                return fb.Step(n, label + fb.FAILED_SUFFIX, 0, i, failed="mesh refused")
            return fb.Step(n, label, 0, i)

        fb._template_step = template_step
        fb._chain_step = chain_step

        def run(steps_, fail=None, automatic=False, records=True):
            calls.clear()
            recorded.clear()
            record_failure["on"] = records
            outcome.clear()
            outcome.update(fail or {})
            planned[:] = steps_
            fb._run_planned("Demo", "smoke", {}, automatic=automatic)
            st = fb.state("Demo")
            return [c[0] for c in calls], st["skipped"], sorted(st["failed"])

        p_boots = fb.Step("pieces", "Own mesh · boots", 0, "boots")
        t_trousers = fb.Step("template", "Template drape · trousers", 0, "trousers")
        assemble = fb.Step("assemble", fb.ASSEMBLE_LABEL, 0)
        check("[2a] fresh piece failure", run([p_boots, t_trousers, assemble], {("pieces", "boots"): "mesh refused"}),
              (["pieces", "template"], ["assemble"], ["pieces"]))
        cached = fb.Step("pieces", "Own mesh · boots" + fb.FAILED_SUFFIX, 0, "boots", failed="mesh refused")
        check("[2b] cached failure retried, failed again",
              run([cached, t_trousers, assemble], {("pieces", "boots"): "mesh refused"}),
              (["pieces", "template", "assemble"], [], ["pieces"]))
        check("[2c] fresh drape failure", run([p_boots, t_trousers, assemble], {("template", "trousers"): "stretch"}),
              (["pieces", "template"], ["assemble"], ["template"]))
        check("[2e] drape left due (nothing recorded)",
              run([p_boots, t_trousers, assemble], {("template", "trousers"): "timeout"}, records=False),
              (["pieces", "template", "assemble"], [], ["template"]))
        check("[2e] chain deferred (nothing recorded)",
              run([p_boots, t_trousers, assemble], {("pieces", "boots"): "hub busy"}, records=False),
              (["pieces", "template", "assemble"], [], ["pieces"]))
        check("[2f] automatic: a first recorded drape failure",
              run([p_boots, t_trousers, assemble], {("template", "trousers"): "stretch"}, automatic=True),
              (["pieces", "template", "assemble"], [], ["template"]))
        due_after["step"] = fb.Step("template", "Template drape · trousers", 0, "trousers")
        check("[2d] drape key moved after the pieces", run([p_boots, assemble]),
              (["pieces", "template", "assemble"], [], []))
        check("[2d] the re-planned drape is the trousers'", calls[1], ("template", "trousers"))
        due_after["step"] = None
        check("[2d] nothing due after the pieces", run([p_boots, assemble]), (["pieces", "assemble"], [], []))
        due_after["step"] = fb.Step("template", "Template drape · trousers" + fb.FAILED_SUFFIX, 0, "trousers",
                                    failed="stretch")
        check("[2d] automatic: a cached failed drape is not added", run([p_boots, assemble], automatic=True),
              (["pieces", "assemble"], [], []))

        print("[3] a worn-open template piece keeps its own change row")
        drape = "Drape failed: stretch_max 1.8 (limit 1.3)"
        w_open = fig(own=("blazer",), template=("blazer",), open=("blazer",), pieces={"outer": "blazer"})
        d_open = fig(own=(), left_out={"blazer": drape}, pieces={"outer": "blazer"})
        check("[3] template open, left out", figure._open_mesh_missing(w_open, d_open), {})
        w_own = fig(own=("blazer",), open=("blazer",), pieces={"outer": "blazer"})
        check("[3] own mesh open, left out", figure._open_mesh_missing(w_own, d_open), {"blazer": figure.LEFT_OUT})
        w_acc = fig(own=(), accessory=("blazer",), open=("blazer",), pieces={"outer": "blazer"})
        check("[3] accessory open", figure._open_mesh_missing(w_acc, d_open), {})

        print("[4] the assembly records the figure it delivered")
        directory = root / "model3d"
        (directory / "assembled").mkdir(parents=True)
        bare = directory / "sig1.glb"
        bare.write_bytes(b"glb-bare")
        old_fig = fig(own=("boots",), left_out={"trousers": "Not draped yet"})
        bare.with_suffix(".json").write_text(json.dumps({
            "base_signature": "base1", "figure": old_fig.as_dict(),
            "mesh_items": {"intended": ["boots", "trousers"], "effective": ["boots"],
                           "unpainted": ["boots", "trousers"], "missing": {"trousers": "Not draped yet"},
                           "warnings": []},
            "garment_warnings": ["Not fitted on this outfit body, served without: boots (fit refused)"]}))
        assembled = garment_assembly.assembled_path(directory, "sig1", garment_assembly.FULL)
        assembled.write_bytes(b"glb-assembled")
        assembled.with_suffix(".json").write_text(json.dumps({
            "figure": old_fig.as_dict(), "garments": {"boots": {}, "trousers": {}},
            "bare_revision": garment_assembly.bare_revision(bare)}))
        model3d.find_model3d = lambda c, s=None, **_kw: bare if s == "sig1" else None
        stale = {"why": ""}
        base_body.figure_stale = lambda *_a, **_kw: stale["why"]
        now_fig = fig(own=("boots", "trousers"), template=("trousers",))
        check("[4] rewritten", base_body.record_delivered_figure("Demo", "sig1", now_fig),
              {"rewritten": True, "intended_changed": False})
        meta = json.loads(bare.with_suffix(".json").read_text())
        check("[4] bare figure", meta["figure"], now_fig.as_dict())
        check("[4] bare mesh_items", {k: meta["mesh_items"][k] for k in ("intended", "effective", "unpainted",
                                                                         "missing")},
              {"intended": ["boots", "trousers"], "effective": ["boots", "trousers"],
               "unpainted": ["boots", "trousers"], "missing": {}})
        side = json.loads(assembled.with_suffix(".json").read_text())
        check("[4] garment warnings kept", meta.get("garment_warnings"),
              ["Not fitted on this outfit body, served without: boots (fit refused)"])
        check("[4] assembly carries the figure", side["figure"], now_fig.as_dict())
        check("[4] assembly still current", side["bare_revision"], garment_assembly.bare_revision(bare))
        check("[4] second call", base_body.record_delivered_figure("Demo", "sig1", now_fig)["rewritten"], False)
        before = bare.with_suffix(".json").read_text()
        stale["why"] = "figure"
        other = fig(own=("boots",), left_out={"trousers": "Drape failed"})
        check("[4] stale model left alone", base_body.record_delivered_figure("Demo", "sig1", other)["rewritten"],
              False)
        check("[4] sidecar unchanged", bare.with_suffix(".json").read_text(), before)
        stale["why"] = ""
        check("[4] another signature", base_body.record_delivered_figure(
            "Demo", "sig1", fig(signature="sig2", own=("boots",)))["rewritten"], False)

    print(f"{len(FAILS)} failure(s)" if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
