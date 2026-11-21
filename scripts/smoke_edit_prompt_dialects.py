"""Smoke: the edit-prompt pass-through and the four dialect renderers (app/imagegen/edit_prompt.py).

Usage:
    ./.venv/bin/python scripts/smoke_edit_prompt_dialects.py

Pure functions — no server, no world DB, no config. Design: docs/edit-prompts.md §1-§3.

Stub backends (only ``model`` / ``prompt_dialect_setting`` / ``name`` are read):
PH3 = "P-H3-Image" -> picture_edit, MM = "MiniMax-H3-Image" -> picture_subject, QW = "Qwen2.1" -> image_tag,
FX = "Flux2-9B" -> ordinal (DIALECT_BY_MODEL, first substring hit).

Expected values, derived by hand from the rules in the module doc / design §3:

[1] Two slots, A = "Put the hat from the second image on the first image."
    mentions: "the second image" -> slot 2, "the first image" -> slot 1 (rule "ordinal").
    PH3: tokens <Picture 2>, <Picture 1>; the text does not start "Edit <Picture N>" -> prefix "Edit <Picture 1>. "
         -> "Edit <Picture 1>. Put the hat from <Picture 2> on <Picture 1>."  rewrites 2, prefixed, notes
         ["keep_missing"] (no "keep").
    MM:  "Put the hat from <Picture 2> on <Picture 1>."  notes ["free_text"] (no "<Subject").
    QW:  "Put the hat from <image2> on <image1>."  notes ["role_missing"] (2 slots, no "canvas").
    FX:  unchanged (each mention renders to itself), rewrites 0, notes [].
[2] One slot, B = "Keep the face of the first image."
    QW: total 1 -> "the image": "Keep the face of the image."  rewrites 1.
    PH3: "Edit <Picture 1>. Keep the face of <Picture 1>."  (keep present -> no keep_missing).
    FX: "Keep the face of the image." (ordinal, one image).
[3] Never invent — 2 slots, C = "Use the fabric of <ref 2>. Add the badge from <ref 3>."
    slot 3 is not sent; another sentence remains -> "Add the badge from <ref 3>." dropped with the space before it;
    FX -> "Use the fabric of the second image."  dropped == ["Add the badge from <ref 3>."], unused [1].
    A lone sentence D = "Add the badge from <ref 3>." cannot be dropped -> ordinal wording of slot 3:
    FX -> "Add the badge from the third image."  notes contain "unresolved", unused [1, 2].
[4] Capitalisation: E = "<ref 1> stays; the second image gives the colour." (2 slots, FX)
    -> "The first image stays; the second image gives the colour." (sentence start -> capital T); mid-sentence
    "Picture 2" (capital P) -> "the second image" in lower case ([7]).
[5] P-H3 lead-in: F = "Edit the image. Make it blue, keep the rest." (1 slot, PH3): no mention; the separate
    "Edit the image." sentence is removed, then the prefix -> "Edit <Picture 1>. Make it blue, keep the rest."
    A text already starting "Edit <Picture 2> ..." gets no prefix (the engine node keeps it verbatim).
[6] 0 slots: "Put the hat from the second image on the first image." comes back byte-identical, meta refs [].
    input_mask is not a reference: {input_reference_image_1, input_mask} -> refs [1].
[7] Every spelling of slot 2 (2 slots), in "Take the colour from X." for X in
    "image 2", "<Picture 2>", "<image2>", "@image2", "Picture 2", "the second picture",
    "the second reference image", "reference image 2", "the image 2", "<ref 2>", "<image 2>":
    PH3 -> "Edit <Picture 1>. Take the colour from <Picture 2>."; MM -> "Take the colour from <Picture 2>.";
    QW -> "Take the colour from <image2>."; FX -> "Take the colour from the second image."
[8] Slot gap: keys input_reference_image_1 and _3; "<ref 3>" names SLOT 3, the 2nd reference sent -> PH3
    "<Picture 2>": "Fill <ref 1> from <ref 3>." -> "Edit <Picture 1>. Fill <Picture 1> from <Picture 2>." Every other
    spelling names a POSITION, so normalising that output again changes nothing ([11]).
[9] "the reference image": 1 slot -> slot 1 (PH3 "<Picture 1>"); 2 slots -> not guessed, left as is.
[10] Config beats the table: PH3 model with prompt_dialect_setting "ordinal" -> dialect ordinal, source "config";
     "auto" -> table ("auto"); unknown model -> ordinal ("default").
[11] Idempotent: normalise(normalise(x)) == normalise(x) for every case above; "<ref" never in any output.
[12] Generic renderers, fixed input:
     refs = [Ref(1, canvas, "the sewing pattern"), Ref(2, material, "the shirt")],
     result = "<ref 1> covered with the fabric of <ref 2>", keep = ["every outline", "the white background"],
     transfers = [Transfer(2, "the exact colour and fine weave", 1)], details = ["The fabric lies flat"].
     ordinal: "The first image covered with the fabric of the second image. The fabric lies flat. Keep every outline
               and the white background unchanged."
     picture_edit: "Edit <Picture 1>. <Picture 1> covered with the fabric of <Picture 2>. The fabric lies flat. Keep
               every outline and the white background exactly as they are."
     image_tag: "<image1> covered with the fabric of <image2>. <image1> is the canvas: the sewing pattern. <image2> is
               the material source: the shirt. Take the exact colour and fine weave from <image2> onto <image1>. The
               fabric lies flat. Keep every outline and the white background unchanged."
     picture_subject: "The sewing pattern in <Picture 1> is <Subject 1>. The shirt in <Picture 2> is <Subject 2>. The
               target image shows <Picture 1> covered with the fabric of <Picture 2>. <Subject 1> is partially
               preserved; every outline and the white background remain exactly. <Subject 2> supplies the exact
               colour and fine weave transferred to <Subject 1>. The fabric lies flat."
[13] Sectioned template S = "{# c #}\n## picture_edit\nEdit {{ ref(1) }}. Fill {{ ref(1) }} from {{ ref(2) }}.\n
     ## ordinal\nFill {{ ref(1) }} with {{ piece }}\n from {{ ref(2) }}.\n", piece = "cloth":
     picture_edit "Edit <Picture 1>. Fill <Picture 1> from <Picture 2>." (its own section);
     picture_subject "Fill <Picture 1> with cloth from <Picture 2>." (the ordinal section, its tokens, the line
     break collapsed); image_tag "Fill <image1> with cloth from <image2>."; ordinal "Fill the first image with cloth
     from the second image." A missing variable raises (StrictUndefined); "## foo" raises ValueError; no ## ordinal
     raises ValueError. Each rendered text passes normalise unchanged on its own dialect (PH3 starts "Edit <Picture").
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.imagegen import edit_prompt as ep  # noqa: E402

FAILS: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  OK   {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL {label}\n       got:  {got!r}\n       want: {want!r}")


class B:
    def __init__(self, model: str, setting: str = "", name: str = "stub"):
        self.model, self.prompt_dialect_setting, self.name = model, setting, name


PH3, MM, QW, FX = B("P-H3-Image"), B("MiniMax-H3-Image"), B("Qwen2.1"), B("Flux2-9B")


def refs(*slots: int) -> dict:
    return {"reference_images": {f"input_reference_image_{n}": f"/tmp/r{n}.png" for n in slots}}


OUTPUTS: list[tuple] = []


def norm(prompt: str, params: dict, backend: B):
    out, meta = ep.normalise(prompt, params, backend)
    OUTPUTS.append((out, params, backend))
    return out, meta


print("[1] two slots, ordinal wording in")
A = "Put the hat from the second image on the first image."
out, meta = norm(A, refs(1, 2), PH3)
check("PH3", out, "Edit <Picture 1>. Put the hat from <Picture 2> on <Picture 1>.")
check("PH3 meta", (meta["rewrites"], meta["prefixed"], meta["notes"]), (2, True, ["keep_missing"]))
out, meta = norm(A, refs(1, 2), MM)
check("MM", out, "Put the hat from <Picture 2> on <Picture 1>.")
check("MM notes", meta["notes"], ["free_text"])
out, meta = norm(A, refs(1, 2), QW)
check("QW", out, "Put the hat from <image2> on <image1>.")
check("QW notes", meta["notes"], ["role_missing"])
out, meta = norm(A, refs(1, 2), FX)
check("FX unchanged", out, A)
check("FX meta", (meta["rewrites"], meta["notes"]), (0, []))

print("[2] one slot")
Bp = "Keep the face of the first image."
out, meta = norm(Bp, refs(1), QW)
check("QW one image", out, "Keep the face of the image.")
check("QW rewrites", meta["rewrites"], 1)
out, meta = norm(Bp, refs(1), PH3)
check("PH3 one image", out, "Edit <Picture 1>. Keep the face of <Picture 1>.")
check("PH3 keep present", meta["notes"], [])
out, _ = norm(Bp, refs(1), FX)
check("FX one image", out, "Keep the face of the image.")

print("[3] never invent")
C = "Use the fabric of <ref 2>. Add the badge from <ref 3>."
out, meta = norm(C, refs(1, 2), FX)
check("sentence dropped", out, "Use the fabric of the second image.")
check("dropped", meta["dropped"], ["Add the badge from <ref 3>."])
check("unused", meta["unused"], [1])
D = "Add the badge from <ref 3>."
out, meta = norm(D, refs(1, 2), FX)
check("lone sentence kept, ordinal", out, "Add the badge from the third image.")
check("unresolved note", ("unresolved" in meta["notes"], meta["unused"]), (True, [1, 2]))

print("[4] capitalisation")
out, _ = norm("<ref 1> stays; the second image gives the colour.", refs(1, 2), FX)
check("sentence start", out, "The first image stays; the second image gives the colour.")

print("[5] P-H3 lead-in")
out, meta = norm("Edit the image. Make it blue, keep the rest.", refs(1), PH3)
check("one prefix", out, "Edit <Picture 1>. Make it blue, keep the rest.")
out, meta = norm("Edit <Picture 2> so the hat is red. Keep the rest.", refs(1, 2), PH3)
check("verbatim edit kept", (out, meta["prefixed"]), ("Edit <Picture 2> so the hat is red. Keep the rest.", False))

print("[6] no slot")
out, meta = norm(A, {}, PH3)
check("byte-identical", out, A)
check("refs []", meta["refs"], [])
check("mask not counted", ep.slots_of({"reference_images": {"input_reference_image_1": "a", "input_mask": "m"}}),
      [1])

print("[7] every spelling of slot 2")
SPELLINGS = ("image 2", "<Picture 2>", "<image2>", "@image2", "Picture 2", "the second picture",
             "the second reference image", "reference image 2", "the image 2", "<ref 2>", "<image 2>")
WANT = {"PH3": "Edit <Picture 1>. Take the colour from <Picture 2>.", "MM": "Take the colour from <Picture 2>.",
        "QW": "Take the colour from <image2>.", "FX": "Take the colour from the second image."}
for x in SPELLINGS:
    for label, b in (("PH3", PH3), ("MM", MM), ("QW", QW), ("FX", FX)):
        out, _ = norm(f"Take the colour from {x}.", refs(1, 2), b)
        check(f"{x!r} -> {label}", out, WANT[label])

print("[8] slot gap")
out, _ = norm("Fill <ref 1> from <ref 3>.", refs(1, 3), PH3)
check("position, not slot number", out, "Edit <Picture 1>. Fill <Picture 1> from <Picture 2>.")

print("[9] the reference image")
out, _ = norm("Match the reference image.", refs(1), PH3)
check("one slot", out, "Edit <Picture 1>. Match <Picture 1>.")
out, _ = norm("Match the reference image.", refs(1, 2), FX)
check("two slots: not guessed", out, "Match the reference image.")

print("[10] dialect resolution")
check("config beats auto", ep.resolve_dialect(B("P-H3-Image", "ordinal")), ("ordinal", "config"))
check("auto -> table", ep.resolve_dialect(B("P-H3-Image", "auto")), ("picture_edit", "auto"))
check("unknown -> ordinal", ep.resolve_dialect(B("SomeModel")), ("ordinal", "default"))

print("[11] idempotent, no <ref")
for out, params, b in list(OUTPUTS):
    again, _ = ep.normalise(out, params, b)
    if again != out:
        check(f"idempotent {out!r}", again, out)
    if "<ref" in out:
        check(f"no <ref in {out!r}", False, True)
check(f"idempotent + no <ref over {len(OUTPUTS)} outputs", True, True)

print("[12] generic renderers")
E = ep.EditPrompt(refs=[ep.Ref(1, "canvas", "the sewing pattern"), ep.Ref(2, "material", "the shirt")],
                  result="<ref 1> covered with the fabric of <ref 2>",
                  keep=["every outline", "the white background"],
                  transfers=[ep.Transfer(2, "the exact colour and fine weave", 1)],
                  details=["The fabric lies flat"])
check("ordinal", E.render("ordinal"),
      "The first image covered with the fabric of the second image. The fabric lies flat. Keep every outline and "
      "the white background unchanged.")
check("picture_edit", E.render("picture_edit"),
      "Edit <Picture 1>. <Picture 1> covered with the fabric of <Picture 2>. The fabric lies flat. Keep every outline "
      "and the white background exactly as they are.")
check("image_tag", E.render("image_tag"),
      "<image1> covered with the fabric of <image2>. <image1> is the canvas: the sewing pattern. <image2> is the "
      "material source: the shirt. Take the exact colour and fine weave from <image2> onto <image1>. The fabric lies "
      "flat. Keep every outline and the white background unchanged.")
check("picture_subject", E.render("picture_subject"),
      "The sewing pattern in <Picture 1> is <Subject 1>. The shirt in <Picture 2> is <Subject 2>. The target image "
      "shows <Picture 1> covered with the fabric of <Picture 2>. <Subject 1> is partially preserved; every outline "
      "and the white background remain exactly. <Subject 2> supplies the exact colour and fine weave transferred to "
      "<Subject 1>. The fabric lies flat.")

print("[13] sectioned template")
S = ("{# c #}\n## picture_edit\nEdit {{ ref(1) }}. Fill {{ ref(1) }} from {{ ref(2) }}.\n"
     "## ordinal\nFill {{ ref(1) }} with {{ piece }}\n from {{ ref(2) }}.\n")
two = [ep.Ref(1, "canvas"), ep.Ref(2, "material")]
T = ep.from_source(S, two, piece="cloth")
want = {"picture_edit": "Edit <Picture 1>. Fill <Picture 1> from <Picture 2>.",
        "picture_subject": "Fill <Picture 1> with cloth from <Picture 2>.",
        "image_tag": "Fill <image1> with cloth from <image2>.",
        "ordinal": "Fill the first image with cloth from the second image."}
for d, w in want.items():
    check(f"section {d}", T.render(d), w)
for d, b in (("picture_edit", PH3), ("picture_subject", MM), ("image_tag", QW), ("ordinal", FX)):
    out, _ = ep.normalise(T.render(d), refs(1, 2), b)
    check(f"normalise keeps {d}", out, T.render(d))
try:
    ep.from_source(S, two)
    check("missing variable raises", False, True)
except Exception as e:  # noqa: BLE001
    check("missing variable raises", type(e).__name__, "UndefinedError")
for bad in ("## foo\nx\n## ordinal\ny", "## picture_edit\nx\n"):
    try:
        ep.from_source(bad, two)
        check(f"bad template raises {bad!r}", False, True)
    except ValueError:
        check(f"bad template raises {bad!r}", True, True)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS[:10])}")
    sys.exit(1)
print("ALL OK")
