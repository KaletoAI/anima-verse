#!/usr/bin/env python3
"""Smoke: a standing Improvements entry works a subject again when it goes
stale AGAIN, and never re-offers a done subject whose inputs stayed
(review 09b#1).

Usage:
    ./.venv/bin/python scripts/smoke_improvement_restale.py

Runs without the server, against a temp storage dir. The store diff
(``store.replace_steps_scan``) is unchanged: it inserts only NEW keys and
leaves done rows alone. What makes a re-stale a new step is the candidate key:
each type puts the token that makes its work due into the key (the
face_cleanup_rerun pattern). Expected values, derived by hand from the module
docstrings of the types:

[1] fit_refit, one character "Mia" on a base whose model sha is "SHA1", one
    stale unit ("Dress"). The key is ``character:Mia:<t>``, ``t`` = the first
    12 hex of sha256 over the JSON ``[FIT_VERSION, SCALE_RETRY_VERSION,
    INSOLE_VERSION, POSTURE_MATCH_VERSION, "SHA1"]`` (sorted keys).
    A standing entry scans → {"added": 1, "closed": 0}; the step is marked
    done. A rescan that still lists the subject unchanged (the step ended
    done but the lister still names it) → {"added": 0, "closed": 0}: the done
    step is NOT re-offered. The subject fixed (no unit) → {"added": 0,
    "closed": 0}. Then FIT_VERSION["clothing"] + 1 makes the Dress stale
    again → the token changes → {"added": 1, "closed": 0}, the new step is
    pending, the old one stays done (2 steps: done 1, pending 1). The old
    code keyed ``character:Mia`` both times: the second listing hit the done
    row (INSERT OR IGNORE) → added 0 — the regression.
[2] A step stored in the OLDER key shape ``character:Mia`` (pending) is not
    listed by a scan any more → closed 1 (the store's rule for an unlisted
    pending row), the token key added 1. The types still read the old shape:
    fit_refit ``_name("character:Mia")`` = "Mia"; collision_capsules
    ``split_key("character:Mia:base1")`` = ("Mia", "base1"); garment_fill
    ``split_key("clothing:Mia:dress")`` = ("clothing", "Mia", "dress") and
    ``split_key("footwear:shoe")`` = ("footwear", "", "shoe"); base_refresh
    ``_parse("base:Mia")`` = "Mia"; outfit_rebuild
    ``_parse("outfit:Mia:sig1")`` = ("Mia", "sig1"); the base
    ``subject_character`` of every new shape names "Mia".
[3] The tokens follow their inputs (stubs, one input changed at a time —
    each must move the token, the same inputs must give the same token):
    outfit_rebuild ``stale_token``: base sha, base signature, stale reason;
    collision_capsules ``wanted_token``: channels_sig, identity sha, VERSION
    stays the module's; extension_rig_rebuild ``wanted_token``: a target's
    wanted fingerprint.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="improvement-restale-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="improvement-restale-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import base_body, footwear_insole, garment_fit, outfit_body_posture  # noqa: E402
from app.core.improvements import engine, registry, store  # noqa: E402
from app.core.improvements.types import (base_refresh, collision_capsules, extension_rig_rebuild,  # noqa: E402
                                         fit_refit, garment_fill, outfit_rebuild)

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


def fit_token(fit_version, base_sha):
    inputs = [fit_version, garment_fit.SCALE_RETRY_VERSION, footwear_insole.INSOLE_VERSION,
              outfit_body_posture.POSTURE_MATCH_VERSION, base_sha]
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def main() -> int:
    typ = registry.get("fit_refit")
    work = {"Mia": ["Dress"]}
    fit_version = dict(garment_fit.FIT_VERSION)
    with patch.object(fit_refit, "_names", lambda params: ["Mia"]), \
         patch.object(fit_refit, "_work", lambda name, profile: list(work[name])), \
         patch.object(fit_refit, "_profile", lambda name: {}), \
         patch.object(base_body, "current_base", lambda name, profile=None: ("base1", "SHA1")), \
         patch.object(garment_fit, "FIT_VERSION", fit_version):
        print("[1] fit_refit in a standing entry")
        key1 = f"character:Mia:{fit_token(fit_version, 'SHA1')}"
        check("the key carries the version token", [c.key for c in typ.find_candidates({})], [key1])
        entry = store.create(typ.id, "Refit", {}, "standing")["id"]
        check("scan", engine.scan(entry), {"added": 1, "closed": 0})
        store.mark_running(entry, key1)
        store.mark_result(entry, key1, status="done", count_attempt=False)
        check("unchanged and still listed: not re-offered", engine.scan(entry), {"added": 0, "closed": 0})
        work["Mia"] = []
        check("fixed: nothing listed", engine.scan(entry), {"added": 0, "closed": 0})
        fit_version["clothing"] = fit_version["clothing"] + 1
        work["Mia"] = ["Dress"]
        key2 = f"character:Mia:{fit_token(fit_version, 'SHA1')}"
        check("a version bump: a new key", key2 != key1, True)
        check("stale again: a new step", engine.scan(entry), {"added": 1, "closed": 0})
        check("the old step stays done, the new one is pending",
              sorted((s["candidate_key"], s["status"]) for s in store.list_steps(entry)),
              sorted([(key1, "done"), (key2, "pending")]))
        check("the queue names the new step", [r["candidate_key"] for r in engine.ordered_queue()
                                                if r["improvement_id"] == entry], [key2])

        print("[2] a step of the older key shape")
        old = store.create(typ.id, "Refit (old)", {}, "standing")["id"]
        store.replace_steps_scan(old, [("character:Mia", "Mia", 0, "")])
        check("closed by absence, the token key added", engine.scan(old), {"added": 1, "closed": 1})
    check("fit_refit reads the old shape", fit_refit._name("character:Mia"), "Mia")
    check("collision reads the old shape", collision_capsules.split_key("character:Mia:base1"), ("Mia", "base1"))
    check("garment_fill reads the old clothing shape", garment_fill.split_key("clothing:Mia:dress"),
          ("clothing", "Mia", "dress"))
    check("garment_fill reads the old footwear shape", garment_fill.split_key("footwear:shoe"),
          ("footwear", "", "shoe"))
    check("base_refresh reads the old shape", base_refresh._parse("base:Mia"), "Mia")
    check("outfit_rebuild reads the old shape", outfit_rebuild._parse("outfit:Mia:sig1"), ("Mia", "sig1"))
    check("the new shapes still name their character",
          [registry.get(t).subject_character(k) for t, k in (
              ("fit_refit", "character:Mia:abc"), ("collision_capsules", "character:Mia:base1:abc"),
              ("garment_fill", "clothing:Mia:dress:abc"), ("base_refresh", "base:Mia:base1:abc"),
              ("outfit_rebuild", "outfit:Mia:sig1:abc"), ("hair_fill", "character:Mia:hair:abc"))],
          ["Mia"] * 6)

    print("[3] the tokens follow their inputs")
    base = {"bsig": "base1", "sha": "SHA1"}
    with patch.object(base_body, "base_signature", lambda name: base["bsig"]), \
         patch.object(base_body, "base_model_sha256", lambda name, bsig: base["sha"] + bsig):
        t0 = outfit_rebuild.stale_token("Mia", "older_base")
        check("outfit: same inputs, same token", outfit_rebuild.stale_token("Mia", "older_base"), t0)
        check("outfit: the token is sha256 of '<bsig>:<sha>:<reason>'", t0,
              hashlib.sha256(b"base1:SHA1base1:older_base").hexdigest()[:12])
        t_reason = outfit_rebuild.stale_token("Mia", "figure")
        base["sha"] = "SHA2"
        t_sha = outfit_rebuild.stale_token("Mia", "older_base")
        base["bsig"] = "base2"
        t_sig = outfit_rebuild.stale_token("Mia", "older_base")
        check("outfit: reason, base sha, base signature each move it", len({t0, t_reason, t_sha, t_sig}), 4)

    from app.core import collision, collision_channels
    wanted = {"sig": "C1", "sha": "S1"}
    with patch.object(collision_channels, "wanted_channels", lambda *a, **k: ([], wanted["sig"])), \
         patch.object(collision, "identity", lambda path, meta: ("own", wanted["sha"])), \
         patch.object(collision, "character_scales", lambda name, profile=None: {"leg": 1.0}), \
         patch.object(collision, "extension_chains", lambda meta: []), \
         patch("app.models.character.get_character_profile", lambda name: {}):
        c0 = collision_capsules.wanted_token("Mia", Path("x.glb"), {})
        check("collision: the token is sha256 over [VERSION, identity, scales, groups, channels_sig]", c0,
              hashlib.sha256(json.dumps([collision.VERSION, ["own", "S1"], {"leg": 1.0}, [], "C1"],
                                        sort_keys=True).encode("utf-8")).hexdigest()[:12])
        wanted["sig"] = "C2"
        c_sig = collision_capsules.wanted_token("Mia", Path("x.glb"), {})
        wanted["sha"] = "S2"
        c_sha = collision_capsules.wanted_token("Mia", Path("x.glb"), {})
        check("collision: channels and model identity each move it", len({c0, c_sig, c_sha}), 3)

    from app.core import extension_rig, model3d
    fingerprint = {"value": "F1"}
    with patch.object(model3d, "extension_rebuild_targets", lambda name: ([Path("base1.glb")], [])), \
         patch.object(model3d, "_read_sidecar", lambda path: {}), \
         patch.object(model3d, "_extension_groups_for", lambda meta, groups: []), \
         patch.object(model3d, "stored_mesh_variant", lambda name, meta: ""), \
         patch.object(extension_rig, "rig_groups_for", lambda *a, **k: []), \
         patch.object(extension_rig, "effective_extension_overrides", lambda *a: {}), \
         patch.object(extension_rig, "extension_rig_fingerprint", lambda groups, overrides: fingerprint["value"]), \
         patch("app.models.character.get_character_profile", lambda name: {}):
        e0 = extension_rig_rebuild.wanted_token("Mia")
        check("extension: the token is sha256 over [[stem, fingerprint]]", e0,
              hashlib.sha256(json.dumps([["base1", "F1"]]).encode("utf-8")).hexdigest()[:12])
        fingerprint["value"] = "F2"
        check("extension: a changed declaration moves it", extension_rig_rebuild.wanted_token("Mia") != e0, True)

    print("\nOK" if not FAILS else f"\nFAILED ({len(FAILS)}): {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
