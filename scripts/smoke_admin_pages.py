#!/usr/bin/env python3
"""Smoke run for the admin-settings section paging (`SECTIONS[...]["pages"]`).

A section may split its admin page into several navigation sub-entries by
declaring `pages`: a list of `{id, label, icon?, description?, fields?,
sub_arrays?}`. The renderer (static/admin/settings.js) shows exactly the
listed fields/sub_arrays per page and drops everything unassigned onto the
FIRST page, so a forgotten field is invisible in the navigation structure but
still editable. This check makes that safety net unnecessary in practice: it
asserts that TODAY every field and every sub_array of a paged section is
assigned exactly once, that no page names something the section does not
have, and that page ids/labels are well-formed and unique.

No config, no world, no DB — it only imports the schema module.

Usage:  ./.venv/bin/python scripts/smoke_admin_pages.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config_schema import SECTIONS  # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print(f"  OK   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILS.append(msg)


def check_section(key: str, sec: dict) -> None:
    pages = sec.get("pages")
    print(f"\n[{key}] {len(pages)} pages")
    fields = list((sec.get("fields") or {}).keys())
    sub_arrays = list((sec.get("sub_arrays") or {}).keys())

    seen_ids = set()
    seen_fields = []
    seen_arrays = []
    for page in pages:
        pid = page.get("id")
        check(isinstance(pid, str) and pid, f"page id present: {pid!r}")
        check(pid not in seen_ids, f"page id unique: {pid!r}")
        seen_ids.add(pid)
        check(bool(page.get("label")), f"page {pid!r} has a label")
        for name in page.get("fields") or []:
            seen_fields.append(name)
        for name in page.get("sub_arrays") or []:
            seen_arrays.append(name)
        n_f = len(page.get("fields") or [])
        n_a = len(page.get("sub_arrays") or [])
        check(n_f + n_a > 0, f"page {pid!r} is not empty ({n_f} fields, {n_a} sub-arrays)")

    unknown_f = [n for n in seen_fields if n not in fields]
    unknown_a = [n for n in seen_arrays if n not in sub_arrays]
    check(not unknown_f, f"no unknown field names in pages (got {unknown_f})")
    check(not unknown_a, f"no unknown sub_array names in pages (got {unknown_a})")

    dup_f = sorted({n for n in seen_fields if seen_fields.count(n) > 1})
    dup_a = sorted({n for n in seen_arrays if seen_arrays.count(n) > 1})
    check(not dup_f, f"no field assigned twice (got {dup_f})")
    check(not dup_a, f"no sub_array assigned twice (got {dup_a})")

    missing_f = [n for n in fields if n not in seen_fields]
    missing_a = [n for n in sub_arrays if n not in seen_arrays]
    check(not missing_f,
          f"all {len(fields)} fields assigned to a page (unassigned: {missing_f})")
    check(not missing_a,
          f"all {len(sub_arrays)} sub_arrays assigned to a page (unassigned: {missing_a})")


def main() -> int:
    paged = {k: s for k, s in SECTIONS.items()
             if isinstance(s, dict) and isinstance(s.get("pages"), list)}
    print(f"paged sections: {sorted(paged) or '(none)'}")
    # image_generation is the section the paging was built for — losing its
    # pages silently would put ~50 fields back on one screen.
    check("image_generation" in paged, "image_generation declares pages")
    for key, sec in paged.items():
        check_section(key, sec)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
