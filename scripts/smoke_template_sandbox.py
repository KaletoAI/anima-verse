#!/usr/bin/env python3
"""Checks that the prompt-template engine is sandboxed and still renders.

Usage:
    ./.venv/bin/python scripts/smoke_template_sandbox.py

Pure: no server, no world DB, no LLM. A throwaway storage root is pinned
before the first app import; the only files touched are the template trees
(read-only) and one temp dir for the cache test.

WHY (SEC-9b)

Prompt templates are live-editable at /admin/templates. With a plain
``jinja2.Environment`` "may edit a prompt" therefore equals "may run code":
``{{ ''.__class__.__mro__[1].__subclasses__() }}`` is the textbook chain, and
``{{ cycler.__init__.__globals__ }}`` reaches the same place through a Jinja
global. ``jinja2.sandbox.SandboxedEnvironment`` routes every attribute access
and every call through ``is_safe_attribute`` / ``is_safe_callable``, so both
chains die at the first underscore attribute.

The price is that the sandbox can also break a LEGITIMATE template — one that
uses ``str.format``, mutates a list, or reads an underscore attribute. That is
what part [3] is for: every template file in the repo is compiled and rendered
once, and a ``SecurityError`` anywhere is a failure. The check therefore proves
both halves of the change at once.

EXPECTED VALUES, derived by hand from the jinja2 sandbox contract
(jinja2/sandbox.py, ``SandboxedEnvironment.getattr`` /
``unsafe_undefined`` / ``is_safe_attribute``), never recorded from a run:

[1] ``prompt_templates._env`` is an instance of ``SandboxedEnvironment`` and
    keeps ``StrictUndefined`` (a missing placeholder must still raise, the
    sandbox must not soften that) and ``autoescape=False`` (prompts are plain
    text, not HTML).

[2] Each of these five payloads raises ``jinja2.sandbox.SecurityError``:
        {{ ''.__class__ }}                     underscore attr on a str
        {{ ''.__class__.__mro__ }}             the classic chain
        {{ cycler.__init__ }}                  underscore attr on a global
        {{ cycler.__init__.__globals__ }}      the classic chain via a global
        {{ '{0.__class__}'.format(s) }}        the chain through str.format
    ``is_safe_attribute`` refuses every name starting with "_", and
    ``unsafe_undefined`` hands back an Undefined whose exception class is
    SecurityError — so the raise happens where the value is USED, which is
    inside the render. ``str.format`` is not forbidden outright (the sandbox
    routes it through ``SandboxedFormatter``); what the formatter refuses is
    exactly the attribute chain in a format spec, which is the only way out.
    Two counter-checks so [2] cannot pass with a merely broken environment:
    ``{{ 'x' | upper }}`` renders "X", and ``{{ '{0}!'.format('a') }}``
    renders "a!" — an ordinary filter and an ordinary format still work.

[3] EVERY template file under shared/templates/llm/ and under
    plugins/*/templates/llm/ (plus plugins/installed/* when present) compiles,
    and rendering it with a permissive stand-in context raises no
    SecurityError. Templates that cannot be rendered for lack of context
    (a variable used as a number, a loop over a pair list, ...) are LISTED,
    not failed — the context here is deliberately generic; the real contexts
    are covered by smoke_chat_prompt_order / smoke_thought_template_parity /
    smoke_llm_task_catalog and by the /admin/templates preview drivers.

[4] The compile cache (LLM-9) is mtime-keyed: ``render`` of the same template
    twice returns the identical compiled Template object, and after the file's
    content changes (mtime + size differ) the next render recompiles. Derived
    from the cache key (file, st_mtime_ns, st_size) in
    ``prompt_templates._compile`` — templates are live-editable, so a saved
    edit must take effect with no invalidation call anywhere.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Throwaway storage root BEFORE any app import (scripts storage lint rule).
_TMP_STORAGE = tempfile.mkdtemp(prefix="smoke_template_sandbox_")
os.environ.setdefault("ANIMATION_CLIPS_DIR", str(Path(_TMP_STORAGE) / "clips"))
from app.core import paths  # noqa: E402
paths.init(_TMP_STORAGE)

from jinja2.sandbox import SandboxedEnvironment, SecurityError  # noqa: E402
from jinja2 import StrictUndefined  # noqa: E402

from app.core import prompt_templates as pt  # noqa: E402

FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")
        print(f"FAIL {name}: got {got!r}, want {want!r}")
    else:
        print(f"ok   {name}")


# ── [1] the environment itself ───────────────────────────────────────────
check("[1] env is sandboxed", isinstance(pt._env, SandboxedEnvironment), True)
check("[1] StrictUndefined kept", pt._env.undefined is StrictUndefined, True)
check("[1] autoescape off", bool(pt._env.autoescape), False)


# ── [2] SSTI payloads ────────────────────────────────────────────────────
PAYLOADS = [
    "{{ ''.__class__ }}",
    "{{ ''.__class__.__mro__ }}",
    "{{ cycler.__init__ }}",
    "{{ cycler.__init__.__globals__ }}",
    "{{ '{0.__class__}'.format(s) }}",
]
for src in PAYLOADS:
    try:
        pt._env.from_string(src).render(s="plain")
        outcome = "rendered"
    except SecurityError:
        outcome = "SecurityError"
    except Exception as e:  # noqa: BLE001 — any other error is also not the contract
        outcome = type(e).__name__
    check(f"[2] {src} blocked", outcome, "SecurityError")

try:
    plain = pt._env.from_string("{{ 'x' | upper }}").render()
except Exception as e:  # noqa: BLE001
    plain = f"<{type(e).__name__}>"
check("[2] ordinary filter still works", plain, "X")

try:
    fmt = pt._env.from_string("{{ '{0}!'.format('a') }}").render()
except Exception as e:  # noqa: BLE001
    fmt = f"<{type(e).__name__}>"
check("[2] ordinary format still works", fmt, "a!")


# ── [3] every template compiles and renders ──────────────────────────────
class Stand(str):
    """Stand-in for any template variable: a non-empty string that also
    answers any (non-underscore) attribute with another stand-in.

    A str subclass because that is what nearly every prompt variable is:
    truthy, printable, iterable, and it works with ``|length``/``|join``.
    Attribute lookups that a dict/object would answer (``x.name``) fall to
    ``__getattr__``; an underscore attribute deliberately does NOT — the
    sandbox has to be the thing that refuses it.
    """

    def __getattr__(self, item):
        if item.startswith("_"):
            raise AttributeError(item)
        return Stand(f"<{item}>")

    def __iter__(self):
        # A loop over a list of records must reach the loop BODY — iterating
        # the raw string would yield plain characters and every `row.field`
        # inside would die on the first attribute.
        return iter((Stand("<item1>"), Stand("<item2>")))

    def __call__(self, *a, **kw):
        return Stand("<called>")


def _roots():
    out = [ROOT / "shared" / "templates" / "llm"]
    for base in (ROOT / "plugins", ROOT / "plugins" / "installed"):
        if not base.is_dir():
            continue
        for pkg in sorted(base.iterdir()):
            d = pkg / "templates" / "llm"
            if d.is_dir():
                out.append(d)
    return out


ROOTS = _roots()
# Register the package roots exactly the way the plugin loader does, so the
# real loader resolves plugin templates too.
pt.register_package_template_dirs([r for r in ROOTS[1:]])

from jinja2 import meta  # noqa: E402

compiled = 0
rendered = 0
security = []
no_context = []
broken = []

for root in ROOTS:
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        label = str(path.relative_to(ROOT))
        text = pt._strip_frontmatter(path.read_text(encoding="utf-8"))
        # Prefer the real loader; fall back to the file text when another root
        # shadows this name (same relative path in two roots).
        try:
            src, filename, _ = pt._env.loader.get_source(pt._env, rel)
            if filename and Path(filename).resolve() != path.resolve():
                src = None
        except Exception:
            src = None
        body = pt._strip_frontmatter(src) if src is not None else text
        try:
            tmpl = pt._env.from_string(body)
            compiled += 1
        except Exception as e:  # noqa: BLE001
            broken.append(f"{label}: compile {type(e).__name__}: {e}")
            continue
        names = meta.find_undeclared_variables(pt._env.parse(body))
        ctx = {n: Stand(f"<{n}>") for n in names}
        try:
            tmpl.render(**ctx)
            rendered += 1
        except SecurityError as e:
            security.append(f"{label}: {e}")
        except Exception as e:  # noqa: BLE001
            no_context.append(f"{label}: {type(e).__name__}: {e}")

print(f"     {len(ROOTS)} template roots, {compiled} templates compiled, "
      f"{rendered} rendered")
check("[3] every template compiles", broken, [])
check("[3] no template hits the sandbox", security, [])
if no_context:
    print(f"     {len(no_context)} template(s) not renderable with the generic "
          "context (not a failure):")
    for line in no_context:
        print(f"       - {line}")


# ── [4] mtime-keyed compile cache ────────────────────────────────────────
cache_dir = Path(tempfile.mkdtemp(prefix="smoke_template_cache_"))
(cache_dir / "tasks").mkdir()
probe = cache_dir / "tasks" / "smoke_cache_probe.md"
probe.write_text("## user\nONE\n", encoding="utf-8")
pt.register_package_template_dirs([cache_dir])

first = pt.render_task("smoke_cache_probe")
t1 = pt._compiled_cache["tasks/smoke_cache_probe.md"][3]
second = pt.render_task("smoke_cache_probe")
t2 = pt._compiled_cache["tasks/smoke_cache_probe.md"][3]
check("[4] unchanged file reuses the compiled template", t1 is t2, True)
check("[4] cached render is correct", (first[1], second[1]), ("ONE", "ONE"))

probe.write_text("## user\nTWO AND MORE\n", encoding="utf-8")
os.utime(probe, (0, 0))  # force a different mtime even on a coarse clock
third = pt.render_task("smoke_cache_probe")
t3 = pt._compiled_cache["tasks/smoke_cache_probe.md"][3]
check("[4] edited file recompiles", t3 is not t1, True)
check("[4] edited file renders the new text", third[1], "TWO AND MORE")

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ALL CHECKS PASSED")
