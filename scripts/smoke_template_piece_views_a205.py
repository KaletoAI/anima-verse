"""Smoke check (A205): a template piece bakes from its own piece-only views; a sheer piece only from them.

Usage: ./.venv/bin/python scripts/smoke_template_piece_views_a205.py   (no server, no world DB, no image job: the
render is stubbed, a temp storage dir)

Hand-derived expectations:
  [A] prompt: a sheer piece's front prompt = the ghost text of its class (a skirt slotted ``bottom`` -> waistband
      class: GHOST_WAISTBAND + GHOST_STANCE) + SHEER_LINE; the back adds GHOST_SIDE["back"] and BACK_LINE before
      SHEER_LINE; a medium piece has no SHEER_LINE. The negative of a sheer piece holds "legs" and "body".
  [B] skin check on a 100x100 fully opaque cut-out: piece core after a 2-px erosion = 96x96 = 9216 px.
      Lavender cloth (200,190,230): Cr = 128 + 100 - 79.55 - 18.70 = 129.75 < 133 -> no skin -> share 0, ok.
      A 20x20 block of (224,172,140): Y 183.9, Cr 156.6 in [133,180], Cb 103.2 in [77,127] -> skin; 400 px in the
      core -> 400 / 9216 = 0.0434 > 0.01 -> refused. With a tone (224,172,140) the block stays (ΔRGB 0); with a
      tone (90,60,40) it leaves (mean |Δ| = (134+112+100)/3 = 115.3 > 45) -> share 0.
  [C] generate with a stubbed render: attempt 1 has legs (refused), attempt 2 is clean -> published from attempt 2,
      exactly 2 renders. Both refused -> ViewRefused after exactly 2 renders (the A190 cap), nothing published;
      "Use this" on attempt 1 then publishes it with accepted_by_user True.
  [D] bake sources: sheer without views -> {} and key_for's reason SHEER_NEEDS_VIEWS (the piece is due, 2 hub jobs
      in ``status``); with only the front -> still {} (both required), hub_jobs 1; with both -> source "piece_only".
      A medium piece without views -> "item_image"; with a front only -> piece_only, back = front. The tsig changes
      when a view's bytes change (the sha256 is in the key). ``run_drape``'s ``prepare_view`` keeps the alpha of a
      piece_only source (garment_only False).
  [E] pre-fix proof against 2e15dbd4e: that module's ``texture_sources`` has no piece-only views — a sheer piece
      bakes from the item picture ("item_image").
"""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="smoke_a205_"))
paths.init(str(TMP))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import garment_clothing as gc  # noqa: E402
from app.core import garment_store, garment_template as gt, garment_template_views as tv  # noqa: E402
from app.models import inventory  # noqa: E402

PRE = "2e15dbd4e"
failures = []


def check(label, ok, detail=""):
    print(f"  {'ok ' if ok else 'FAIL'} {label}{(' — ' + str(detail)) if detail else ''}")
    if not ok:
        failures.append(label)


GARMENTS = TMP / "garments"
garment_store.garments_dir = lambda c: GARMENTS  # type: ignore[assignment]
PICTURE = TMP / "item.png"
Image.new("RGB", (64, 64), (200, 190, 230)).save(PICTURE)
ITEMS = {
    "sheer": {"id": "sheer", "category": "outfit_piece", "name": "Moon skirt",
              "outfit_piece": {"slots": ["bottom"], "template": {"params": {"kind": "skirt", "fabric": "sheer"}}}},
    "plain": {"id": "plain", "category": "outfit_piece", "name": "Wool skirt",
              "outfit_piece": {"slots": ["bottom"], "template": {"params": {"kind": "skirt", "fabric": "medium"}}}},
}
inventory.get_item = lambda i: ITEMS.get(i)  # type: ignore[assignment]
inventory.get_item_image_path = lambda i: str(PICTURE)  # type: ignore[assignment]
tv.skin_tone = lambda c: None  # type: ignore[assignment]


def image(path: Path, *, legs: bool, bg: bool = False) -> Path:
    """A 100x100 lavender piece (a 20x20 skin block in its middle with ``legs``); ``bg``: as a render comes — opaque,
    on a 140x140 plain light-grey background (the cut-out takes the border-connected background away)."""
    px = np.zeros((100, 100, 4), dtype=np.uint8)
    px[..., :3] = (200, 190, 230)
    px[..., 3] = 255
    if legs:
        px[40:60, 40:60, :3] = (224, 172, 140)
    if bg:
        canvas = np.full((140, 140, 4), 255, dtype=np.uint8)
        canvas[..., :3] = (230, 230, 230)
        canvas[20:120, 20:120] = px
        px = canvas
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(px).save(path)
    return path


print("[A] prompt")
front, neg = tv.prompt_for(ITEMS["sheer"], "front")
check("sheer front = waistband ghost + stance + sheer line",
      front == " ".join([gc.GHOST_WAISTBAND, gc.GHOST_STANCE, tv.SHEER_LINE, tv.GREEN_LINE]), front)
back, _ = tv.prompt_for(ITEMS["sheer"], "back")
check("sheer back adds side + turn-around before the sheer line",
      back == " ".join([gc.GHOST_WAISTBAND, gc.GHOST_SIDE["back"], gc.GHOST_STANCE, tv.BACK_LINE, tv.SHEER_LINE, tv.GREEN_LINE]),
      back)
check("medium has no sheer line", tv.SHEER_LINE not in tv.prompt_for(ITEMS["plain"], "front")[0])
check("sheer negative names legs and body", "legs" in neg.split(", ") and "body" in neg.split(", "), neg)

print("[B] skin check")
clean = image(TMP / "b" / "clean.png", legs=False)
legs = image(TMP / "b" / "legs.png", legs=True)
r = tv.skin_check(clean)
check("clean lavender: share 0, ok", r["ok"] and r["skin"] == 0.0, r)
r = tv.skin_check(legs)
check("legs block: 400/9216 = 0.0434, refused", (not r["ok"]) and r["skin"] == round(400 / 9216, 4)
      and r["pixels"] == 400, r)
r = tv.skin_check(legs, tone=[224, 172, 140])
check("tone of the block keeps it", r["skin"] == round(400 / 9216, 4), r)
r = tv.skin_check(legs, tone=[90, 60, 40])
check("a far tone drops it", r["ok"] and r["skin"] == 0.0, r)

print("[C] generate (stubbed render)")
calls = []


def stub(plan):
    def render(character_name, item_id, view, *, prompt, negative, source, target, attempt):
        calls.append((view, attempt))
        return image(target, legs=plan[attempt - 1], bg=True)
    return render


tv._render = stub([True, False])  # type: ignore[assignment]
out = tv.generate("Gelina", "sheer", "front")
rec = tv._read(out.with_suffix(".json"))
check("attempt 1 refused at 400/9216 after the cut-out",
      tv._read(tv.attempt_path("Gelina", "sheer", "front", 1).with_suffix(".json")).get("skin") == round(400 / 9216, 4))
check("attempt 2 published, 2 renders", rec.get("attempt") == 2 and calls == [("front", 1), ("front", 2)], (rec, calls))
calls.clear()
tv._render = stub([True, True])  # type: ignore[assignment]
try:
    tv.generate("Gelina", "sheer", "back")
    check("both refused raises", False)
except tv.ViewRefused as e:
    check("both refused: ViewRefused after 2 renders, nothing published",
          calls == [("back", 1), ("back", 2)] and tv.accepted("Gelina", "sheer", "back") is None, (calls, str(e)))

print("[D] bake sources and key")
st = tv.status("Gelina", "sheer")
check("sheer with front only: status due, 1 hub job", st["missing"] == ["back"] and st["hub_jobs"] == 1, st["missing"])
check("sheer with front only: no source", gt.texture_sources("Gelina", "sheer") == {})
sig, reason, _ = gt.key_for("Gelina", "sheer", base_sha="b" * 64, lower=[])
check("sheer key blocked with the sheer reason", sig is None and reason == tv.SHEER_NEEDS_VIEWS, reason)
tv.use_attempt("Gelina", "sheer", "back", 1)
rec = tv._read(tv.view_path("Gelina", "sheer", "back").with_suffix(".json"))
check("Use this on a refused attempt: accepted_by_user", rec.get("accepted_by_user") is True, rec)
src = gt.texture_sources("Gelina", "sheer")
check("sheer with both: piece_only", src.get("source") == "piece_only"
      and src["back"].endswith("sheer_back.png"), src)
sig1, _, _ = gt.key_for("Gelina", "sheer", base_sha="b" * 64, lower=[])
image(TMP / "u.png", legs=False, bg=True)
tv.upload("Gelina", "sheer", "back", (TMP / "u.png").read_bytes())
sig2, _, _ = gt.key_for("Gelina", "sheer", base_sha="b" * 64, lower=[])
check("a new back changes the drape key", sig1 and sig2 and sig1 != sig2, (sig1, sig2))
check("medium without views: item picture", gt.texture_sources("Gelina", "plain").get("source") == "item_image")
tv._render = stub([False])  # type: ignore[assignment]
tv.generate("Gelina", "plain", "front")
src = gt.texture_sources("Gelina", "plain")
check("medium with a front: piece_only, back = front", src.get("source") == "piece_only" and src["back"] == src["front"], src)
source = (ROOT / "app/core/garment_template.py").read_text()
check("prepare_view keeps a piece_only source's alpha",
      'garment_only=sources.get("source") not in ("cutout", "piece_only")' in source)

print(f"[E] pre-fix proof ({PRE})")
old_src = subprocess.run(["git", "-C", str(ROOT), "show", f"{PRE}:app/core/garment_template.py"],
                         capture_output=True, text=True)
if old_src.returncode != 0:
    check("pre-fix module readable", False, old_src.stderr.strip())
else:
    path = TMP / "gt_pre.py"
    path.write_text(old_src.stdout)
    spec = importlib.util.spec_from_file_location("gt_pre", path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)  # type: ignore[union-attr]
    got = old.texture_sources("Gelina", "sheer")
    check("pre-fix: a sheer piece bakes from the item picture", got.get("source") == "item_image", got)

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print("FAIL" if failures else "ALL OK", failures if failures else "")
sys.exit(1 if failures else 0)
