#!/usr/bin/env python3
"""A scene photo keeps its people: an LLM rewrite of the dialog prompt that refused or dropped a person is never
taken, a prompt that lost people gets them back with what they do, and the camera line holds no raw metres.

Usage:
    ./.venv/bin/python scripts/smoke_scene_photo_people.py

No server, no world DB of a real world, no LLM, no network: a throwaway STORAGE_DIR / INSTANCE_DIR (``paths.init``
before any world import) and a stub in place of ``llm_router.llm_call``.

WHY (2026-11-25): a scene photo of two people showed only the room. The "Improve prompt" button sent the prepared
prompt (both people, their action, "People in the frame: …") with a change wish; the LLM answered with the
refusal sentence REFUSAL below (10 tokens), ``enhance_prompt`` handed it back unchecked, the dialog wrote it into
the prompt field, and a second click (empty wish = optimise) turned it into an interior description. Nothing put
the people back, so the render got the room plus two appended "… is in the picture too." lines.

Fixture (neutral, hand-written): ORIGINAL = a two-person prompt naming Mira and Kai (length printed below, > 200);
REFUSAL = "No image generation is provided or attempted here." (50 characters).

EXPECTED VALUES, derived by hand from the sources
--------------------------------------------------------------------------
[1] ``prompt_guard.is_prompt_refusal(REFUSAL, "")`` is False — the sentence matches none of the refusal openers,
    so only the length rule can catch it; ``rewrite_rejection`` therefore has to pass the original. With the
    original: 50 < 0.25 * len(ORIGINAL) (wish) and 50 < 0.5 * len(ORIGINAL) (optimise) -> rejected both ways.
[2] Names (``names=["Mira", "Kai", "Kaira"]``): a full-length rewrite that names Kai but not Mira -> rejected,
    reason exactly "The LLM rewrite dropped Mira from the prompt."; "Kaira" is never in ORIGINAL, so it is never asked for. The same
    rewrite with the wish "leave Mira out" -> accepted (""), the wish names her. A rewrite keeping both -> "".
[3] ``enhance_prompt`` with the stub answering REFUSAL: strict=True raises ``PromptRewriteRejected``;
    strict=False returns ORIGINAL unchanged. The LLM call carries the label "image prompt improver".
    Proof on the code before the fix (commit ec9479219, pinned — not HEAD): the same call returns REFUSAL.
[4] Route ``POST /world/imagegen-enhance-prompt`` with the stub answering REFUSAL -> 422, detail starts
    "The LLM refused"; with a stub answering a valid rewrite -> 200 and that rewrite.
[5] ``scene_photo.with_subjects`` (hint_of: Mira -> "standing by the window", Kai -> "";
    describe(names) -> "People in the frame: " + "; ".join(f"{n} (look)")):
    a) prompt "A minimalist modern interior, wide shot." with subjects [Mira, Kai] and the pair
       (Mira, Kai, "sitting") ->
         "In the picture: Mira and Kai (sitting together).\\nA minimalist modern interior, wide shot.\\n"
         "People in the frame: Mira (look); Kai (look)"
       — the people LEAD, the old text follows, the descriptions close it.
    b) the same subjects without a pair -> "In the picture: Mira (standing by the window); Kai.\\n…".
    c) a prompt naming Kai only, pair (Mira, Kai, "sitting") -> the pair comes back whole
       ("In the picture: Mira and Kai (sitting together).") but only Mira is described.
    d) a prompt naming both -> byte-identical; "Kaira waves" does not count as naming Kai.
[6] ``scene_photo._view_framing`` with height_m 4.5576, pitch 0, fov 50, nobody visible ->
    "Photograph from an unseen photographer at the given angle. Camera at eye level, close view. No people in the
    frame." — no digit at all; height_m 0.6 -> "Camera at eye level, close view, low camera close to the floor.";
    exactly 1.0 -> not low (the rule is "< 1.0").
    Proof on ec9479219: the old line holds "4.5576 m above ground".
[7] Regenerate of a broken scene photo: ``character_ops.regenerate_image_worker`` with ``regenerate_image``
    stubbed (it records ``original_prompt``) and ``scene_render._appearance_text`` stubbed to "look". Gallery
    owner Kai; sidecar STORED_META = {scene_photo: True, photo_subjects: [Mira, Kai], prompt: STORED} where
    STORED = "A minimalist modern interior in a clean architectural photography style." names no one (the shape
    of the 2026-11-25 sidecar). ``with_photo_subjects`` calls ``with_subjects`` with no pairs, an empty hint and
    an appearance-only describe (a re-render keeps the references of its own moment, so no current outfit):
    a) dialog sends no selection (None) -> the recorded subjects; the stub receives
         "In the picture: Mira; Kai.\n" + STORED + "\nPeople in the frame: Mira (look); Kai (look)"
    b) dialog selection ["Kai"] -> "In the picture: Kai.\n" + STORED + "\nPeople in the frame: Kai (look)"
    c) the same prompt on an image whose sidecar has no ``scene_photo`` -> STORED, byte-identical.
    d) a scene photo whose prompt names both -> byte-identical.
    Proof on ec9479219 (pinned): the old worker hands STORED through unchanged, naming neither.
"""
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD_COMMIT = "ec9479219d4f3535a60a0f5d8ddae7556544e7b5"
FAILS = []

ORIGINAL = (
    "Mira and Kai sit together on the edge of a bed, close and relaxed, in a candid moment. Kai leans toward Mira "
    "and she rests her hand on his shoulder; both look at each other and smile. The room is softly lit, with rain "
    "visible against the window.\n"
    "People in the frame: Mira (young woman, 20s, short blonde hair, blue eyes, green sweater); "
    "Kai (man in his 40s, short brown hair, light stubble, grey shirt)")
REFUSAL = "No image generation is provided or attempted here."
DROPS_MIRA = ORIGINAL.replace("Mira and Kai sit", "Kai sits").replace("toward Mira and she", "forward, a hand")\
    .replace("People in the frame: Mira (young woman, 20s, short blonde hair, blue eyes, green sweater); ", "")


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:260] + ("" if ok else f" — expected {want!r}"[:260]))
    if not ok:
        FAILS.append(label)


class _Answer:
    def __init__(self, content):
        self.content = content


def _old_module(path: str, name: str):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:{path}"],
                         check=True, capture_output=True, text=True).stdout
    mod = types.ModuleType(name)
    mod.__file__ = path
    exec(compile(src, f"{OLD_COMMIT[:9]}:{path}", "exec"), mod.__dict__)
    return mod


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="scene-photo-people-"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    from app.core import paths
    paths.init(str(tmp / "world"))
    paths.init_instance(str(tmp / "instance"))
    from app.core import db
    db.init_schema()

    from app.core import llm_router
    from app.imagegen.prompt_guard import is_prompt_refusal
    from app.skills import image_regenerate as ir
    from app.core import scene_photo as sp

    print(f"ORIGINAL is {len(ORIGINAL)} characters, REFUSAL {len(REFUSAL)}")
    check("ORIGINAL > 200 characters", len(ORIGINAL) > 200, True)

    print("[1] refusal needs the original")
    check("opener alone misses it", is_prompt_refusal(REFUSAL, ""), False)
    check("wish: rejected", bool(ir.rewrite_rejection(REFUSAL, ORIGINAL, "make it warmer", names=[])), True)
    check("optimise: rejected", bool(ir.rewrite_rejection(REFUSAL, ORIGINAL, "", names=[])), True)

    print("[2] names")
    names = ["Mira", "Kai", "Kaira"]
    reason = ir.rewrite_rejection(DROPS_MIRA, ORIGINAL, "", names=names)
    check("drop Mira: rejected", bool(reason), True)
    check("reason names Mira only", reason, "The LLM rewrite dropped Mira from the prompt.")
    check("drop Mira with a wish naming her", ir.rewrite_rejection(DROPS_MIRA, ORIGINAL, "leave Mira out",
                                                                   names=names), "")
    kept = ORIGINAL.replace("softly lit", "warmly lit")
    check("both kept", ir.rewrite_rejection(kept, ORIGINAL, "warmer light", names=names), "")

    print("[3] enhance_prompt")
    calls = []

    def stub(answer):
        def _call(**kw):
            calls.append(kw)
            return _Answer(answer)
        return _call

    real = llm_router.llm_call
    try:
        llm_router.llm_call = stub(REFUSAL)
        try:
            ir.enhance_prompt(ORIGINAL, "make it warmer", None, True, "image", True)
            check("strict raises", False, True)
        except ir.PromptRewriteRejected:
            check("strict raises", True, True)
        check("non-strict keeps the original", ir.enhance_prompt(ORIGINAL, "make it warmer", None, True), ORIGINAL)
        check("label", calls[-1].get("label"), "image prompt improver")
        old = _old_module("app/skills/image_regenerate.py", "old_image_regenerate")
        check(f"proof: {OLD_COMMIT[:9]} hands the refusal back",
              old.enhance_prompt(ORIGINAL, "make it warmer", None, True), REFUSAL)

        print("[4] route")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes import world as world_routes
        app = FastAPI()
        app.include_router(world_routes.router)
        client = TestClient(app)
        r = client.post("/world/imagegen-enhance-prompt", json={"prompt": ORIGINAL, "improvement_request": "x"})
        check("refusal -> 422", r.status_code, 422)
        check("detail", str(r.json().get("detail", "")).startswith("The LLM refused"), True)
        llm_router.llm_call = stub(kept)
        r = client.post("/world/imagegen-enhance-prompt", json={"prompt": ORIGINAL, "improvement_request": "x"})
        check("valid -> 200", (r.status_code, r.json().get("prompt")), (200, kept))
    finally:
        llm_router.llm_call = real

    print("[5] with_subjects")
    hints = {"Mira": "standing by the window", "Kai": ""}

    def describe(ns):
        return "People in the frame: " + "; ".join(f"{n} (look)" for n in ns)

    room = "A minimalist modern interior, wide shot."
    check("a) pair", sp.with_subjects(room, ["Mira", "Kai"], [("Mira", "Kai", "sitting")],
                                      hint_of=hints.get, describe=describe),
          "In the picture: Mira and Kai (sitting together).\n" + room
          + "\nPeople in the frame: Mira (look); Kai (look)")
    check("b) no pair", sp.with_subjects(room, ["Mira", "Kai"], [], hint_of=hints.get, describe=describe),
          "In the picture: Mira (standing by the window); Kai.\n" + room
          + "\nPeople in the frame: Mira (look); Kai (look)")
    only_kai = "Kai sits on the bed."
    check("c) partner named", sp.with_subjects(only_kai, ["Mira", "Kai"], [("Mira", "Kai", "sitting")],
                                               hint_of=hints.get, describe=describe),
          "In the picture: Mira and Kai (sitting together).\n" + only_kai + "\nPeople in the frame: Mira (look)")
    both = "Mira and Kai sit on the bed."
    check("d) both named", sp.with_subjects(both, ["Mira", "Kai"], [], hint_of=hints.get, describe=describe), both)
    check("d) Kaira is not Kai", sp.with_subjects("Kaira waves.", ["Kai"], [], hint_of=hints.get,
                                                  describe=describe),
          "In the picture: Kai.\nKaira waves.\nPeople in the frame: Kai (look)")

    print("[6] camera line")

    def view(h):
        return sp.PhotoView.model_validate({"visible": [], "camera": {"pitch_deg": 0, "height_m": h, "fov_deg": 50}})

    check("4.5576 m", sp._view_framing(view(4.5576), []),
          "Photograph from an unseen photographer at the given angle. Camera at eye level, close view. "
          "No people in the frame.")
    check("0.6 m", sp._view_framing(view(0.6), []).split(" Camera ")[1].split(" No people")[0],
          "at eye level, close view, low camera close to the floor.")
    check("1.0 m is not low", "low camera" in sp._view_framing(view(1.0), []), False)
    old_sp = _old_module("app/core/scene_photo.py", "old_scene_photo")
    check(f"proof: {OLD_COMMIT[:9]} prints the raw metres",
          "4.5576 m above ground" in old_sp._view_framing(old_sp.PhotoView.model_validate(
              {"visible": [], "camera": {"pitch_deg": 0, "height_m": 4.5576, "fov_deg": 50}}), []), True)

    print("[7] regenerate of a scene photo")
    from app.core import character_ops
    from app.core import scene_render
    from app.models.character import add_character_image_metadata, get_character_dir, get_character_images_dir
    stored = "A minimalist modern interior in a clean architectural photography style."
    get_character_dir("Kai", create=True)
    images = get_character_images_dir("Kai")
    for fn, meta in (("Kai_photo_vbroken.png", {"scene_photo": True, "photo_subjects": ["Mira", "Kai"]}),
                     ("Kai_plain.png", {})):
        (images / fn).write_bytes(b"\x89PNG\r\n\x1a\n")
        add_character_image_metadata("Kai", fn, {"prompt": stored, **meta})

    received = []

    def fake_regenerate(character_name, output_path, original_prompt, **kw):
        received.append(original_prompt)
        return True, original_prompt, output_path

    class _Tq:
        def track_finish(self, *a, **k):
            pass

    def run_worker(worker, fn, prompt, names):
        received.clear()
        worker("Kai", images / fn, prompt, "", "", {}, None, "", names, "", "", "", "", "t", True, True,
               False, _Tq())
        return received[0] if received else None

    real_regen, real_look = ir.regenerate_image, scene_render._appearance_text
    try:
        ir.regenerate_image = fake_regenerate
        scene_render._appearance_text = lambda n: "look"
        w = character_ops.regenerate_image_worker
        check("a) recorded subjects", run_worker(w, "Kai_photo_vbroken.png", stored, None),
              "In the picture: Mira; Kai.\n" + stored + "\nPeople in the frame: Mira (look); Kai (look)")
        check("b) dialog selection", run_worker(w, "Kai_photo_vbroken.png", stored, ["Kai"]),
              "In the picture: Kai.\n" + stored + "\nPeople in the frame: Kai (look)")
        check("c) no scene photo", run_worker(w, "Kai_plain.png", stored, None), stored)
        named = "Mira and Kai sit on the bed."
        check("d) both named", run_worker(w, "Kai_photo_vbroken.png", named, None), named)
        old_ops = _old_module("app/core/character_ops.py", "old_character_ops")
        check(f"proof: {OLD_COMMIT[:9]} passes the prompt without the people",
              run_worker(old_ops.regenerate_image_worker, "Kai_photo_vbroken.png", stored, None), stored)
    finally:
        ir.regenerate_image, scene_render._appearance_text = real_regen, real_look

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
