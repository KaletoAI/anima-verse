"""Smoke: the dialect table, the backend lint and the one-table guard (app/imagegen/edit_prompt.py).

Usage:
    ./.venv/bin/python scripts/smoke_edit_prompt_table.py

Pure — no server, no world DB, no config. Design: docs/edit-prompts.md §1, §5.

Expected values, derived by hand from ``DIALECT_BY_MODEL`` (lower-case substring of ``model``, first hit wins):

[1] the model ids of the current routing table
    "P-H3-Image" -> "p-h3" -> picture_edit; "MiniMax-H3-Image" -> "minimax-h3" -> picture_subject;
    "Qwen2.1" and "Qwen2.1-Turbo" -> "qwen2.1" -> image_tag; "Qwen-Image-2.1" -> "qwen-image-2.1" -> image_tag;
    "Flux2-9B", "Z-Image-Turbo", "" -> no hit -> ordinal (source "default").
    A configured field beats the table: "Qwen2.1" with "picture_edit" -> picture_edit ("config"); "auto" and an
    unknown value ("Picture") -> the table.
[2] lint_backend (codes):
    picture_edit, extra {} -> ["upsampler_on"] (the hub runs the upsampler when the key is not sent);
    extra {"use_prompt_upsampler": false} -> [].
    image_tag, width 1024, extra {"cfg": 1.5} -> ["below_native", "cfg_not_1"]; width 2048, {"cfg": 1} -> [].
    picture_subject, extra {"steps": 8} -> ["fixed_sampling"]; {} -> []. ordinal -> [].
[3] Guard: in app/ no Python string CONSTANT equals (case-insensitive) a needle of the table outside
    app/imagegen/edit_prompt.py — except the CivitAI video engine names "minimax-h3" (an API value of that service,
    not a reference-wording rule) in backends/civitai_video.py and the config schema's video_engine choices.
    Fails on 7fc7c386d (prompt_adapters.PICTURE_REFERENCE_MODELS = ("p-h3", "minimax-h3")).
[4] The choke point: a stub ``ImageBackend`` (model "Qwen2.1", manual prompt limit 100000 so no hub is asked, the
    image-prompt log redirected to a temp file) gets ``generate("Put the hat from the second image on the first
    image.", "", {2 slots}, log_meta={})``: the engine receives "Put the hat from <image2> on <image1>.", log_meta
    carries final_prompt = that text and edit_prompt with dialect "image_tag", source "auto", refs [1, 2],
    rewrites 2; the jsonl row has the same edit_prompt. Without reference images the engine receives the prompt
    byte-identical and neither log_meta nor the row has an edit_prompt key. A configured prompt_dialect
    ("picture_edit" via the env bridge SKILL_..._PROMPT_DIALECT read in __init__) gives "Edit <Picture 1>. Put the
    hat from <Picture 2> on <Picture 1>.".
"""
from __future__ import annotations

import ast
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
    def __init__(self, model: str, setting: str = "", width: int = 1024, extra=None):
        self.model, self.prompt_dialect_setting, self.width = model, setting, width
        self.extra_params = extra if extra is not None else {}
        self.name = "stub"


print("[1] table")
for model, want in (("P-H3-Image", ("picture_edit", "auto")), ("MiniMax-H3-Image", ("picture_subject", "auto")),
                    ("Qwen2.1", ("image_tag", "auto")), ("Qwen2.1-Turbo", ("image_tag", "auto")),
                    ("Qwen-Image-2.1", ("image_tag", "auto")), ("Flux2-9B", ("ordinal", "default")),
                    ("Z-Image-Turbo", ("ordinal", "default")), ("", ("ordinal", "default"))):
    check(f"{model!r}", ep.resolve_dialect(B(model)), want)
check("config beats the table", ep.resolve_dialect(B("Qwen2.1", "picture_edit")), ("picture_edit", "config"))
check("auto -> table", ep.resolve_dialect(B("Qwen2.1", "auto")), ("image_tag", "auto"))
check("unknown value -> table", ep.resolve_dialect(B("Qwen2.1", "Picture")), ("image_tag", "auto"))
check("settings", ep.DIALECT_SETTINGS, ("auto", "picture_edit", "picture_subject", "image_tag", "ordinal"))


def codes(b) -> list:
    return [x["code"] for x in ep.lint_backend(b)]


print("[2] lint")
check("P-H3 upsampler on", codes(B("P-H3-Image")), ["upsampler_on"])
check("P-H3 upsampler off", codes(B("P-H3-Image", extra={"use_prompt_upsampler": False})), [])
check("Qwen 1024 cfg 1.5", codes(B("Qwen2.1", extra={"cfg": 1.5})), ["below_native", "cfg_not_1"])
check("Qwen 2048 cfg 1", codes(B("Qwen2.1", width=2048, extra={"cfg": 1})), [])
check("MiniMax steps", codes(B("MiniMax-H3-Image", extra={"steps": 8})), ["fixed_sampling"])
check("MiniMax clean", codes(B("MiniMax-H3-Image")), [])
check("ordinal", codes(B("Flux2-9B", extra={"cfg": 3})), [])
check("levels", [x["level"] for x in ep.lint_backend(B("P-H3-Image"))], ["warning"])

print("[3] one table")
needles = {n for n, _ in ep.DIALECT_BY_MODEL}
ALLOWED = {("app/imagegen/backends/civitai_video.py", "minimax-h3"), ("app/core/config_schema.py", "minimax-h3")}
hits = []
for path in sorted((ROOT / "app").rglob("*.py")):
    rel = path.relative_to(ROOT).as_posix()
    if rel == "app/imagegen/edit_prompt.py":
        continue
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            v = node.value.strip().lower()
            if v in needles and (rel, v) not in ALLOWED:
                hits.append(f"{rel}:{node.lineno} {node.value!r}")
check("no model-name rule outside edit_prompt.py", hits, [])

print("[4] the choke point")
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402

with tempfile.TemporaryDirectory(prefix="edit-prompt-") as tmp:
    os.environ["STORAGE_DIR"] = os.environ["INSTANCE_DIR"] = tmp
    from app.core import paths  # noqa: E402
    paths.init(Path(tmp) / "world")
    from app.imagegen.base import ImageBackend  # noqa: E402
    from app.utils import image_prompt_logger as ipl  # noqa: E402
    ipl.LOG_DIR = Path(tmp) / "logs"
    ipl.LOG_FILE = ipl.LOG_DIR / "image_prompts.jsonl"

    class Stub(ImageBackend):
        def __init__(self, prefix: str = "EPSTUB_"):
            super().__init__(name="stub", api_url="http://stub", cost=0.0, api_type="stub", env_prefix=prefix)
            self.model = "Qwen2.1"
            self.prompt_char_limit = 100000
            self.calls = []

        def _generate(self, prompt, negative_prompt, params):
            self.calls.append(prompt)
            return [b"png"]

        def check_availability(self):
            return True

    A = "Put the hat from the second image on the first image."
    two = {"reference_images": {"input_reference_image_1": "a.png", "input_reference_image_2": "b.png"}}
    s = Stub()
    meta: dict = {}
    s.generate(A, "", dict(two), log_meta=meta)
    check("engine prompt", s.calls[-1], "Put the hat from <image2> on <image1>.")
    check("log_meta final_prompt", meta.get("final_prompt"), "Put the hat from <image2> on <image1>.")
    em = meta.get("edit_prompt") or {}
    check("log_meta edit_prompt", (em.get("dialect"), em.get("dialect_source"), em.get("refs"), em.get("rewrites")),
          ("image_tag", "auto", [1, 2], 2))
    rows = [json.loads(x) for x in ipl.LOG_FILE.read_text(encoding="utf-8").splitlines()]
    check("jsonl edit_prompt", (rows[-1].get("edit_prompt") or {}).get("dialect"), "image_tag")
    meta = {}
    s.generate(A, "", {}, log_meta=meta)
    rows = [json.loads(x) for x in ipl.LOG_FILE.read_text(encoding="utf-8").splitlines()]
    check("no refs: byte-identical, no edit_prompt", (s.calls[-1], "edit_prompt" in meta, "edit_prompt" in rows[-1]),
          (A, False, False))
    os.environ["EPCFG_PROMPT_DIALECT"] = "picture_edit"
    c = Stub("EPCFG_")
    c.generate(A, "", dict(two), log_meta=None)
    check("configured dialect", c.calls[-1], "Edit <Picture 1>. Put the hat from <Picture 2> on <Picture 1>.")

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
    sys.exit(1)
print("ALL OK")
