"""Smoke: the LLM pose check before image generation (app/imagegen/pose_check.py).

Usage:
    ./.venv/bin/python scripts/smoke_pose_check.py

Runs without the server and without a world DB (temp storage, in-memory config,
a stubbed llm_call — no LLM is contacted).

Expected values, derived by hand from the design (2026-11-01, user request
"auswählbar bei jedem Image Routing" + the regenerate dialogs):

A) Catalog — exactly the occasions that render people offer the check:
   photo, instagram, profile, expression, scene_view, event, regenerate (7).
   location / prop / item / tpose / mesh_* do not.
B) Task — "image_pose_check" is a catalog task; unrouted it borrows
   "image_prompt" (fallback_parent).
C) Switch — default off: no config -> apply() returns the prompt unchanged and
   calls no LLM. image_generation.pose_check = {"photo": true} -> "photo"
   checks, "instagram" does not.
D) Override — override=False skips even with the switch on; override=True runs
   even with the switch off; an occasion without people never checks, even
   with override=True.
E) Guard — an answer shorter than half the prompt (111 chars -> < 55.5) is a
   refusal / dropped content: the original stays. An empty answer and an
   exception keep the original too.
F) Save validator — {"photo": true} passes; a non-object, a non-bool value and
   an occasion without people ("location") are refused with "Pose check:".
G) Template — renders the prompt into the user turn and names the limb budget,
   the selfie rule and the CHECK/PROMPT answer form.
H) Answer form (2026-11-01, the model returned a waist-up selfie unchanged
   until it had to list every limb first) — "CHECK: …\nPROMPT: <p>" yields
   <p>; a bare prompt without markers is taken as it is; an answer that is
   only "CHECK: …" carries no prompt -> the original stays. The length guard
   measures the extracted prompt: "CHECK: <long>\nPROMPT: short" is refused.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_pose_check_")
os.environ["STORAGE_DIR"] = _tmp
os.environ["INSTANCE_DIR"] = _tmp

from app.core import paths  # noqa: E402
paths.init(_tmp)

from app.core import config  # noqa: E402
import app.core.llm_router as llm_router  # noqa: E402
from app.imagegen import pose_check  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# --- stubbed LLM -----------------------------------------------------------
calls = []
answer = {"text": "", "raise": False}


class _Resp:
    def __init__(self, content):
        self.content = content


def _fake_llm_call(task, system_prompt="", user_prompt="", agent_name="", **_kw):
    calls.append(task)
    if answer["raise"]:
        raise RuntimeError("no LLM")
    return _Resp(answer["text"])


llm_router.llm_call = _fake_llm_call

PROMPT = ("Kira sitting on the floor, propped on one elbow, one hand waving, "
          "other hand holding a cup, fingers on her lips")
FIXED = "Kira sitting on the floor, propped on her left elbow, her right hand holding a cup near her lips"
assert len(PROMPT) == 111, len(PROMPT)

print("A) catalog")
from app.imagegen.occasions import OCCASIONS, catalog_payload  # noqa: E402
want = {"photo", "instagram", "profile", "expression", "scene_view", "event", "regenerate"}
got = {o for o in OCCASIONS if pose_check.supported(o)}
check("exactly the 7 people occasions offer the check", got == want, f"{sorted(got)}")
check("catalog payload carries the flag",
      {r["id"] for r in catalog_payload() if r["pose_check"]} == want)

print("B) task")
from app.core.llm_tasks import TASK_TYPES  # noqa: E402
check("image_pose_check is a catalog task", "image_pose_check" in TASK_TYPES)
check("unrouted it borrows image_prompt",
      llm_router.fallback_parent("image_pose_check") == "image_prompt")

print("C) switch")
config._CONFIG.setdefault("image_generation", {}).pop("pose_check", None)
answer["text"] = FIXED
calls.clear()
check("default off: unchanged", pose_check.apply("photo", PROMPT) == (PROMPT, False))
check("default off: no LLM call", calls == [])
config._CONFIG["image_generation"]["pose_check"] = {"photo": True}
check("switch on: photo rewritten", pose_check.apply("photo", PROMPT) == (FIXED, True))
check("switch on: task image_pose_check", calls == ["image_pose_check"], f"{calls}")
check("switch is per occasion: instagram untouched",
      pose_check.apply("instagram", PROMPT) == (PROMPT, False))

print("D) override")
calls.clear()
check("override False beats the switch", pose_check.apply("photo", PROMPT, override=False) == (PROMPT, False))
check("override True with switch off", pose_check.apply("instagram", PROMPT, override=True) == (FIXED, True))
check("no people -> never", pose_check.apply("location", PROMPT, override=True) == (PROMPT, False))
check("exactly one LLM call in D", calls == ["image_pose_check"], f"{calls}")
check("parse_override", (pose_check.parse_override(True), pose_check.parse_override("false"),
                         pose_check.parse_override(None), pose_check.parse_override("x"))
      == (True, False, None, None))

print("E) guard")
answer["text"] = "Sorry, I can't."
check("short answer keeps the original", pose_check.check_pose(PROMPT) == PROMPT)
answer["text"] = "x" * 56
check("56 chars (> 55.5) is accepted", pose_check.check_pose(PROMPT) == "x" * 56)
answer["text"] = "   "
check("empty answer keeps the original", pose_check.check_pose(PROMPT) == PROMPT)
answer["raise"] = True
check("an exception keeps the original", pose_check.check_pose(PROMPT) == PROMPT)
answer["raise"] = False

print("F) save validator")
from app.routes.admin_settings import _validate_pose_check  # noqa: E402
check("valid object passes", _validate_pose_check({"pose_check": {"photo": True}}) == "")
check("absent passes", _validate_pose_check({}) == "")
check("non-object refused", _validate_pose_check({"pose_check": ["photo"]}).startswith("Pose check:"))
check("non-bool refused", _validate_pose_check({"pose_check": {"photo": "yes"}}).startswith("Pose check:"))
check("occasion without people refused",
      _validate_pose_check({"pose_check": {"location": True}}).startswith("Pose check:"))

print("G) template")
from app.core.prompt_templates import render_task  # noqa: E402
system, user = render_task("image_pose_check", original_prompt=PROMPT)
check("prompt in the user turn", PROMPT in user)
check("limb budget in the system prompt", "two arms" in system and "two legs" in system)
check("selfie rule in the system prompt", "selfie needs one hand" in system)
check("answer form in the system prompt", "CHECK:" in system and "PROMPT:" in system)

print("H) answer form")
answer["text"] = "CHECK: Kira: left hand elbow, right hand cup\nPROMPT: " + FIXED
check("CHECK + PROMPT -> the prompt", pose_check.check_pose(PROMPT) == FIXED)
answer["text"] = "CHECK:\nKira: left hand x\nKai: both arms y\n\nPROMPT:\n" + FIXED + "\n"
check("multi-line CHECK, prompt on its own line", pose_check.check_pose(PROMPT) == FIXED)
answer["text"] = FIXED
check("bare prompt without markers", pose_check.check_pose(PROMPT) == FIXED)
answer["text"] = "CHECK: Kira: left hand elbow, right hand cup, no conflicts at all here " * 2
check("CHECK only -> original", pose_check.check_pose(PROMPT) == PROMPT)
answer["text"] = "CHECK: " + "x" * 200 + "\nPROMPT: too short"
check("guard measures the extracted prompt", pose_check.check_pose(PROMPT) == PROMPT)

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
