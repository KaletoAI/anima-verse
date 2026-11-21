"""Smoke: the cut texture's three prompt variants in the four edit-prompt dialects (docs/edit-prompts.md §6).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_dialects.py

Pure — the shipped sectioned templates rendered through ``garment_cut_texture.edit_prompt`` on fixture islands; no
server, no world DB, no hub.

Fixture islands, derived by hand (``layout_words``: centre = bbox centre / atlas_px; top < 0.36 < middle < 0.64 <
bottom, left < 0.36, right > 0.64; bottom with no side and centre > 0.9 = "at the very bottom"; the largest bbox =
"the large piece"; a bbox 6 x longer than wide = "the long thin strip"; pieces in ``PROMPT_PIECE_NAMES`` order):

KAI (atlas_px 1000): front (20, 20, 500, 450) -> (0.26, 0.235) top left, the largest (480 x 430);
    sleeve_l (20, 400, 330, 600) -> (0.175, 0.5) middle left; sleeve_r (670, 400, 980, 600) -> (0.825, 0.5) middle
    right; band (100, 800, 900, 850) -> (0.5, 0.825) bottom, 800 / 50 = 16 >= 6 -> "the long thin strip at the bottom".
    pieces "front panel, left sleeve, right sleeve, neckband"; sleeves "left sleeve", "right sleeve".
DARIO: front as Kai; sleeve_l (20, 650, 330, 850) -> (0.175, 0.75) bottom left; sleeve_r (670, 650, 980, 850) ->
    bottom right; band (100, 930, 900, 970) -> (0.5, 0.95) "at the very bottom", 800 / 40 = 20 -> long thin strip.

[1] picture_subject, front, piece "T-shirt" on KAI = candidate N of the MiniMax A/B byte for byte
    (~/claude-out/prompt-test-minimax/prompts.json "MiniMax:kai_front:N"):
    "The flat sewing pattern of a T-shirt on a white background in <Picture 1> is <Subject 1>; it has exactly these
    pieces: front panel, left sleeve, right sleeve, neckband, where the large piece at the top left is the front panel;
    the piece in the middle left is the left sleeve; the piece in the middle right is the right sleeve; the long thin
    strip at the bottom is the neckband, each filled with a plain colour. The T-shirt in <Picture 2> is <Subject 2>.
    The fabric of <Subject 2>, its colour and fine weave, is <Subject 3>. The target image shows <Subject 1> as a
    flat, evenly lit texture map covered with <Subject 3>. <Subject 1> is partially preserved; every outline, the
    layout, the proportions and the white background remain exactly, while the plain fill of every piece becomes
    <Subject 3>. <Subject 3> supplies the exact colour and weave transferred to every piece of <Subject 1>. <Subject 2>
    serves only as the source of its fabric and its front decoration. Any embroidery, print or logo that <Subject 2>
    shows on its front appears on the front panel of <Subject 1> at the same place and size. The left sleeve and right
    sleeve of <Subject 1> carry only the plain fabric. The fabric lies perfectly flat with even light, without folds,
    wrinkles, shadows, perspective, buttons, labels, text or anything that <Subject 2> does not show."
    The decorated front's picture_subject is the SAME text. DARIO with "long-sleeve shirt" = "MiniMax:dario_front:N"
    (same text, "long-sleeve shirt", layout "...; the piece at the bottom left is the left sleeve; the piece at the
    bottom right is the right sleeve; the long thin strip at the very bottom is the neckband").
    The back, piece "T-shirt" = "MiniMax:kai_back:N": "The flat sewing pattern of the back panel of a T-shirt on a
    white background in <Picture 1> is <Subject 1>, filled with a plain colour. The back of the T-shirt in <Picture 2>
    is <Subject 2>. The fabric of <Subject 2>, its colour and fine weave, is <Subject 3>. The target image shows
    <Subject 1> as a flat, evenly lit texture map covered with <Subject 3>. <Subject 1> is partially preserved; its
    outline, proportions and the white background remain exactly, while its plain fill becomes <Subject 3>.
    <Subject 3> supplies the exact colour and weave transferred to <Subject 1>. <Subject 2> serves only as the source
    of its fabric and of any decoration on its back. An embroidery, print or logo that <Subject 2> shows appears on
    <Subject 1> at the same place and size; a plain back stays plain fabric. The fabric lies perfectly flat with even
    light, without folds, wrinkles, shadows, perspective, labels, text or anything that <Subject 2> does not show."
    sleeve_print "picture" -> no sleeves -> the sentence "The left sleeve and right sleeve of <Subject 1> carry only the
    plain fabric." is absent.
[2] picture_edit = "Edit <Picture 1>. " + the winners on main (~/claude-out/prompt-test/winner_*.txt):
    plain "Edit <Picture 1>. Texture the sewing pattern in <Picture 1> with the fabric of the T-shirt in <Picture 2>.
    Keep every shape, its colour and the white background exactly. Add only the fine weave of the fabric, flat and
    evenly lit."; decorated (front_place "top left", "long-sleeve shirt") "Edit <Picture 1>. The top left shape of
    <Picture 1> is the front of the long-sleeve shirt in <Picture 2>, laid flat. Paint it as that front: same fabric,
    same print or embroidery at the same place. The other shapes get plain fabric only. Outlines, colour and white
    background stay unchanged."; back "Edit <Picture 1>. Texture the shape in <Picture 1> with the fabric on the back
    of the T-shirt in <Picture 2>. Keep the shape, its colour and the white background exactly. Add only the fine
    weave of the fabric, flat and evenly lit."
[3] ordinal = the picture_edit text without "Edit <Picture 1>. " and with "the first image" / "the second image".
[4] image_tag: every variant names <image1> and <image2>, never "<Picture" / "the first image"; the decorated one says
    "on the top left piece, the front panel".
[5] Every variant x dialect: no "{{", "{%", "<ref"; normalise (2 slots) on the dialect's own backend leaves it as is
    (P-H3 "P-H3-Image", MiniMax "MiniMax-H3-Image", Qwen "Qwen2.1", ordinal "Flux2-9B").
[6] compose(use_case garment_cut_texture, keep_negations=True) keeps the N text byte-identical (the clause "without
    folds, wrinkles, …" stays); without keep_negations the guard would move it (folds, wrinkles … into the negative) —
    the reason the flag exists.
[7] PROMPT_SHA = md5 of the three files joined by NUL; one changed character in one section gives another sha.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  OK   {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL {label}\n       got:  {got!r}\n       want: {want!r}")


def isl(name, box):
    return {"name": name, "bbox_px": list(box), "verts_px": []}


KAI = {"atlas_px": 1000, "islands": [isl("front", (20, 20, 500, 450)), isl("sleeve_l", (20, 400, 330, 600)),
                                     isl("sleeve_r", (670, 400, 980, 600)), isl("band", (100, 800, 900, 850))]}
DARIO = {"atlas_px": 1000, "islands": [isl("front", (20, 20, 500, 450)), isl("sleeve_l", (20, 650, 330, 850)),
                                       isl("sleeve_r", (670, 650, 980, 850)), isl("band", (100, 930, 900, 970))]}

N_KAI_FRONT = (
    "The flat sewing pattern of a T-shirt on a white background in <Picture 1> is <Subject 1>; it has exactly these "
    "pieces: front panel, left sleeve, right sleeve, neckband, where the large piece at the top left is the front "
    "panel; the piece in the middle left is the left sleeve; the piece in the middle right is the right sleeve; the "
    "long thin strip at the bottom is the neckband, each filled with a plain colour. The T-shirt in <Picture 2> is "
    "<Subject 2>. The fabric of <Subject 2>, its colour and fine weave, is <Subject 3>. The target image shows "
    "<Subject 1> as a flat, evenly lit texture map covered with <Subject 3>. <Subject 1> is partially preserved; every "
    "outline, the layout, the proportions and the white background remain exactly, while the plain fill of every "
    "piece becomes <Subject 3>. <Subject 3> supplies the exact colour and weave transferred to every piece of "
    "<Subject 1>. <Subject 2> serves only as the source of its fabric and its front decoration. Any embroidery, print "
    "or logo that <Subject 2> shows on its front appears on the front panel of <Subject 1> at the same place and size. "
    "The left sleeve and right sleeve of <Subject 1> carry only the plain fabric. The fabric lies perfectly flat with "
    "even light, without folds, wrinkles, shadows, perspective, buttons, labels, text or anything that <Subject 2> "
    "does not show.")
N_DARIO_FRONT = N_KAI_FRONT.replace("a T-shirt", "a long-sleeve shirt").replace("The T-shirt", "The long-sleeve shirt") \
    .replace("the piece in the middle left", "the piece at the bottom left") \
    .replace("the piece in the middle right", "the piece at the bottom right") \
    .replace("the long thin strip at the bottom", "the long thin strip at the very bottom")
N_KAI_BACK = (
    "The flat sewing pattern of the back panel of a T-shirt on a white background in <Picture 1> is <Subject 1>, "
    "filled with a plain colour. The back of the T-shirt in <Picture 2> is <Subject 2>. The fabric of <Subject 2>, its "
    "colour and fine weave, is <Subject 3>. The target image shows <Subject 1> as a flat, evenly lit texture map "
    "covered with <Subject 3>. <Subject 1> is partially preserved; its outline, proportions and the white background "
    "remain exactly, while its plain fill becomes <Subject 3>. <Subject 3> supplies the exact colour and weave "
    "transferred to <Subject 1>. <Subject 2> serves only as the source of its fabric and of any decoration on its "
    "back. An embroidery, print or logo that <Subject 2> shows appears on <Subject 1> at the same place and size; a "
    "plain back stays plain fabric. The fabric lies perfectly flat with even light, without folds, wrinkles, shadows, "
    "perspective, labels, text or anything that <Subject 2> does not show.")
PLAIN = ("Texture the sewing pattern in {1} with the fabric of the T-shirt in {2}. Keep every shape, its colour and "
         "the white background exactly. Add only the fine weave of the fabric, flat and evenly lit.")
DECO = ("The top left shape of {1} is the front of the long-sleeve shirt in {2}, laid flat. Paint it as that front: "
        "same fabric, same print or embroidery at the same place. The other shapes get plain fabric only. Outlines, "
        "colour and white background stay unchanged.")
BACK = ("Texture the shape in {1} with the fabric on the back of the T-shirt in {2}. Keep the shape, its colour and "
        "the white background exactly. Add only the fine weave of the fabric, flat and evenly lit.")


def main() -> int:
    from app.core import garment_cut_texture as gct
    from app.imagegen.edit_prompt import DIALECTS, normalise

    # the prompts.json strings, when the A/B folder is there (the docstring quotes them either way)
    pj = Path.home() / "claude-out" / "prompt-test-minimax" / "prompts.json"
    if pj.is_file():
        data = json.loads(pj.read_text(encoding="utf-8"))
        check("prompts.json kai_front:N = the quoted text", data["MiniMax:kai_front:N"]["prompt"], N_KAI_FRONT)
        check("prompts.json dario_front:N = the quoted text", data["MiniMax:dario_front:N"]["prompt"], N_DARIO_FRONT)
        check("prompts.json kai_back:N = the quoted text", data["MiniMax:kai_back:N"]["prompt"], N_KAI_BACK)

    def ep(islands, piece, side="front", decorated=False, sleeve_print="plain"):
        return gct.edit_prompt(piece=piece, side=side, decorated=decorated,
                               front_place=gct.front_place(islands) if side == "front" else "",
                               pieces=gct.prompt_pieces(islands), layout=gct.layout_words(islands),
                               sleeves=gct.prompt_sleeves(islands, sleeve_print))

    print("[0] fixture words")
    check("kai pieces", gct.prompt_pieces(KAI), ["front panel", "left sleeve", "right sleeve", "neckband"])
    check("kai layout", gct.layout_words(KAI), [
        "the large piece at the top left is the front panel", "the piece in the middle left is the left sleeve",
        "the piece in the middle right is the right sleeve", "the long thin strip at the bottom is the neckband"])
    check("front_place", gct.front_place(KAI), "top left")

    print("[1] picture_subject = candidate N")
    check("kai front", ep(KAI, "T-shirt").render("picture_subject"), N_KAI_FRONT)
    check("kai front decorated: same text", ep(KAI, "T-shirt", decorated=True).render("picture_subject"), N_KAI_FRONT)
    check("dario front", ep(DARIO, "long-sleeve shirt", decorated=True).render("picture_subject"), N_DARIO_FRONT)
    check("kai back", ep({"atlas_px": 1000, "islands": [isl("back", (0, 0, 10, 10))]}, "T-shirt", side="back")
          .render("picture_subject"), N_KAI_BACK)
    check("sleeve_print picture: no plain-sleeve sentence",
          ep(KAI, "T-shirt", sleeve_print="picture").render("picture_subject"),
          N_KAI_FRONT.replace(" The left sleeve and right sleeve of <Subject 1> carry only the plain fabric.", ""))

    print("[2] picture_edit = the short winners with the node's prefix")
    tok = {"1": "<Picture 1>", "2": "<Picture 2>"}
    check("plain", ep(KAI, "T-shirt").render("picture_edit"),
          "Edit <Picture 1>. " + PLAIN.replace("{1}", tok["1"]).replace("{2}", tok["2"]))
    check("decorated", ep(DARIO, "long-sleeve shirt", decorated=True).render("picture_edit"),
          "Edit <Picture 1>. " + DECO.replace("{1}", tok["1"]).replace("{2}", tok["2"]))
    back_isl = {"atlas_px": 1000, "islands": [isl("back", (0, 0, 10, 10))]}
    check("back", ep(back_isl, "T-shirt", side="back").render("picture_edit"),
          "Edit <Picture 1>. " + BACK.replace("{1}", tok["1"]).replace("{2}", tok["2"]))

    print("[3] ordinal = today's texts")
    o1, o2 = "the first image", "the second image"
    check("plain", ep(KAI, "T-shirt").render("ordinal"), PLAIN.replace("{1}", o1).replace("{2}", o2))
    check("decorated", ep(DARIO, "long-sleeve shirt", decorated=True).render("ordinal"),
          DECO.replace("{1}", o1).replace("{2}", o2))
    check("back", ep(back_isl, "T-shirt", side="back").render("ordinal"), BACK.replace("{1}", o1).replace("{2}", o2))

    print("[4] image_tag")
    variants = {"plain": ep(KAI, "T-shirt"), "decorated": ep(DARIO, "long-sleeve shirt", decorated=True),
                "back": ep(back_isl, "T-shirt", side="back")}
    for name, e in variants.items():
        t = e.render("image_tag")
        check(f"{name}: <image1>/<image2> only", ("<image1>" in t, "<image2>" in t, "<Picture" in t,
                                                  "the first image" in t), (True, True, False, False))
    check("decorated: the front place", "on the top left piece, the front panel" in
          variants["decorated"].render("image_tag"), True)

    print("[5] every variant x dialect is clean and passes the normaliser unchanged")
    two = {"reference_images": {"input_reference_image_1": "t.png", "input_reference_image_2": "i.png"}}
    backends = {"picture_edit": "P-H3-Image", "picture_subject": "MiniMax-H3-Image", "image_tag": "Qwen2.1",
                "ordinal": "Flux2-9B"}
    for name, e in variants.items():
        for d in DIALECTS:
            t = e.render(d)
            bad = [m for m in ("{{", "{%", "<ref") if m in t]
            out = normalise(t, two, SimpleNamespace(model=backends[d], name="stub"))[0]
            check(f"{name} {d}", (bad, out == t), ([], True))

    print("[6] compose keeps the tested negation clause")
    from app.core import paths
    import tempfile
    with tempfile.TemporaryDirectory(prefix="cut-dialects-") as tmp:
        paths.init(Path(tmp) / "world")
        (Path(tmp) / "world").mkdir(parents=True, exist_ok=True)
        paths.get_config_path().write_text("{}")
        from app.core import config
        config.load(paths.get_config_path(), instance_path=Path(tmp) / "instance" / "config.json")
        from app.core.prompt_compose import compose
        mm = SimpleNamespace(model="MiniMax-H3-Image", image_family="natural")
        kept = compose(use_case=gct.CUT_USE_CASE, subject=N_KAI_FRONT, backend=mm, keep_negations=True)
        check("keep_negations: byte-identical", (kept.prompt, kept.negative, kept.meta["negations_moved"]),
              (N_KAI_FRONT, "", []))
        moved = compose(use_case=gct.CUT_USE_CASE, subject=N_KAI_FRONT, backend=mm)
        check("without it the guard would cut the clause", ("without folds" in moved.prompt,
                                                             "folds" in moved.meta["negations_moved"]), (False, True))

    print("[7] PROMPT_SHA")
    texts = [gct.PROMPT_FILES[v].read_text(encoding="utf-8") for v in ("front_plain", "front_decorated", "back")]
    check("md5 of the three files", gct.PROMPT_SHA, hashlib.md5("\0".join(texts).encode("utf-8")).hexdigest())
    changed = [texts[0].replace("<Subject 3> supplies", "<Subject 3>  supplies", 1)] + texts[1:]
    check("one changed section changes it", hashlib.md5("\0".join(changed).encode("utf-8")).hexdigest()
          != gct.PROMPT_SHA, True)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
