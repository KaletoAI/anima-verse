#!/usr/bin/env python3
"""Smoke: scripts/migrate_instance_config.py moves a world's server settings
into the instance — and touches nothing else.

Usage:
    ./.venv/bin/python scripts/smoke_migrate_instance_config.py

No server, no world DB, no network. Everything happens in a temp directory;
the script under test runs as a subprocess (its exit codes are part of the
contract), with STORAGE_DIR and INSTANCE_DIR pointing at throwaway dirs.

FIXTURE — four directories under <tmp>/worlds:

  src    providers "Local" + "Cloud" and image backend "flux-a", their keys in
         an OLD position-based secrets.json; the legacy field
         image_generation.outfit_imagegen_default = "flux*"; a use case
         "scene" with its own style; chat; skills.searx.url.
  other  its own provider "OtherLLM" (+ key), telegram, proactive, chat.
  bare   chat only (written with indent 4, so a rewrite would show).
  nocfg  no config.json at all.

EXPECTATIONS, derived by hand from the scope rules and the migrations:

  * instance = the instance part of src: providers, image backends,
    skills.searx.url and image_generation.routing. The routing is seeded from
    the legacy field by config._IMAGE_ROUTING_SEED, where "flux*" from
    outfit_imagegen_default lands in the chains of `expression` and `tpose`
    (both read expression_imagegen_default, then outfit_imagegen_default) —
    so routing == {"expression": ["flux*"], "tpose": ["flux*"]}.
  * instance/secrets.json holds the three keys in the by-NAME format
    (config._split_secrets on a named list); instance/config.json has the
    keys blanked.
  * src keeps chat and use_cases.scene; providers, backends, skills.searx.url
    and the legacy field are gone; its secrets.json is deleted (nothing secret
    left on the world side).
  * other loses providers (instance scope), telegram and proactive (unknown
    roots); the report names proactive. Its secrets.json is deleted.
  * bare is byte-identical (nothing to change -> not rewritten).
  * The backup holds config.json + secrets.json of src, other, bare,
    byte-identical to the originals; nocfg is listed as "no config.json".
  * A second run exits 2; with --if-needed it exits 0; neither writes.
  * config.load(src, instance) yields providers / chat / routing equal to the
    values hard-coded below.
  * --dry-run prints the report and writes nothing (no backup dir either).
  * An unreadable secrets.json in any world aborts with exit 2 before the
    first write, naming the file. A missing source world exits 2.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="smoke_migrate_instance_"))
# Throwaway storage + instance roots BEFORE any app import
# (scripts/smoke_scripts_storage_lint.py).
os.environ["STORAGE_DIR"] = str(TMP / "storage")
os.environ["INSTANCE_DIR"] = str(TMP / "unused_instance")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
SCRIPT = REPO / "scripts" / "migrate_instance_config.py"
PY = sys.executable

FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ── Fixture ──────────────────────────────────────────────────────────────

SRC_CONFIG = {
    "providers": [
        {"name": "Local", "type": "openai", "api_base": "http://llm.local/v1",
         "api_key": "", "timeout": 120},
        {"name": "Cloud", "type": "openai", "api_base": "https://cloud.example/v1",
         "api_key": ""},
    ],
    "image_generation": {
        "outfit_imagegen_default": "flux*",
        "backends": [
            {"name": "flux-a", "api_type": "a1111", "api_url": "http://img.local:7860",
             "api_key": "", "enabled": True, "category": "txt2img", "cost": 1},
        ],
        "use_cases": {
            "scene": {
                "styles": {
                    "natural": {"prompt_style": "moody film still",
                                "prompt_negative": "", "prompt_instruction": ""},
                    "keywords": {"prompt_style": "", "prompt_negative": "",
                                 "prompt_instruction": ""},
                },
                "llm_compose": False,
            },
        },
    },
    "chat": {"chattiness": 0.8, "anti_rep_lookback": 9},
    "skills": {"searx": {"url": "http://searx.local:8080"}},
}
# The OLD secrets format: lists by position.
SRC_SECRETS = {
    "providers": [{"api_key": "sk-local"}, {"api_key": "sk-cloud"}],
    "image_generation": {"backends": [{"api_key": "img-key"}]},
}
OTHER_CONFIG = {
    "providers": [{"name": "OtherLLM", "type": "openai",
                   "api_base": "http://other.local/v1", "api_key": ""}],
    "telegram": {"enabled": True, "password": ""},
    "proactive": {"min_turn_gap_seconds": 99},
    "chat": {"chattiness": 0.2},
}
OTHER_SECRETS = {"providers": [{"api_key": "sk-other"}],
                 "telegram": {"password": "tg-pass"}}
BARE_CONFIG = {"chat": {"chattiness": 0.9}}

# ── Hard-coded expectations (by hand, see the docstring) ─────────────────

EXPECTED_PROVIDERS = [
    {"name": "Local", "type": "openai", "api_base": "http://llm.local/v1",
     "api_key": "sk-local", "timeout": 120},
    {"name": "Cloud", "type": "openai", "api_base": "https://cloud.example/v1",
     "api_key": "sk-cloud"},
]
EXPECTED_CHAT = {"chattiness": 0.8, "anti_rep_lookback": 9}
EXPECTED_ROUTING = {"expression": ["flux*"], "tpose": ["flux*"]}
EXPECTED_INSTANCE_SECRETS = {
    "providers": {"Local": {"api_key": "sk-local"}, "Cloud": {"api_key": "sk-cloud"}},
    "image_generation": {"backends": {"flux-a": {"api_key": "img-key"}}},
}


def build(root: Path) -> Path:
    """Write the fixture worlds under ``root/worlds``; returns that dir."""
    worlds = root / "worlds"
    for name, cfg, sec in (("src", SRC_CONFIG, SRC_SECRETS),
                           ("other", OTHER_CONFIG, OTHER_SECRETS)):
        (worlds / name).mkdir(parents=True)
        (worlds / name / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (worlds / name / "secrets.json").write_text(json.dumps(sec, indent=2), encoding="utf-8")
    (worlds / "bare").mkdir(parents=True)
    (worlds / "bare" / "config.json").write_text(json.dumps(BARE_CONFIG, indent=4),
                                                 encoding="utf-8")
    (worlds / "nocfg").mkdir(parents=True)
    (worlds / "nocfg" / "notes.txt").write_text("not a world config\n", encoding="utf-8")
    return worlds


def snapshot(root: Path) -> dict:
    """{relative path: bytes} of every file under ``root``."""
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    return subprocess.run(
        [PY, str(SCRIPT), "--worlds-dir", str(root / "worlds"),
         "--instance", str(root / "instance"),
         "--backup-dir", str(root / "backup"), *extra],
        capture_output=True, text=True, env=env, cwd=str(REPO))


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    print("1. the real run on the fixture")
    root = TMP / "run"
    worlds = build(root)
    before = snapshot(worlds)
    proc = run(root, "--from", "src")
    out = proc.stdout
    check("exit code 0", proc.returncode == 0,
          f"rc={proc.returncode}\n{out}\n{proc.stderr}")
    check("the script verified itself", "verified" in out)

    inst_cfg = root / "instance" / "config.json"
    inst_sec = root / "instance" / "secrets.json"
    check("instance/config.json written", inst_cfg.is_file())
    check("instance/secrets.json written", inst_sec.is_file())
    if not (inst_cfg.is_file() and inst_sec.is_file()):
        return finish()
    inst = read(inst_cfg)
    check("instance has the providers of src (keys blanked)",
          [p.get("name") for p in inst.get("providers") or []] == ["Local", "Cloud"]
          and all(p.get("api_key") == "" for p in inst["providers"]),
          json.dumps(inst.get("providers")))
    backends = (inst.get("image_generation") or {}).get("backends") or []
    check("instance has the image backend of src (key blanked)",
          [b.get("name") for b in backends] == ["flux-a"] and backends[0]["api_key"] == "",
          json.dumps(backends))
    check("instance routing seeded from outfit_imagegen_default",
          (inst.get("image_generation") or {}).get("routing") == EXPECTED_ROUTING,
          json.dumps((inst.get("image_generation") or {}).get("routing")))
    check("instance has skills.searx.url",
          ((inst.get("skills") or {}).get("searx") or {}).get("url") == "http://searx.local:8080")
    check("no secret value in instance/config.json",
          not any(s in inst_cfg.read_text(encoding="utf-8")
                  for s in ("sk-local", "sk-cloud", "img-key")))
    check("instance/secrets.json in the by-name format",
          read(inst_sec) == EXPECTED_INSTANCE_SECRETS, json.dumps(read(inst_sec)))
    check("instance has no world value (chat, use_cases)",
          "chat" not in inst
          and "use_cases" not in (inst.get("image_generation") or {}))

    src = read(worlds / "src" / "config.json")
    check("src keeps chat", src.get("chat") == EXPECTED_CHAT, json.dumps(src.get("chat")))
    check("src keeps use_cases.scene",
          ((src.get("image_generation") or {}).get("use_cases") or {}).get("scene")
          == SRC_CONFIG["image_generation"]["use_cases"]["scene"])
    check("src has no providers", "providers" not in src)
    check("src has no skills.searx.url",
          "url" not in ((src.get("skills") or {}).get("searx") or {}))
    check("src has no backends / routing / legacy default field",
          not ({"backends", "routing", "outfit_imagegen_default"}
               & set((src.get("image_generation") or {}).keys())),
          json.dumps(sorted((src.get("image_generation") or {}).keys())))
    check("src/secrets.json deleted", not (worlds / "src" / "secrets.json").exists())

    other = read(worlds / "other" / "config.json")
    check("other has no telegram / proactive / providers",
          not ({"telegram", "proactive", "providers"} & set(other)), json.dumps(other))
    check("other keeps chat", other.get("chat") == {"chattiness": 0.2})
    check("other/secrets.json deleted", not (worlds / "other" / "secrets.json").exists())
    check("the report names proactive", "proactive" in out)
    check("the report lists nocfg as having no config.json",
          any("nocfg" in line and "no config.json" in line for line in out.splitlines()))

    check("bare is byte-identical",
          (worlds / "bare" / "config.json").read_bytes() == before["bare/config.json"])
    check("nocfg untouched",
          (worlds / "nocfg" / "notes.txt").read_bytes() == before["nocfg/notes.txt"])

    stamps = sorted((root / "backup").glob("instance-config-*"))
    check("exactly one backup directory", len(stamps) == 1, str(stamps))
    if stamps:
        backed = snapshot(stamps[0])
        originals = {k: v for k, v in before.items()
                     if k.endswith(("config.json", "secrets.json"))}
        check("the backup is byte-identical to the originals", backed == originals,
              f"backup {sorted(backed)} vs originals {sorted(originals)}")
        check("the backup path is printed", str(stamps[0]) in out)

    print("2. config.load(src, instance) — hard-coded expectations")
    from app.core import config
    cfg = config.load(worlds / "src" / "config.json", inst_cfg, strict=True)
    check("providers", cfg.get("providers") == EXPECTED_PROVIDERS,
          json.dumps(cfg.get("providers")))
    check("chat", cfg.get("chat") == EXPECTED_CHAT, json.dumps(cfg.get("chat")))
    check("routing", (cfg.get("image_generation") or {}).get("routing") == EXPECTED_ROUTING,
          json.dumps((cfg.get("image_generation") or {}).get("routing")))
    config.check_instance_ready(worlds / "src" / "config.json", inst_cfg)
    check("check_instance_ready passes for src", True)

    print("3. a second run")
    after_first = snapshot(root)
    proc = run(root, "--from", "src")
    check("exit code 2 (instance exists)", proc.returncode == 2,
          f"rc={proc.returncode} {proc.stdout} {proc.stderr}")
    proc = run(root, "--from", "src", "--if-needed")
    check("--if-needed: exit code 0", proc.returncode == 0,
          f"rc={proc.returncode} {proc.stdout} {proc.stderr}")
    check("neither second run wrote anything", snapshot(root) == after_first)

    print("4. --dry-run")
    droot = TMP / "dry"
    dworlds = build(droot)
    dbefore = snapshot(droot)
    proc = run(droot, "--from", "src", "--dry-run")
    check("exit code 0", proc.returncode == 0, f"rc={proc.returncode} {proc.stderr}")
    check("the report names proactive", "proactive" in proc.stdout)
    check("the report names the instance paths",
          "providers" in proc.stdout and "skills.searx.url" in proc.stdout)
    check("nothing written (no backup, no instance, worlds unchanged)",
          snapshot(droot) == dbefore and not (droot / "backup").exists()
          and not (droot / "instance").exists())
    check("no secret value in the report",
          not any(s in proc.stdout for s in ("sk-local", "sk-cloud", "img-key", "tg-pass")))
    del dworlds

    print("5. an unreadable world file aborts before the first write")
    broot = TMP / "broken"
    bworlds = build(broot)
    (bworlds / "other" / "secrets.json").write_text("{not json", encoding="utf-8")
    bbefore = snapshot(broot)
    proc = run(broot, "--from", "src")
    check("exit code 2", proc.returncode == 2, f"rc={proc.returncode} {proc.stdout}")
    check("the message names the file",
          str(bworlds / "other" / "secrets.json") in proc.stdout + proc.stderr)
    check("nothing written", snapshot(broot) == bbefore
          and not (broot / "backup").exists() and not (broot / "instance").exists())

    print("6. a missing source world")
    proc = run(broot, "--from", "nope")
    check("exit code 2", proc.returncode == 2, f"rc={proc.returncode}")
    check("nothing written", snapshot(broot) == bbefore
          and not (broot / "backup").exists() and not (broot / "instance").exists())

    return finish()


def finish() -> int:
    shutil.rmtree(TMP, ignore_errors=True)
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
