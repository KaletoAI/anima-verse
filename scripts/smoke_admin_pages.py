#!/usr/bin/env python3
"""Smoke run for the admin-settings section paging (`SECTIONS[...]["pages"]`).

A section may split its admin page into several navigation sub-entries by
declaring `pages`: a list of `{id, label, icon?, description?, fields?,
sub_arrays?, custom?}`. The renderer (static/admin/settings.js) shows exactly
the listed fields/sub_arrays per page and drops everything unassigned onto the
FIRST page, so a forgotten field is invisible in the navigation structure but
still editable. This check makes that safety net unnecessary in practice: it
asserts that TODAY every field and every sub_array of a paged section is
assigned exactly once, that no page names something the section does not
have, and that page ids/labels are well-formed and unique.

A page with `custom: true` renders NO config fields of its own — its whole
content is hand-built by a page script (the Tasks and Overview pages of
`llm_routing` are built by static/admin/settings-routing.js). Such a page must
therefore be empty, and it must not be the only page of a section, or the
section's fields would have nowhere to go.

`llm_routing` gets one check of its own, because its LLMs page is hand-built
too and still renders the section's fields: `max_concurrent` — the LANE COUNT
of an LLM entry (plan-cache-lanes.md § 5, phase 4 item 11) — has to be in that
page's field list, or the only place the lane count can be set disappears from
the UI while the backend keeps reading it.

Hand-derived expectations, all of them structural: the numbers below are the
schema's own (10 fields on llm_routing today), never a recorded output.

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
    custom_pages = []
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
        if page.get("custom"):
            custom_pages.append(pid)
            check(n_f + n_a == 0,
                  f"custom page {pid!r} lists no fields ({n_f} fields, {n_a} sub-arrays)")
        else:
            check(n_f + n_a > 0, f"page {pid!r} is not empty ({n_f} fields, {n_a} sub-arrays)")

    unknown_f = [n for n in seen_fields if n not in fields]
    unknown_a = [n for n in seen_arrays if n not in sub_arrays]
    check(not unknown_f, f"no unknown field names in pages (got {unknown_f})")
    check(not unknown_a, f"no unknown sub_array names in pages (got {unknown_a})")

    dup_f = sorted({n for n in seen_fields if seen_fields.count(n) > 1})
    dup_a = sorted({n for n in seen_arrays if seen_arrays.count(n) > 1})
    check(not dup_f, f"no field assigned twice (got {dup_f})")
    check(not dup_a, f"no sub_array assigned twice (got {dup_a})")

    check(len(custom_pages) < len(pages),
          f"not every page is custom (custom: {custom_pages})")

    missing_f = [n for n in fields if n not in seen_fields]
    missing_a = [n for n in sub_arrays if n not in seen_arrays]
    check(not missing_f,
          f"all {len(fields)} fields assigned to a page (unassigned: {missing_f})")
    check(not missing_a,
          f"all {len(sub_arrays)} sub_arrays assigned to a page (unassigned: {missing_a})")


def check_llm_routing_lanes(sec: dict) -> None:
    """The lane count must be reachable on LLM Routing › LLMs.

    The page is hand-built (static/admin/settings-routing.js) and renders the
    fields its page entry lists, in that order. `max_concurrent` is the number
    of cache lanes of an LLM entry — the one setting the whole cache-lane
    mechanism is steered with — so it belongs on that list and it belongs with
    provider/model rather than among the sampling values.
    """
    print("\n[llm_routing] the lane count on the LLMs page")
    fields = sec.get("fields") or {}
    page = next((p for p in (sec.get("pages") or [])
                 if isinstance(p, dict) and p.get("id") == "llms"), None)
    check(page is not None, "the LLMs page exists")
    if page is None:
        return
    listed = list(page.get("fields") or [])
    check("max_concurrent" in fields, "the schema has the field max_concurrent")
    check("max_concurrent" in listed, "the LLMs page lists max_concurrent")
    spec = fields.get("max_concurrent") or {}
    check(spec.get("type") == "int", f"max_concurrent is an int field (got {spec.get('type')!r})")
    check(int(spec.get("min", 0)) >= 1,
          f"at least one lane per entry (min={spec.get('min')!r})")
    check(int(spec.get("default", 0)) == 1,
          f"the default is one lane (default={spec.get('default')!r})")
    # "Lanes" has to be in the LABEL: the description explains the mechanism,
    # but the label is what the admin reads while scanning the entry.
    check("lane" in str(spec.get("label", "")).lower(),
          f"the label names lanes (got {spec.get('label')!r})")
    if "max_concurrent" in listed and "model" in listed:
        check(listed.index("max_concurrent") == listed.index("model") + 1,
              "Lanes sits directly below Model")


def main() -> int:
    paged = {k: s for k, s in SECTIONS.items()
             if isinstance(s, dict) and isinstance(s.get("pages"), list)}
    print(f"paged sections: {sorted(paged) or '(none)'}")
    # image_generation is the section the paging was built for — losing its
    # pages silently would put ~50 fields back on one screen.
    check("image_generation" in paged, "image_generation declares pages")
    for key, sec in paged.items():
        check_section(key, sec)
    check_llm_routing_lanes(paged.get("llm_routing") or {})

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
