"""Smoke: the prompt character limit per backend (app/imagegen/prompt_limit.py).

Usage:
    ./.venv/bin/python scripts/smoke_prompt_limit.py

Runs without the server and without a world DB (temp storage, a fake GPU
queue, a stubbed hub GET and a stubbed llm_call — nothing leaves the process).

Background (docs/prompt-limit-anforderung.md, 2026-11-12): a 1551-character
T-pose prompt was refused with HTTP 400 by a backend whose model allows 1500.
Rulings PL1-PL3: the limit comes from the backend's manual
``prompt_char_limit`` (wins) or the hub's alias schema; an over-limit prompt
is condensed by the LLM task ``image_prompt_shorten`` BEFORE the GPU
submission, then checked hard and cut if needed; image_prompts.jsonl records
what happened. The mechanism is general — two different stub backend types
go through the same handoff (``ImageService.run_on_backend_channel`` +
``ImageBackend.generate``).

Expected values, derived by hand:

The test prompt P = HEAD + ", " + ", ".join(SEG_1 .. SEG_47)
  HEAD  = "Keep the person from <Picture 1> exactly as is."  -> 47 chars
  SEG_i = "seg NN with plain filler texts"                    -> 30 chars
  len(P) = 47 + 2 + 47*30 + 46*2 = 47 + 2 + 1410 + 92 = 1551   (the evidence)
  The comma after SEG_j sits at index 47 + 2 + 30j + 2(j-1) = 47 + 32j, so the
  text before it is 47 + 32j long. Largest j with 47 + 32j <= 1500: 32j <= 1453
  -> j = 45 -> the cut is 47 + 1440 = 1487 chars and ends with "seg 45 with
  plain filler texts" (j = 46 would give 1519 > 1500). HEAD's "." is followed
  by "," (no whitespace), so it is no sentence boundary. 1487 >= 750 (half the
  limit), so the comma cut stands. "<Picture 1>" sits at 21..32: kept.

A) Hub reader (contract of the ai-hub session):
   {"prompt_limit": {"max_chars": 1500, "status": "known"}}   -> 1500
   {"prompt_limit": {"max_chars": 1500, "status": "unknown"}} -> None
   {"prompt_limit": {"max_chars": null, "status": "known"}}   -> None
   {} (field missing)                                          -> None
   HTTP 404                                                    -> None
   a connection error                                          -> None
   a second read of the same alias inside the TTL issues no GET (cache), also
   for a "no limit" answer (404) — one request per alias per TTL.
B) Manual field beats the hub: manual 1500, hub says 1000 -> 1500, and the hub
   is not even asked (0 GETs).
C) The cut alone: cut_to_limit(P, 1500) -> 1487 chars (see above), ends with
   "seg 45 with plain filler texts", keeps "<Picture 1>".
   Token guard: "a"*1495 + "<Picture 2>" + "b"*50 (1556 chars, no comma) ->
   no boundary, the only space is at 1503 (inside the token) > 1500 -> hard
   cut at 1500 would split the token at 1495..1506 -> moved to 1495: "a"*1495.
D) Stub backend type 1 (image, manual limit 1500), LLM answers 1200 chars
   (with "<Picture 1>"): the first channel pass bounces (nothing sent), the
   LLM runs on the CALLER thread with no slot held, the second pass sends
   exactly the 1200-char answer -> 2 submissions, priority 25 then 24,
   _generate called once with the 1200-char text, method "llm".
   jsonl row: final_prompt = the 1200 chars, prompt_char_limit 1500,
   shorten_method "llm", unshortened_prompt = P (1551), original_prompt
   present (the caller's).
E) Cache: the same prompt again -> the LLM is NOT called again (1 call total),
   ONE submission (the decision comes from the cache, no bounce).
F) LLM fails (raises) on a new prompt P2 = P with "seg" -> "sec" (same
   lengths) -> the cut: 1487 chars ending "sec 45 with plain filler texts",
   method "cut".
G) LLM answer drops "<Picture 1>" (1200 chars without it) -> rejected ->
   the cut of the original (1487), method "cut". An LLM answer of 1600 chars
   (with the token) is still too long -> its own cut (<= 1500), method "cut".
H) No limit (manual 0, hub 404): the prompt reaches _generate byte-identical,
   ONE submission, no LLM call, method "none", prompt_char_limit 0.
I) Stub backend type 2 (video, no manual limit, hub says 1500 for its model):
   the same handoff shortens it (LLM answer 1300 chars) -> 2 submissions,
   _generate gets the 1300 chars, method "llm".
J) A second pass without a decision (cache cleared, may_bounce False) cuts in
   place: 1487 chars, no LLM call.
K) LoRA trigger words are kept (review 09#8). ``get_lora_trigger_words`` answers
   ["zxq-style"] for the LoRA "k.safetensors"; backend manual 1500; the caller's
   prompt P4 = P with "seg " -> "sek " (1551, a new cache key). generate()
   prepends "zxq-style, " -> the final prompt has 9 + 2 + 1551 = 1562 chars.
   The LLM answers ANSWER (1200 chars, keeps "<Picture 1>", lacks "zxq-style")
   -> rejected -> the cut of the final prompt: HEAD now starts at 11, its comma
   at 58, the comma after SEK_j at 58 + 32j; largest j with 58 + 32j <= 1500 is
   45 -> 1498 chars, starting "zxq-style, Keep the person", ending "sek 45 with
   plain filler texts", method "cut" — through the bounce, whose shortening on
   the caller's thread is handed no keep words by its caller (service.py).
   (Fails on 1dbf8d3af: _generate got the 1200-char answer without the trigger.)
   The cut alone: cut_to_limit("one, my trigger word here and more text", 12)
   -> comma boundary at 3 < 6 (half the limit) -> last space at or under 12 is
   7 -> "one, my"; with keep ["my trigger word"] (span 5..20) the end 7 lies
   inside it -> moved to 5 -> "one, " stripped -> "one".
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_prompt_limit_")
os.environ["STORAGE_DIR"] = _tmp
os.environ["INSTANCE_DIR"] = _tmp

from app.core import paths  # noqa: E402
paths.init(_tmp)

import requests  # noqa: E402

import app.core.llm_queue as llm_queue  # noqa: E402
import app.core.llm_router as llm_router  # noqa: E402
import app.utils.image_prompt_logger as ipl  # noqa: E402
from app.imagegen import prompt_limit as pl  # noqa: E402
from app.imagegen import service as service_mod  # noqa: E402
from app.imagegen.base import ImageBackend  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# --- the test prompt (hand-derived lengths, see docstring) -----------------
HEAD = "Keep the person from <Picture 1> exactly as is."
SEGS = [f"seg {i:02d} with plain filler texts" for i in range(1, 48)]
P = HEAD + ", " + ", ".join(SEGS)
assert len(HEAD) == 47 and all(len(s) == 30 for s in SEGS), "fixture lengths"
check("fixture: the prompt has 1551 chars", len(P) == 1551, len(P))
P2 = P.replace("seg ", "sec ")

# --- isolate the jsonl log --------------------------------------------------
ipl.LOG_DIR = Path(_tmp) / "logs"
ipl.LOG_FILE = ipl.LOG_DIR / "image_prompts.jsonl"


def last_row():
    lines = ipl.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1])


# --- stub hub ---------------------------------------------------------------
HUB = {}       # url -> (status, json | Exception)
gets = []


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.content = b"x"

    def json(self):
        return self._body


def fake_get(url, headers=None, timeout=None, **kw):
    gets.append(url)
    status, body = HUB.get(url, (404, {"detail": "not found"}))
    if isinstance(body, Exception):
        raise body
    return _Resp(status, body)


requests.get = fake_get

# --- stub LLM ---------------------------------------------------------------
slot = {"held": False}
llm = {"answer": "", "raise": False, "calls": [], "held_during": [], "threads": []}


class _LLMResp:
    def __init__(self, content):
        self.content = content


def fake_llm_call(task, system_prompt, user_prompt, **kw):
    llm["calls"].append(task)
    llm["held_during"].append(slot["held"])
    llm["threads"].append(threading.current_thread().name)
    if llm["raise"]:
        raise RuntimeError("no LLM available")
    return _LLMResp(llm["answer"])


llm_router.llm_call = fake_llm_call

# --- fake GPU queue (runs the callable on a worker thread, holding a "slot") -
subs = []


class FakeQueue:
    def submit_gpu_task(self, provider_name="", task_type="", priority=20,
                        callable_fn=None, agent_name="", label="", gpu_type=""):
        subs.append((provider_name, priority))
        box = {}

        def worker():
            slot["held"] = True
            try:
                box["result"] = callable_fn()
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc
            finally:
                slot["held"] = False

        t = threading.Thread(target=worker, name="fake-channel-worker")
        t.start()
        t.join()
        if "error" in box:
            raise box["error"]
        return box["result"]


llm_queue.get_llm_queue = lambda: FakeQueue()
service_mod.media_generation_enabled = lambda: True
run_on_channel = service_mod.ImageService.run_on_backend_channel


# --- two different stub backend types ---------------------------------------
class _StubBase(ImageBackend):
    def __init__(self, name, api_type, prefix, *, manual=0, model="", url=""):
        os.environ[f"{prefix}PROMPT_CHAR_LIMIT"] = str(manual) if manual else ""
        super().__init__(name, url, 0.0, api_type, prefix)
        self.model = model
        self.api_key = "k"
        self.sent = []

    def check_availability(self):
        return True

    def _generate(self, prompt, negative_prompt, params):
        self.sent.append(prompt)
        return [b"img"]


class StubImageBackend(_StubBase):
    MEDIA_TYPE = "image"


class StubVideoBackend(_StubBase):
    MEDIA_TYPE = "video"


def render(backend, prompt, agent="Demo"):
    meta = {"agent_name": agent, "original_prompt": "caller prompt"}
    return run_on_channel(backend, lambda: backend.generate(prompt, "", {}, log_meta=meta),
                          task_type="image_generation", agent_name=agent)


def reset():
    subs.clear()
    llm.update(answer="", calls=[], held_during=[], threads=[])
    llm["raise"] = False


# ---------------------------------------------------------------------------
print("A) hub reader")
H = "http://hub.test"
HUB[f"{H}/v1/generations/a-known/schema"] = (200, {"prompt_limit": {"max_chars": 1500, "unit": "characters", "status": "known", "candidates": []}})
HUB[f"{H}/v1/generations/a-unknown/schema"] = (200, {"prompt_limit": {"max_chars": 1500, "status": "unknown"}})
HUB[f"{H}/v1/generations/a-null/schema"] = (200, {"prompt_limit": {"max_chars": None, "status": "known"}})
HUB[f"{H}/v1/generations/a-missing/schema"] = (200, {"images": []})
HUB[f"{H}/v1/generations/a-down/schema"] = (0, requests.ConnectionError("refused"))
check("known -> 1500", pl.hub_prompt_limit(H, "a-known") == 1500)
check("unknown -> None", pl.hub_prompt_limit(H, "a-unknown") is None)
check("null -> None", pl.hub_prompt_limit(H, "a-null") is None)
check("missing field -> None", pl.hub_prompt_limit(H, "a-missing") is None)
check("404 -> None", pl.hub_prompt_limit(H, "a-404") is None)
check("connection error -> None", pl.hub_prompt_limit(H, "a-down") is None)
n = len(gets)
pl.hub_prompt_limit(H, "a-known")
pl.hub_prompt_limit(H, "a-404")
check("a second read inside the TTL issues no GET (limit and 404 alike)", len(gets) == n, len(gets) - n)
check("a model id with a slash keeps its path",
      pl.hub_prompt_limit(H, "vendor.ai/model-x") is None
      and gets[-1] == f"{H}/v1/generations/vendor.ai/model-x/schema", gets[-1])

print("B) the manual field beats the hub")
HUB[f"{H}/v1/generations/b-model/schema"] = (200, {"prompt_limit": {"max_chars": 1000, "status": "known"}})
manual = StubImageBackend("Manual", "stub_image", "SMOKE_PL_B_", manual=1500, model="b-model", url=H)
n = len(gets)
check("manual 1500 wins over hub 1000", pl.resolve_limit(manual) == 1500)
check("the hub is not asked when the manual field is set", len(gets) == n)
hubonly = StubImageBackend("HubOnly", "stub_image", "SMOKE_PL_B2_", model="b-model", url=H)
check("without the manual field the hub value counts (1000)", pl.resolve_limit(hubonly) == 1000)

print("C) the cut")
cut = pl.cut_to_limit(P, 1500)
check("cut lands on the comma after seg 45: 1487 chars", len(cut) == 1487, len(cut))
check("cut ends with 'seg 45 with plain filler texts'", cut.endswith("seg 45 with plain filler texts"), cut[-40:])
check("cut keeps <Picture 1>", "<Picture 1>" in cut)
tok = "a" * 1495 + "<Picture 2>" + "b" * 50
tcut = pl.cut_to_limit(tok, 1500)
check("hard cut never splits <Picture 2>: 1495 x 'a'", tcut == "a" * 1495, len(tcut))
check("a prompt within the limit is returned as is", pl.cut_to_limit("short, prompt", 1500) == "short, prompt")

print("D) stub type 1 (image, manual 1500): LLM answer of 1200 chars is sent")
reset()
img = StubImageBackend("Stub Image", "stub_image", "SMOKE_PL_D_", manual=1500, model="", url="")
ANSWER = (HEAD + " " + "condensed wording " * 70)[:1199] + "."
assert len(ANSWER) == 1200 and ANSWER == ANSWER.strip() and "<Picture 1>" in ANSWER
llm["answer"] = ANSWER
render(img, P)
check("two submissions (bounce, then the send)", len(subs) == 2, subs)
check("priority 25 then 24", [p for _, p in subs] == [25, 24], subs)
check("_generate called once", len(img.sent) == 1, len(img.sent))
check("the 1200-char answer is what was sent", img.sent and img.sent[0] == ANSWER,
      len(img.sent[0]) if img.sent else None)
check("one LLM call, task image_prompt_shorten", llm["calls"] == ["image_prompt_shorten"], llm["calls"])
check("the LLM ran with no slot held, on the caller thread",
      llm["held_during"] == [False] and llm["threads"] == [threading.current_thread().name],
      (llm["held_during"], llm["threads"]))
row = last_row()
check("jsonl: final_prompt is the sent text", row.get("final_prompt") == ANSWER)
check("jsonl: prompt_char_limit 1500", row.get("prompt_char_limit") == 1500, row.get("prompt_char_limit"))
check("jsonl: shorten_method llm", row.get("shorten_method") == "llm", row.get("shorten_method"))
check("jsonl: unshortened_prompt is the 1551-char prompt", row.get("unshortened_prompt") == P)
check("jsonl: original_prompt is the caller's", row.get("original_prompt") == "caller prompt",
      row.get("original_prompt"))

print("E) cache")
reset()
img.sent.clear()
render(img, P)
check("no second LLM call", llm["calls"] == [], llm["calls"])
check("one submission (cache decides in the channel)", len(subs) == 1, subs)
check("the cached 1200 chars are sent", img.sent == [ANSWER])

print("F) LLM failure -> the cut")
reset()
img.sent.clear()
llm["raise"] = True
render(img, P2)
check("sent text is the 1487-char comma cut", img.sent and len(img.sent[0]) == 1487,
      len(img.sent[0]) if img.sent else None)
check("ends with 'sec 45 with plain filler texts'", img.sent and img.sent[0].endswith("sec 45 with plain filler texts"))
check("<Picture 1> kept by the cut", img.sent and "<Picture 1>" in img.sent[0])
check("jsonl: shorten_method cut", last_row().get("shorten_method") == "cut")

print("G) unusable LLM answers")
reset()
llm["answer"] = ("condensed wording " * 80)[:1200]           # no <Picture 1>
text, method = pl.shorten(P.replace("plain", "plaim"), 1500)
check("an answer without <Picture 1> is rejected -> the cut (1487)", (len(text), method) == (1487, "cut"), (len(text), method))
reset()
llm["answer"] = (HEAD + ", " + "long condensed wording, " * 80)[:1600]
text, method = pl.shorten(P.replace("plain", "plaid"), 1500)
check("a 1600-char answer is cut to <= 1500", len(text) <= 1500 and method == "cut", (len(text), method))
check("its cut keeps <Picture 1>", "<Picture 1>" in text)

print("H) no limit -> byte-identical")
reset()
free = StubImageBackend("Free", "stub_image", "SMOKE_PL_H_", model="h-model", url=H)
render(free, P)
check("the prompt reaches _generate byte-identical", free.sent == [P])
check("one submission, no LLM call", len(subs) == 1 and llm["calls"] == [], (subs, llm["calls"]))
row = last_row()
check("jsonl: shorten_method none, prompt_char_limit 0",
      (row.get("shorten_method"), row.get("prompt_char_limit")) == ("none", 0),
      (row.get("shorten_method"), row.get("prompt_char_limit")))
check("jsonl: no unshortened_prompt", "unshortened_prompt" not in row)

print("I) stub type 2 (video, hub limit 1500) through the same handoff")
reset()
HUB[f"{H}/v1/generations/i-video/schema"] = (200, {"prompt_limit": {"max_chars": 1500, "status": "known"}})
vid = StubVideoBackend("Stub Video", "stub_video", "SMOKE_PL_I_", model="i-video", url=H)
VANSWER = (HEAD + " " + "motion wording " * 100)[:1299] + "."
llm["answer"] = VANSWER
P3 = P.replace("filler", "fillar")
render(vid, P3)
check("two submissions", len(subs) == 2, subs)
check("_generate got the 1300-char answer", vid.sent == [VANSWER])
check("jsonl: method llm, limit 1500",
      (last_row().get("shorten_method"), last_row().get("prompt_char_limit")) == ("llm", 1500))

print("J) a second pass without a decision cuts in place")
reset()
with pl._cache_lock:
    pl._cache.clear()
token = pl.CHANNEL.set(pl.ChannelContext(limit=1500, may_bounce=False))
try:
    fit = pl.fit_prompt(img, P)
finally:
    pl.CHANNEL.reset(token)
check("1487 chars, method cut, no LLM call",
      (len(fit.prompt), fit.method, llm["calls"]) == (1487, "cut", []),
      (len(fit.prompt), fit.method, llm["calls"]))

print("K) LoRA trigger words survive the shortening")
reset()
import app.core.config as config_mod  # noqa: E402
config_mod.get_lora_trigger_words = lambda names: ["zxq-style"] if "k.safetensors" in names else []
trig = StubImageBackend("Trig", "stub_image", "SMOKE_PL_K_", manual=1500, model="", url="")
P4 = P.replace("seg ", "sek ")
llm["answer"] = ANSWER
run_on_channel(trig, lambda: trig.generate(P4, "", {"loras": [{"name": "k.safetensors"}]},
                                           log_meta={"agent_name": "Demo"}),
               task_type="image_generation", agent_name="Demo")
sent = trig.sent[0] if trig.sent else ""
check("the LLM was asked once", llm["calls"] == ["image_prompt_shorten"], llm["calls"])
check("the cut was sent: 1498 chars", len(sent) == 1498, len(sent))
check("it starts with the trigger word", sent.startswith("zxq-style, Keep the person"), sent[:30])
check("it ends with SEK 45", sent.endswith("sek 45 with plain filler texts"), sent[-30:])
check("jsonl: method cut", last_row().get("shorten_method") == "cut", last_row().get("shorten_method"))
T = "one, my trigger word here and more text"
check("cut without keep", pl.cut_to_limit(T, 12) == "one, my", pl.cut_to_limit(T, 12))
check("cut never ends inside a kept word", pl.cut_to_limit(T, 12, ["my trigger word"]) == "one",
      pl.cut_to_limit(T, 12, ["my trigger word"]))

print()
if failures:
    print(f"FAILED — {len(failures)} check(s): {failures}")
    sys.exit(1)
print("all checks passed")
