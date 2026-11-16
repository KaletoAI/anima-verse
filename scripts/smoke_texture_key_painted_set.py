#!/usr/bin/env python3
"""Ruling A115: a texture is keyed by (shape, PAINTED set) — an own-mesh piece never touches it.

Spec docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md, "Reuse, not rebuild": a body is cached by its
in-body set (shape key) and a texture by the set of painted pieces on that shape; changing an own-mesh piece never
touches the body. The outfit's full-body reference (the picture the dressed front is an edit of) is part of the
texture key, so it must be keyed by the painted set too and show only the painted pieces
(``outfit_references.reference_key``, ``full_body_reference.outfit_block``).

Usage:
    ./.venv/bin/python scripts/smoke_texture_key_painted_set.py

No world, no server, no hub: storage + instance are throwaway temp dirs, and every input the keys read from a
world (the reference records, the dress text, the texture inputs, the open-state map) is a stand-in below.

Fixture pieces: S = stockings (painted), T = thong (painted), K = skirt (own mesh), B = blazer (own mesh),
U = bodysuit (in body). Worn: {legs: S, underwear_bottom: T, bottom: K, outer: B}.

Expected, derived by hand:
 [1] reference_key(pieces, (), painted=(S, T)) = "or" + sha256('{"open":[],"pieces":["S","T"]}')[:10] — the
     canonical JSON of the sorted PAINTED ids only (``outfit_key``: sort_keys, separators ",", ":").
 [2] removing K, adding a third own-mesh piece J, or swapping B for J leaves [1]'s key unchanged (K/B/J are not
     painted).
 [3] adding a painted piece P changes it: "or" + sha256('{"open":[],"pieces":["P","S","T"]}')[:10].
 [4] texture_key on the plain body with a reference record R (sha "r"*64) under [1]'s key: equal for the outfit
     with K, without K, and with B swapped for J (own-mesh add/remove/swap → same texture key, so the plan finds
     the stored texture); the stand-in texture inputs see only the painted ids, and the reference part is "r"*64.
 [5] adding P changes the texture key (a painted add → a new texture → its views are a texture step).
 [6] shape_key: no in-body piece → the plain body bsig for all of [4]; adding U (in body) → an "ob" key ≠ bsig
     (an in-body change → a shape step).
 [7] full_body_reference.outfit_block wears only the painted pieces: its render_outfit stand-in is asked for
     {legs: S, underwear_bottom: T} — never K or B.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


def by_hand(ids):
    raw = '{"open":[],"pieces":[' + ",".join(f'"{i}"' for i in ids) + "]}"
    return "or" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_a115_"))
    (tmp / "world").mkdir()
    (tmp / "instance").mkdir()
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    from app.core import paths
    paths.init(tmp / "world")
    paths.init_instance(tmp / "instance")
    from app.core import base_body, figure, full_body_reference, outfit_references

    S, T, K, B, J, P, U = "S", "T", "K", "B", "J", "P", "U"
    worn = {"legs": S, "underwear_bottom": T, "bottom": K, "outer": B}
    painted = (S, T)

    # [1]-[3]
    key = outfit_references.reference_key(worn, (), painted)
    check("[1] reference key = painted ids only", key, by_hand(["S", "T"]))
    no_k = {s: i for s, i in worn.items() if i != K}
    check("[2] own-mesh removed", outfit_references.reference_key(no_k, (), painted), key)
    check("[2] own-mesh added", outfit_references.reference_key({**worn, "feet": J}, (), painted), key)
    check("[2] own-mesh swapped", outfit_references.reference_key({**worn, "outer": J}, (), painted), key)
    check("[3] painted added", outfit_references.reference_key({**worn, "top": P}, (), (P, S, T)),
          by_hand(["P", "S", "T"]))

    # Stand-ins for what the keys read from a world.
    records = {key: {"image": "ref.png", "sha256": "r" * 64}}
    outfit_references.references_of = lambda name, *, profile=None: dict(records)
    seen = {}

    def texture_inputs(name, *, pieces, items, variant, mesh_effective=(), bsig=None, profile=None):
        left = set(mesh_effective)
        ids = sorted(i for i in (pieces or {}).values() if i not in left)
        seen.setdefault("inputs", []).append(ids)
        return {"base_signature": bsig, "base_variant": variant, "dress_text": {"front": ",".join(ids)}}

    base_body.texture_inputs = texture_inputs
    base_body.dress_text = lambda name, view, *, pieces, items, profile, mesh_items=(): ",".join(
        sorted(i for i in (pieces or {}).values() if i not in set(mesh_items)))
    base_body.side_views_dressed = lambda: False
    base_body.dressed_views = lambda: ("front",)
    BSIG = "base0123abcd"

    def sets_of(pieces, own, in_body=()):
        ids = set(pieces.values())
        return figure.WornSets(in_body=tuple(sorted(in_body)), painted=tuple(sorted(ids - set(own) - set(in_body))),
                               own={i: "clothing" for i in own}, hair_in_body=False, hair_item="", pieces=dict(pieces))

    def keys(pieces, own, in_body=()):
        sets = sets_of(pieces, own, in_body)
        shape = figure.shape_key("Demo", sets, bsig=BSIG, variant="rigged", profile={})
        return shape, figure.texture_key("Demo", sets, shape=shape, bsig=BSIG, variant="rigged", profile={})

    with_k = keys(worn, (K, B))
    without_k = keys(no_k, (B,))
    swapped = keys({**worn, "outer": J}, (K, J))
    check("[4] texture key: own-mesh removed", without_k[1], with_k[1])
    check("[4] texture key: own-mesh swapped", swapped[1], with_k[1])
    check("[4] texture inputs saw the painted ids only", all(ids == ["S", "T"] for ids in seen["inputs"]), True)
    plain = texture_inputs("Demo", pieces=worn, items=[], variant="rigged", mesh_effective=(K, B), bsig=BSIG)
    plain["outfit_reference"] = "r" * 64
    check("[4] texture key by hand", with_k[1], base_body.texture_signature(plain))
    check("[5] painted added → new texture", keys({**worn, "top": P}, (K, B))[1] != with_k[1], True)
    check("[6] no in-body piece → plain body", (with_k[0], without_k[0], swapped[0]), (BSIG, BSIG, BSIG))
    shaped = keys({**worn, "inner": U}, (K, B), (U,))[0]
    check("[6] in-body added → a meshed shape", shaped.startswith("ob") and shaped != BSIG, True)

    # [7]
    asked = {}
    import app.core.outfit_renderer as renderer

    def render_outfit(*, profile, character_name, equipped_pieces, equipped_items, mesh_input):
        asked["pieces"] = dict(equipped_pieces)
        return {"pieces": ", ".join(sorted(equipped_pieces.values()))}

    renderer.render_outfit = render_outfit
    full_body_reference._attributes = lambda name, profile: "Demo"
    block = full_body_reference.outfit_block("Demo", profile={"equipped_pieces": worn}, painted=painted)
    check("[7] outfit block wears the painted pieces only", asked.get("pieces"), {"legs": S, "underwear_bottom": T})
    check("[7] outfit block text", block, "Demo, wearing S, T")

    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'ALL PASS'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
