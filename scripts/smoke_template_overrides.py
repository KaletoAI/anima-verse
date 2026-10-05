"""Smoke world prompt overrides. Usage: ./.venv/bin/python scripts/smoke_template_overrides.py

Hand-derived expectations: A includes OVERRIDE instead of SHIPPED; B reuses
its compiled parent and deletion restores SHIPPED; C an overridden parent
keeps its shipped child; D shipped_source ignores overrides; E no-storage
subprocess prints A SHIPPED; F SQL stores exactly path/content/base_hash/
updated_at; G old includes become stale; H own override rekeys composition
and deletion restores its key; I any child override rekeys composition;
J skill metadata replaces its name and rejects an old-revision cache entry.
Task 8 expectations: G saving/deleting leaves every shipped file hash unchanged;
H reads X as override with shipped source and unchanged base; I wrong base hash
flags read/list; J1/J2 invalid syntax preserves absent/existing override;
K saving shipped source removes override; L orphan reads/lists/deletes but cannot
save, and traversal deletion is rejected.
Every part starts and ends with no overrides. Only temporary storage is used.
"""
import os
import hashlib
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
        with part("Task7-G"):
            old = pt._env.get_template(inner)
            save(inner, "NEW")
            assert old.is_up_to_date is False
            assert pt.render(outer) == "A NEW"
        with part("Task7-H"):
            k0 = key()
            name = "tasks/image_prompt_compose.md"
            save(name, pt.shipped_source(name) + "\nX")
            assert key() != k0
            overrides.delete_override(name)
            assert key() == k0
        with part("Task7-I"):
            k0 = key()
            save("chat/intent_markers.md", "X")
            assert key() != k0
        with part("Task7-J"):
            skill = next((pt._TEMPLATE_DIR / "skills").glob("*.md")).stem
            old_rev = overrides.revision()
            old = pt.load_skill_meta(skill)
            save(f"skills/{skill}.md", "---\nname: Other\n---\nbody")
            assert pt.load_skill_meta(skill)["name"] == "Other"
            pt._skill_meta_cache[skill] = (old_rev, old)
            assert pt.load_skill_meta(skill)["name"] == "Other"
        from app.core import template_preview as editor
        name = "tasks/consolidation_daily.md"
        with part("Task8-H"):
            assert isinstance(editor.read_template(name), dict), "read_template must return metadata, not a string"
            editor.save_template(name, "X")
            data = editor.read_template(name)
            assert isinstance(data, dict), "read_template must return metadata, not a string"
            assert data["origin"] == "override" and data["content"] == "X"
            assert data["shipped"] == pt.shipped_source(name)
            assert data["base_changed"] is False and data["world"] == "world"
        def hashes():
            return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                    for folder in pt.template_search_dirs() for p in folder.rglob("*") if p.is_file()}
        with part("Task8-G"):
            before = hashes()
            editor.save_template(name, "X")
            editor.delete_template_override(name)
            assert hashes() == before
        with part("Task8-I"):
            overrides.set_override(name, "X", "0" * 64)
            assert editor.read_template(name)["base_changed"] is True
            assert next(t for t in editor.list_templates() if t["path"] == name)["base_changed"] is True
        for existing in (False, True):
            with part("Task8-J2" if existing else "Task8-J1"):
                if existing:
                    save(name, "X")
                try:
                    editor.save_template(name, "{% if %}")
                except ValueError as exc:
                    assert "line 1" in str(exc)
                else:
                    raise AssertionError("invalid syntax accepted")
                ov = overrides.lookup(name)
                assert (ov.content == "X") if existing else (ov is None)
        with part("Task8-K"):
            save(name, "X")
            assert editor.save_template(name, pt.shipped_source(name))["origin"] == "shipped"
            assert overrides.lookup(name) is None
        with part("Task8-L"):
            orphan = "gone/vanished.md"
            overrides.set_override(orphan, "X", "0" * 64)
            data = editor.read_template(orphan)
            assert data["origin"] == "override" and data["orphan"] is True
            assert data["shipped"] == ""
            assert next(t for t in editor.list_templates() if t["path"] == orphan)["kind"] == "orphan"
            assert editor.delete_template_override(orphan) is True
            for action in (lambda: editor.save_template(orphan, "Y"),
                           lambda: editor.delete_template_override("../x.md")):
                try:
                    action()
                except ValueError:
                    pass
                else:
                    raise AssertionError("invalid operation accepted")
        assert overrides.fingerprint() == ""
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
