"""Smoke world prompt overrides. Usage: ./.venv/bin/python scripts/smoke_template_overrides.py

Hand-derived expectations: A includes OVERRIDE instead of SHIPPED; B reuses
its compiled parent and deletion restores SHIPPED; C an overridden parent
keeps its shipped child; D shipped_source ignores overrides; E no-storage
subprocess prints A SHIPPED; F SQL stores exactly path/content/base_hash/
updated_at; G old includes become stale; H own override rekeys composition
and deletion restores its key; I any child override rekeys composition;
J skill metadata replaces its name and rejects an old-revision cache entry.
Every part starts and ends with no overrides. Only temporary storage is used.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory(prefix="smoke_template_overrides_") as tmp:
        root = Path(tmp)
        paths.init(root / "world")
        import app.core.template_overrides as overrides
        from app.core import db, prompt_templates as pt, prompt_compose_llm as compose
        db.init_schema()
        package = root / "pkg" / "llm"
        (package / "smoke").mkdir(parents=True)
        (package / "smoke/outer.md").write_text('A {% include "smoke/inner.md" %}', encoding="utf-8")
        (package / "smoke/inner.md").write_text("SHIPPED", encoding="utf-8")
        pt.register_package_template_dirs([package])
        inner, outer = "smoke/inner.md", "smoke/outer.md"

        @contextmanager
        def part(letter):
            assert overrides.all_overrides() == {}, letter
            try:
                yield
            finally:
                for name in list(overrides.all_overrides()):
                    overrides.delete_override(name)
            assert overrides.all_overrides() == {}, letter
            print(f"{letter}: PASS")

        def save(name, content):
            return overrides.set_override(name, content, overrides.content_hash(pt.shipped_source(name)))

        def key():
            return compose.cache_key("s", "subj", "h", "natural")

        with part("A"):
            assert pt.render(outer) == "A SHIPPED"
            save(inner, "OVERRIDE")
            assert pt.render(outer) == "A OVERRIDE"
        with part("B"):
            save(inner, "OVERRIDE")
            assert pt.render(outer) == "A OVERRIDE"
            cached = pt._compiled_cache[outer][1]
            assert pt.render(outer) == "A OVERRIDE"
            assert pt._compiled_cache[outer][1] is cached
            assert overrides.delete_override(inner)
            assert pt.render(outer) == "A SHIPPED"
            assert not overrides.delete_override(inner)
        with part("C"):
            save(outer, "B {% include 'smoke/inner.md' %}")
            assert pt.render(outer) == "B SHIPPED"
        with part("D"):
            save(inner, "OVERRIDE")
            assert pt.shipped_source(inner) == "SHIPPED"
            pt.check_syntax("---\nname: Example\n---\n{{ value }}")
            try:
                pt.check_syntax("{% if %}")
            except ValueError as exc:
                assert "line 1" in str(exc)
            else:
                raise AssertionError("invalid syntax accepted")
        with part("E"):
            env = dict(os.environ)
            env.pop("STORAGE_DIR", None)
            code = ('from pathlib import Path; from app.core import prompt_templates as pt; '
                    'pt.register_package_template_dirs([Path(__import__("sys").argv[1])]); '
                    'print(pt.render("smoke/outer.md"))')
            result = subprocess.run(["timeout", "60", sys.executable, "-c", code, str(package)],
                                    env=env, capture_output=True, text=True, check=True)
            assert result.stdout.strip() == "A SHIPPED", result.stdout
        with part("F"):
            old_rev = overrides.revision()
            ov = save(inner, "OVERRIDE")
            assert overrides.revision() != old_rev
            row = db.get_connection().execute("SELECT * FROM llm_template_overrides").fetchone()
            assert row.keys() == ["path", "content", "base_hash", "updated_at"]
            assert tuple(row) == (ov.name, ov.content, ov.base_hash, ov.updated_at)
            fingerprint = overrides.fingerprint()
            save(inner, "OVERRIDE")
            assert overrides.fingerprint() == fingerprint
            assert overrides.lookup(inner).content == "OVERRIDE"
        with part("G"):
            old = pt._env.get_template(inner)
            save(inner, "NEW")
            assert old.is_up_to_date is False
            assert pt.render(outer) == "A NEW"
        with part("H"):
            k0 = key()
            name = "tasks/image_prompt_compose.md"
            save(name, pt.shipped_source(name) + "\nX")
            assert key() != k0
            overrides.delete_override(name)
            assert key() == k0
        with part("I"):
            k0 = key()
            save("chat/intent_markers.md", "X")
            assert key() != k0
        with part("J"):
            skill = next((pt._TEMPLATE_DIR / "skills").glob("*.md")).stem
            old_rev = overrides.revision()
            old = pt.load_skill_meta(skill)
            save(f"skills/{skill}.md", "---\nname: Other\n---\nbody")
            assert pt.load_skill_meta(skill)["name"] == "Other"
            pt._skill_meta_cache[skill] = (old_rev, old)
            assert pt.load_skill_meta(skill)["name"] == "Other"
        assert overrides.fingerprint() == ""
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
