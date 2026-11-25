"""Round 2026-11-25 (plan "cups in a top", task 1): a top can carry bra cups — the field ``cups`` (none | bra), the one
switch ``build_kind`` ("bra" for a cupped top), the field lists ``fields_of`` and the two parameter views: what is
STORED (``stored_params``: a top keeps both field sets, the top's and the cups') and what is ACTIVE
(``validate_params``: every field outside ``fields_of`` at its ``PARAM_SPEC`` default — the set every build, key,
region and prompt path reads). Pure functions, no server, no world DB, no Blender. Every expectation is derived by
hand from the schema:

[P1] ``validate_params({"kind": "top"})``: ``cups`` is not given -> its default "none"; ``shoulders`` not given on a
     top -> "covered" (A221, today's rule).
[P2] A cupped top ``{kind top, cups bra, cup_style balconette, shoulders straps, neckline sweetheart, sleeves short,
     underband_m 0.05}``: ``fields_of`` = ``TOP_CUPS_FIELDS`` (kind, cups, fabric, opacity, length_m, cup_style,
     cup_coverage, push_up, center_gore, closure, straps, texture, sleeve_print) -> the ACTIVE set keeps
     cup_style balconette; shoulders / neckline / sleeves / underband_m are not in that list -> their PARAM_SPEC
     defaults strapless / crew / none / 0.02. The STORED set keeps shoulders straps and neckline sweetheart (parked
     top fields, normalised as a top's: a top with straps is a corset top, A221, so its parked sleeves are "none" —
     the plan's "sleeves short" would contradict that rule; [P8b] proves parked sleeves on a covered top);
     ``underband_m`` is in neither top list (a bra's band, the top's band comes from its length) -> 0.02 there too.
[P3] ``{kind bra, cups bra}``: cups is a top's field only -> "none".
[P4] "cups" is never in ``keyed_params`` of a piece without cups (a top, a bra): the key of every existing piece
     stays byte for byte.
[P5] ``keyed_params`` of a cupped top holds cups "bra" and the cup fields cup_style, cup_coverage, push_up,
     center_gore, closure, straps.
[P6] Pinned to d0bae1f34 (``git archive`` of that commit, run in a subprocess — never ``HEAD``): for a covered
     T-shirt, Lirien's stored top (the literal below, as the world holds it), a strapless corset top and a bra,
     ``keyed_params(validate_params(p))`` equals the old one, and ``validate_params(p)`` less its new key "cups" equals
     the old one (the active set of a piece without cups is unchanged). Also the full keys: ``tsig`` and
     ``garment_template_cut.cut_sig`` with fixed other inputs (base0 / tex0 / [item_a]) equal the old ones.
[P7] Round trip none -> bra -> none (E6), T0 = {kind top, shoulders straps, neckline sweetheart, length_m 0.27,
     straps wide, fabric leather_rough}: S1 = stored(T0 + cups bra + cup_style balconette), S2 = stored(S1 + cups
     none) -> S2 shoulders straps and neckline sweetheart (never the schema default strapless, the review's finding);
     keyed_params(validate(S2)) == keyed_params(validate(T0)) (same key: the old drape is reused); S2 cup_style
     balconette (the cup choice stays parked for the next switch).
[P8] Parked fields key nothing: A = T0 + cups bra, B = A + neckline crew + sleeves long -> equal keyed_params; and
     ``body_regions(validate(B))`` has no "arm" (a cupped top has no bodice, so no sleeves; review focus 7).
[P8b] A covered top with cups and long sleeves {kind top, cups bra, shoulders covered, sleeves long}: the STORED set
     keeps sleeves long (a covered top's sleeves, parked), the ACTIVE set has sleeves none and its ``body_regions``
     no "arm"; ``has_sleeves`` of the active set is False.
[P9] ``build_kind``: a cupped top -> "bra"; a top without cups -> "top"; a bra -> "bra"; a cupped top's raw stored
     dict (not validated, as ``bust_shaping`` reads it) -> "bra".

Usage: ./.venv/bin/python scripts/smoke_top_cups_params.py
"""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-top-cups-params-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


def attempt(label, fn):
    try:
        return fn()
    except Exception as exc:          # a missing field / function on the old code fails the check, not the smoke
        check(label, False, f"{type(exc).__name__}: {exc}")
        return None


validate = gt.validate_params
stored = getattr(gt, "stored_params", None)

# [P1]
p1 = validate({"kind": "top"})[0]
check("[P1] top: cups none, shoulders covered", p1.get("cups") == "none" and p1["shoulders"] == "covered", p1.get("cups"))

# [P2]
RAW2 = {"kind": "top", "cups": "bra", "cup_style": "balconette", "shoulders": "straps", "neckline": "sweetheart",
        "sleeves": "short", "underband_m": 0.05}
a2, e2 = validate(RAW2)
check("[P2] no errors", not e2, e2)
check("[P2] active: cups bra, balconette kept", a2.get("cups") == "bra" and a2["cup_style"] == "balconette", a2)
check("[P2] active: top fields at their schema defaults",
      (a2["shoulders"], a2["neckline"], a2["sleeves"], a2["underband_m"]) == ("strapless", "crew", "none", 0.02),
      (a2["shoulders"], a2["neckline"], a2["sleeves"], a2["underband_m"]))
s2 = attempt("[P2] stored_params exists", lambda: stored(RAW2)[0])
if s2 is not None:
    check("[P2] stored: parked top fields kept",
          (s2["shoulders"], s2["neckline"], s2["sleeves"]) == ("straps", "sweetheart", "none"), s2)
    check("[P2] stored: underband_m in neither top list -> 0.02", s2["underband_m"] == 0.02, s2["underband_m"])
    check("[P2] stored: cups and cup fields kept", s2["cups"] == "bra" and s2["cup_style"] == "balconette", s2)

# [P3]
p3 = validate({"kind": "bra", "cups": "bra"})[0]
check("[P3] cups only on a top", p3.get("cups") == "none", p3.get("cups"))

# [P4]
check("[P4] top without cups: cups not keyed", "cups" not in gt.keyed_params(validate({"kind": "top"})[0]))
check("[P4] bra: cups not keyed", "cups" not in gt.keyed_params(validate({"kind": "bra"})[0]))

# [P5]
k5 = gt.keyed_params(a2)
check("[P5] cupped top keys cups and its cup fields",
      k5.get("cups") == "bra" and all(f in k5 for f in ("cup_style", "cup_coverage", "push_up", "center_gore",
                                                         "closure", "straps")), sorted(k5))

# [P6] pinned to the base commit
TSHIRT = {"kind": "top", "shoulders": "covered", "sleeves": "short", "neckline": "crew", "length_m": 0.6, "fit": 0.4,
          "fabric": "medium", "texture": "cut"}
LIRIEN = {"kind": "top", "length_m": 0.27, "flare": 0.3, "waist_height": "natural", "slit": "none", "slit_m": 0.0,
          "shoulders": "straps", "sleeves": "none", "band_m": 0.025, "band_drop_m": 0.05, "lacing": "none",
          "lace_depth_m": 0.15, "sleeve_fit": 0.3, "fit": 0.4, "neckline": "sweetheart", "neck_depth_m": 0.08,
          "front": "closed", "collar": "none", "placket": "none", "buttons": 0, "fabric": "leather_rough",
          "opacity": 0.4, "rise": "mid", "leg_cut": 0.5, "back_coverage": 1.0, "side_width_m": 0.05, "gusset_m": 0.06,
          "waistband": "thin", "leg_length_m": 0.0, "sides": "fabric", "string_width_m": 0.008,
          "cup_style": "molded", "cup_coverage": 0.7, "push_up": 0.0, "underband_m": 0.02, "center_gore": "narrow",
          "closure": "back_hook", "straps": "thin", "fingers": "full", "length": "wrist", "cuff": "none",
          "tights_style": "tights", "feet": "closed", "garters": "none", "trouser_length": "full",
          "leg_shape": "straight", "seat": "regular", "trouser_waist": "belt", "fly": "zip", "hem": "plain",
          "texture": "cut", "sleeve_print": "plain"}
CORSET = {"kind": "top", "shoulders": "strapless", "neckline": "sweetheart", "neck_depth_m": 0.06, "length_m": 0.45,
          "fit": 0.1, "fabric": "stiff"}
BRA = {"kind": "bra", "cup_style": "balconette", "cup_coverage": 0.6, "push_up": 0.8, "center_gore": "wide",
       "closure": "none", "straps": "wide", "fabric": "leather_rough", "underband_m": 0.05}
CASES = {"tshirt": TSHIRT, "lirien": LIRIEN, "corset": CORSET, "bra": BRA}
PROBE = r"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.core import paths
s = Path(tempfile.mkdtemp())
paths.init(s / "world"); paths.init_instance(s / "instance")
from app.core import garment_template as gt, garment_template_cut as gtc
out = {}
for name, raw in json.loads(sys.argv[2]).items():
    p, _e = gt.validate_params(raw)
    out[name] = {"active": p, "keyed": gt.keyed_params(p),
                 "tsig": gt.tsig(p, base_sha="base0", texture_sha="tex0", lower=["item_a"]),
                 "cut_sig": gtc.cut_sig(p, base_sha="base0", lower=["item_a"])}
print(json.dumps(out))
"""
OLD = "d0bae1f34"


def probe(repo):
    r = subprocess.run([sys.executable, "-c", PROBE, str(repo), json.dumps(CASES)], capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(repo)})
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


arc = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", OLD, "app", "shared/templates",
                      "shared/languages"], capture_output=True)
if arc.returncode != 0:
    print(f"SKIP [P6] {OLD} not in this checkout")
else:
    old_dir = _SCRATCH / "old"
    old_dir.mkdir()
    tar = _SCRATCH / "old.tar"
    tar.write_bytes(arc.stdout)
    with tarfile.open(tar) as tf:
        tf.extractall(old_dir, filter="data")
    new, old = probe(ROOT), probe(old_dir)
    for name in CASES:
        check(f"[P6] {name}: keyed_params as at {OLD}", new[name]["keyed"] == old[name]["keyed"],
              (new[name]["keyed"], old[name]["keyed"]))
        active = {k: v for k, v in new[name]["active"].items() if k != "cups"}
        check(f"[P6] {name}: active set less cups as at {OLD}", active == old[name]["active"],
              {k: (active.get(k), old[name]["active"].get(k)) for k in set(active) | set(old[name]["active"])
               if active.get(k) != old[name]["active"].get(k)})
        check(f"[P6] {name}: tsig / cut_sig as at {OLD}",
              (new[name]["tsig"], new[name]["cut_sig"]) == (old[name]["tsig"], old[name]["cut_sig"]),
              (new[name]["tsig"], new[name]["cut_sig"], old[name]["tsig"], old[name]["cut_sig"]))

# [P7] round trip none -> bra -> none
T0 = {"kind": "top", "shoulders": "straps", "neckline": "sweetheart", "length_m": 0.27, "straps": "wide",
      "fabric": "leather_rough"}
S1 = attempt("[P7] stored_params", lambda: stored({**T0, "cups": "bra", "cup_style": "balconette"})[0])
if S1 is not None:
    S2 = stored({**S1, "cups": "none"})[0]
    check("[P7] back to none: shoulders straps, neckline sweetheart",
          (S2["shoulders"], S2["neckline"]) == ("straps", "sweetheart"), (S2["shoulders"], S2["neckline"]))
    check("[P7] back to none: the same key as before",
          gt.keyed_params(validate(S2)[0]) == gt.keyed_params(validate(T0)[0]))
    check("[P7] the cup choice stays parked", S2["cup_style"] == "balconette", S2["cup_style"])

# [P8] parked fields key nothing
A = {**T0, "cups": "bra"}
B = {**A, "neckline": "crew", "sleeves": "long"}
check("[P8] parked neckline / sleeves: equal keys", gt.keyed_params(validate(A)[0]) == gt.keyed_params(validate(B)[0]))
regions = gt.body_regions(validate(B)[0])
check("[P8] body_regions of a cupped top with parked long sleeves: no arm", "arm" not in regions, sorted(regions))

# [P8b] parked sleeves of a covered top
RAW8 = {"kind": "top", "cups": "bra", "shoulders": "covered", "sleeves": "long"}
s8 = attempt("[P8b] stored_params", lambda: stored(RAW8)[0])
if s8 is not None:
    a8 = validate(RAW8)[0]
    check("[P8b] stored keeps sleeves long", s8["sleeves"] == "long", s8["sleeves"])
    check("[P8b] active: sleeves none, no arm region, no sleeves",
          a8["sleeves"] == "none" and "arm" not in gt.body_regions(a8) and not gt.has_sleeves(a8),
          (a8["sleeves"], sorted(gt.body_regions(a8))))

# [P9] the one switch
bk = getattr(gt, "build_kind", None)
if bk is None:
    check("[P9] build_kind exists", False)
else:
    check("[P9] cupped top -> bra", bk(a2) == "bra", bk(a2))
    check("[P9] top -> top", bk(p1) == "top", bk(p1))
    check("[P9] bra -> bra", bk(p3) == "bra", bk(p3))
    check("[P9] raw stored cupped top -> bra", bk({"kind": "top", "cups": "bra", "shoulders": "straps"}) == "bra")

print()
print("all checks passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
