"""Check the Setup → Packages inventory (loader.package_inventory) on temporary packages.

Usage: .venv/bin/python scripts/smoke_package_inventory.py
No world, server, real plugin folder or private pack is touched; the registry
is never populated, so every row reports loaded=False.

Expected values, derived by hand from the rule in loader.package_category
("category" when it is skill/content/adult, else "skill" with verbs, "content"
without) and the scan order of package_inventory (repo root first, then
installed/, repo wins on an id collision, symlinked folder = "linked"):

  verbs        skills: [...], no category           -> skill,   repo
  species      no skills, on_load only               -> content, repo
  spicy        skills + category: adult              -> adult,   repo
  shouty       no skills + category: ADULT           -> adult    (case-folded)
  odd          skills + category: bogus              -> skill    (unknown ignored)
  needy        requires: [ghost] (ghost not on disk) -> LISTED, requires ["ghost"]
                                                        (discovery would drop it)
  linkpack     symlink into another directory        -> source linked
  market       only in installed/                    -> source installed
  verbs (dup)  also in installed/ with category adult -> NOT listed twice; the
                                                        repo row (skill) wins
  broken       plugin.yaml is a YAML list, not a map -> skipped
  Ids come back sorted: linkpack market needy odd shouty species spicy verbs.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label} — got {got!r}, expected {want!r}")
    if not ok:
        FAILS.append(label)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


VERB = "skills:\n  - skill_id: probe_verb\n    module: skill.py\n"


def main() -> int:
    from app.plugins.loader import package_category, package_inventory

    print("1) package_category by hand")
    check("verbs, no category", package_category({"skills": [{"skill_id": "a"}]}), "skill")
    check("no verbs, no category", package_category({"on_load": "x.py"}), "content")
    check("declared adult", package_category({"category": "adult"}), "adult")
    check("declared case-folded", package_category({"category": " Adult "}), "adult")
    check("unknown category ignored", package_category({"category": "bogus", "skill_id": "a"}), "skill")

    print("2) package_inventory on a temporary plugin dir")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "plugins"
        write(base / "verbs/plugin.yaml", "name: verbs\n" + VERB)
        write(base / "species/plugin.yaml", "name: species\non_load: reg.py\n")
        write(base / "spicy/plugin.yaml", "name: spicy\ncategory: adult\n" + VERB)
        write(base / "shouty/plugin.yaml", "name: shouty\ncategory: ADULT\non_load: reg.py\n")
        write(base / "odd/plugin.yaml", "name: odd\ncategory: bogus\n" + VERB)
        write(base / "needy/plugin.yaml", "name: needy\nrequires: [ghost]\n" + VERB)
        write(base / "broken/plugin.yaml", "- just\n- a list\n")
        elsewhere = Path(tmp) / "elsewhere" / "linkpack"
        write(elsewhere / "plugin.yaml", "name: linkpack\non_load: reg.py\n")
        (base / "linkpack").symlink_to(elsewhere, target_is_directory=True)
        write(base / "installed/market/plugin.yaml", "name: market\n" + VERB)
        write(base / "installed/verbs/plugin.yaml", "name: verbs\ncategory: adult\n" + VERB)

        rows = {r["id"]: r for r in package_inventory(base)}
        check("ids sorted, broken skipped, dup once",
              [r["id"] for r in package_inventory(base)],
              ["linkpack", "market", "needy", "odd", "shouty", "species", "spicy", "verbs"])
        check("verbs", (rows["verbs"]["category"], rows["verbs"]["source"]), ("skill", "repo"))
        check("species", rows["species"]["category"], "content")
        check("spicy", rows["spicy"]["category"], "adult")
        check("shouty", rows["shouty"]["category"], "adult")
        check("odd", rows["odd"]["category"], "skill")
        check("needy listed with its requirement", rows["needy"]["requires"], ["ghost"])
        check("linkpack source", rows["linkpack"]["source"], "linked")
        check("market source", rows["market"]["source"], "installed")
        check("nothing loaded", any(r["loaded"] for r in rows.values()), False)

    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
