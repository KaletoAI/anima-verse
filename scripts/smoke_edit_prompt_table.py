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

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
    sys.exit(1)
print("ALL OK")
