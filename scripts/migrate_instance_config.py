#!/usr/bin/env python3
"""Move a world's server settings into the instance config (one-time migration).

Usage:
    ./.venv/bin/python scripts/migrate_instance_config.py --from NAME
        [--worlds-dir DIR]   (default: <repo>/worlds)
        [--instance DIR]     (default: <repo>/instance)
        [--backup-dir DIR]   (default: <repo>/migration_backup)
        [--dry-run] [--if-needed] [--follow-symlinks]

Run it with the server STOPPED. Since the two config layers exist
(``app/core/config.py``), a world's config.json holds only world settings;
everything of instance scope (LLM providers, image backends, routing, ports,
keys — ``app/core/config_scope.py``) lives in ``<instance>/config.json`` +
``secrets.json``, shared by every world. This script builds the instance from
ONE world (``--from``) and trims EVERY world under ``--worlds-dir`` to its
world part.

THE ORDER IS LOAD-BEARING:

1. Pre-check. The instance config.json exists -> exit 2 (``--if-needed``:
   exit 0, no action). An instance secrets.json without a config.json ->
   exit 2 (it would be overwritten). The source world has no config.json ->
   exit 2. A world directory that is a symlink or resolves outside
   ``--worlds-dir`` belongs to another checkout: it is NOT read, backed up,
   written or verified, only listed as SKIPPED — unless
   ``--follow-symlinks`` (a symlinked SOURCE without it -> exit 2). Then
   EVERY world (a subdirectory of ``--worlds-dir`` with a config.json; the
   others are listed as "no config.json") is read strictly:
   an unreadable config.json or secrets.json aborts the run with exit 2,
   naming the file, before anything is written.
2. Plan, in memory. Per world: config.json with ITS OWN secrets.json merged
   on top (``config._layer_with_secrets``), then ``_apply_file_migrations``
   on that RAW, UNSPLIT union — ``_migrate_image_routing`` must still see the
   legacy ``*_imagegen_default`` fields of ``image_generation``,
   ``random_events``, ``story_engine``, ``messaging_frame`` and
   ``skills.instagram``, some of which are world fields that a split would
   separate from the instance-side ``routing`` they seed. Then
   ``split_by_scope`` -> instance part / world part / unknown roots, each
   part ``prune``d. The SOURCE world's instance part becomes the instance;
   every other world's instance part is dropped (reported, with whether it
   differs from the source's). Unknown roots are dropped everywhere.
3. Report (stdout): per world the removed root keys (instance + unknown),
   the removed instance sub-paths of mixed sections, the fields the
   migrations removed, the values pruned as equal to the shipped default —
   and ``proactive`` explicitly (the old source of the thought cadence,
   not carried over). For the instance: the paths written. Secret VALUES are
   never printed. ``--dry-run`` stops here: nothing is written, not even
   the backup directory.
4. Backup. config.json + secrets.json of every world go byte-identical to
   ``<backup-dir>/instance-config-<utc stamp>/<world>/`` (read back and
   compared). The path is printed.
5. Write. First the instance, then every world — the same shape
   ``config.save`` produces: pruned, sensitive values split into the layer's
   own secrets.json (named lists by entry name), a secrets.json only when
   non-empty (an empty world secrets.json is deleted), a file only when its
   content changes, atomically. Right before the first write every world
   file is compared with the bytes read in step 1 — a file changed meanwhile
   aborts the run (exit 1).
6. Verify. For every migrated world: ``config.load(world, instance,
   strict=True)`` succeeds, ``check_instance_ready`` passes, and re-reading
   both layers yields exactly the planned pruned parts (the next boot's
   ``migrate_file`` writes nothing). Prints "verified"; a mismatch exits 1
   and names the backup to restore from.

Exit codes: 0 done (or nothing to do with ``--if-needed``), 1 a write or the
verification failed (restore from the printed backup), 2 refused before any
write.

The instance default ``<repo>/instance`` is set HERE, in the tool — app/
code names no instance path. Docker calls this script on every start with
``--if-needed`` (``docker/docker-entrypoint.sh``).
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core import config, config_scope  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402

DEFAULT_WORLDS = REPO / "worlds"
DEFAULT_INSTANCE = REPO / "instance"
DEFAULT_BACKUP = REPO / "migration_backup"

EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2

# The old source of the thought cadence (``thoughts`` replaced it; the load
# fallback is gone). Named explicitly in the report so nobody misses it.
PROACTIVE = "proactive"


class Refused(Exception):
    """A pre-check failed — nothing has been written."""


class World:
    """One world's files, what was read from them, and the plan for them."""

    def __init__(self, name: str, directory: Path):
        self.name = name
        self.dir = directory
        # The resolved target when the directory is a followed symlink.
        self.link: Optional[Path] = None
        self.config_path = directory / "config.json"
        self.secrets_path = directory / "secrets.json"
        self.original: dict = {}        # file name -> bytes as read
        self.raw: dict = {}             # config.json + own secrets, unmigrated
        self.migrated: dict = {}        # raw after _apply_file_migrations
        self.inst_pruned: dict = {}
        self.world_pruned: dict = {}
        self.raw_instance_keys: list = []
        self.raw_unknown: list = []
        self.migrated_away: list = []
        self.pruned_default: list = []


# ── Helpers ─────────────────────────────────────────────────────────────────

def _leaves(node, prefix: tuple = ()) -> list:
    """Every leaf path of a dict as a tuple (a list or scalar is one leaf)."""
    if isinstance(node, dict) and node:
        out: list = []
        for key, value in node.items():
            out.extend(_leaves(value, prefix + (str(key),)))
        return out
    return [prefix] if prefix else []


def _under(path: tuple, prefixes) -> bool:
    return any(path[:len(p)] == p for p in prefixes)


def _dotted(parts) -> str:
    return ".".join(parts)


def _value_at(cfg: dict, dotted_key: str):
    node = cfg
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _masked(value):
    """``value`` with every sensitive string blanked (for printing)."""
    return config._split_secrets(value)[0]


def _short(items: list, limit: int = 12) -> str:
    if not items:
        return "-"
    more = f" … and {len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(items[:limit]) + more


def _file_json(data: bytes, path: Path) -> dict:
    """Parse bytes read from ``path`` like ``config._read_json_file``."""
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"cannot read {path}: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} is not a JSON object")
    return parsed


# ── 1. Pre-check + strict read ──────────────────────────────────────────────

def _foreign_target(d: Path, worlds_dir: Path) -> Optional[Path]:
    """The resolved path when ``d`` is a symlink or resolves outside
    ``worlds_dir`` (another checkout's world), else None."""
    resolved = d.resolve()
    if d.is_symlink() or resolved.parent != worlds_dir.resolve():
        return resolved
    return None


def discover_worlds(worlds_dir: Path, follow_symlinks: bool) -> tuple:
    """``(worlds, skipped_names, symlinked)`` — a world is a subdirectory
    with a config.json. ``symlinked`` = ``[(name, resolved path)]`` of the
    symlinked / outside worlds left alone (without ``follow_symlinks``)."""
    worlds, skipped, symlinked = [], [], []
    for d in sorted(p for p in worlds_dir.iterdir() if p.is_dir()):
        if not (d / "config.json").is_file():
            skipped.append(d.name)
            continue
        target = _foreign_target(d, worlds_dir)
        if target is not None and not follow_symlinks:
            symlinked.append((d.name, target))
            continue
        w = World(d.name, d)
        w.link = target
        worlds.append(w)
    return worlds, skipped, symlinked


def read_world(w: World) -> None:
    """Read both files strictly. Raises ``Refused`` naming the file."""
    for f in (w.config_path, w.secrets_path):
        if f.exists():
            try:
                w.original[f.name] = f.read_bytes()
            except OSError as e:
                raise Refused(f"cannot read {f}: {e}") from e
            try:
                _file_json(w.original[f.name], f)
            except ValueError as e:
                raise Refused(str(e)) from e
    try:
        w.raw = config._layer_with_secrets(w.config_path, strict=True)
    except ValueError as e:
        raise Refused(str(e)) from e
    # The merge read the files a second time — they must be the bytes above.
    for fname, data in w.original.items():
        f = w.dir / fname
        if not f.exists() or f.read_bytes() != data:
            raise Refused(f"{f} changed while it was being read — is the server running?")
    if w.secrets_path.exists() and w.secrets_path.name not in w.original:
        raise Refused(f"{w.secrets_path} appeared while it was being read")


# ── 2. Plan ─────────────────────────────────────────────────────────────────

def plan_world(w: World) -> None:
    raw_inst, raw_world, w.raw_unknown = config_scope.split_by_scope(w.raw)
    w.raw_instance_keys = config._split_keys(raw_inst)

    w.migrated = json.loads(json.dumps(w.raw))
    config._apply_file_migrations(w.migrated)
    inst, world, _unknown = config_scope.split_by_scope(w.migrated)
    w.inst_pruned = config_scope.prune(inst)
    w.world_pruned = config_scope.prune(world)

    # What the migrations removed: leaves of the file that are gone after
    # them — outside the instance keys and unknown roots reported on their own.
    skip = [tuple(k.split(".")) for k in w.raw_instance_keys] + [(r,) for r in w.raw_unknown]
    after = set(_leaves(w.migrated))
    w.migrated_away = [_dotted(p) for p in _leaves(w.raw)
                       if p not in after and not _under(p, skip)]
    # Values of the file's world part that are dropped as the shipped default.
    kept = set(_leaves(w.world_pruned))
    world_after = set(_leaves(world))
    w.pruned_default = [_dotted(p) for p in _leaves(raw_world)
                        if p in world_after and p not in kept]


def file_outcome(w: World) -> str:
    """How step 5 changes this world's files, from the bytes read in step 1."""
    clean, secrets = config._split_secrets(w.world_pruned)
    cfg_now = _file_json(w.original["config.json"], w.config_path)
    parts = []
    parts.append("config.json unchanged" if config._json_equal(cfg_now, clean)
                 else "config.json rewritten")
    had_secrets = "secrets.json" in w.original
    if secrets:
        if had_secrets and config._json_equal(
                _file_json(w.original["secrets.json"], w.secrets_path), secrets):
            parts.append("secrets.json unchanged")
        else:
            parts.append(f"secrets.json written ({len(_leaves(secrets))} value(s))")
    elif had_secrets:
        parts.append("secrets.json deleted (nothing secret left)")
    return ", ".join(parts)


# ── 3. Report ───────────────────────────────────────────────────────────────

def _dead_field(dotted_key: str) -> bool:
    """True for a key ``_strip_dead_config_fields`` removes (feature gone)."""
    parts = dotted_key.split(".")
    if len(parts) == 1:
        return parts[0] in config.DEAD_TOPLEVEL_FIELDS
    return len(parts) == 2 and parts[1] in config.DEAD_CONFIG_FIELDS.get(parts[0], ())


def report(source: World, worlds: list, skipped: list, symlinked: list,
           inst_cfg: Path) -> None:
    src_raw_inst = config_scope.split_by_scope(source.raw)[0]
    for w in worlds:
        is_source = w is source
        print(f"\nWorld '{w.name}'{' (source of the instance)' if is_source else ''}"
              f"{f' (symlink → {w.link})' if w.link else ''}:")
        roots = [k for k in w.raw_instance_keys if "." not in k]
        subs = [k for k in w.raw_instance_keys if "." in k]

        def label(keys, w=w, is_source=is_source):
            out = []
            for k in keys:
                notes = []
                if _value_at(w.migrated, k) is None and _dead_field(k):
                    notes.append("dead field, stripped")
                elif _value_at(w.migrated, k) is None:
                    # A legacy field the migrations consumed (the old
                    # *_imagegen_default fields seed image_generation.routing).
                    notes.append("consumed by the migrations")
                elif not is_source:
                    same = _value_at(w.raw, k) == _value_at(src_raw_inst, k)
                    notes.append(f"{'same as' if same else 'DIFFERS from'} the instance")
                out.append(f"{k} [{'; '.join(notes)}]" if notes else k)
            return _short(out)
        verb = ("moved to the instance" if is_source
                else f"dropped (the instance comes from '{source.name}')")
        print(f"  instance root keys, {verb}: {label(roots)}")
        print(f"  instance sub-paths of mixed sections, {verb}: {label(subs)}")
        print(f"  unknown root keys, dropped: {_short(w.raw_unknown)}")
        print(f"  removed by the load-time migrations: {_short(w.migrated_away)}")
        print(f"  pruned (equal to the shipped default): {len(w.pruned_default)}"
              + (f" — {_short(w.pruned_default, 8)}" if w.pruned_default else ""))
        if PROACTIVE in w.raw:
            print(f"  NOTE: '{PROACTIVE}' is removed — it was the old source of the "
                  f"thought cadence and is NOT carried over: "
                  f"{json.dumps(_masked(w.raw[PROACTIVE]), ensure_ascii=False)}. "
                  f"Set the matching 'thoughts' fields in /admin/settings if this "
                  f"world relied on it.")
        print(f"  files: {file_outcome(w)}")
    for name, target in symlinked:
        print(f"\nWorld '{name}': SKIPPED (symlink → {target}) — pass "
              f"--follow-symlinks to migrate it")
    for name in skipped:
        print(f"\nSkipped '{name}': no config.json")

    clean, secrets = config._split_secrets(source.inst_pruned)
    print(f"\nInstance {inst_cfg}:")
    print(f"  config.json paths: {_short(config._split_keys(clean), 40)}")
    routing = (clean.get("image_generation") or {}).get("routing")
    if routing:
        print(f"  image_generation.routing: {json.dumps(routing, ensure_ascii=False)}")
    if secrets:
        print(f"  secrets.json: {_short([_dotted(p) for p in _leaves(secrets)], 40)}")
    else:
        print("  secrets.json: none (no secret value)")


# ── 4. Backup ───────────────────────────────────────────────────────────────

def backup(worlds: list, backup_dir: Path) -> Path:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    root = backup_dir / f"instance-config-{stamp}"
    n = 1
    while root.exists():
        n += 1
        root = backup_dir / f"instance-config-{stamp}-{n}"
    root.mkdir(parents=True)
    os.chmod(root, 0o700)
    for w in worlds:
        target = root / w.name
        target.mkdir()
        for fname, data in w.original.items():
            dst = target / fname
            with open(dst, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(dst, 0o600)
            if dst.read_bytes() != data:
                raise RuntimeError(f"backup {dst} differs from the original")
    return root


# ── 5. Write ────────────────────────────────────────────────────────────────

def assert_unchanged(worlds: list) -> None:
    for w in worlds:
        for f in (w.config_path, w.secrets_path):
            now = f.read_bytes() if f.exists() else None
            if now != w.original.get(f.name):
                raise RuntimeError(f"{f} changed since it was read — nothing written; "
                                   f"is the server running?")


def write(source: World, worlds: list, inst_cfg: Path) -> None:
    assert_unchanged(worlds)
    config._write_layer(inst_cfg, source.inst_pruned)
    print(f"  written: {inst_cfg}"
          + (f", {inst_cfg.parent / 'secrets.json'}"
             if (inst_cfg.parent / "secrets.json").exists() else ""))
    for w in worlds:
        if config._write_layer(w.config_path, w.world_pruned):
            print(f"  written: world '{w.name}' ({file_outcome(w)})")


# ── 6. Verify ───────────────────────────────────────────────────────────────

def verify(source: World, worlds: list, inst_cfg: Path) -> list:
    problems = []
    for w in worlds:
        try:
            config.load(w.config_path, inst_cfg, strict=True)
            config.check_instance_ready(w.config_path, inst_cfg)
            union = config._compose(w.config_path, inst_cfg, strict=True)
        except Exception as e:  # noqa: BLE001 — every failure is reported
            problems.append(f"world '{w.name}': {type(e).__name__}: {e}")
            continue
        inst, world, unknown = config_scope.split_by_scope(union)
        if unknown:
            problems.append(f"world '{w.name}': unknown roots after migration: {unknown}")
        if not config._json_equal(config_scope.prune(inst), source.inst_pruned):
            problems.append(f"world '{w.name}': the instance re-reads differently "
                            f"than planned")
        if not config._json_equal(config_scope.prune(world), w.world_pruned):
            problems.append(f"world '{w.name}': the world part re-reads differently "
                            f"than planned")
    return problems


# ── Main ────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="source", required=True,
                    help="name of the world whose instance settings become the instance")
    ap.add_argument("--worlds-dir", type=Path, default=DEFAULT_WORLDS,
                    help=f"directory holding the worlds (default: {DEFAULT_WORLDS})")
    ap.add_argument("--instance", type=Path, default=DEFAULT_INSTANCE,
                    help=f"instance directory to create (default: {DEFAULT_INSTANCE})")
    ap.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP,
                    help=f"where the backup goes (default: {DEFAULT_BACKUP})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the report, write nothing (no backup either)")
    ap.add_argument("--follow-symlinks", action="store_true",
                    help="also migrate world directories that are symlinks or resolve "
                         "outside --worlds-dir (default: skip them)")
    ap.add_argument("--if-needed", action="store_true",
                    help="exit 0 without action when the instance config exists")
    args = ap.parse_args(argv)
    # The app modules log every step at INFO; this tool prints its own
    # report — keep warnings (e.g. a secret without a counterpart).
    logging.getLogger().setLevel(logging.WARNING)

    worlds_dir = args.worlds_dir.resolve()
    inst_dir = args.instance.resolve()
    inst_cfg = inst_dir / "config.json"
    inst_sec = inst_dir / "secrets.json"

    # 1. Pre-check.
    try:
        if inst_cfg.exists():
            if args.if_needed:
                print(f"Instance config {inst_cfg} exists — nothing to do.")
                return EXIT_OK
            raise Refused(f"the instance config {inst_cfg} already exists — "
                          f"the migration has run")
        if inst_sec.exists():
            raise Refused(f"{inst_sec} exists without a config.json — it would be "
                          f"overwritten; move it away first")
        if not worlds_dir.is_dir():
            raise Refused(f"worlds directory {worlds_dir} does not exist")
        if not (worlds_dir / args.source / "config.json").is_file():
            raise Refused(f"source world '{args.source}' has no config.json in {worlds_dir}")
        worlds, skipped, symlinked = discover_worlds(worlds_dir, args.follow_symlinks)
        source = next((w for w in worlds if w.name == args.source), None)
        linked = dict(symlinked)
        if source is None and args.source in linked:
            raise Refused(f"source world '{args.source}' is a symlink → "
                          f"{linked[args.source]} — pass --follow-symlinks to migrate it")
        if source is None:
            # e.g. "--from ../x": a config.json, but not a world of this dir.
            raise Refused(f"'{args.source}' is not a world directory of {worlds_dir}")
        for w in worlds:
            read_world(w)
    except Refused as e:
        print(f"REFUSED: {e}")
        return EXIT_REFUSED

    # 2. Plan.
    for w in worlds:
        plan_world(w)

    # 3. Report.
    print(f"Instance config migration — source world '{source.name}'"
          + (" — DRY RUN, nothing is written" if args.dry_run else ""))
    print(f"  worlds dir: {worlds_dir}")
    print(f"  instance:   {inst_dir}")
    report(source, worlds, skipped, symlinked, inst_cfg)
    if args.dry_run:
        print("\nDry run — nothing written.")
        return EXIT_OK

    # 4. Backup.
    try:
        backup_root = backup(worlds, args.backup_dir.resolve())
    except Exception as e:  # noqa: BLE001
        print(f"\nFAILED: backup — {e}. Nothing else was written.")
        return EXIT_FAILED
    print(f"\nBackup (byte-identical): {backup_root}")

    # 5. Write.
    try:
        write(source, worlds, inst_cfg)
    except Exception as e:  # noqa: BLE001
        print(f"\nFAILED while writing: {e}\nRestore the world files from {backup_root} "
              f"and remove {inst_dir} before running again.")
        return EXIT_FAILED

    # 6. Verify.
    problems = verify(source, worlds, inst_cfg)
    if problems:
        print("\nVERIFICATION FAILED:")
        for p in problems:
            print(f"  {p}")
        print(f"Restore the world files from {backup_root} and remove {inst_dir}.")
        return EXIT_FAILED
    print(f"\nverified: {len(worlds)} world(s) load with the instance, "
          f"none blocks the start, a re-read writes nothing")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
