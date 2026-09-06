#!/usr/bin/env python3
"""Smoke run for the prop field `mount` and its LLM classifier
(plan-furnish-v2.md § 2 B1 / decision E3, task 1).

Usage:  ./.venv/bin/python scripts/smoke_props_mount.py

No world DB, no server, no LLM: a throwaway props directory in /tmp gets its
props through the real store, and `llm_router.llm_call` — the one hop
`llm_json` makes — is replaced by canned answers. Everything else is the real
path: the real template render, the real JSON extraction, the real validator,
the real sidecar writes. Every expected value below is derived BY HAND from
the rule, never recorded from a run.

---------------------------------------------------------------------------
[1] THE FIELD: ABSENCE IS "UNCLASSIFIED", NOT "FLOOR"
---------------------------------------------------------------------------
`mount` is one of floor / wall / ceiling / surface and lives on the PROP
sidecar beside name/category/tags. Hand-derived from the rule:

    create_prop(mount="wall")  -> sidecar {"mount": "wall"},
                                  record  mount "wall", mount_suggested False
    create_prop()              -> NO `mount` key in the sidecar,
                                  record  mount "",     mount_suggested False
    create_prop(mount="floor") -> the key IS written: an explicit floor is an
                                  answer and must be distinguishable from
                                  silence
    create_prop(mount="roof")  -> ValueError (unknown kind)

Both records carry both fields: the lean one (`list_props()`, what the
furnish solver and /assets/props read) and the full one (`get_prop`).

---------------------------------------------------------------------------
[2] THE PATCH PATH VALIDATES, AND A REFUSAL WRITES NOTHING
---------------------------------------------------------------------------
`mount` is a `PROP_PATCH_KEYS` field, so it travels the ordinary prop patch
(the route maps the ValueError to a 400 naming the kinds):

    {"mount": "roof"}     -> ValueError, sidecar BYTE-IDENTICAL
    {"mount": "ceiling"}  -> stored
    {"mount": ""}         -> the key GOES (back to unclassified)

---------------------------------------------------------------------------
[3] CLASSIFY: THE ANSWER IS MATCHED BACK, THE REST STAYS UNCLASSIFIED
---------------------------------------------------------------------------
Three props go in as `#1`, `#2`, `#3` (the order of the given id list), and
the canned answer is

    {"mounts": [{"ref": "#1", "mount": "surface"},
                {"ref": "#2", "mount": "attic"},
                {"ref": "#9", "mount": "wall"}]}

Hand-derived from the validator's three drop rules:

    #1  surface -> a known ref and a known kind        => Candle  = surface
    #2  attic   -> known ref, kind not in MOUNT_KINDS  => dropped
    #9  wall    -> the batch never handed out a #9     => dropped

    => classified 1, mounts {Candle: "surface"},
       unresolved [Kettle, Shelf]  (the selection minus the classified)

The one written value is a SUGGESTION: `mount_suggested` True on Candle and
on nobody else. A MANUAL patch is the confirmation and clears the mark:

    update_prop(Candle, {"mount": "floor"})
        -> mount "floor", mount_suggested False

---------------------------------------------------------------------------
[4] NOTHING TO CLASSIFY DOES NOTHING
---------------------------------------------------------------------------
With every prop of the stock classified, the default selection is empty:

    classify_mounts()  -> {"classified": 0, "mounts": {}, "unresolved": []}
                          and NOT ONE LLM call

Both counts at zero is what the route turns into its 409 — a selection the
model answered nothing for would leave its ids in `unresolved` instead.

---------------------------------------------------------------------------
[5] BATCHES OF AT MOST 40
---------------------------------------------------------------------------
45 unclassified props, `BATCH_MAX` 40, so ceil(45 / 40) = 2 LLM calls, and
the batches are 40 and 5 props long. Each batch is its own prompt and numbers
from `#1` again — the second call's rows are `#1 … #5`.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-mount-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import llm_router, props as store, props_mount  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class FakeResponse:
    """What `llm_json` reads off a queue response: its `content`."""

    def __init__(self, content: str) -> None:
        self.content = content


class FakeLLM:
    """`llm_router.llm_call` with canned answers. Records every user prompt,
    so the batching can be counted at the one place it is decided."""

    def __init__(self, answers) -> None:
        self.answers = answers
        self.prompts = []

    def __call__(self, *, task, system_prompt, user_prompt, agent_name="",
                 label="", **_kw) -> FakeResponse:
        self.prompts.append(user_prompt)
        answer = self.answers[min(len(self.prompts) - 1, len(self.answers) - 1)]
        return FakeResponse(json.dumps(answer))


def install(answers) -> FakeLLM:
    fake = FakeLLM(answers)
    llm_router.llm_call = fake
    return fake


def refs(prompt: str) -> list:
    """The `#n` references one rendered batch prompt lists."""
    return [line.split(" ")[0] for line in prompt.splitlines()
            if line.startswith("#")]


def main() -> int:
    print(f"World: {WORLD}")
    print("[1] the field")
    wall = store.create_prop(name="Poster", mount="wall")
    plain = store.create_prop(name="Bench")
    floor = store.create_prop(name="Bed", mount="floor")
    check("create with mount stores it",
          store.read_sidecar(wall["id"]).get("mount") == "wall",
          json.dumps(store.read_sidecar(wall["id"]).get("mount")))
    check("create without mount writes NO key",
          "mount" not in store.read_sidecar(plain["id"]))
    check("an explicit floor IS stored",
          store.read_sidecar(floor["id"]).get("mount") == "floor")
    rec = store.get_prop(wall["id"])
    check("the full record carries mount + mount_suggested",
          rec["mount"] == "wall" and rec["mount_suggested"] is False,
          f"{rec['mount']} / {rec['mount_suggested']}")
    lean = {p["id"]: p for p in store.list_props()}
    check("the lean record carries them too",
          lean[wall["id"]]["mount"] == "wall"
          and lean[plain["id"]]["mount"] == ""
          and lean[plain["id"]]["mount_suggested"] is False,
          json.dumps([lean[wall["id"]]["mount"], lean[plain["id"]]["mount"]]))
    try:
        store.create_prop(name="Roofy", mount="roof")
        check("create refuses an unknown kind", False)
    except ValueError as e:
        check("create refuses an unknown kind",
              all(k in str(e) for k in store.MOUNT_KINDS), str(e))

    print("[2] the patch path")
    before = (Path(store._prop_dir(plain["id"])) / "sidecar.json").read_bytes()
    try:
        store.update_prop(plain["id"], {"mount": "roof"})
        check("a patch with an unknown kind is refused", False)
    except ValueError as e:
        check("a patch with an unknown kind is refused",
              all(k in str(e) for k in store.MOUNT_KINDS), str(e))
    after = (Path(store._prop_dir(plain["id"])) / "sidecar.json").read_bytes()
    check("the refused patch left the sidecar byte-identical", before == after)
    store.update_prop(plain["id"], {"mount": "ceiling"})
    check("a valid patch is stored",
          store.read_sidecar(plain["id"]).get("mount") == "ceiling")
    store.update_prop(plain["id"], {"mount": ""})
    check("an empty patch clears the key",
          "mount" not in store.read_sidecar(plain["id"]))

    print("[3] classify")
    candle = store.create_prop(name="Candle", height_m=0.2)
    kettle = store.create_prop(name="Kettle", height_m=0.25)
    shelf = store.create_prop(name="Shelf", height_m=1.8)
    fake = install([{"mounts": [{"ref": "#1", "mount": "surface"},
                                {"ref": "#2", "mount": "attic"},
                                {"ref": "#9", "mount": "wall"}]}])
    result = props_mount.classify_mounts([candle["id"], kettle["id"],
                                          shelf["id"]])
    check("one LLM call for three props", len(fake.prompts) == 1,
          str(len(fake.prompts)))
    check("the prompt refers to #1..#3, never to a prop id",
          refs(fake.prompts[0]) == ["#1", "#2", "#3"]
          and candle["id"] not in fake.prompts[0],
          json.dumps(refs(fake.prompts[0])))
    check("exactly the valid ref was classified",
          result["classified"] == 1
          and result["mounts"] == {candle["id"]: "surface"},
          json.dumps(result["mounts"]))
    check("the unknown kind and the unknown ref left their props alone",
          sorted(result["unresolved"]) == sorted([kettle["id"], shelf["id"]]),
          json.dumps(result["unresolved"]))
    rec = store.get_prop(candle["id"])
    check("the classified prop is marked as a SUGGESTION",
          rec["mount"] == "surface" and rec["mount_suggested"] is True,
          f"{rec['mount']} / {rec['mount_suggested']}")
    check("the unresolved props stayed unclassified",
          store.get_prop(kettle["id"])["mount"] == ""
          and "mount" not in store.read_sidecar(shelf["id"]))
    store.update_prop(candle["id"], {"mount": "floor"})
    rec = store.get_prop(candle["id"])
    check("a manual patch confirms it (the suggestion mark goes)",
          rec["mount"] == "floor" and rec["mount_suggested"] is False,
          f"{rec['mount']} / {rec['mount_suggested']}")

    print("[4] nothing to classify")
    for pid in (plain["id"], kettle["id"], shelf["id"]):
        store.update_prop(pid, {"mount": "floor"})
    fake = install([{"mounts": []}])
    result = props_mount.classify_mounts()
    check("an empty selection answers with zeros",
          result == {"classified": 0, "mounts": {}, "unresolved": []},
          json.dumps(result))
    check("…and makes no LLM call at all", fake.prompts == [])

    print("[5] batching")
    many = [store.create_prop(name=f"Crate {i}")["id"] for i in range(45)]
    fake = install([{"mounts": []}])
    result = props_mount.classify_mounts()
    check("45 unclassified props are two calls", len(fake.prompts) == 2,
          str(len(fake.prompts)))
    check("the batches are 40 and 5 props long",
          [len(refs(p)) for p in fake.prompts] == [40, 5],
          json.dumps([len(refs(p)) for p in fake.prompts]))
    check("every batch numbers from #1 again",
          refs(fake.prompts[1]) == ["#1", "#2", "#3", "#4", "#5"],
          json.dumps(refs(fake.prompts[1])))
    check("nothing was answered, so all 45 are unresolved",
          result["classified"] == 0
          and sorted(result["unresolved"]) == sorted(many),
          str(len(result["unresolved"])))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(WORLD, ignore_errors=True)
