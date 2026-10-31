#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_prop_action_pack.py

Package prop actions (plan-pack-prop-actions.md, phase 1): a package's
source adds actions to every matching prop at RUNTIME only; the prop file,
its save base and every export stay the author's.

Hand-derived expectations on the run fixture (smoke_prop_action_runs:
one prop, own action "rest" = pose "sitting", one capacity-1 "seat" marker
"body"); the package "testpack" is loaded by patching the registry:

a. ``pack_action_id`` is ``pack-`` + uuid5(URL, "anima:pack-action:<owner>:<key>"):
   the same owner+key give the same id, another owner another id.
b. No loaded source: ``effective_document`` returns the SAME object, the
   signature is "", ``action_revision`` == ``revision``.
c. Source with "sit back" (pose "sitting" -> group seat) and "doze"
   (ability sleep -> group lie): the runtime document holds rest + both,
   ``action_sources`` names testpack for both; "sit back" binds marker
   "body", "doze" binds none (no lie marker). ``revision`` is still the hash
   of the raw sidecar, ``action_revision`` differs. The offer list carries
   "sit back" (enabled, with the runtime revision) under its German name
   for lang "de" ("Zurücklehnen") and its English one for "en". "doze" binds
   no marker of the placement, so it is no offer at all — the offers are
   exactly {rest, sit back}.
d. Export: the ZIP's sidecar.json equals the raw sidecar; no "pack-" in it.
e. A request of "sit back" with the offer's revision starts (approaching).
   The package source is then removed: the offer disappears, and the
   running action ends on its next tick (the runtime revision it was
   requested with no longer exists -> stale_definition) — no exception, no
   claim left.
f. Exclusions: document-level ``exclude_actions`` [sit back] removes it from
   the runtime document; validation accepts that, refuses an own id there
   ("rest"), refuses an own action whose id starts with "pack-", and accepts a
   marker exclusion of a pack id no loaded package knows.
g. A definition without a pack id, and one with an unknown ability, are
   skipped; the valid one stays.
h. ``match`` {"categories": ["throne"]}: the fixture prop (category "") gets
   nothing; {"tags": ["Lounge"]} admits it once the prop is tagged "lounge".
i. Changing a definition's description changes the signature, the scene
   fingerprint and the offer revision; the OLD revision is refused
   (stale_definition) and the new one accepted.
j. Editor (phase 2): the validate route lists "sit back" read-only as
   ``pack_actions`` (package testpack, not excluded) and binds it on "body"
   beside "rest"; with the draft excluding it, the row says excluded and
   only "rest" binds. The batch save stores ``exclude_actions`` deduplicated
   ([sit back] from [sit back, sit back]) — a new author revision, the
   runtime revision now equal to it, no offer; an own id ("rest") is a 422
   (PropDocumentInvalid), a non-list a ValueError; saving [] removes the key
   and the offer comes back.
"""
import io
import json
from pathlib import Path
import sys
import zipfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from uuid import NAMESPACE_URL, uuid5  # noqa: E402

LOADED = {"testpack"}
S = F = A = R = SRC = P = props = registry = None


def _load():
    """Import the fixture and the core only now: the fixture points storage
    at its private world before any world module is imported."""
    global S, F, A, R, SRC, P, props, registry
    import smoke_prop_action_runs as fixture
    S, F, A, R = fixture, fixture.F, fixture.A, fixture.R
    F.paths.init(F.ROOT / "world")
    from app.core import prop_action_sources, prop_actions, props as prop_store
    from app.plugins import registry as package_registry
    SRC, P, props, registry = prop_action_sources, prop_actions, prop_store, package_registry
    real = registry.get_package
    patch.object(registry, "get_package",
                 lambda package_id: object() if package_id in LOADED else real(package_id)).start()


def definition(key, **kw):
    base = dict(id="pack-" + str(uuid5(NAMESPACE_URL, f"anima:pack-action:testpack:{key}")), name=key.title(), description="Package fixture",
                enabled=True, ability="pose", pose_key="sitting", participants=1, presence="any",
                interrupt_on_presence_change=False, phases=[], requirements=[], effects=[])
    base.update(kw)
    return base


SIT = definition("sit back", name="Sit back", name_de="Zurücklehnen")
DOZE = definition("doze", name="Doze", ability="sleep", pose_key="")
SOURCE = [SIT, DOZE]


def offers(name, lang="en"):
    P._offers_cache.clear()
    return {o["action_id"]: o for o in P.offers(name, lang=lang)}


def identity(target):
    return {k: target[k] for k in ("location_id", "room_id", "placement_id", "variant_uid")}


def main():
    _load()

    # a
    expected = "pack-" + str(uuid5(NAMESPACE_URL, "anima:pack-action:testpack:sit back"))
    assert SIT["id"] == expected == SRC.pack_action_id("testpack", "sit back")
    assert SRC.pack_action_id("other", "sit back") != expected
    print("PASS a: stable package action ids with the reserved prefix")

    # b
    name, target, pid = S.setup_run()
    raw = props.read_sidecar(pid)
    assert P.effective_document(raw) is raw and SRC.signature() == ""
    record = props.get_prop(pid)
    assert record["action_revision"] == record["revision"] == props._document_revision(raw)
    print("PASS b: without a source the runtime document is the raw one")

    # c
    SRC.register_source("testpack", lambda: SOURCE)
    effective = P.effective_document(raw)
    assert [a["id"] for a in effective["actions"]] == ["rest", SIT["id"], DOZE["id"]]
    assert effective["action_sources"] == {SIT["id"]: "testpack", DOZE["id"]: "testpack"}
    bindings = {b["action_id"]: b["marker_ids"] for b in P.derive_bindings(effective, raw["model_variants"][0])}
    assert bindings == {"rest": ["body"], SIT["id"]: ["body"], DOZE["id"]: []}, bindings
    record = props.get_prop(pid)
    assert record["revision"] == props._document_revision(raw)
    assert record["action_revision"] == props._document_revision(effective) != record["revision"]
    assert [a["id"] for a in record["actions"]] == ["rest"]
    en, de = offers(name), offers(name, "de")
    assert en[SIT["id"]]["label"] == "Sit back" and de[SIT["id"]]["label"] == "Zurücklehnen"
    assert en[SIT["id"]]["definition_revision"] == record["action_revision"]
    assert en[SIT["id"]]["enabled"], en[SIT["id"]]
    # "doze" binds no marker of this placement -> no offer at all (it could
    # only be refused with incompatible_pose_marker).
    assert DOZE["id"] not in en and set(en) == {"rest", SIT["id"]}, sorted(en)
    print("PASS c: package actions bind at runtime, the author record stays raw")

    # d
    with zipfile.ZipFile(io.BytesIO(__import__("app.core.content_io", fromlist=["x"]).export_prop_to_zip(pid))) as zf:
        exported = zf.read("files/sidecar.json")
    assert json.loads(exported) == props.read_sidecar(pid) and b"pack-" not in exported
    print("PASS d: the export carries the raw sidecar, no package action")

    # e
    started = A.request(name, identity(target), SIT["id"], en[SIT["id"]]["definition_revision"])
    assert started["status"] == "approaching", started
    SRC.unregister_source("testpack")
    assert SIT["id"] not in offers(name)
    S.tick(1)
    row = R.get(started["execution_id"])
    assert row["status"] in ("failed", "cancelled") and row["reason"] == "stale_definition", row
    assert not R.claims()
    print("PASS e: removing the source ends the running action cleanly")

    # f
    SRC.register_source("testpack", lambda: SOURCE)
    doc = props.read_sidecar(pid)
    doc["exclude_actions"] = [SIT["id"]]
    assert [a["id"] for a in P.effective_document(doc)["actions"]] == ["rest", DOZE["id"]]
    errors = lambda d: [i["code"] for i in P.validate_document(d) if i["severity"] == "error"]
    assert errors(doc) == []
    assert errors({**doc, "exclude_actions": ["rest"]}) == ["invalid_action_reference"]
    own_pack = json.loads(json.dumps(doc))
    own_pack["actions"][0]["id"] = "pack-mine"
    own_pack.pop("exclude_actions")
    assert "invalid_id" in errors(own_pack)
    marker = json.loads(json.dumps(doc))
    marker["model_variants"][0]["markers"][0]["exclude_actions"] = ["pack-of-an-absent-package"]
    assert errors(marker) == []
    print("PASS f: exclusions on prop and marker, the reserved prefix")

    # g
    SRC.register_source("testpack", lambda: [SIT, {**DOZE, "id": "doze"}, definition("odd", ability="dance")])
    assert [p["action"]["id"] for p in SRC.pack_actions()] == [SIT["id"]]
    print("PASS g: invalid definitions are skipped, the valid one stays")

    # h
    SRC.register_source("testpack", lambda: [{**SIT, "match": {"categories": ["throne"]}}])
    assert [a["id"] for a in P.effective_document(raw)["actions"]] == ["rest"]
    SRC.register_source("testpack", lambda: [{**SIT, "match": {"tags": ["Lounge"]}}])
    assert [a["id"] for a in P.effective_document(raw)["actions"]] == ["rest"]
    assert [a["id"] for a in P.effective_document({**raw, "tags": ["lounge"]})["actions"]] == ["rest", SIT["id"]]
    print("PASS h: match by category and tag")

    # i
    from app.core.scene_recipe import scene_fingerprint
    from app.models.world import get_location_by_id
    location = get_location_by_id(target["location_id"])
    SRC.register_source("testpack", lambda: [SIT])
    before = (SRC.signature(), scene_fingerprint(location, location["id"]), offers(name)[SIT["id"]]["definition_revision"])
    SRC.register_source("testpack", lambda: [{**SIT, "description": "Changed"}])
    after = (SRC.signature(), scene_fingerprint(location, location["id"]), offers(name)[SIT["id"]]["definition_revision"])
    assert all(b != a for b, a in zip(before, after)), (before, after)
    assert A.check(name, identity(target), SIT["id"], before[2]) == dict(enabled=False, reason="stale_definition")
    assert A.check(name, identity(target), SIT["id"], after[2])["enabled"]
    print("PASS i: a changed definition moves signature, scene key and revision")

    # j — the editor's side (phase 2)
    from app.routes import prop_actions as route
    SRC.register_source("testpack", lambda: [SIT])
    raw = props.read_sidecar(pid)
    answer = route.validate(pid, route.Document(document=raw), user={})
    assert [(row["id"], row["name"], row["package"], row["excluded"]) for row in answer["pack_actions"]] \
        == [(SIT["id"], "Sit back", "testpack", False)], answer["pack_actions"]
    uid = raw["model_variants"][0]["uid"]
    assert {b["action_id"]: b["marker_ids"] for b in answer["derived_bindings"][uid]} \
        == {"rest": ["body"], SIT["id"]: ["body"]}
    off = route.validate(pid, route.Document(document={**raw, "exclude_actions": [SIT["id"]]}), user={})
    assert off["pack_actions"][0]["excluded"] is True
    assert [b["action_id"] for b in off["derived_bindings"][uid]] == ["rest"]
    base = props.get_prop(pid)["revision"]
    saved = props.bulk_update(pid, {"exclude_actions": [SIT["id"], SIT["id"]]}, base_revision=base)
    assert props.read_sidecar(pid)["exclude_actions"] == [SIT["id"]]
    assert saved["exclude_actions"] == [SIT["id"]] and saved["revision"] != base
    assert saved["action_revision"] == saved["revision"]   # nothing added any more
    assert SIT["id"] not in offers(name)
    for bad, error in (({"exclude_actions": ["rest"]}, props.PropDocumentInvalid),
                       ({"exclude_actions": "rest"}, ValueError)):
        try:
            props.bulk_update(pid, bad, base_revision=saved["revision"])
        except error:
            pass
        else:
            raise AssertionError(f"{bad} was accepted")
    cleared = props.bulk_update(pid, {"exclude_actions": []}, base_revision=saved["revision"])
    assert "exclude_actions" not in props.read_sidecar(pid) and SIT["id"] in offers(name)
    assert cleared["action_revision"] != cleared["revision"]
    print("PASS j: the editor lists package actions read-only and saves the prop's exclusion")
    SRC.unregister_source("testpack")
    F.assert_no_external_work()


if __name__ == "__main__":
    main()
