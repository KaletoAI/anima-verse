"""Jinja2-based prompt template loader.

Templates live under `shared/templates/llm/`:

    tasks/<task>.md       — one file per llm_call() task; split into
                            `## system` and `## user` sections via YAML
                            frontmatter + body markers.
    sections/<name>.md    — reusable building blocks for the system
                            prompt builder (identity, situation, ...).
    chat/<scenario>.md    — top-level chat/thought composites that
                            include sections.
    skills/<skill>.md     — name + description metadata per skill;
                            frontmatter `name`, body = description.

Public API:
    render_task(task, **vars)          -> (system_prompt, user_prompt)
    render(template_path, **vars)      -> str
    load_skill_meta(skill_file)        -> {"name": str, "description": str}

The loader is intentionally minimal: Jinja2 with autoescape disabled
(prompts are plain text, not HTML), `StrictUndefined` (missing
placeholders raise loud errors instead of silently rendering empty),
and `trim_blocks`/`lstrip_blocks` so that `{% if %}` blocks don't leak
extra whitespace.

The environment is a `SandboxedEnvironment` (SEC-9): templates are
live-editable at /admin/templates, so a plain `Environment` would turn
"may edit a prompt" into "may run code" via the classic
`{{ ''.__class__.__mro__ }}` attribute chain. Prompt templates only ever
interpolate strings, lists and dicts the caller passes in — none of them
needs an underscore attribute or `.format`, so the sandbox costs nothing
here and every escape route raises `SecurityError` instead.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

from jinja2 import FileSystemLoader, StrictUndefined, Template
from jinja2.sandbox import SandboxedEnvironment

# Resolve template dir relative to repo root: <repo>/shared/templates/llm
_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "shared" / "templates" / "llm"

# Skill packages may contribute their own template dirs (plugins/<pkg>/templates/llm);
# registered by the plugin loader. The main tree is searched first.
_package_template_dirs: List[Path] = []


def _build_env() -> SandboxedEnvironment:
    return SandboxedEnvironment(
        loader=FileSystemLoader(
            [str(_TEMPLATE_DIR)] + [str(p) for p in _package_template_dirs]),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )


_env = _build_env()


def register_package_template_dirs(dirs: List[Path]) -> None:
    """Replace the package search path (called by the plugin loader).

    Rebuilds the Jinja environment and clears the skill-meta cache so a
    plugin reload picks up added/removed package templates.
    """
    global _env, _package_template_dirs
    new_dirs = [Path(d) for d in dirs]
    if new_dirs == _package_template_dirs:
        return
    _package_template_dirs = new_dirs
    _env = _build_env()
    _skill_meta_cache.clear()
    # The cached templates are bound to the OLD env (and its loader), so an
    # `{% include %}` in one would still resolve on the old search path.
    _compiled_cache.clear()


def template_search_dirs() -> List[Path]:
    """All template roots in search order (main tree first, then packages)."""
    return [_TEMPLATE_DIR] + list(_package_template_dirs)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SECTION_SPLIT_RE = re.compile(r"^##\s+(system|user)\s*$", re.MULTILINE | re.IGNORECASE)


def _strip_frontmatter(text: str) -> str:
    """Drop YAML frontmatter if present. Frontmatter is documentation
    (purpose, placeholders) that must not be sent to the LLM."""
    m = _FRONTMATTER_RE.match(text)
    if m:
        return text[m.end():]
    return text


def _split_system_user(body: str) -> Tuple[str, str]:
    """Split a task body into (system, user) chunks at `## system` / `## user`
    markers. Either section may be empty."""
    parts = _SECTION_SPLIT_RE.split(body)
    # parts = [pre, "system", system_body, "user", user_body, ...]
    # If the first marker is the very start, parts[0] is "".
    if len(parts) < 3:
        # No section markers — treat whole body as user prompt.
        return "", body.strip()

    system = ""
    user = ""
    # Walk pairs of (label, body)
    for i in range(1, len(parts) - 1, 2):
        label = parts[i].lower()
        chunk = parts[i + 1].strip()
        if label == "system":
            system = chunk
        elif label == "user":
            user = chunk

    return system, user


# Compiled bodies, keyed by template name -> (file, mtime_ns, size, Template).
# `from_string` bypasses Jinja's own cache, so every render used to re-read the
# file from disk and recompile it (LLM-9: 3.4 ms for chat/chat_stream.md, on
# every single chat turn). Templates are live-editable at /admin/templates, so
# the key carries the file's mtime+size: a saved edit changes both and the next
# render recompiles by itself — no invalidation call anywhere.
_compiled_cache: Dict[str, Tuple[str, int, int, Template]] = {}


def _compile(template_name: str) -> Template:
    """Compile a template's body (frontmatter stripped), cached by mtime."""
    hit = _compiled_cache.get(template_name)
    if hit is not None:
        filename, mtime_ns, size, tmpl = hit
        try:
            st = os.stat(filename)
            if st.st_mtime_ns == mtime_ns and st.st_size == size:
                return tmpl
        except OSError:
            pass  # moved or deleted — fall through to a fresh lookup
    raw, filename, _uptodate = _env.loader.get_source(_env, template_name)
    tmpl = _env.from_string(_strip_frontmatter(raw))
    if filename:
        try:
            st = os.stat(filename)
            _compiled_cache[template_name] = (filename, st.st_mtime_ns,
                                              st.st_size, tmpl)
        except OSError:
            pass
    return tmpl


def render_task(task: str, **vars) -> Tuple[str, str]:
    """Render `tasks/<task>.md` and return (system_prompt, user_prompt).

    Raises if the template is missing or a placeholder is undefined.
    """
    # Compiled from the body (after frontmatter strip) so `{% include %}` etc.
    # still works, and so frontmatter is not handled twice.
    rendered = _compile(f"tasks/{task}.md").render(**vars)
    return _split_system_user(rendered)


def render(template_path: str, **vars) -> str:
    """Render any single template file (sections/, chat/, ...) and return
    the result as a plain string."""
    return _compile(template_path).render(**vars).strip()


def template_exists(template_path: str) -> bool:
    try:
        _env.loader.get_source(_env, template_path)
        return True
    except Exception:
        return False


_SKILL_META_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_FRONT_KEY_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.+?)\s*$", re.MULTILINE)

_skill_meta_cache: Dict[str, Dict[str, str]] = {}


def load_skill_meta(skill_file: str) -> Dict[str, str]:
    """Load name + description for a skill from
    ``shared/templates/llm/skills/<skill_file>.md``.

    File format:
        ---
        name: SendMessage
        ---
        Full description text (rest of the file).

    Returns ``{"name": "...", "description": "..."}``. Description is
    stripped of leading/trailing whitespace so the template can use
    multi-line bodies. Result is cached per process — the cache is
    invalidated when ``save_template`` clears the Jinja env cache (admin
    template editor save path).
    """
    if skill_file in _skill_meta_cache:
        return _skill_meta_cache[skill_file]

    template_name = f"skills/{skill_file}.md"
    raw = _env.loader.get_source(_env, template_name)[0]
    m = _SKILL_META_RE.match(raw)
    if not m:
        raise ValueError(
            f"Skill template {template_name} missing YAML frontmatter "
            f"(expected ---\\nname: ...\\n---)"
        )
    front_text, body = m.group(1), m.group(2)
    front: Dict[str, str] = {}
    for fm in _FRONT_KEY_RE.finditer(front_text):
        front[fm.group(1)] = fm.group(2).strip()
    name = front.get("name", "").strip()
    if not name:
        raise ValueError(
            f"Skill template {template_name} missing `name:` in frontmatter"
        )
    description = body.strip()
    # All frontmatter keys pass through (e.g. `action_hint:` for the
    # constrained-mode tool prompt) — name/description keep priority.
    meta = dict(front)
    meta["name"] = name
    meta["description"] = description
    _skill_meta_cache[skill_file] = meta
    return meta


def _invalidate_skill_meta_cache() -> None:
    """Called from template_preview.save_template after a write."""
    _skill_meta_cache.clear()
