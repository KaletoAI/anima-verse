"""Smoke: key isolation of the template pieces (2026-11-25, Glut's gloves).

A piece's drape key (``garment_template.tsig``), cut key (``garment_template_cut.cut_sig``) and cut-texture key
(``garment_cut_texture.csig``) change only when the piece itself, the body it sits on, or a piece that really overlaps
its body region changes; every version in them is scoped to the kinds / features it affects; and a rejected cut texture
is not rendered again by a Build while the request would be the same.

Usage:
    ./.venv/bin/python scripts/smoke_key_isolation.py

Runs without the server, without a world DB and without Blender (``paths.init`` on a temp dir first; items are dicts
handed to a patched ``inventory.get_item``; the cut-texture records live in a temp ``cut_dir``).

THE CASES (``garment_template.validate_params`` of each):

    skirt            {"kind": "skirt"}
    dress_straps     {"kind": "dress", "shoulders": "straps", "neckline": "crew"}
    dress_strapless  {"kind": "dress", "shoulders": "strapless"}
    top_covered      {"kind": "top", "shoulders": "covered", "sleeves": "short"}
    top_corset       {"kind": "top", "shoulders": "strapless", "neckline": "straight"}
    top_corset_straps{"kind": "top", "shoulders": "straps", "neckline": "sweetheart"}
    top_cups         {"kind": "top", "cups": "bra", "cup_style": "balconette"}
    jacket           {"kind": "jacket"}
    trousers, briefs, bra, gloves, tights   {"kind": <kind>}

Their predicates, read off the definitions in ``app/core/garment_template.py`` by hand:

    case              build_kind  pattern_group  panel  leg  strap  corset  corset_straps  neck(cut)  bra_edge  cup_tip  no_bodice_dress
    skirt             skirt       skirt          yes    yes  -      -       -              -          -         -        -
    dress_straps      dress       dress          yes    yes  yes    -       -              yes        -         -        -
    dress_strapless   dress       dress          yes    yes  -      -       -              yes        -         -        yes
    top_covered       top         top            -      -    -      -       -              -          -         -        -
    top_corset        top         corset_top     yes    -    -      yes     -              -          -         -        -
    top_corset_straps top         corset_top     yes    -    -      yes     yes            -          -         -        -
    top_cups          bra         bra            -      -    -      -       -              -          yes       yes      -
    jacket            jacket      jacket         yes    -    -      -       -              yes        -         -        -
    trousers .. tights  = their kind (fitted), no feature column

    (panel = ``panel_piece``: PANEL_KINDS skirt/jacket/dress, or a top with shoulders strapless/straps; leg =
    ``leg_piece``: skirt, dress; strap = ``strap_piece``: dress/top with straps and a neckline not straight/sweetheart —
    the corset with straps has a sweetheart neckline, so no; corset = ``corset_top``; neck = ``neck_piece``: every
    jacket and dress, a covered top only with a collar or a placket — the case has neither; bra_edge = build kind "bra";
    cup_tip = ``straight_cup_top`` (balconette / bandeau: top_cups is balconette -> yes, bra default molded -> no);
    no_bodice_dress = a dress without a bodice: ``STRAPLESS_UNDERARM_M`` in its tsig.)

WHAT IS CHECKED, and where every expected value comes from

[A] The drape key. Each KNOB below is bumped alone (an int + 1000, a sha / metre value changed); the case's ``tsig``
    (base "b" * 64, texture "t", lower []) must change exactly for the cases the table names, and stay for every other:
      TEMPLATE_VERSIONS[k]      -> the cases whose build_kind is k (top_cups follows "bra")
      FITTED_VERSIONS[k]        -> the cases whose build_kind is the fitted kind k
      PANEL_VERSION             -> panel = yes
      LEG_VERSION               -> leg = yes
      STRAP_VERSION             -> strap = yes (dress_straps only)
      CORSET_VERSION            -> corset = yes
      CORSET_STRAPS_VERSION     -> corset_straps = yes
      BRA_EDGE_VERSION          -> bra, top_cups
      CUP_TIP_VERSION           -> top_cups
      STRAPLESS_UNDERARM_M      -> dress_strapless
      NECK_VERSION, UV_PATTERN_KEYS[*], FITTED_PATTERN_KEYS[*], CORSET_DARTS_KEYS[*] -> none (cut-only)
    In particular, for the gloves: only TEMPLATE_VERSIONS["gloves"] and FITTED_VERSIONS["gloves"] move the key.
[B] The cut key, the same way (lower []):
      TEMPLATE_VERSIONS[k], FITTED_VERSIONS[k] -> as in [A]
      UV_PATTERN_KEYS[g]        -> the cases whose pattern_group is g
      FITTED_PATTERN_KEYS[k]    -> the cases whose build_kind is the fitted kind k
      PANEL_VERSION, LEG_VERSION, STRAP_VERSION, CORSET_STRAPS_VERSION, BRA_EDGE_VERSION, CUP_TIP_VERSION -> as in [A]
      CORSET_VERSION            -> corset = yes (build kind top and a panel piece)
      CORSET_DARTS_KEYS[v]      -> the corset top of variant v (``corset_variant``: shoulders "straps" -> "straps",
                                   else "strapless"): [strapless] top_corset only, [straps] top_corset_straps only
      NECK_VERSION              -> neck = yes
      STRAPLESS_UNDERARM_M      -> none (drape-only)
    For the gloves: TEMPLATE_VERSIONS["gloves"], FITTED_VERSIONS["gloves"], UV_PATTERN_KEYS["gloves"],
    FITTED_PATTERN_KEYS["gloves"] and nothing else.
[C] No key moved when the tables came in: every TEMPLATE_VERSIONS entry is 10 and every FITTED_VERSIONS entry 1 (the
    shared values before), every UV_PATTERN_KEYS entry but "top", every FITTED_PATTERN_KEYS entry and every
    CORSET_DARTS_KEYS entry is the md5[:12] of its file at ac232ef4d (``git show``; the keys before were the live md5
    of that file) — "top" stays c926b67f0's 9f1a4a8ce3b8 —; every PROMPT_KEYS entry is its family's md5 at ac232ef4d
    (the full md5 of the family's three files joined by NUL in front_plain, front_decorated, back order — what
    ``PROMPT_SHAS`` was keyed by before): "" and "top" the top files', every other kind the fitted files'; and the cut key of a default glove equals the hand-built payload
    {"params": cut_params, "version": 10, "uv_pattern": <ac232ef4d md5>, "base", "lower": [], "fitted": 1,
    "fitted_pattern": <ac232ef4d md5>} (md5 of the compact sorted json, 12 hex).
[D] The guard: ``UV_PATTERN_REVIEWED`` / ``FITTED_PATTERN_REVIEWED`` / ``CORSET_DARTS_REVIEWED`` are the md5[:12] of
    the files as they are now, ``PROMPT_REVIEWED[family]`` the live ``PROMPT_SHAS[family]`` — a change of
    ``uv_pattern.py`` / ``fitted_pattern.py`` / ``corset_darts.py`` / a family's prompt files fails here until its
    author has decided which groups' / variants' / kinds' pins move (``garment_template_cut`` and
    ``garment_cut_texture`` ``PROMPT_KEYS`` comments).
[E] A related change DOES move the key: a glove's own parameter (length "wrist" -> "elbow") changes tsig and cut_sig;
    another base sha changes both; a lower token changes both (a piece under it); the picture's texture sha changes
    tsig, not cut_sig.
[F] Worn pieces (``inner_pieces``, the source of the lower tokens; items as dicts): worn with a template bra, template
    briefs, template tights and a covered short-sleeved template top, the gloves (regions hand + arm) lie over NONE of
    them — the bra (chest), briefs (hip), tights (leg, foot, hip) share no region, and the top (chest, waist, arm with
    sleeves) shares "arm" but has the same LAYER_RANK 1 and does not cover "hands", so neither the slot order nor the
    rank puts it under. Changing the bra's parameters therefore cannot reach the gloves' key. The control: template
    trousers (rank 1) worn with the briefs (rank 0, hip overlaps) lie over the briefs, so a change of the briefs'
    drape key moves the trousers' tsig (its token "<briefs id>:<briefs tsig>").
[G] The cut texture key: ``csig`` takes the KIND's prompt pin (``prompt_sha_of`` = ``PROMPT_KEYS[prompt_kind]``).
    Hand-derived prompt kinds (``prompt_kind``: build_kind, "strapless" for a top with shoulders strapless / straps):
      skirt -> skirt, dress_straps / dress_strapless -> dress, top_covered -> top, top_corset / top_corset_straps ->
      strapless, top_cups -> bra, jacket -> jacket, the five fitted cases -> their kind.
    Families (``prompt_family``, the files the request is built from): top_covered "top", every other case "fitted".
    Changing PROMPT_KEYS[k] moves exactly the cases of prompt kind k — PROMPT_KEYS["skirt"] only skirt,
    PROMPT_KEYS["gloves"] only gloves; the gloves' csig moves for PROMPT_KEYS["gloves"] and no other entry. Changing
    the live PROMPT_SHAS (a reworded file, a dialect section) moves no csig — only the guard [D] notices it. A kind
    outside the table keys like "" (the top files' pin).
[H] A post-processing version renders nothing again: a READY record of csig S0 (islands "i", item "m", back "k",
    the fitted prompt sha, POST_VERSION p) with raw_front / raw_back files; under POST_VERSION p + 1 the csig S1
    differs, and ``reused_jobs(S1, ["front", "back"])`` re-uses BOTH answers from S0 (``reused_from`` S0, ``raw_from``
    the S0 file) — 0 image jobs. A predecessor with another item sha ("m2") is not one (a new picture renders).
    Redo ``only="back"`` re-uses the front alone.
    The negative case (review 2026-11-25): an own record of S1 (POST_VERSION p + 1, state rejected) whose front entry
    is "ready" with its own raw file and whose back entry is "rejected" with ``reused_from`` S0 (the re-posted answer
    the new post-processing rejected): ``reused_jobs(S1)`` re-uses the front from S1 itself (no ``reused_from``) and
    NOT the back — the back renders anew. The same record with the back entry "failed" (no verdict) still re-uses the
    back from S0.
[I] The retry rule (``retry_changes_request``) on hand-made records of the current csig:
      Glut's record (state rejected; back rejected after attempts 1 and 2, both judged on their intended entry; no
      "chain" recorded)                                                      -> False (the Build renders nothing)
      the same with "chain" == the current chain                             -> False
      the same with "chain" != the current chain                            -> True
      attempt 2's routing with "fallback_from"                              -> True
      attempt 2 "failed"                                                     -> True
      the back entry re-posted from a predecessor (``reused_from``)          -> True
      record state "failed"                                                  -> True
      a rejected record with no job entry carrying a judged attempt          -> True (nothing proves the request)
[J] The seed: ``job_seed("a28d4d8cf4b7", "back", 0)`` = int("a28d4d8c", 16) + 1 mod 2**31 = 2727169420 + 1 -
    2147483648 = 579685773 — the seed of hub job f32b5bed…; round 1 = 579685773 + 100000 = 579785773; the front's
    round 0 = 579685772. ``next_round``: None -> 0; an entry with attempts and no round -> 1; round 1 with attempts ->
    2; an entry without attempts (re-used) -> 0.
[K] The Build step (``figure_build._cut_texture_step`` with ``build_state`` stubbed): held -> label
    ``BUILD_HELD_LABEL`` ("Texture from cut · Glutstulpen: rejected (0 image jobs — Redo …)"), jobs 0, failed = the
    reason; due with jobs 2 / max 4 -> "Texture from cut · Glutstulpen (+2 image jobs, up to 4 when an attempt is
    rejected)"; due with jobs 1 / max 1 -> "(+1 image jobs)".
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_key_isolation_"))
os.environ.setdefault("STORAGE_DIR", str(_TMP / "world"))
from app.core import paths  # noqa: E402

paths.init(str(_TMP / "world"))

from app.core import garment_template as gt  # noqa: E402
from app.core import garment_template_cut as gtc  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402
from app.core import cut_texture_post  # noqa: E402

_fails = []
_n = 0


def check(name, ok, detail=None):
    global _n
    _n += 1
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or detail is None else f"   {detail}"))
    if not ok:
        _fails.append(name)


def V(**kw):
    return gt.validate_params(kw)[0]


CASES = {
    "skirt": V(kind="skirt"),
    "dress_straps": V(kind="dress", shoulders="straps", neckline="crew"),
    "dress_strapless": V(kind="dress", shoulders="strapless"),
    "top_covered": V(kind="top", shoulders="covered", sleeves="short"),
    "top_corset": V(kind="top", shoulders="strapless", neckline="straight"),
    "top_corset_straps": V(kind="top", shoulders="straps", neckline="sweetheart"),
    "top_cups": V(kind="top", cups="bra", cup_style="balconette"),
    "jacket": V(kind="jacket"),
    "trousers": V(kind="trousers"), "briefs": V(kind="briefs"), "bra": V(kind="bra"), "gloves": V(kind="gloves"),
    "tights": V(kind="tights"),
}
FITTED = ("trousers", "briefs", "bra", "gloves", "tights")
# the table of the docstring, typed in by hand
BUILD = {"skirt": "skirt", "dress_straps": "dress", "dress_strapless": "dress", "top_covered": "top",
         "top_corset": "top", "top_corset_straps": "top", "top_cups": "bra", "jacket": "jacket",
         **{k: k for k in FITTED}}
GROUP = {**BUILD, "top_corset": "corset_top", "top_corset_straps": "corset_top"}
PANEL = {"skirt", "dress_straps", "dress_strapless", "top_corset", "top_corset_straps", "jacket"}
LEG = {"skirt", "dress_straps", "dress_strapless"}
STRAP = {"dress_straps"}
CORSET = {"top_corset", "top_corset_straps"}
CORSET_STRAPS = {"top_corset_straps"}
NECK = {"dress_straps", "dress_strapless", "jacket"}
BRA_EDGE = {"bra", "top_cups"}
CUP_TIP = {"top_cups"}
NO_BODICE_DRESS = {"dress_strapless"}

KINDS = ("skirt", "dress", "top", "jacket", "trousers", "briefs", "bra", "gloves", "tights")
GROUPS = ("top", "corset_top", "skirt", "jacket", "dress") + FITTED


@contextmanager
def bump_attr(mod, name):
    old = getattr(mod, name)
    setattr(mod, name, old + 1000 if isinstance(old, int) else (old + 0.5 if isinstance(old, float) else "f" * 12))
    try:
        yield
    finally:
        setattr(mod, name, old)


@contextmanager
def bump_entry(mod, name, key):
    table = getattr(mod, name)
    old = table[key]
    with patch.dict(table, {key: old + 1000 if isinstance(old, int) else "f" * 12}):
        yield


def tsig_of(p, **kw):
    return gt.tsig(p, base_sha=kw.get("base", "b" * 64), texture_sha=kw.get("texture", "t"), lower=kw.get("lower", []))


def cut_of(p, **kw):
    return gtc.cut_sig(p, base_sha=kw.get("base", "b" * 64), lower=kw.get("lower", []))


KNOBS = []   # (label, context factory, tsig-moved set, cut-moved set)
for k in KINDS:
    moved = {c for c, b in BUILD.items() if b == k}
    KNOBS.append((f"TEMPLATE_VERSIONS[{k}]", lambda k=k: bump_entry(gt, "TEMPLATE_VERSIONS", k), moved, moved))
for k in FITTED:
    moved = {c for c, b in BUILD.items() if b == k}
    KNOBS.append((f"FITTED_VERSIONS[{k}]", lambda k=k: bump_entry(gt, "FITTED_VERSIONS", k), moved, moved))
    KNOBS.append((f"FITTED_PATTERN_KEYS[{k}]", lambda k=k: bump_entry(gtc, "FITTED_PATTERN_KEYS", k), set(), moved))
for g in GROUPS:
    moved = {c for c, gg in GROUP.items() if gg == g}
    KNOBS.append((f"UV_PATTERN_KEYS[{g}]", lambda g=g: bump_entry(gtc, "UV_PATTERN_KEYS", g), set(), moved))
KNOBS += [
    ("PANEL_VERSION", lambda: bump_attr(gt, "PANEL_VERSION"), PANEL, PANEL),
    ("LEG_VERSION", lambda: bump_attr(gt, "LEG_VERSION"), LEG, LEG),
    ("STRAP_VERSION", lambda: bump_attr(gt, "STRAP_VERSION"), STRAP, STRAP),
    ("CORSET_VERSION", lambda: bump_attr(gt, "CORSET_VERSION"), CORSET, CORSET),
    ("CORSET_STRAPS_VERSION", lambda: bump_attr(gt, "CORSET_STRAPS_VERSION"), CORSET_STRAPS, CORSET_STRAPS),
    ("BRA_EDGE_VERSION", lambda: bump_attr(gt, "BRA_EDGE_VERSION"), BRA_EDGE, BRA_EDGE),
    ("CUP_TIP_VERSION", lambda: bump_attr(gt, "CUP_TIP_VERSION"), CUP_TIP, CUP_TIP),
    ("STRAPLESS_UNDERARM_M", lambda: bump_attr(gt, "STRAPLESS_UNDERARM_M"), NO_BODICE_DRESS, set()),
    ("NECK_VERSION", lambda: bump_attr(gt, "NECK_VERSION"), set(), NECK),
    ("CORSET_DARTS_KEYS[strapless]", lambda: bump_entry(gtc, "CORSET_DARTS_KEYS", "strapless"), set(),
     {"top_corset"}),
    ("CORSET_DARTS_KEYS[straps]", lambda: bump_entry(gtc, "CORSET_DARTS_KEYS", "straps"), set(),
     {"top_corset_straps"}),
]

print("smoke_key_isolation")
base_t = {c: tsig_of(p) for c, p in CASES.items()}
base_c = {c: cut_of(p) for c, p in CASES.items()}
for label, ctx, want_t, want_c in KNOBS:
    with ctx():
        got_t = {c for c, p in CASES.items() if tsig_of(p) != base_t[c]}
        got_c = {c for c, p in CASES.items() if cut_of(p) != base_c[c]}
    check(f"[A] {label}: tsig moves exactly for {sorted(want_t) or 'none'}", got_t == want_t, sorted(got_t))
    check(f"[B] {label}: cut_sig moves exactly for {sorted(want_c) or 'none'}", got_c == want_c, sorted(got_c))

glove_t = {label for label, ctx, wt, wc in KNOBS if "gloves" in wt}
glove_c = {label for label, ctx, wt, wc in KNOBS if "gloves" in wc}
check("[A] the gloves' tsig: only their own template and fitted versions",
      glove_t == {"TEMPLATE_VERSIONS[gloves]", "FITTED_VERSIONS[gloves]"}, sorted(glove_t))
check("[B] the gloves' cut_sig: only their own versions and pins",
      glove_c == {"TEMPLATE_VERSIONS[gloves]", "FITTED_VERSIONS[gloves]", "FITTED_PATTERN_KEYS[gloves]",
                  "UV_PATTERN_KEYS[gloves]"}, sorted(glove_c))

# [C]


def md5_at(commit, rel):
    out = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{rel}"], capture_output=True, check=True).stdout
    return hashlib.md5(out).hexdigest()[:12]


check("[C] TEMPLATE_VERSIONS: every built kind at 10", gt.TEMPLATE_VERSIONS == {k: 10 for k in KINDS},
      gt.TEMPLATE_VERSIONS)
check("[C] FITTED_VERSIONS: every fitted kind at 1", gt.FITTED_VERSIONS == {k: 1 for k in FITTED}, gt.FITTED_VERSIONS)
try:
    uv_old = md5_at("ac232ef4d", "app/blender/scripts/uv_pattern.py")
    fp_old = md5_at("ac232ef4d", "app/blender/scripts/fitted_pattern.py")
    top_old = md5_at("c926b67f0", "app/blender/scripts/uv_pattern.py")
    cd_old = md5_at("ac232ef4d", "app/blender/scripts/corset_darts.py")
    fam_old = {}
    for _fam, _files in (("top", ("front_plain", "front_decorated", "back")),
                         ("fitted", ("fitted_front_plain", "fitted_front_decorated", "fitted_back"))):
        _texts = [subprocess.run(["git", "-C", str(ROOT), "show",
                                  f"ac232ef4d:shared/templates/image/garment_cut_texture_{f}.md"],
                                 capture_output=True, check=True).stdout.decode("utf-8") for f in _files]
        fam_old[_fam] = hashlib.md5("\0".join(_texts).encode("utf-8")).hexdigest()
except (OSError, subprocess.CalledProcessError) as e:
    print(f"NOTE [C] git show failed ({e}): [C] is skipped")
    uv_old = fp_old = top_old = cd_old = fam_old = None
if uv_old:
    check("[C] CORSET_DARTS_KEYS: both variants at ac232ef4d's md5",
          gtc.CORSET_DARTS_KEYS == {"strapless": cd_old, "straps": cd_old}, (gtc.CORSET_DARTS_KEYS, cd_old))
    PKINDS = ("", "top", "skirt", "dress", "jacket", "strapless") + FITTED
    check("[C] PROMPT_KEYS: \"\" and top at the top files' md5 at ac232ef4d, every other kind at the fitted files'",
          gct.PROMPT_KEYS == {k: fam_old["top" if k in ("", "top") else "fitted"] for k in PKINDS},
          (gct.PROMPT_KEYS, fam_old))
    check("[C] UV_PATTERN_KEYS: every group but top at ac232ef4d's md5, top at c926b67f0's",
          gtc.UV_PATTERN_KEYS == {**{g: uv_old for g in GROUPS}, "top": top_old}, (gtc.UV_PATTERN_KEYS, uv_old))
    check("[C] FITTED_PATTERN_KEYS: every fitted kind at ac232ef4d's md5",
          gtc.FITTED_PATTERN_KEYS == {k: fp_old for k in FITTED}, gtc.FITTED_PATTERN_KEYS)
    g = CASES["gloves"]
    want = hashlib.md5(json.dumps({"params": gtc.cut_params(g), "version": 10, "uv_pattern": uv_old,
                                   "base": "b" * 64, "lower": [], "fitted": 1, "fitted_pattern": fp_old},
                                  sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
    check("[C] a default glove's cut key = the payload it had at ac232ef4d", cut_of(g) == want, (cut_of(g), want))

# [D]
check("[D] uv_pattern.py reviewed (UV_PATTERN_REVIEWED = its md5; else decide which groups' pins move)",
      gtc.file_sha(gtc.UV_PATTERN_FILE) == gtc.UV_PATTERN_REVIEWED,
      (gtc.file_sha(gtc.UV_PATTERN_FILE), gtc.UV_PATTERN_REVIEWED))
check("[D] fitted_pattern.py reviewed (FITTED_PATTERN_REVIEWED = its md5; else decide which kinds' pins move)",
      gtc.file_sha(gtc.FITTED_PATTERN_FILE) == gtc.FITTED_PATTERN_REVIEWED,
      (gtc.file_sha(gtc.FITTED_PATTERN_FILE), gtc.FITTED_PATTERN_REVIEWED))

check("[D] corset_darts.py reviewed (CORSET_DARTS_REVIEWED = its md5; else decide which variants' pins move)",
      gtc.file_sha(gtc.CORSET_DARTS_FILE) == gtc.CORSET_DARTS_REVIEWED,
      (gtc.file_sha(gtc.CORSET_DARTS_FILE), gtc.CORSET_DARTS_REVIEWED))
for _fam in ("top", "fitted"):
    check(f"[D] the {_fam} prompt files reviewed (PROMPT_REVIEWED = their md5; else decide which kinds' pins move)",
          gct.PROMPT_SHAS[_fam] == gct.PROMPT_REVIEWED[_fam], (gct.PROMPT_SHAS[_fam], gct.PROMPT_REVIEWED[_fam]))

# [E]
g = CASES["gloves"]
g2 = V(kind="gloves", length="elbow")
check("[E] the glove's own length moves tsig and cut_sig", tsig_of(g2) != tsig_of(g) and cut_of(g2) != cut_of(g))
check("[E] another base moves both", tsig_of(g, base="c" * 64) != tsig_of(g) and cut_of(g, base="c" * 64) != cut_of(g))
check("[E] a lower token moves both", tsig_of(g, lower=["x:1"]) != tsig_of(g) and cut_of(g, lower=["x:1"]) != cut_of(g))
check("[E] the texture sha moves tsig (cut_sig takes no texture)", tsig_of(g, texture="u") != tsig_of(g))

# [F]


def item(iid, slots, params):
    return {"id": iid, "category": "outfit_piece",
            "outfit_piece": {"slots": slots, "mesh_mode": "template", "template": {"params": params}}}


ITEMS = {
    "glove": item("glove", ["hands"], {"kind": "gloves", "length": "elbow"}),
    "bra": item("bra", ["underwear_top"], {"kind": "bra"}),
    "briefs": item("briefs", ["underwear_bottom"], {"kind": "briefs"}),
    "tights": item("tights", ["legs"], {"kind": "tights"}),
    "top": item("top", ["top"], {"kind": "top", "shoulders": "covered", "sleeves": "short"}),
    "trousers": item("trousers", ["bottom"], {"kind": "trousers"}),
}
with patch("app.models.inventory.get_item", lambda i: ITEMS.get(str(i))):
    worn = ["bra", "briefs", "tights", "top"]
    tpl, own = gt.inner_pieces("glove", "gloves", worn)
    check("[F] the gloves lie over none of bra, briefs, tights, a sleeved top", (tpl, own) == ([], []),
          ([t[0] for t in tpl], [o[0] for o in own]))
    tpl2, _own2 = gt.inner_pieces("trousers", "trousers", ["briefs", "glove", "bra"])
    check("[F] control: the trousers lie over the briefs (and not over the gloves or the bra)",
          [t[0] for t in tpl2] == ["briefs"], [t[0] for t in tpl2])
b1 = tsig_of(V(kind="briefs"))
b2 = tsig_of(V(kind="briefs", rise="high"))
tr = CASES["trousers"]
check("[F] control: a change of the briefs' drape moves the trousers' tsig",
      tsig_of(tr, lower=[f"briefs:{b1}"]) != tsig_of(tr, lower=[f"briefs:{b2}"]))

# [G]
PKIND = {"skirt": "skirt", "dress_straps": "dress", "dress_strapless": "dress", "top_covered": "top",
         "top_corset": "strapless", "top_corset_straps": "strapless", "top_cups": "bra", "jacket": "jacket",
         **{k: k for k in FITTED}}
FAMILY = {c: ("top" if c == "top_covered" else "fitted") for c in CASES}
check("[G] prompt kinds as derived", {c: gct.prompt_kind(p) for c, p in CASES.items()} == PKIND,
      {c: gct.prompt_kind(p) for c, p in CASES.items()})
got_family = {c: gct.prompt_family(gct.prompt_kind(p)) for c, p in CASES.items()}
check("[G] prompt families as derived", got_family == FAMILY, got_family)


def csig_of(p):
    return gct.csig("i", "m", "k", gct.prompt_sha_of(gct.prompt_kind(p)))


before = {c: csig_of(p) for c, p in CASES.items()}
glove_keys = set()
for k in sorted(gct.PROMPT_KEYS):
    with patch.dict(gct.PROMPT_KEYS, {k: "f" * 32}):
        moved = {c for c, p in CASES.items() if csig_of(p) != before[c]}
    if "gloves" in moved:
        glove_keys.add(k)
    check(f"[G] PROMPT_KEYS[{k!r}] moves exactly the csig of prompt kind {k!r}",
          moved == {c for c in CASES if PKIND[c] == k}, sorted(moved))
check("[G] the gloves' csig: only PROMPT_KEYS['gloves']", glove_keys == {"gloves"}, sorted(glove_keys))
with patch.dict(gct.PROMPT_SHAS, {"top": "f" * 32, "fitted": "e" * 32}):
    moved = {c for c, p in CASES.items() if csig_of(p) != before[c]}
check("[G] a reworded prompt file (the live PROMPT_SHAS) moves no csig", moved == set(), sorted(moved))
check("[G] a kind outside the table keys like a piece without parameters",
      gct.prompt_sha_of("cape") == gct.PROMPT_KEYS[""] and gct.csig("i", "m", "k") == gct.csig("i", "m", "k",
                                                                                              gct.PROMPT_KEYS[""]))

# [H]
CUT = _TMP / "cut"
CUT.mkdir(parents=True, exist_ok=True)
psha = gct.PROMPT_KEYS["gloves"]


def write_record(sig, item_sha, post):
    rec = {"csig": sig, "state": "ready", "islands_sha": "i", "item_sha": item_sha, "back_sha": "k",
           "prompt_sha": psha, "post_version": post, "created_at": f"2026-11-25T10:00:0{post % 10}",
           "item_px": 1024, "upscale": None,
           "jobs": {"front": {"state": "ready", "attempts": [{"attempt": 1, "state": "ready"}]},
                    "back": {"state": "ready", "attempts": [{"attempt": 1, "state": "ready"}]}}}
    (CUT / f"glove_{sig}.json").write_text(json.dumps(rec), encoding="utf-8")
    for job in ("front", "back"):
        (CUT / f"glove_{sig}.raw_{job}.png").write_bytes(f"{sig}-{job}".encode())


with patch.object(gct, "cut_dir", lambda _c: CUT):
    p0 = cut_texture_post.POST_VERSION
    s0 = gct.csig("i", "m", "k", psha)
    write_record(s0, "m", p0)
    s_other = gct.csig("i", "m2", "k", psha)
    write_record(s_other, "m2", p0)
    with patch.object(cut_texture_post, "POST_VERSION", p0 + 1):
        s1 = gct.csig("i", "m", "k", psha)
        check("[H] a new POST_VERSION gives a new csig", s1 != s0)
        reuse = gct.reused_jobs("Char", "glove", s1, ["front", "back"])
        check("[H] both answers re-used from the predecessor (0 image jobs)",
              sorted(reuse) == ["back", "front"] and all(e.get("reused_from") == s0 for e in reuse.values())
              and Path(reuse["back"]["raw_from"]).read_bytes() == f"{s0}-back".encode(),
              {k: (v.get("reused_from"), v.get("raw_from")) for k, v in reuse.items()})
        check("[H] another item picture is no predecessor", [s for s, _r in gct.predecessors("Char", "glove", s1)] == [s0],
              [s for s, _r in gct.predecessors("Char", "glove", s1)])
        only = gct.reused_jobs("Char", "glove", s1, ["front", "back"], only="back")
        check("[H] Redo back re-uses the front alone", sorted(only) == ["front"], sorted(only))
        # the negative case: S1's own record, back re-posted from S0 and rejected by the new post-processing
        own = {"csig": s1, "state": "rejected", "islands_sha": "i", "item_sha": "m", "back_sha": "k",
               "prompt_sha": psha, "post_version": p0 + 1, "created_at": "2026-11-25T11:00:00",
               "jobs": {"front": {"state": "ready", "attempts": [{"attempt": 1, "state": "ready"}]},
                        "back": {"state": "rejected", "reused_from": s0,
                                 "attempts": [{"attempt": 1, "state": "ready"}]}}}
        (CUT / f"glove_{s1}.json").write_text(json.dumps(own), encoding="utf-8")
        (CUT / f"glove_{s1}.raw_front.png").write_bytes(f"{s1}-front".encode())
        (CUT / f"glove_{s1}.raw_back.png").write_bytes(f"{s0}-back".encode())
        again = gct.reused_jobs("Char", "glove", s1, ["front", "back"])
        check("[H] a re-posted answer the new post-processing rejected is not taken again (the back renders)",
              sorted(again) == ["front"] and "reused_from" not in again["front"],
              {k: v.get("reused_from") for k, v in again.items()})
        own["jobs"]["back"] = {"state": "failed", "reason": "x"}
        (CUT / f"glove_{s1}.json").write_text(json.dumps(own), encoding="utf-8")
        again = gct.reused_jobs("Char", "glove", s1, ["front", "back"])
        check("[H] a back entry without a verdict (failed) still takes the predecessor's answer",
              sorted(again) == ["back", "front"] and again["back"].get("reused_from") == s0
              and "reused_from" not in again["front"], {k: v.get("reused_from") for k, v in again.items()})
        for f in CUT.glob(f"glove_{s1}.*"):
            f.unlink()          # S1's record is no part of the check below
    check("[H] under the same POST_VERSION a record is no predecessor of its own csig",
          gct.predecessors("Char", "glove", s0) == [])

# [I]
GLUT = {"state": "rejected", "reason": "Back: back weave 16.88 > 14.01",
        "jobs": {"front": {"state": "ready", "attempts": [{"attempt": 1, "state": "ready",
                                                           "routing": {"routing": {"position": 1}}}]},
                 "back": {"state": "rejected", "round": 0,
                          "attempts": [{"attempt": 1, "state": "rejected", "routing": {"routing": {"position": 1}}},
                                       {"attempt": 2, "state": "rejected",
                                        "routing": {"routing": {"position": 2},
                                                    "attempt_entry": {"attempt": 2, "position": 2}}}]}}}
CHAIN = [("MiniMax-H3-Image", "rule", 1), ("P-H3-Image", "rule", 2)]


def variant(**changes):
    rec = json.loads(json.dumps(GLUT))
    for k, v in changes.items():
        if k == "attempt2":
            rec["jobs"]["back"]["attempts"][1].update(v)
        elif k == "back":
            rec["jobs"]["back"].update(v)
        else:
            rec[k] = v
    return rec


with patch("app.imagegen.routing.chain_for", lambda *a, **k: list(CHAIN)):
    check("[I] Glut's record (no chain recorded): no retry", gct.retry_changes_request(GLUT) is False)
    check("[I] chain == now: no retry",
          gct.retry_changes_request(variant(chain=["MiniMax-H3-Image", "P-H3-Image"])) is False)
    check("[I] chain != now: retry", gct.retry_changes_request(variant(chain=["MiniMax-H3-Image"])) is True)
    check("[I] attempt 2 behind its intended entry: retry",
          gct.retry_changes_request(variant(attempt2={"routing": {"fallback_from": {"position": 2}}})) is True)
    check("[I] attempt 2 failed: retry", gct.retry_changes_request(variant(attempt2={"state": "failed"})) is True)
    check("[I] re-posted from a predecessor: retry",
          gct.retry_changes_request(variant(back={"reused_from": "abcdefabcdef"})) is True)
    check("[I] record failed: retry", gct.retry_changes_request(variant(state="failed")) is True)
    check("[I] a rejected record without a judged attempt: retry",
          gct.retry_changes_request({"state": "rejected", "reason": "x"}) is True)

# [J]
check("[J] the back's seed of csig a28d4d8cf4b7, round 0 = 579685773 (hub job f32b5bed)",
      gct.job_seed("a28d4d8cf4b7", "back", 0) == 579685773, gct.job_seed("a28d4d8cf4b7", "back", 0))
check("[J] round 1 = 579785773", gct.job_seed("a28d4d8cf4b7", "back", 1) == 579785773,
      gct.job_seed("a28d4d8cf4b7", "back", 1))
check("[J] the front's round 0 = 579685772", gct.job_seed("a28d4d8cf4b7", "front", 0) == 579685772)
check("[J] next_round", [gct.next_round(None), gct.next_round({"attempts": [{}]}),
                         gct.next_round({"round": 1, "attempts": [{}]}), gct.next_round({"state": "ready"})]
      == [0, 1, 2, 0])

# [K]
from app.core import figure_build  # noqa: E402
NAME = "Glutstulpen"
with patch.object(figure_build, "_item_name", lambda _i: NAME):
    for st, want_label, want_jobs, want_failed in (
            ({"state": gct.BUILD_FAILED, "reason": "Back: back weave 16.88 > 14.01", "jobs": 0, "max": 0,
              "estimate": False, "retry": "", "held": True},
             f"Texture from cut · {NAME}: rejected (0 image jobs — Redo in the texture dialog tries a new seed)", 0,
             "Back: back weave 16.88 > 14.01"),
            ({"state": gct.BUILD_DUE, "reason": "", "jobs": 2, "max": 4, "estimate": False, "retry": "", "held": False},
             f"Texture from cut · {NAME} (+2 image jobs, up to 4 when an attempt is rejected)", 2, ""),
            ({"state": gct.BUILD_DUE, "reason": "", "jobs": 1, "max": 1, "estimate": False, "retry": "", "held": False},
             f"Texture from cut · {NAME} (+1 image jobs)", 1, "")):
        with patch.object(gct, "build_state", lambda *_a, st=st, **_k: dict(st)):
            step = figure_build._cut_texture_step("Char", "glove")
        check(f"[K] {st['state']} held={st['held']} max={st['max']}: label, jobs, failed",
              (step.label, step.jobs, step.failed) == (want_label, want_jobs, want_failed),
              (step.label, step.jobs, step.failed))

print(f"\n{_n - len(_fails)}/{_n} checks passed")
if _fails:
    print("FAILED:", _fails)
sys.exit(1 if _fails else 0)
