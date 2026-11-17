#!/usr/bin/env python3
"""A197: purge every 3D mesh of a world's characters, except a keep list and temporary NPCs.

User decision 2026-11-18: delete all outfit (worn-piece) meshes and all base-body / outfit-body / combination
models of every character, except the keep list (default ``Spoty,Gelina``) and the temporary NPCs. Images stay.

What goes, per purged character (grouped so the dry run shows it):

- ``model3d/`` — the whole folder: base body (``bas*``: unrigged/prerig/raw/rigged/covered/facefix/low,
  geometry ``.npz``), outfit bodies (``ob*``), texture models (``tex*``), combination models (one rigged GLB per
  outfit signature + its tiers), assembled figures, rollback snapshots — plus a legacy ``model/`` folder.
- ``garments/`` — everything EXCEPT ``garments/images/`` (the worn/ghost/cutout/base views stay): fits + records,
  ``low/``, ``raw/`` (incl. HairDeck/HAAR hair job folders), ``prepared/``, ``layers/``, ``bodies/`` (outfit-body
  fits), ``attempts/``, ``shell/``, ``templates/`` (template drapes), ``failed/`` (so no automatic trigger skips the
  rebuild), ``limbs/``.
- shared ``<world>/footwear/<item>/<ssig>/`` shoe meshes (``raw.glb``, ``prepared.glb``, ``insole.json``) of every
  footwear item that NO kept character and no temporary NPC holds or wears; the ``mesh`` / ``insole`` steps are
  dropped from that source's ``record.json`` (the original record is backed up), the image steps stay.
- ``hub_ops`` rows (and their ``<world>/hub_ops/<op_id>/`` folders) of the character's model / hair jobs
  (subjects ``model3d:<name>:…``, ``garment_haar:<name>:…``), so no resumed job publishes into a purged folder.

The character profiles hold no mesh state (worn pieces, hairstyle choice and ``model3d_opts`` are choices and stay);
fit/mesh/acceptance records are sidecar files and go with their meshes. The next Build plans the rebuild.

Temporary NPCs are the characters whose template carries the feature ``temporary_npc``
(``character.is_temporary_npc``); the template is read from ``shared/templates/character/<template>.json``.

Nothing is deleted: everything is MOVED to ``<world>/.purge-backup-a197-<stamp>/`` under the same relative path,
the DB rows go to ``db_rows.json`` there, ``manifest.json`` lists every move (written before the first move,
so an interrupted ``--apply`` is undone by ``--restore`` too).

Usage (server STOPPED — ``./start.sh --stop``):
    ./.venv/bin/python scripts/purge_meshes_a197.py --world "worlds/Anima Divide"            # dry run
    ./.venv/bin/python scripts/purge_meshes_a197.py --world "worlds/Anima Divide" --apply    # move to backup
    ./.venv/bin/python scripts/purge_meshes_a197.py --world "worlds/Anima Divide" \\
        --restore "worlds/Anima Divide/.purge-backup-a197-<stamp>"                            # undo
Options: ``--keep A,B`` (default ``Spoty,Gelina``; every name must be a character of the world).
Standalone: opens ``world.db`` with sqlite3 directly, imports nothing from ``app``, no network.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
DEFAULT_KEEP = "Spoty,Gelina"
BACKUP_PREFIX = ".purge-backup-a197-"
TEMPLATES_DIR = REPO / "shared" / "templates" / "character"
#: footwear source files that are meshes (the rest of the source folder are images + record)
FOOTWEAR_MESH_FILES = ("raw.glb", "prepared.glb", "insole.json")
FOOTWEAR_MESH_STEPS = ("mesh", "insole")
HUB_SUBJECT_PREFIXES = ("model3d:", "garment_haar:")


# --- safety -----------------------------------------------------------------

def server_running(repo: Path = REPO) -> Optional[str]:
    """A reason string when an Anima Verse server looks alive, else None (pid file + process scan)."""
    pid_file = repo / ".pids" / "main.pid"
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return f"pid file {pid_file} names live process {pid}"
    except (FileNotFoundError, ValueError, ProcessLookupError):
        pass
    except PermissionError:
        return f"pid file {pid_file} names a live process"
    proc = Path("/proc")
    if proc.is_dir():
        for d in proc.iterdir():
            if not d.name.isdigit() or int(d.name) == os.getpid():
                continue
            try:
                cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            except OSError:
                continue
            if "app.server:app" in cmd and "uvicorn" in cmd:
                return f"process {d.name} runs uvicorn app.server:app"
    return None


# --- world reading ----------------------------------------------------------

def is_temp_template(template: str) -> bool:
    """Template feature ``temporary_npc`` (fails closed like ``template_feature``)."""
    if not template:
        return False
    path = TEMPLATES_DIR / f"{template}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool((data.get("features") or {}).get("temporary_npc", False))


def read_world(world: Path) -> Tuple[Dict[str, Dict], List[Dict], Dict[str, set]]:
    """``({name: {template, temp}}, hub_ops rows, {item_id: holders})`` — read-only."""
    con = sqlite3.connect(f"file:{world / 'world.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        chars: Dict[str, Dict] = {}
        for r in con.execute("SELECT name, template, profile_json FROM characters"):
            try:
                prof = json.loads(r["profile_json"] or "{}")
            except ValueError:
                prof = {}
            tmpl = str(prof.get("template") or r["template"] or "human-default")
            chars[r["name"]] = {"template": tmpl, "temp": is_temp_template(tmpl)}
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        hub = [dict(r) for r in con.execute("SELECT * FROM hub_ops")] if "hub_ops" in tables else []
        holders: Dict[str, set] = {}
        for t in ("equipped_pieces", "equipped_items", "inventory_items"):
            if t in tables:
                for r in con.execute(f"SELECT character_name, item_id FROM {t}"):
                    holders.setdefault(str(r[1]), set()).add(str(r[0]))
    finally:
        con.close()
    return chars, hub, holders


# --- planning ---------------------------------------------------------------

def _model3d_group(rel: Path) -> str:
    parts = rel.parts  # ("model3d", ...)
    if parts[0] == "model":
        return "legacy model/"
    if len(parts) > 1 and parts[1] in ("assembled", "rollback"):
        return f"model3d: {parts[1]}"
    name = parts[-1]
    for p in parts[1:]:
        if p.startswith("bas"):
            return "model3d: base body"
    if name.startswith("bas"):
        return "model3d: base body"
    if name.startswith("o") and not name.startswith("op"):
        return "model3d: outfit bodies"
    if name.startswith("tex"):
        return "model3d: texture models"
    return "model3d: combination models"


def _garment_group(rel: Path) -> str:
    parts = rel.parts  # ("garments", ...)
    if len(parts) == 2:
        return "garments: fits"
    sub = parts[1]
    if sub == "raw" and len(parts) > 3:
        return "garments: hair jobs (HairDeck/HAAR)"
    return f"garments: {sub}"


def _files(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink())


def plan(world: Path, keep: List[str]) -> Dict:
    chars, hub, holders = read_world(world)
    cdir = world / "characters"
    names = set(chars) | ({d.name for d in cdir.iterdir() if d.is_dir()} if cdir.is_dir() else set())
    unknown = [k for k in keep if k not in names]
    if unknown:
        raise SystemExit(f"--keep names no character of this world: {', '.join(unknown)} "
                         f"(characters: {', '.join(sorted(names))})")
    protected = set(keep) | {n for n, c in chars.items() if c["temp"]}
    out: Dict = {"characters": {}, "footwear": [], "hub_ops": [], "skipped": {}}
    for name in sorted(names):
        info = chars.get(name, {"template": "(no DB row)", "temp": False})
        if name in keep:
            out["skipped"][name] = "keep list"
            continue
        if info["temp"]:
            out["skipped"][name] = f"temporary NPC ({info['template']})"
            continue
        entries = []
        base = cdir / name
        for top in ("model3d", "model"):
            if (base / top).is_dir():
                for f in _files(base / top):
                    rel = f.relative_to(base)
                    entries.append({"path": str(f.relative_to(world)), "group": _model3d_group(rel),
                                    "size": f.lstat().st_size})
        g = base / "garments"
        if g.is_dir():
            for f in _files(g):
                rel = f.relative_to(base)
                if rel.parts[1] == "images":
                    continue
                entries.append({"path": str(f.relative_to(world)), "group": _garment_group(rel),
                                "size": f.lstat().st_size})
        out["characters"][name] = {"template": info["template"], "files": entries}
    fw = world / "footwear"
    if fw.is_dir():
        for item in sorted(d for d in fw.iterdir() if d.is_dir()):
            who = holders.get(item.name, set())
            if who & protected:
                out["skipped"][f"footwear/{item.name}"] = "held/worn by " + ", ".join(sorted(who & protected))
                continue
            for src in sorted(d for d in item.iterdir() if d.is_dir()):
                files = [src / n for n in FOOTWEAR_MESH_FILES if (src / n).is_file()]
                rec = src / "record.json"
                steps = {}
                if rec.is_file():
                    try:
                        steps = json.loads(rec.read_text(encoding="utf-8")).get("steps") or {}
                    except ValueError:
                        steps = {}
                drop = [s for s in FOOTWEAR_MESH_STEPS if s in steps]
                if files or drop:
                    out["footwear"].append({
                        "dir": str(src.relative_to(world)), "holders": sorted(who),
                        "files": [{"path": str(f.relative_to(world)), "size": f.stat().st_size} for f in files],
                        "record": str(rec.relative_to(world)) if drop else None, "drop_steps": drop})
    purged = set(out["characters"])
    for row in hub:
        subj = str(row.get("subject") or "")
        for pre in HUB_SUBJECT_PREFIXES:
            if subj.startswith(pre) and subj[len(pre):].split(":", 1)[0] in purged:
                d = world / "hub_ops" / str(row["op_id"])
                files = [{"path": str(f.relative_to(world)), "size": f.lstat().st_size}
                         for f in _files(d)] if d.is_dir() else []
                out["hub_ops"].append({"row": row, "dir": str(d.relative_to(world)) if d.is_dir() else None,
                                       "files": files})
    return out


def human(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024
    return f"{n} B"


def report(p: Dict, verbose: bool = True) -> int:
    total = 0
    count = 0
    print("== Characters")
    for name, c in p["characters"].items():
        files = c["files"]
        size = sum(e["size"] for e in files)
        total += size
        count += len(files)
        print(f"\n## {name} [{c['template']}] — {len(files)} files, {human(size)}")
        groups: Dict[str, List[Dict]] = {}
        for e in files:
            groups.setdefault(e["group"], []).append(e)
        for g in sorted(groups):
            es = groups[g]
            print(f"   {g}: {len(es)} files, {human(sum(e['size'] for e in es))}")
            if verbose:
                for e in es:
                    print(f"      {e['path']}  ({human(e['size'])})")
    print("\n== Skipped")
    for k, why in p["skipped"].items():
        print(f"   {k}: {why}")
    print("\n== Shared footwear shoe meshes (items no kept character / temporary NPC holds)")
    for f in p["footwear"]:
        size = sum(e["size"] for e in f["files"])
        total += size
        count += len(f["files"])
        print(f"   {f['dir']} (holders: {', '.join(f['holders']) or '-'}): {len(f['files'])} files, {human(size)}"
              + (f"; record drops steps {', '.join(f['drop_steps'])}" if f["drop_steps"] else ""))
        if verbose:
            for e in f["files"]:
                print(f"      {e['path']}  ({human(e['size'])})")
    print("\n== hub_ops rows (DB) of purged characters")
    for h in p["hub_ops"]:
        size = sum(e["size"] for e in h["files"])
        total += size
        count += len(h["files"])
        r = h["row"]
        print(f"   {r['op_id']} {r['kind']} {r['subject']} [{r['status']}] + {len(h['files'])} files, {human(size)}")
    if not p["hub_ops"]:
        print("   (none)")
    print(f"\n== TOTAL: {count} files, {human(total)}; {len(p['hub_ops'])} DB rows; "
          f"{len(p['characters'])} characters purged, {len(p['skipped'])} skipped entries")
    return total


# --- apply / restore ----------------------------------------------------------

def _move(world: Path, backup: Path, rel: str, moves: List[str]) -> None:
    src = world / rel
    dst = backup / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    moves.append(rel)


def _prune_empty(world: Path, rels: List[str]) -> None:
    dirs = sorted({p for r in rels for p in Path(r).parents if str(p) != "."}, key=lambda p: -len(p.parts))
    for d in dirs:
        full = world / d
        if full.is_dir() and full != world and not any(full.iterdir()):
            full.rmdir()


def _write_json(path: Path, data: Dict) -> None:
    """Atomic JSON write (temp sibling + ``os.replace``): a crash leaves the old or the new file, never half."""
    tmp = path.with_name(path.name + ".a197tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def apply(world: Path, p: Dict, stamp: Optional[str] = None) -> Path:
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    backup = world / f"{BACKUP_PREFIX}{stamp}"
    backup.mkdir()
    rows = [h["row"] for h in p["hub_ops"]]
    # Manifest + DB rows are written BEFORE the first move, listing the whole plan: a run that dies
    # half-way (one unreadable file, a full disk, a record that changed since the plan) still leaves a
    # backup that --restore undoes — restore brings back exactly the entries that reached the backup.
    planned = ([e["path"] for c in p["characters"].values() for e in c["files"]]
               + [e["path"] for f in p["footwear"] for e in f["files"]]
               + [e["path"] for h in p["hub_ops"] for e in h["files"]])
    _write_json(backup / "db_rows.json", {"hub_ops": rows})
    _write_json(backup / "manifest.json", {"moved": planned, "complete": False,
                                           "records_rewritten": [f["record"] for f in p["footwear"]
                                                                 if f["record"]]})
    moves: List[str] = []
    records: List[str] = []
    for c in p["characters"].values():
        for e in c["files"]:
            _move(world, backup, e["path"], moves)
    for f in p["footwear"]:
        for e in f["files"]:
            _move(world, backup, e["path"], moves)
        if f["record"]:
            rec = world / f["record"]
            (backup / f["record"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(rec, backup / f["record"])
            data = json.loads(rec.read_text(encoding="utf-8"))
            for s in f["drop_steps"]:
                data.get("steps", {}).pop(s, None)
            tmp = rec.with_suffix(".json.a197tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, rec)
            records.append(f["record"])
    for h in p["hub_ops"]:
        for e in h["files"]:
            _move(world, backup, e["path"], moves)
    _write_json(backup / "manifest.json", {"moved": moves, "records_rewritten": records, "complete": True})
    if rows:
        con = sqlite3.connect(str(world / "world.db"))
        try:
            with con:
                con.executemany("DELETE FROM hub_ops WHERE op_id = ?", [(r["op_id"],) for r in rows])
        finally:
            con.close()
    _prune_empty(world, moves)
    return backup


def restore(world: Path, backup: Path) -> None:
    man = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    # An interrupted apply leaves the planned list: only what actually reached the backup comes back.
    moved = [r for r in man["moved"] if os.path.lexists(backup / r)]
    clash = [r for r in moved if os.path.lexists(world / r)]
    if clash:
        raise SystemExit(f"refusing to restore: {len(clash)} target files exist again, e.g. {clash[0]}")
    for r in moved:
        (world / r).parent.mkdir(parents=True, exist_ok=True)
        os.replace(backup / r, world / r)
    for r in man["records_rewritten"]:
        # The original is copied aside before the rewrite; a copy that exists is the original.
        if os.path.lexists(backup / r):
            os.replace(backup / r, world / r)
    # Rows an interrupted apply never deleted are re-inserted unchanged (INSERT OR REPLACE, same values).
    rows = json.loads((backup / "db_rows.json").read_text(encoding="utf-8")).get("hub_ops") or []
    if rows:
        con = sqlite3.connect(str(world / "world.db"))
        try:
            with con:
                for r in rows:
                    cols = list(r)
                    con.execute(f"INSERT OR REPLACE INTO hub_ops ({', '.join(cols)}) "
                                f"VALUES ({', '.join('?' for _ in cols)})", [r[c] for c in cols])
        finally:
            con.close()
    shutil.rmtree(backup)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--world", required=True, help="world directory, e.g. 'worlds/Anima Divide'")
    ap.add_argument("--keep", default=DEFAULT_KEEP, help=f"comma list of kept characters (default {DEFAULT_KEEP})")
    ap.add_argument("--apply", action="store_true", help="move everything listed into the backup folder")
    ap.add_argument("--restore", metavar="BACKUP", help="move a backup folder's contents back and re-insert rows")
    ap.add_argument("--summary", action="store_true", help="dry run without the per-file lines")
    ap.add_argument("--no-server-check", action="store_true", help=argparse.SUPPRESS)  # tests on a temp world
    a = ap.parse_args(argv)
    world = Path(a.world).resolve()
    if not (world / "world.db").is_file():
        print(f"no world.db in {world}", file=sys.stderr)
        return 2
    if not a.no_server_check:
        why = server_running()
        if why:
            print(f"The server is running ({why}). Stop it first:  ./start.sh --stop", file=sys.stderr)
            return 3
    if a.restore:
        restore(world, Path(a.restore).resolve())
        print(f"restored from {a.restore}")
        return 0
    keep = [k.strip() for k in a.keep.split(",") if k.strip()]
    p = plan(world, keep)
    report(p, verbose=not a.summary)
    if not a.apply:
        print("\nDRY RUN — nothing changed. Add --apply to move all of the above into a backup folder.")
        return 0
    backup = apply(world, p)
    print(f"\nAPPLIED. Backup: {backup}\nRestore (server stopped):\n"
          f"  ./.venv/bin/python scripts/purge_meshes_a197.py --world \"{a.world}\" --restore \"{backup}\"\n"
          f"Delete the backup once the rebuild is fine:  rm -rf \"{backup}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
