#!/usr/bin/env python3
"""Saved face values make the base model's face step due (Task UI2 gap 1 of
docs/superpowers/plans/2026-11-12-unified-worn-pieces.md; rule R3 "a setting saved on its own makes its step
stale" → R1 "Run all picks it up").

Usage:
    ./.venv/bin/python scripts/smoke_face_settings_due.py

Runs against a THROWAWAY storage directory (``paths.init(<tmp>)`` before any world module is imported) — no world,
no hub, no server, nothing renders. The profile store is a dict (``get_character_profile`` /
``save_character_profile`` patched); the stored model is a file in the tmp dir with a hand-written sidecar.

Expected, by hand from the rule in ``model3d.face_settings_fingerprint``'s docstring (sha256 of
``json.dumps({"photo": …, "controls": …}, sort_keys=True, separators=(",", ":"))``, every number a float, the
first 16 hex digits; the defaults are ``face_photo_adjust.DEFAULTS`` balance/tone_match/skin_recolor/brightness
1.0 and ``face_retexture.validated_params`` strength 1, feather 0.18, render_resolution 768, yaw 0):

[1] Nothing stored → F0 = sha256('{"controls":{"feather":0.18,"render_resolution":768.0,"strength":1.0,"yaw":0.0},
    "photo":{"balance":1.0,"brightness":1.0,"skin_recolor":1.0,"tone_match":1.0}}')[:16] (one line, no spaces).
    face_controls {strength: 0.8} stored → F1 = the same with "strength":0.8 — F1 != F0. The defaults saved again
    (the key is gone, deviations only) → F0 again. face_photo {balance: 0.5} → F2 = F0's text with "balance":0.5.
    An int 1 and a float 1.0 give the same text ("strength":1.0) — no spurious due after a dialog run.
[2] ``figure_build._face_retexture_pending`` (switch on, humanoid, model + ``unrigged/<sig>.glb`` on disk):
    record applied with settings F0 while F0 is saved → ""; face_photo {balance: 0.5} saved → "changed"; a record
    WITHOUT "settings" (made before UI2) → "" whatever is saved; failed → "missing"; switch off → "".
[3] ``base_run_all`` with the plain body current, no cleanup due, ``mesh_hub_stages`` = [mesh, face, rig] and the
    record of [2] outdated → kind "face_retexture", face_due "changed", steps [face 1, rig 1], hub_jobs 2, note
    starting "face values changed — not applied yet: face + rig"; record current → kind "", face_due "".
[4] ``_face_retexture_model`` (the face dialog / Run all path) up to its hub record (``hub_ops.create`` patched to
    capture the inputs and stop): the dialog's explicit controls {strength 0.6} and photo {balance 0, tone_match 1,
    skin_recolor 1, brightness 1} on a LOCAL backend with a FRONT reference while balance 0.5 is remembered →
    face_controls stored {strength: 0.6}; the remembered balance stays 0.5 (a front run cannot express it);
    inputs.settings_fingerprint == fingerprint of {strength 0.6, balance 0.5} == ``face_settings_fingerprint``
    after the run (the SETTINGS, not the mode-rewritten balance 0 the run applies).
[5] The record writes it: the face meta of a bake (``_face_source_stages``' attempt) carries
    ``'settings': inputs['settings_fingerprint']`` and the mesh run's face inputs set
    ``"settings_fingerprint": face_settings_fingerprint(character_name)`` (source wiring — the bake needs a hub).

Fails on 55a2a478: AttributeError — module ``model3d`` has no attribute ``face_settings_fingerprint``.
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="smoke_face_due_"))
from app.core import paths  # noqa: E402
paths.init(str(_tmp))
from app.core import db  # noqa: E402
db.init_schema()  # an empty world: readers that look a character's config up find no row, not no table

from app.core import base_body, base_skin, face_retexture, figure_build, hub_ops, model3d  # noqa: E402
import app.models.character as character_model  # noqa: E402

FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


class Patch:
    def __init__(self, *triples):
        self.triples, self.saved = triples, []

    def __enter__(self):
        for obj, name, value in self.triples:
            self.saved.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)
        return self

    def __exit__(self, *exc):
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


C, BSIG = "Mia", "b0123456789a"
F0 = sha16('{"controls":{"feather":0.18,"render_resolution":768.0,"strength":1.0,"yaw":0.0},'
           '"photo":{"balance":1.0,"brightness":1.0,"skin_recolor":1.0,"tone_match":1.0}}')
F1 = sha16('{"controls":{"feather":0.18,"render_resolution":768.0,"strength":0.8,"yaw":0.0},'
           '"photo":{"balance":1.0,"brightness":1.0,"skin_recolor":1.0,"tone_match":1.0}}')
F2 = sha16('{"controls":{"feather":0.18,"render_resolution":768.0,"strength":1.0,"yaw":0.0},'
           '"photo":{"balance":0.5,"brightness":1.0,"skin_recolor":1.0,"tone_match":1.0}}')
F4 = sha16('{"controls":{"feather":0.18,"render_resolution":768.0,"strength":0.6,"yaw":0.0},'
           '"photo":{"balance":0.5,"brightness":1.0,"skin_recolor":1.0,"tone_match":1.0}}')

store = {C: {"name": C}}
profiles = Patch((character_model, "get_character_profile", lambda c, **k: json.loads(json.dumps(store.get(c) or {}))),
                 (character_model, "save_character_profile", lambda c, p, **k: store.__setitem__(c, dict(p)) or True))


def save(updates):
    model3d.set_model3d_options(C, updates)


def reset():
    store[C] = {"name": C}


DEFAULT_CONTROLS = {"strength": 1, "feather": 0.18, "render_resolution": 768, "yaw": 0}

with profiles:
    # [1]
    check("[1] nothing stored = F0", model3d.face_settings_fingerprint(C), F0)
    save({"face_controls": {**DEFAULT_CONTROLS, "strength": 0.8}})
    check("[1] strength 0.8 = F1", model3d.face_settings_fingerprint(C), F1)
    check("[1] F1 differs from F0", F1 != F0)
    save({"face_controls": dict(DEFAULT_CONTROLS)})
    check("[1] defaults again = F0", model3d.face_settings_fingerprint(C), F0)
    save({"face_photo": {"balance": 0.5}})
    check("[1] balance 0.5 = F2", model3d.face_settings_fingerprint(C), F2)
    reset()
    save({"face_controls": {**DEFAULT_CONTROLS, "strength": 1.0, "yaw": 0.0}})
    check("[1] floats for ints change nothing", model3d.face_settings_fingerprint(C), F0)

    # [2]
    reset()
    store[C]["model3d_opts"] = {"face_before_rig": True}
    mdir = _tmp / "m3d"
    (mdir / "unrigged").mkdir(parents=True)
    model = mdir / f"{BSIG}.glb"
    model.write_bytes(b"glb")
    (mdir / "unrigged" / f"{BSIG}.glb").write_bytes(b"src")
    record = {"rec": {"status": "applied", "settings": F0}}
    files = Patch((model3d, "required_rig", lambda c, *a, **k: "mixamo"),
                  (model3d, "find_model3d", lambda c, s: model if model.exists() else None),
                  (model3d, "_read_sidecar", lambda path: {"face_retexture": record["rec"]}))
    with files:
        pend = lambda: figure_build._face_retexture_pending(C, BSIG)  # noqa: E731
        check("[2] applied with the saved values", pend(), "")
        save({"face_photo": {"balance": 0.5}})
        check("[2] other values saved → changed", pend(), "changed")
        record["rec"] = {"status": "applied"}
        check("[2] record without a fingerprint counts as current", pend(), "")
        record["rec"] = {"status": "failed", "settings": F0}
        check("[2] failed → missing", pend(), "missing")
        record["rec"] = {"status": "applied", "settings": F0}
        store[C]["model3d_opts"]["face_before_rig"] = False
        check("[2] switch off", pend(), "")
        store[C]["model3d_opts"]["face_before_rig"] = True

        # [3]
        plan_stubs = Patch(
            (figure_build, "on_pipeline", lambda c, profile=None: True),
            (base_body, "base_refresh_plan", lambda c, profile=None, missing=False: {
                "signature": BSIG, "views": [], "model": False, "reason": ""}),
            (base_skin, "enabled", lambda: False),
            (model3d, "mesh_hub_stages", lambda c, s: ["mesh", "face", "rig"]),
            (model3d, "face_cleanup_state", lambda c, s: {"can_reapply": False}),
            (model3d, "extension_settings_changed", lambda c, path, meta=None: False))
        with plan_stubs:
            p = figure_build.base_run_all(C, profile={"name": C})
            check("[3] face step due after a save", [p["kind"], p["face_due"], [(s["name"], s["jobs"]) for s in p["steps"]],
                                                     p["hub_jobs"]],
                  ["face_retexture", "changed", [("face", 1), ("rig", 1)], 2])
            check("[3] its note", p["note"].startswith("face values changed — not applied yet: face + rig"))
            record["rec"] = {"status": "applied", "settings": F2}
            p = figure_build.base_run_all(C, profile={"name": C})
            check("[3] values applied → nothing due", [p["kind"], p["face_due"], p["hub_jobs"]], ["", "", 0])

    # [4]
    reset()
    save({"face_photo": {"balance": 0.5}})
    captured = {}

    class Stop(Exception):
        pass

    def create(kind, subject, inputs, **k):
        captured.update(inputs)
        raise Stop()

    def fake_check(c, s, reference, _snapshot=None):
        _snapshot.update(image=b"img", rgba=b"rgba")
        return {"problems": [], "reference": "front"}

    with Patch((face_retexture, "check", fake_check),
               (face_retexture, "runnable", lambda c, glob="": {"ok": True, "problems": []}),
               (face_retexture, "photo_controls_supported", lambda c, glob="": False),
               (face_retexture, "flatten_photo", lambda raw, photo=None: b"flat"),
               (hub_ops, "create", create),
               (model3d, "get_model3d_dir", lambda c: _tmp / "m3d")):
        try:
            model3d._face_retexture_model(C, BSIG, params={**DEFAULT_CONTROLS, "strength": 0.6},
                                          photo={"balance": 0, "tone_match": 1, "skin_recolor": 1, "brightness": 1})
            check("[4] stopped at the hub record", False)
        except Stop:
            pass
    opts = store[C].get("model3d_opts") or {}
    check("[4] dialog controls remembered", opts.get("face_controls"), {"strength": 0.6})
    check("[4] remembered balance kept on a local front run", opts.get("face_photo"), {"balance": 0.5})
    check("[4] the record's fingerprint = the settings", captured.get("settings_fingerprint"), F4)
    check("[4] … = face_settings_fingerprint now", model3d.face_settings_fingerprint(C), F4)
    check("[4] the run itself applies balance 0 (mode rewrite)", (captured.get("photo") or {}).get("balance"), 0.0)

# [5]
source = (ROOT / "app/core/model3d.py").read_text(encoding="utf-8")
check("[5] the bake's face meta carries the fingerprint",
      "'settings': inputs['settings_fingerprint']" in source)
check("[5] the mesh run's face inputs set it",
      '"settings_fingerprint": face_settings_fingerprint(character_name)' in source)

print("\n" + ("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
