#!/usr/bin/env python3
"""Smoke: docs/garment-templates.md still states the numbers and names the code uses.

Usage:  ./.venv/bin/python scripts/smoke_docs_garment_templates.py

The reference for the pattern-piece UVs of a garment template and the "texture from cut" path
(plan ``docs/superpowers/plans/2026-11-20-template-cut-uv-texture.md``, Task 11) is full of exact values
— the template version, the atlas size, the gate thresholds, the occasion, the routes. Each of them is a
claim about one constant in the code, and a changed constant would leave the document lying without
anyone noticing. This check reads the constants out of the SOURCE TEXT (regex / ``ast.literal_eval``;
nothing from ``app`` is imported, no server, no world DB, no storage) and requires the document to say
the same thing.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) ``TEMPLATE_VERSION`` (``app/core/garment_template.py``) — the document says "TEMPLATE_VERSION <n>".
B) The atlas: ``PATTERN_ATLAS_PX`` and ``PATTERN_MARGIN_CM`` (``app/blender/scripts/garment_template_build.py``)
   appear with their values ("2048", "1.5 cm").
C) The parts: every name of ``PARTS`` and every id of ``STRIP_PARTS`` (``app/blender/scripts/uv_pattern.py``)
   appears in the document's parts table as a row "| <id> | `<name>` | strip/panel |", with "strip" exactly for
   the ids in ``STRIP_PARTS``.
D) Pattern UV for every kind (B17): ``PATTERN_KINDS`` (read from the source) is every kind of ``KINDS``, the
   document names each of them in its "Which pieces get them" section, ``garment_template.py`` sends no ``uv_mode``
   build arg, the builder carries none of the grid UV's names (``uv_mode``, ``UV_TORSO``, ``UV_CAP``, ``UV_COLLAR``,
   ``UV_SLEEVE``, ``grid_uv``) and bakes at the atlas size only (no 1024 fallback), and the document no longer
   states a ``uv_mode`` rule.
E) The occasion: ``garment_cut_texture`` with its admin label (the first string of its ``_image(...)`` call in
   ``app/imagegen/occasions.py``), ``min_ref_slots=2`` and ``requires_chain=True`` there, and the document names
   all three.
F) The gate: every key and value of ``CUT_GATE`` (``app/core/cut_texture_post.py``) is a row of the gate table,
   "| `<key>` | <meaning> | ≥/≤ <value with two decimals> |"; ``BLEED_CM``, ``SPILL_CM``, ``CLAMP_DE`` and ``POST_VERSION`` appear with their values.
G) ``csig``: its five inputs as named in ``garment_cut_texture.csig`` (``islands_sha``, ``item_sha``,
   ``back_sha``, ``PROMPT_SHA``, ``POST_VERSION``) all appear in the document, and the document does NOT say csig carries tsig
   (the line naming csig's inputs must not list ``tsig``).
H) ``MIN_ITEM_SIDE`` (``app/core/garment_cut_texture.py``) appears with its value.
I) The routes: every ``@router`` path in ``app/routes/figure.py`` that contains "/cut" or "pattern.png" appears in
   the document, with ``{character_name}`` shortened to ``{c}``.
J) The P-H3 backend entry: ``"use_prompt_upsampler": false`` appears (the string ``_upsampler_on`` tests for).
K) Every prompt file of ``PROMPT_FILES`` in ``garment_cut_texture.py`` (three: front plain, front decorated, back)
   exists and the document names it;
   the document states the sleeve rule and names every part of ``BACK_PARTS`` (the back panel; since step 3a also a
   trouser's back leg panels and a glove's palms).
L) The param ``texture``: its choices ``TEXTURE_SOURCES`` and that it is in ``TEXTURE_ONLY``
   (``garment_template.py``) — the document says "TEXTURE_ONLY".
M) The file names: ``{item}_{tsig}.islands.json`` (``islands_path``) and ``templates/cut/`` (``cut_dir``).
N) Plan group B, phases E / F / G (section 1d): ``NECK_VERSION`` and ``CORSET_VERSION`` (``garment_template.py``) and
   ``PLACKET_VERSION`` (``cut_texture_post.py``) — the document says "`NECK_VERSION`", "`CORSET_VERSION`" and
   "`PLACKET_VERSION` <n>" with the code's n; ``PLACKET_CLEAR_CM`` appears as "<value> cm" and ``PLACKET_CLEAR_DETAIL``
   with its value; ``BAND_SCOOP_MAX_M`` (``garment_template_build.py``) as "<value x 100> cm"; the dart rule names
   ``corset_darts.py`` and that file exists.
"""
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "garment-templates.md"
GT = REPO / "app" / "core" / "garment_template.py"
BUILD = REPO / "app" / "blender" / "scripts" / "garment_template_build.py"
UVP = REPO / "app" / "blender" / "scripts" / "uv_pattern.py"
OCC = REPO / "app" / "imagegen" / "occasions.py"
POST = REPO / "app" / "core" / "cut_texture_post.py"
GCT = REPO / "app" / "core" / "garment_cut_texture.py"
ROUTES = REPO / "app" / "routes" / "figure.py"

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def const(path: Path, name: str):
    """The literal value of a module-level ``NAME = <literal>`` (``ast.literal_eval``; a ``frozenset({...})``
    call is read as a set)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets, value = [node.target.id], node.value
        if name in targets:
            if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "frozenset":
                return set(ast.literal_eval(value.args[0]))
            return ast.literal_eval(value)
    raise KeyError(f"{name} not found in {path}")


def main() -> int:
    print("smoke_docs_garment_templates")
    if not DOC.is_file():
        check("docs/garment-templates.md exists", False, str(DOC))
        print(f"\n{_checks - len(_failures)}/{_checks} checks passed")
        return 1
    doc = DOC.read_text(encoding="utf-8")
    gt = GT.read_text(encoding="utf-8")

    # A
    v = const(GT, "TEMPLATE_VERSION")
    check(f"A  TEMPLATE_VERSION {v}", f"TEMPLATE_VERSION {v}" in doc or f"`TEMPLATE_VERSION` {v}" in doc)

    # B
    px, margin = const(BUILD, "PATTERN_ATLAS_PX"), const(BUILD, "PATTERN_MARGIN_CM")
    check(f"B  atlas {px} px", f"{px}" in doc and "PATTERN_ATLAS_PX" in doc)
    check(f"B  margin {margin} cm", f"{margin} cm" in doc and "PATTERN_MARGIN_CM" in doc)

    # C
    parts, strips = const(UVP, "PARTS"), const(UVP, "STRIP_PARTS")
    for pid, name in sorted(parts.items()):
        kind = "strip" if pid in strips else "panel"
        row = re.search(rf"^\|\s*{pid}\s*\|\s*`{re.escape(name)}`\s*\|\s*{kind}\b", doc, re.M)
        check(f"C  part {pid} `{name}` is a {kind}", row is not None)

    # D
    kinds, all_kinds = const(GT, "PATTERN_KINDS"), const(GT, "KINDS")
    check("D  PATTERN_KINDS is every kind", isinstance(kinds, tuple) and set(kinds) == set(all_kinds or ()),
          (kinds, all_kinds))
    sec = doc[doc.index("### Which pieces get them"):][:900] if "### Which pieces get them" in doc else ""
    for kind in kinds or ():
        check(f"D  doc names kind {kind} as a pattern kind", f"`{kind}`" in sec)
    check("D  garment_template.py sends no uv_mode", '"uv_mode"' not in gt)
    build = BUILD.read_text(encoding="utf-8")
    gone = [n for n in ("uv_mode", "UV_TORSO", "UV_CAP", "UV_COLLAR", "UV_SLEEVE", "grid_uv") if n in build]
    check("D  the builder has no grid UV left", not gone, gone)
    check("D  the bake is at the atlas size only", "1024" not in build, "1024" in build)
    check("D  the doc states no uv_mode rule", not re.search(r'`uv_mode`:\s*`?"pattern"', doc))

    # E
    occ = OCC.read_text(encoding="utf-8")
    m = re.search(r'"garment_cut_texture":\s*_image\(\s*"([^"]+)"(.*?)\),\n', occ, re.S)
    check("E  occasion garment_cut_texture in occasions.py", m is not None)
    if m:
        label, rest = m.group(1), m.group(2)
        check("E  occasion has min_ref_slots=2", "min_ref_slots=2" in rest)
        check("E  occasion has requires_chain=True", "requires_chain=True" in rest)
        check(f"E  doc names the occasion, its label {label!r}, min_ref_slots 2, requires_chain",
              "`garment_cut_texture`" in doc and label in doc and "`min_ref_slots`" in doc and " 2" in doc
              and "`requires_chain`" in doc)

    # F
    gate = const(POST, "CUT_GATE")
    for key, val in gate.items():
        check(f"F  gate {key} {val:.2f}", re.search(rf"^\|\s*`{key}`\s*\|[^\n]*\|\s*[<>≤≥]*\s*{val:.2f}\s*\|\s*$", doc, re.M) is not None)
    for name, unit in (("BLEED_CM", " cm"), ("SPILL_CM", " cm"), ("CLAMP_DE", ""), ("POST_VERSION", "")):
        val = const(POST, name)
        check(f"F  {name} = {val}", re.search(rf"`{name}`\D{{0,12}}{re.escape(str(val))}{unit}", doc) is not None)

    # G
    gct = GCT.read_text(encoding="utf-8")
    body = re.search(r"def csig\(.*?return", gct, re.S)
    inputs = ["islands_sha", "item_sha", "back_sha", "PROMPT_SHA", "POST_VERSION"]
    check("G  csig inputs found in the code", body is not None and all(i in body.group(0) for i in inputs))
    line = next((ln for ln in doc.splitlines() if "`csig`" in ln and "PROMPT_SHA" in ln), "")
    check("G  doc line naming csig's five inputs", all(i in line for i in inputs), line[:120])
    check("G  that line does not put tsig into csig",
          bool(line) and re.search(r"csig[^.]*=\s*[^.]*`tsig`", line) is None)

    # H
    side = const(GCT, "MIN_ITEM_SIDE")
    check(f"H  MIN_ITEM_SIDE {side}", "`MIN_ITEM_SIDE`" in doc and f"{side} px" in doc)

    # I
    routes = ROUTES.read_text(encoding="utf-8")
    paths = [p for p in re.findall(r'@router\.\w+\("([^"]+)"', routes) if "/cut" in p or "pattern.png" in p]
    check("I  the cut/pattern routes exist in figure.py", len(paths) >= 4, str(paths))
    for p in paths:
        short = p.replace("{character_name}", "{c}")
        check(f"I  route {short}", short in doc)

    # J
    check('J  "use_prompt_upsampler": false', '"use_prompt_upsampler": false' in doc)

    # K
    block = re.search(r"PROMPT_FILES = \{(.*?)\}", gct, re.DOTALL)
    names = re.findall(r'_PROMPT_DIR / "([^"]+)"', block.group(1)) if block else []
    check("K  PROMPT_FILES has three files", len(names) == 3, names)
    for name in names:
        rel = f"shared/templates/image/{name}"
        check(f"K  doc names {rel} and it exists", rel in doc and (REPO / rel).is_file())
    check("K  doc states the sleeve rule and the back parts", "**Sleeve rule:**" in doc
          and "`BACK_PARTS`" in doc
          and all(f"`{part}`" in doc for part in const(GCT, "BACK_PARTS")))   # step 3a: + back_l/r, palm_l/r

    # L
    sources, only = const(GT, "TEXTURE_SOURCES"), const(GT, "TEXTURE_ONLY")
    check("L  texture is TEXTURE_ONLY in the code", "texture" in only)
    check(f"L  doc: param texture {sources} and TEXTURE_ONLY",
          "`TEXTURE_ONLY`" in doc and all(f'"{s}"' in doc for s in sources))

    # M
    check("M  islands file name", "{item}_{tsig}.islands.json" in gt and "{item}_{tsig}.islands.json" in doc)
    check("M  templates/cut/", '"templates" / "cut"' in gct and "templates/cut/" in doc)

    # N
    check("N  doc names NECK_VERSION and CORSET_VERSION", const(GT, "NECK_VERSION") >= 1 and const(GT, "CORSET_VERSION")
          >= 1 and "`NECK_VERSION`" in doc and "`CORSET_VERSION`" in doc)
    pv = const(POST, "PLACKET_VERSION")
    check(f"N  doc: PLACKET_VERSION {pv}", f"`PLACKET_VERSION` {pv}" in doc)
    cc, cd_ = const(POST, "PLACKET_CLEAR_CM"), const(POST, "PLACKET_CLEAR_DETAIL")
    check(f"N  doc: PLACKET_CLEAR_CM {cc} cm, PLACKET_CLEAR_DETAIL {cd_}",
          f"`PLACKET_CLEAR_CM` {cc} cm" in doc and f"`PLACKET_CLEAR_DETAIL` {cd_}" in doc)
    bs = const(BUILD, "BAND_SCOOP_MAX_M")
    check(f"N  doc: BAND_SCOOP_MAX_M {bs * 100:g} cm", f"`BAND_SCOOP_MAX_M` ({bs * 100:g} cm)" in doc)
    check("N  doc names corset_darts.py and it exists", "corset_darts.py" in doc
          and (REPO / "app" / "blender" / "scripts" / "corset_darts.py").is_file())

    print(f"\n{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        print("  failed: " + "; ".join(_failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
