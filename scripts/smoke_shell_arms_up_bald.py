"""A190 — piece-only attempt cap, bald worn views and arms-up side views of a shell piece.

Usage: ./.venv/bin/python scripts/smoke_shell_arms_up_bald.py   (no server, no world DB, no image job)

Expected values derived by hand from the A190 design (2026-11-17):
[C1] the cap: ``GHOST_RUN_JOBS`` = 2. Inside one ``run_budget`` a piece-only (ghost) view whose renders are all
     refused spends 2 renders in its first call (attempts 1, 2), then 0 in a second call of the same run (a pair
     repair / re-run) — refused at once with the budget reason. A new run starts again at 2. A worn view (not the
     capped step) keeps ``ATTEMPTS`` = 2 per call, in every call. A ghost view accepted on attempt 1 leaves 1 for a
     repair in the same run.
[C2] prompts: a shell piece's worn front ends with "Their head stays completely bald with a smooth bare scalp." and
     its negative names "hair" (the hair negative) — on a haired plain body too; a piece that is no shell keeps the
     old text (no bald line). A shell side draft has "both arms raised straight up above the head" where the base
     draft said "same A-pose"; its back draft on a haired plain body says "completely bald" (hair=BALD), on a bald
     plain body the back draft is the base draft unchanged (nothing ages).
     Variants: shell front/back on a bald plain body "", on a haired one "bald"; a side "arms_up" / "bald+arms_up";
     a piece that is no shell "" everywhere.
[C3] the pose (``pose_arms_up``), a box torso and one left arm hanging straight down from the shoulder joint
     (0.2, 1.4, 0) to the hand joint (0.2, 0.9, 0), arm vertices weighted 1.0 on LeftArm: after the pose the hand
     vertex (0.2, 0.9, 0) is at (0.2 + 0.5·sin 12°, 1.4 + 0.5·cos 12°, 0) = (0.30396, 1.88907, 0); a vertex weighted
     0.5 on the arm moves half the way; torso vertices do not move; the vertex order is kept (index i of the posed
     body is index i of the rest body). A right arm mirrors: its hand at (-0.30396, 1.88907, 0).
[C4] index mapping through a side view (camera on +x looking along -x, depth = x): the flank vertex (0.15, 1.2, 0)
     lies behind the hanging arm (arm surface at x = 0.2 covers y 0.9..1.4 at z = 0) — hidden at rest; posed, the arm
     is above y = 1.4 at the flank's z, so the flank vertex is the front-most there — seen; the covered mark maps back
     to the same index of the rest mesh.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile  # noqa: E402

from app.core import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="smoke_a190_"))
paths.init(str(TMP))   # before any world-DB module
import numpy as np  # noqa: E402

from app.core import garment_images as gi  # noqa: E402
from app.core import garment_shell as gsh  # noqa: E402
from app.core import shell_base_views as sbv  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# --- [C1] the cap --------------------------------------------------------------------------------------------------
class Kind:
    FROM_WORN_STEP = "ghost"
    EDIT_STEPS = {"worn": {"source": "base"}, "ghost": {"source": "worn"}}

    @staticmethod
    def edit_prompt(*_a, **_k):
        return "p", "n"


renders = []
verdict = {"ok": False}


def fake_render(*_a, **_k):
    renders.append(1)
    return None   # "render failed": a refused attempt


import app.core.expression_regen as er  # noqa: E402
er.render_character_image = fake_render
gi._gate_inputs = lambda *a, **k: ((8, 8), {"source_rgb": None}, None)
gi._accepted = lambda path: False
gi._regate_stored = lambda *a, **k: None
gi._publish = lambda *a, **k: Path("/published")
from contextlib import contextmanager  # noqa: E402


@contextmanager
def fake_square(_source, _refs):
    yield Path("/ref.png"), 8, (0, 0), (8, 8)


gi.square_reference = fake_square


def call(step, view="back"):
    before = len(renders)
    try:
        gi._render_edit_step("C", "item", "abcdef123456", step, view, Kind, profile={}, base=Path("/b"), source=Path("/s"),
                             refs_dir=TMP, final=TMP / "final.png", pair_check=None, prompt_hints=None)
        refused = None
    except gi.GateRefused as e:
        refused = e
    return len(renders) - before, refused


gi._kind_module = lambda item_id: Kind
check("[C1] GHOST_RUN_JOBS = 2", gi.GHOST_RUN_JOBS == 2)
with gi.run_budget():
    n1, r1 = call("ghost")
    n2, r2 = call("ghost")
    n3, _ = call("ghost", "front")
    w1, _ = call("worn")
    w2, _ = call("worn")
check("[C1] first call of a ghost view: 2 renders, refused", n1 == 2 and r1 is not None, f"{n1}")
check("[C1] second call in the same run: 0 renders, budget reason",
      n2 == 0 and r2 is not None and any(rec.get("budget") for rec in r2.records), f"{n2}")
check("[C1] another view has its own 2", n3 == 2, f"{n3}")
check("[C1] the worn step is not capped: 2 + 2", (w1, w2) == (2, 2), f"{w1},{w2}")
with gi.run_budget():
    n4, _ = call("ghost")
check("[C1] a new run starts at 2 again", n4 == 2, f"{n4}")
# accepted on attempt 1 -> 1 left in the run
gi._with_pair = lambda record, pair_check, extra=(): record
gi.crop_back = lambda path, target, *a: Path(target)
gi.read_record = None
er.render_character_image = lambda *a, **k: (renders.append(1), "/rendered.png")[1]
gi._gate_attempt = lambda *a, **k: {"ok": True, "reasons": []}
import app.core.garment_store as gstore  # noqa: E402
gstore.write_record = lambda *a, **k: None
with gi.run_budget():
    a1, _ = call("ghost")
    left = gi.jobs_left("C", "item", "abcdef123456", "ghost", "back", Kind)
check("[C1] accepted on attempt 1: 1 render, 1 left for a repair", a1 == 1 and left == 1, f"{a1},{left}")
check("[C1] outside a run every call has ATTEMPTS", gi.jobs_left("C", "item", "abcdef123456", "ghost", "back", Kind) == 2)

# --- [C2] prompts ---------------------------------------------------------------------------------------------------
from app.core import base_body, garment_clothing as gc  # noqa: E402

ITEM = {"id": "bra", "name": "Bra", "prompt_fragment": "a red bra", "outfit_piece": {"slots": ["underwear_top"], "prompt_fragment": "a red bra",
                                                       "mesh_mode": "shell"}}
gc._item_of = lambda item: ITEM
hair = {"text": ""}
base_body.hair_text = lambda character_name, profile=None: hair["text"]
shell = {"on": True}
sbv._shell_piece = lambda item_id: shell["on"]
gc._profile_of = lambda character_name, profile: {}
base_body._profile_of = lambda character_name, profile: {}
base_body.base_negative = lambda character_name, profile=None, head="": head
prompt, negative = gc.edit_prompt("C", "worn", "front", profile={}, item_id="bra")
check("[C2] shell worn front ends with the bald line", prompt.endswith(sbv.WORN_BALD_LINE), prompt)
check("[C2] its negative names hair", "hair" in negative.split(", "), negative)
hair["text"] = "long red hair"
prompt_h, _ = gc.edit_prompt("C", "worn", "front", profile={}, item_id="bra")
check("[C2] on a haired plain body too", prompt_h.endswith(sbv.WORN_BALD_LINE))
shell["on"] = False
prompt_n, _ = gc.edit_prompt("C", "worn", "front", profile={}, item_id="bra")
check("[C2] not a shell piece: no bald line", sbv.WORN_BALD_LINE not in prompt_n)
check("[C2] variants: no shell -> ''", [sbv.variant_for("C", "bra", v) for v in ("front", "left")] == ["", ""])
shell["on"] = True
check("[C2] variants, haired: bald / bald+arms_up",
      [sbv.variant_for("C", "bra", v) for v in ("front", "back", "left")] == ["bald", "bald", "bald+arms_up"])
side, _ = gc.draft_prompt("C", "worn", profile={}, item_id="bra", view="left")
check("[C2] side draft: arms raised instead of the A-pose",
      "both arms raised straight up above the head" in side and "same A-pose" not in side, side)
back_h, _ = gc.draft_prompt("C", "worn", profile={}, item_id="bra", view="back")
check("[C2] haired: the back draft says completely bald", "completely bald" in back_h, back_h)
hair["text"] = ""
check("[C2] variants, bald plain body: '' / '' / arms_up",
      [sbv.variant_for("C", "bra", v) for v in ("front", "back", "right")] == ["", "", "arms_up"])
back_b, _ = gc.draft_prompt("C", "worn", profile={}, item_id="bra", view="back")
check("[C2] bald plain body: the back draft is the base draft unchanged",
      back_b == base_body.DRAFT_PROMPTS["back"], back_b)
check("[C2] edit texts", sbv.edit_text("bald")[0].endswith(sbv.BALD_TEXT)
      and sbv.edit_text("arms_up")[0].endswith(sbv.ARMS_UP_TEXT)
      and sbv.edit_text("bald+arms_up")[0].endswith(sbv.BALD_AND_ARMS_UP_TEXT))

# --- [C3] the pose --------------------------------------------------------------------------------------------------
names = ["mixamorig:Hips", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand",
         "mixamorig:RightArm", "mixamorig:RightHand"]
heads = {"mixamorig:Hips": np.array([0, 1.0, 0]), "mixamorig:LeftArm": np.array([0.2, 1.4, 0]),
         "mixamorig:LeftForeArm": np.array([0.2, 1.15, 0]), "mixamorig:LeftHand": np.array([0.2, 0.9, 0]),
         "mixamorig:RightArm": np.array([-0.2, 1.4, 0]), "mixamorig:RightHand": np.array([-0.2, 0.9, 0])}
P = np.array([[0.15, 1.2, 0.0],    # 0 torso flank
              [0.2, 0.9, 0.0],     # 1 left hand (weight 1 on LeftHand)
              [0.2, 1.15, 0.0],    # 2 left elbow (0.5 LeftArm + 0.5 Hips)
              [0.0, 1.0, 0.1],     # 3 torso front
              [-0.2, 0.9, 0.0]])   # 4 right hand
J = np.array([[0, 0, 0, 0], [3, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [5, 0, 0, 0]])
Wt = np.array([[1, 0, 0, 0], [1, 0, 0, 0], [0.5, 0.5, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]], float)
Pp = gsh.pose_arms_up(P, J, Wt, names, heads)
t = np.radians(12.0)
want_hand = np.array([0.2 + 0.5 * np.sin(t), 1.4 + 0.5 * np.cos(t), 0.0])
check("[C3] left hand at (0.30396, 1.88907, 0)", np.allclose(Pp[1], want_hand, atol=1e-6), str(Pp[1]))
check("[C3] hand value by hand", np.allclose(want_hand, [0.30396, 1.88907, 0], atol=1e-4))
elbow_full = np.array([0.2 + 0.25 * np.sin(t), 1.4 + 0.25 * np.cos(t), 0.0])
check("[C3] half-weighted elbow moves half the way", np.allclose(Pp[2], P[2] + 0.5 * (elbow_full - P[2]),
                                                                 atol=1e-6), str(Pp[2]))
check("[C3] torso vertices stay", np.allclose(Pp[[0, 3]], P[[0, 3]]))
check("[C3] right arm mirrors", np.allclose(Pp[4], [-0.30396, 1.88907, 0], atol=1e-4), str(Pp[4]))
check("[C3] vertex order kept", Pp.shape == P.shape)

# --- [C4] index mapping through a side view -------------------------------------------------------------------------
# arm surface samples: a line of vertices x = 0.2, y 0.9..1.4, z = 0 (all on LeftArm)
arm = np.c_[np.full(26, 0.2), np.linspace(0.9, 1.4, 26), np.zeros(26)]
Pb = np.vstack([P[:1], arm])
Jb = np.vstack([[0, 0, 0, 0], np.tile([1, 0, 0, 0], (26, 1))])
Wb = np.vstack([[1, 0, 0, 0], np.tile([1, 0, 0, 0], (26, 1))]).astype(float)


def seen_from_plus_x(Q, cell=0.02):
    """Front-most along +x per (y, z) cell: a vertex is seen when no other vertex of its cell has a larger x."""
    key = [(round(q[1] / cell), round(q[2] / cell)) for q in Q]
    return np.array([all(Q[j, 0] <= Q[i, 0] + 1e-9 for j in range(len(Q)) if key[j] == key[i])
                     for i in range(len(Q))])


rest_seen = seen_from_plus_x(Pb)
posed = gsh.pose_arms_up(Pb, Jb, Wb, names, heads)
posed_seen = seen_from_plus_x(posed)
check("[C4] flank vertex hidden behind the arm at rest", not rest_seen[0])
check("[C4] flank vertex seen with the arms up", bool(posed_seen[0]))
covered_rest = np.zeros(len(Pb), bool)
covered_rest[np.nonzero(posed_seen)[0]] = True   # covered marks of the posed body land on the same rest indices
check("[C4] the mark maps back to rest index 0", covered_rest[0] and np.allclose(Pb[0], P[0]))

print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
