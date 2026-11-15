#!/usr/bin/env python3
"""Smoke: the HAAR prompt from the profile picture (Ruling A105, "HAAR braucht einen Prompt für die
Frisurbeschreibung. Dieser soll aus dem Profilbild entstehen mit Hilfe eines LLMs.").

Usage:
    ./.venv/bin/python scripts/smoke_haar_hair_prompt.py

Runs without a server, a hub or an LLM: a temp world (``paths.init`` first), ``llm_router.llm_call`` stubbed in
``app.core.llm_router`` (it records every call; 0 outbound requests), the hub operation of the HAAR step stubbed
(``hub_ops.create`` / ``execute`` record what the step would send).

Fixture (neutral wording): character Demo (human), hairstyle H = create_hairstyle(Demo, "short hair", "haar"),
profile picture ``images/profile.png`` (8 bytes of PNG magic + "x").

Expected values, derived by hand from the code:

[1] The template renders under StrictUndefined: ``render_task("haar_hair_prompt", hairstyle_name="Short hair",
    current_text="short hair")`` has a system part naming "HAAR" and "Leave out" and a user part containing
    "Hairstyle name: Short hair" and "Current text (context, may be outdated): short hair"; a missing placeholder
    raises.
[2] Routing: ``fallback_parent("haar_hair_prompt")`` = "image_recognition"; the task is in ``TASK_TYPES`` with
    ``requirements.vision`` True.
[3] ``llm_call(image_path=…)`` attaches the picture: with the queue's ``submit`` stubbed, the user message content
    is a list ``[{"type": "text", …}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,…"}}]``
    whose text is the user prompt; without ``image_path`` it stays the plain string.
[4] ``clean_haar_prompt``: '<think>a</think>\\n**Description:** "long wavy hair, middle part."' ->
    "long wavy hair, middle part"; "- long hair\\n- dark brown" -> "long hair, dark brown"; "" and
    "I'm sorry, I can't help with that." -> ValueError; 80 x "word phrase" joined by ", " (1038 chars) -> cut at
    the last comma inside 350 chars: 27 phrases = 27*11 + 26*2 = 349 chars (text[:350] ends on the 28th comma).
[5] No profile picture -> ValueError "has no profile picture", NO llm call. An item of another character ->
    ValueError, no call.
[6] With the picture: the stub answers '"Shoulder-length wavy hair, side part, auburn."' ->
    "Shoulder-length wavy hair, side part, auburn"; ONE call, task "haar_hair_prompt", ``image_path`` = the profile
    file, agent "Demo", ``max_tokens`` 200; the item is unchanged (nothing saved).
[7] The route ``suggest_character_hairstyle_text`` returns {item_id: H, text}; no picture -> 400; a raising LLM ->
    502; a refusal answer -> 502. Its dependencies include ``require_admin`` (players are refused);
    ``smoke_auth_gate.py`` covers the gate itself.
[8] The HAAR step receives the saved text: after ``set_hairstyle_description(Demo, H, suggestion)``
    ``garment_store.haar_prompt(H)`` == the suggestion and ``garments._run_haar`` hands it to the hub operation's
    inputs (``prompt``).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS: list = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc, text=""):
    try:
        fn()
    except exc as e:
        check(label, text in str(e), True)
        return
    except Exception as e:  # noqa: BLE001
        check(label, type(e).__name__, exc.__name__)
        return
    check(label, "no exception", exc.__name__)


class Reply:
    def __init__(self, content: str):
        self.content = content


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="haar-hair-prompt-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from fastapi import HTTPException
        from app.core import garment_hair, garments, hub_ops, llm_router
        from app.core import garment_store as gs
        from app.core.llm_tasks import TASK_TYPES
        from app.core.prompt_templates import render_task
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile, get_character_profile
        from app.routes import characters as char_route

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"}, "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("create Other", save_character_profile("Other", dict(human), create_new=True), True)
        hid = garment_hair.create_hairstyle("Demo", "short hair", "haar")
        oid = garment_hair.create_hairstyle("Other", "short hair", "haar")

        print("[1] template")
        system, user = render_task("haar_hair_prompt", hairstyle_name="Short hair", current_text="short hair")
        check("system names HAAR + leave out", ("HAAR" in system, "Leave out" in system), (True, True))
        check("user name", "Hairstyle name: Short hair" in user, True)
        check("user text", "Current text (context, may be outdated): short hair" in user, True)
        raises("missing placeholder raises", lambda: render_task("haar_hair_prompt", hairstyle_name="x"), Exception)

        print("[2] routing")
        check("fallback", llm_router.fallback_parent("haar_hair_prompt"), "image_recognition")
        check("vision task", (TASK_TYPES.get("haar_hair_prompt") or {}).get("requirements", {}).get("vision"), True)

        print("[3] llm_call attaches the image")
        pic = root / "pic.png"
        pic.write_bytes(b"\x89PNG\r\n\x1a\nx")
        sent: list = []

        class FakeQueue:
            def submit(self, **kw):
                sent.append(kw["messages_or_prompt"])
                return Reply("ok")

        class FakeInstance:
            pinned = True
            provider_name = "p"
            model = "m"

            def create_llm(self, **kw):
                return object()

        real = (llm_router.resolve_llm, llm_router.get_llm_queue, llm_router._response_refusal)
        llm_router.resolve_llm = lambda *a, **k: FakeInstance()
        llm_router.get_llm_queue = lambda: FakeQueue()
        llm_router._response_refusal = lambda *a, **k: None
        try:
            llm_router.llm_call("haar_hair_prompt", "S", "U", image_path=pic)
            llm_router.llm_call("haar_hair_prompt", "S", "U")
        finally:
            llm_router.resolve_llm, llm_router.get_llm_queue, llm_router._response_refusal = real
        content = sent[0][1]["content"]
        check("list content", [c.get("type") for c in content], ["text", "image_url"])
        check("text = user prompt", content[0]["text"], "U")
        check("data url", content[1]["image_url"]["url"].startswith("data:image/png;base64,"), True)
        check("no image: plain string", sent[1][1]["content"], "U")

        print("[4] clean_haar_prompt")
        c = garment_hair.clean_haar_prompt
        check("think/markdown/label/quotes", c('<think>a</think>\n**Description:** "long wavy hair, middle part."'),
              "long wavy hair, middle part")
        check("bullets", c("- long hair\n- dark brown"), "long hair, dark brown")
        raises("empty", lambda: c(""), ValueError, "nothing usable")
        raises("refusal", lambda: c("I'm sorry, I can't help with that."), ValueError, "refused")
        check("cap at last comma", len(c(", ".join(["word phrase"] * 80))), 349)

        calls: list = []
        answer = {"value": '"Shoulder-length wavy hair, side part, auburn."'}

        def fake_llm_call(task, system_prompt, user_prompt, **kw):
            calls.append({"task": task, **kw})
            if isinstance(answer["value"], Exception):
                raise answer["value"]
            return Reply(answer["value"])
        llm_router.llm_call = fake_llm_call

        print("[5] no picture")
        raises("no picture", lambda: garment_hair.suggest_haar_prompt("Demo", hid), ValueError, "has no profile picture")
        raises("foreign item", lambda: garment_hair.suggest_haar_prompt("Demo", oid), ValueError, "no hairstyle")
        check("no call", len(calls), 0)

        print("[6] with the picture")
        images = get_character_dir("Demo") / "images"
        images.mkdir(parents=True, exist_ok=True)
        (images / "profile.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
        prof = get_character_profile("Demo")
        prof["profile_image"] = "profile.png"
        check("set picture", save_character_profile("Demo", prof), True)
        before = inventory.get_item(hid)
        text = garment_hair.suggest_haar_prompt("Demo", hid)
        check("text", text, "Shoulder-length wavy hair, side part, auburn")
        check("one call", [(x["task"], Path(x["image_path"]).name, x["agent_name"], x["max_tokens"]) for x in calls],
              [("haar_hair_prompt", "profile.png", "Demo", 200)])
        check("nothing saved", inventory.get_item(hid), before)

        print("[7] route")
        body = char_route.HairstyleItemRequest(item_id=hid)
        check("route answer", char_route.suggest_character_hairstyle_text("Demo", body, {}), {"item_id": hid, "text": text})
        deps = [getattr(p.default, "dependency", None) for p in
                __import__("inspect").signature(char_route.suggest_character_hairstyle_text).parameters.values()]
        from app.core.auth_dependency import require_admin
        check("require_admin dependency", require_admin in deps, True)

        def status(fn):
            try:
                fn()
            except HTTPException as e:
                return e.status_code
            return 200
        answer["value"] = RuntimeError("upstream down")
        check("LLM fails -> 502", status(lambda: char_route.suggest_character_hairstyle_text("Demo", body, {})), 502)
        answer["value"] = "I cannot see any image."
        check("refusal -> 502", status(lambda: char_route.suggest_character_hairstyle_text("Demo", body, {})), 502)
        prof = get_character_profile("Demo")
        prof["profile_image"] = ""
        save_character_profile("Demo", prof)
        check("no picture -> 400", status(lambda: char_route.suggest_character_hairstyle_text("Demo", body, {})), 400)

        print("[8] the HAAR step receives the saved text")
        check("save", garment_hair.set_hairstyle_description("Demo", hid, text), True)
        check("haar_prompt", gs.haar_prompt(hid), text)
        sent_ops: list = []
        real_ops = (hub_ops.create, hub_ops.execute)
        hub_ops.create = lambda kind, key, inputs, **kw: sent_ops.append(inputs) or object()
        hub_ops.execute = lambda op, fn: {"stored": []}
        try:
            garments._run_haar("Demo", hid, "abcdef012345", [1])  # a fixed ssig: garment_ssig would build the image service
        finally:
            hub_ops.create, hub_ops.execute = real_ops
        check("hub op prompt", [o.get("prompt") for o in sent_ops], [text])

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
