#!/usr/bin/env python3
"""Smoke for scripts/purge_meshes_a197.py on a fake world in a temp dir (no server, no network).

Usage: ./.venv/bin/python scripts/smoke_purge_meshes_a197.py

The fake world (hand-built, sizes chosen so the totals are derivable by hand):
- Spoty (animal-default, keep), Gelina (human-roleplay, keep), Tess (npc-temporary), Ann + Bob (human-roleplay).
- every character: model3d/bas0000aaaa.glb (100 B), model3d/0123456789ab.glb (200 B),
  garments/item_x_0123456789ab.glb (50 B), garments/images/item_x_0123456789ab_worn_front.png (10 B),
  model_refs/tpose.png (10 B).
- Ann also: garments/raw/item_h_0123456789ab/record.json (7 B, a hair job folder).
- footwear/item_boot/aaaaaaaaaaaa/{raw.glb 30 B, prepared.glb 20 B, insole.json 5 B, cutout.png, record.json
  with steps cutout+mesh+insole}; held by Bob only -> purged. footwear/item_sandal/... held by Gelina -> kept.
- hub_ops: model3d:Ann:sig (+ hub_ops/hop_a/x.bin 4 B), model3d:Gelina:sig, prop:chair.

Expected by hand: purged = Ann, Bob. Ann: 100+200+50+7 = 357 B in 4 files; Bob: 350 B in 3 files;
footwear item_boot: 30+20+5 = 55 B in 3 files; hub op hop_a: 4 B in 1 file.
Total = 357 + 350 + 55 + 4 = 766 B, 11 files, 1 DB row. Images (worn_front, tpose, cutout) all stay.
"""
import io
import json
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import purge_meshes_a197 as pm  # noqa: E402

FAIL = []


def check(cond, msg):
    if not cond:
        FAIL.append(msg)
        print("FAIL:", msg)


def put(p: Path, n: int) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)


def build(world: Path) -> None:
    con = sqlite3.connect(str(world / "world.db"))
    con.execute("CREATE TABLE characters (name TEXT PRIMARY KEY, template TEXT, profile_json TEXT)")
    con.execute("CREATE TABLE hub_ops (op_id TEXT PRIMARY KEY, kind TEXT, subject TEXT, status TEXT)")
    con.execute("CREATE TABLE inventory_items (character_name TEXT, item_id TEXT)")
    con.execute("CREATE TABLE equipped_pieces (character_name TEXT, slot TEXT, item_id TEXT)")
    chars = {"Spoty": "animal-default", "Gelina": "human-roleplay", "Tess": "npc-temporary",
             "Ann": "human-roleplay", "Bob": "human-roleplay"}
    for n, t in chars.items():
        con.execute("INSERT INTO characters VALUES (?,?,?)", (n, t, json.dumps({"template": t})))
        c = world / "characters" / n
        put(c / "model3d" / "bas0000aaaa.glb", 100)
        put(c / "model3d" / "0123456789ab.glb", 200)
        put(c / "garments" / "item_x_0123456789ab.glb", 50)
        put(c / "garments" / "images" / "item_x_0123456789ab_worn_front.png", 10)
        put(c / "model_refs" / "tpose.png", 10)
    put(world / "characters" / "Ann" / "garments" / "raw" / "item_h_0123456789ab" / "record.json", 7)
    for item, holder in (("item_boot", "Bob"), ("item_sandal", "Gelina")):
        s = world / "footwear" / item / "aaaaaaaaaaaa"
        put(s / "raw.glb", 30)
        put(s / "prepared.glb", 20)
        put(s / "insole.json", 5)
        put(s / "cutout.png", 9)
        (s / "record.json").write_text(json.dumps({"steps": {"cutout": {"accepted": True},
                                                             "mesh": {"accepted": True},
                                                             "insole": {"accepted": True}}}))
        con.execute("INSERT INTO inventory_items VALUES (?,?)", (holder, item))
    con.execute("INSERT INTO hub_ops VALUES ('hop_a','model3d_mesh','model3d:Ann:sig','deferred')")
    con.execute("INSERT INTO hub_ops VALUES ('hop_g','model3d_mesh','model3d:Gelina:sig','deferred')")
    con.execute("INSERT INTO hub_ops VALUES ('hop_p','prop_mesh','prop:chair','deferred')")
    put(world / "hub_ops" / "hop_a" / "x.bin", 4)
    con.commit()
    con.close()


def snapshot(world: Path):
    return sorted(str(p.relative_to(world)) for p in world.rglob("*") if p.is_file() and p.name != "world.db")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        world = Path(tmp) / "w"
        world.mkdir()
        build(world)
        before = snapshot(world)
        rec_before = (world / "footwear/item_boot/aaaaaaaaaaaa/record.json").read_text()
        p = pm.plan(world, ["Spoty", "Gelina"])
        check(sorted(p["characters"]) == ["Ann", "Bob"], f"purged set {sorted(p['characters'])}")
        check("temporary NPC" in p["skipped"].get("Tess", ""), "Tess skipped as temp NPC")
        ann = p["characters"]["Ann"]["files"]
        check(sum(e["size"] for e in ann) == 357 and len(ann) == 4, "Ann 357 B / 4 files")
        check(any(e["group"] == "garments: hair jobs (HairDeck/HAAR)" for e in ann), "hair job grouped")
        check(any(e["group"] == "model3d: base body" for e in ann), "base body grouped")
        check([f["dir"] for f in p["footwear"]] == ["footwear/item_boot/aaaaaaaaaaaa"], "only boot footwear")
        check([h["row"]["op_id"] for h in p["hub_ops"]] == ["hop_a"], "only hop_a")
        buf = io.StringIO()
        with redirect_stdout(buf):
            total = pm.report(p)
        check(total == 766, f"total {total} != 766")
        check("TOTAL: 11 files" in buf.getvalue(), "11 files in report")
        check(snapshot(world) == before, "dry run changed nothing")
        try:
            pm.plan(world, ["Spotty"])
            check(False, "unknown keep name refused")
        except SystemExit:
            pass

        backup = pm.apply(world, p, stamp="test")
        after = set(snapshot(world))
        for n in ("Ann", "Bob"):
            check(not (world / "characters" / n / "model3d").exists(), f"{n} model3d gone")
            check(f"characters/{n}/garments/images/item_x_0123456789ab_worn_front.png" in after, f"{n} image kept")
            check(f"characters/{n}/model_refs/tpose.png" in after, f"{n} model_refs kept")
        for n in ("Spoty", "Gelina", "Tess"):
            check(f"characters/{n}/model3d/bas0000aaaa.glb" in after, f"{n} base kept")
            check(f"characters/{n}/garments/item_x_0123456789ab.glb" in after, f"{n} fit kept")
        check("footwear/item_sandal/aaaaaaaaaaaa/prepared.glb" in after, "sandal kept")
        check("footwear/item_boot/aaaaaaaaaaaa/cutout.png" in after, "boot image kept")
        check("footwear/item_boot/aaaaaaaaaaaa/prepared.glb" not in after, "boot mesh moved")
        steps = json.loads((world / "footwear/item_boot/aaaaaaaaaaaa/record.json").read_text())["steps"]
        check(sorted(steps) == ["cutout"], f"boot record steps {sorted(steps)}")
        con = sqlite3.connect(str(world / "world.db"))
        ops = sorted(r[0] for r in con.execute("SELECT op_id FROM hub_ops"))
        con.close()
        check(ops == ["hop_g", "hop_p"], f"hub ops after apply {ops}")
        man = json.loads((backup / "manifest.json").read_text())
        check(len(man["moved"]) == 11, f"moved {len(man['moved'])} != 11")
        check((backup / "characters/Ann/model3d/0123456789ab.glb").stat().st_size == 200, "backup layout")

        pm.restore(world, backup)
        check(snapshot(world) == before, "restore brings every file back")
        check((world / "footwear/item_boot/aaaaaaaaaaaa/record.json").read_text() == rec_before, "record restored")
        con = sqlite3.connect(str(world / "world.db"))
        ops = sorted(r[0] for r in con.execute("SELECT op_id FROM hub_ops"))
        con.close()
        check(ops == ["hop_a", "hop_g", "hop_p"], f"hub ops after restore {ops}")
        check(not backup.exists(), "backup removed after restore")
    print("FAILED" if FAIL else "OK purge_meshes_a197")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
