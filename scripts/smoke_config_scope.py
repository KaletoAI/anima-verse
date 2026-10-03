#!/usr/bin/env python3
"""Smoke: every config section and field has a scope (instance / world).

Usage:  ./.venv/bin/python scripts/smoke_config_scope.py

No server, no world DB. The storage root is a throwaway temp dir (set before
any app import); the plugin packages are discovered so their config
subsections are part of the schema (``config_schema.get_schema()`` injects
them under ``skills``). Nothing under ``worlds/`` or ``instance/`` is read or
written.

WHY

The server config moves out of the per-world ``config.json`` into an instance
layer. Which file a value belongs to is decided by its ``scope`` in the
schema: ``instance`` = the server/host (endpoints, keys, LLM providers, image
backends, ports), ``world`` = the simulation of one world (chat rules, NPC
behaviour, calendar). ``mixed`` marks only a node whose children differ.
``app/core/config_scope.py::scope_of(path)`` answers the question for any
dotted config path; the recursive split of a config (next task) is built on
``scope_of`` and ``child_scopes_differ``.

PART 1 — what is checked, and where every expected value comes from
-------------------------------------------------------------------

P) PRE-DISCOVERY (runs first, before ``discover_packages()``). The config is
   split at config load, and at server boot that is BEFORE plugin discovery
   — when the registry, and with it ``get_schema()``, knows no package
   subsection. ``config_scope`` then reads the subsections from the
   manifests (``loader.manifest_config_schemas()``):
     - ``loader.is_discovered()`` is False and the registry is empty;
     - the manifest scan imports no package code: no ``plugins.<pkg>.*`` and
       no ``plugins_onload_*`` module appears in ``sys.modules`` that was not
       there before, and the registry is still empty afterwards;
     - ``scope_of("skills.searx.url") == instance`` (searx declares it in its
       plugin.yaml) and ``scope_of("skills.searx") == mixed`` (enabled is
       world by the E5 default, url instance -> rule 4);
       without the manifest view both would be ``world``: an unknown key under
       ``skills`` inherits the section's mixed -> world (rule 3);
     - after ``discover_packages()`` the same two answers (row D below), and
       the view follows the registry: a probe package registered with a
       subsection ``zz_probe`` whose field ``a`` declares instance makes
       ``scope_of("skills.zz_probe.a") == instance``; unregistered again it is
       ``world`` (unknown key under skills, rule 3) — the view is rebuilt,
       not frozen.
   SKIP when searx is not among the manifests.

0) SELF-TEST of the endpoint-name matcher on hand cases: ``url``,
   ``webhook_url``, ``api_key``, ``auth_token``, ``endpoint``,
   ``endpoints_list`` and a ``password``-typed field match; ``enabled``,
   ``engines``, ``urls_seen`` and ``categories`` do not. A matcher that cannot
   see a ``url`` would make check C vacuous.

A) Every NON-virtual schema section declares ``scope`` and the value is one
   of instance/world/mixed. ``llm_simple`` is virtual (a page over
   ``llm_routing``, no config key of its own) and has no scope.
   Every explicit ``scope`` anywhere (section, field, sub_array, subsection,
   plugin field) is one of the three values, and ``mixed`` appears only on a
   node with children, never on a field.

B) The scope table of the plan (spec § 5, E3, E4, E5), written out by hand:
     instance: server, providers, llm_retry, llm_routing, lanes, embedding,
               decision, tts, knowledge, content_marketplace, ui,
               image_generation (section)
     world:    chat, thoughts, intents, relationships, social_reactions,
               random_events, npc, story_engine, game, messaging_frame,
               game_calendar, game_seasons, memory (section)
     mixed:    skills
   plus the four deeper declarations:
     memory.fields.chat_retention_days        -> instance
     image_generation.sub_arrays.use_cases    -> world
     skills.subsections.outfit_change         -> world
     (plugin) skills.searx.fields.url         -> instance
   and the rule that no schema section is missing from this table.

C) ENDPOINT RULE (E5): every field of a plugin config subsection whose name
   is ``url``, ``*_url``, ``api_key``, ``*token*`` or ``endpoint*``, or whose
   type is ``password``, declares ``scope: instance``. A host address or a key
   is the server's business even when the package's other settings are
   world settings. Covers every discovered package — repo, ``installed/`` and
   the symlinked private packs (whose fix would belong in the packs repo).

D) HAND TABLE for ``scope_of`` — each row derived from the four rules of the
   plan, not from running the code:
     server.log_level                -> instance  field, inherits section
                                                  ``server: instance`` (rule 2)
     providers                       -> instance  section declaration
     image_generation                -> mixed     section is instance, but
                                                  sub_array use_cases is world
                                                  -> children differ (rule 4)
     image_generation.backends       -> instance  sub_array without own scope
                                                  inherits the section
     image_generation.routing        -> instance  not in the schema (written
                                                  by the routing page) ->
                                                  nearest known parent (rule 3)
     image_generation.use_cases      -> world     own declaration wins (rule 2)
     image_generation.enabled        -> instance  field inherits section
     memory                          -> mixed     section world, field
                                                  chat_retention_days instance
     memory.max_messages             -> world     field inherits section
     memory.chat_retention_days      -> instance  own declaration (rule 2)
     chat.chattiness                 -> world     field inherits section
     skills                          -> mixed     declared mixed; outfit_change
                                                  world, searx mixed
     skills.searx                    -> mixed     plugin subsection without own
                                                  scope = world (E5), but its
                                                  field url is instance
     skills.searx.url                -> instance  own declaration (plugin.yaml)
     skills.searx.enabled            -> world     field inherits the plugin
                                                  subsection's E5 default
     skills.outfit_change.language   -> world     inherits outfit_change: world
     decision.points                 -> instance  unknown key (page-written),
                                                  parent decision: instance
     llm_task_state.disabled_tasks   -> instance  root from EXTRA_ROOTS (read by
                                                  llm_task_state.py; not in the
                                                  schema, kept on instance)
     game_seasons                    -> world     section declaration
     telegram                        -> None      unknown root (rule 1)
     llm_lanes_migrated              -> None      unknown root (rule 1)
   The ``skills.searx*`` rows and ``skills`` itself need the searx package
   loaded (``skills`` is mixed only through searx.url — without it every
   skills subsection is world and the section resolves to world, rule 4);
   when searx is not discoverable those rows are SKIPPED with the reason.

E) ``child_scopes_differ`` on hand cases: memory, image_generation -> True
   (same reasons as in D); server, image_generation.backends,
   chat.chattiness, llm_task_state, an unknown root -> False; skills and
   skills.searx -> True (SKIP without searx). ``scope_of(p) == mixed``
   exactly when ``child_scopes_differ(p)`` — checked for every row of D.

PART 2 — shipped defaults, prune, split by scope
------------------------------------------------

The instance and world files store only what DIFFERS from what ships, and
each value in the file its scope names. ``config_scope.shipped_default``,
``prune`` and ``split_by_scope`` are that rule.

Schema defaults used below, read by hand from ``app/core/config_schema.py``
(check S0 verifies each against the schema, so a changed default fails
loudly instead of silently shifting the expectations):
     server.log_level                 "INFO"
     server.time_format               "24h"    (X = "12h" is a deviation)
     server.api_key                   no default (password field)
     game_calendar.day_bucket_noon    12       (10 is a deviation)
     game_calendar._calendar_note     note field = pseudo, never a default
     tts.xtts.url                     "http://localhost:8020"  (subsection)
     image_generation.enabled         True
     memory.max_messages              100
     skills.searx.url                 "http://localhost:8888"  (plugin.yaml)
     skills.searx.enabled             False                    (plugin.yaml)
List defaults NOT in the schema, and only these three:
     content_marketplace.catalogs  = config._DEFAULT_MARKETPLACE_CATALOGS
     image_generation.backends     = config._default_mesh_backend_entries()
     game_seasons                  = game_time.default_seasons_config()
Use-case seed (what ``config._seed_default_use_cases`` writes per shipped
use case, readers fall back to "" / False for a missing key):
     {"styles": {fam: {"prompt_style": "", "prompt_negative": "",
                       "prompt_instruction": ""} for fam in natural, keywords},
      "llm_compose": False}

S0) The constants above equal the schema; the game_calendar schema defaults
    equal ``game_time.default_calendar_config()`` field by field (the
    calendar is pruned field-wise through the schema — no special case).

S1) shipped_default(path) -> (has, value):
     server.log_level                      (True, "INFO")
     server.api_key                        (False, None)  no default
     server._grp_x                         (False, None)  pseudo name
     game_calendar._calendar_note          (False, None)  note field
     game_calendar.day_bucket_noon         (True, 12)
     tts.xtts.url                          (True, "http://localhost:8020")
     skills.searx.url                      (True, "http://localhost:8888")
     providers                             (False, None)  array, no default
     providers.0.name                      (False, None)  inside a list entry
     game_seasons                          (True, default_seasons_config())
     game_seasons.0                        (False, None)  a list ENTRY, not the list
     content_marketplace.catalogs          (True, the catalog constant)
     image_generation.backends             (True, the mesh seed entries)
     image_generation.use_cases.scene      (True, the seed)
     image_generation.use_cases.my_uc      (False, None)  not a shipped use
                                           case: the seeding never re-adds it,
                                           so dropping it would lose the key
     telegram.x                            (False, None)  unknown root
    and the returned value is a copy: mutating it changes no later answer.

S2) prune(cfg) -> copy, cfg itself unchanged:
     {"server": {"log_level": "INFO", "time_format": "12h"}}
        -> {"server": {"time_format": "12h"}}
     {"server": {"log_level": "INFO", "time_format": "24h"}}      -> {}
     {"content_marketplace": {"catalogs": <copy of the default>}} -> {}
     {"content_marketplace": {"catalogs": []}}                    -> unchanged
                                                   ([] = an explicit deviation)
     {"image_generation": {"backends": <copy of the seed>}}       -> {}
     {"image_generation": {"backends": []}}                       -> unchanged
     {"game_seasons": default_seasons_config()}                   -> {}
     {"game_seasons": <default with the first season renamed>}    -> unchanged
     {"game_calendar": {"day_bucket_noon": 10}}                   -> unchanged
     {"game_calendar": {"day_bucket_noon": 12}}                   -> {}
     {"game_calendar": default_calendar_config()}                 -> {}
     {"providers": [{"name": "a", "type": "openai", "extra": {}, "_x": 1}]}
        -> unchanged (a list is one value; nothing inside an entry is pruned,
           not even its empty dict or its "_" key)
     {"image_generation": {"routing": {}, "use_cases": {"scene": <seed>,
        "prop": <seed with natural.prompt_style "x">}}}
        -> {"image_generation": {"use_cases": {"prop": <that entry, whole>}}}
     {"image_generation": {"use_cases": {"my_uc": <seed>}}}       -> unchanged
     {"image_generation": {"routing": {"scene": []}}}             -> unchanged
                                                   ([] kept at any depth)
     {"image_generation": {"routing": {"_x": ["a"]}}}             -> unchanged
                       (routing is page-written data, not a schema section:
                        a "_" key there is data, not a pseudo field)
     {"image_generation": {"enabled": 1}}                         -> unchanged
                       (1 is not the bool True: a bool default only matches
                        a bool, so pruning cannot change a value's type)
     {"server": {"_grp_x": 1}}                                    -> {}
     {"tts": {"xtts": {"_note": 1, "url": "http://localhost:8020"}}} -> {}
     {"decision": {"points": {}}, "knowledge": {}}                -> {}
     {"skills": {"searx": {"url": "http://localhost:8888", "enabled": True}}}
        -> {"skills": {"searx": {"enabled": True}}}
     {"telegram": {"x": 1}}                                       -> unchanged
     {"telegram": {}}                                             -> {}

S3) split_by_scope on
     {"server": {"log_level": "DEBUG"},
      "chat": {"chattiness": 0.7},
      "image_generation": {"backends": [{"name": "b"}],
                           "use_cases": {"scene": {"llm_compose": True}},
                           "routing": {"scene": ["b"]}},
      "memory": {"max_messages": 5, "chat_retention_days": 9},
      "skills": {"searx": {"url": "u", "enabled": True},
                 "outfit_change": {"language": "de"}},
      "llm_task_state": {"disabled_tasks": ["x"]},
      "game_seasons": [{"id": "s"}],
      "telegram": {}}
    instance (rows of the Part 1 table D: server, image_generation.backends
    and .routing, memory.chat_retention_days, skills.searx.url and
    llm_task_state are instance):
     {"server": {"log_level": "DEBUG"},
      "image_generation": {"backends": [{"name": "b"}],
                           "routing": {"scene": ["b"]}},
      "memory": {"chat_retention_days": 9},
      "skills": {"searx": {"url": "u"}},
      "llm_task_state": {"disabled_tasks": ["x"]}}
    world:
     {"chat": {"chattiness": 0.7},
      "image_generation": {"use_cases": {"scene": {"llm_compose": True}}},
      "memory": {"max_messages": 5},
      "skills": {"searx": {"enabled": True},
                 "outfit_change": {"language": "de"}},
      "game_seasons": [{"id": "s"}]}
    unknown == ["telegram"]. Both parts are copies (mutating them leaves the
    input unchanged). The skills rows need searx (SKIP without it).

S4) PRE-DISCOVERY (runs before ``discover_packages()``, next to Part P):
    ``split_by_scope({"skills": {"searx": {"url": "u", "enabled": True}}})``
    puts url on the instance side and enabled on the world side, and
    ``shipped_default("skills.searx.url") == (True, "http://localhost:8888")``
    — the config load at boot sees the plugin fields before discovery.
"""
import copy
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_TMP = tempfile.mkdtemp(prefix="smoke_cfg_scope_")
os.environ["STORAGE_DIR"] = _TMP

from app.core import paths  # noqa: E402

paths.init(_TMP)

_failures = []
_skips = []
_checks = 0

VALID = ("instance", "world", "mixed")


def check(cond, msg):
    global _checks
    _checks += 1
    if not cond:
        _failures.append(msg)


def skip(msg):
    _skips.append(msg)


# ---------------------------------------------------------------------------
# Endpoint-name matcher (part C)
# ---------------------------------------------------------------------------

def is_endpoint_field(name: str, fdef: dict) -> bool:
    if isinstance(fdef, dict) and fdef.get("type") == "password":
        return True
    return (name == "url" or name.endswith("_url") or name == "api_key"
            or "token" in name or name.startswith("endpoint"))


def self_test():
    yes = ["url", "webhook_url", "api_key", "auth_token", "endpoint", "endpoints_list"]
    no = ["enabled", "engines", "urls_seen", "categories"]
    for n in yes:
        check(is_endpoint_field(n, {"type": "str"}), f"self-test: {n!r} must match")
    for n in no:
        check(not is_endpoint_field(n, {"type": "str"}), f"self-test: {n!r} must not match")
    check(is_endpoint_field("secret", {"type": "password"}),
          "self-test: a password-typed field must match")


# ---------------------------------------------------------------------------
# Part A — declarations present and valid
# ---------------------------------------------------------------------------

def _walk_nodes(node, where, is_field=False):
    """Yield (where, scope, is_field, has_children) for every schema node."""
    yield where, node.get("scope"), is_field, bool(
        node.get("fields") or node.get("sub_arrays") or node.get("subsections"))
    for fname, fdef in (node.get("fields") or {}).items():
        if isinstance(fdef, dict):
            yield from _walk_nodes(fdef, f"{where}.{fname}", is_field=True)
    for kind in ("sub_arrays", "subsections"):
        for cname, cdef in (node.get(kind) or {}).items():
            if isinstance(cdef, dict):
                yield from _walk_nodes(cdef, f"{where}.{cname}")


def part_a(schema):
    for sname, sdef in schema.items():
        if sdef.get("virtual"):
            check("scope" not in sdef, f"A: virtual section {sname} must not declare a scope")
            continue
        check(sdef.get("scope") in VALID,
              f"A: section {sname} has no valid scope (got {sdef.get('scope')!r})")
        for where, scope, is_field, has_children in _walk_nodes(sdef, sname):
            if scope is None:
                continue
            check(scope in VALID, f"A: {where} has invalid scope {scope!r}")
            if scope == "mixed":
                check(not is_field and has_children,
                      f"A: {where} is 'mixed' but is a field / has no children")


# ---------------------------------------------------------------------------
# Part B — the scope table
# ---------------------------------------------------------------------------

TABLE_INSTANCE = ["server", "providers", "llm_retry", "llm_routing", "lanes",
                  "embedding", "decision", "tts", "knowledge",
                  "content_marketplace", "ui", "image_generation"]
TABLE_WORLD = ["chat", "thoughts", "intents", "relationships", "social_reactions",
               "random_events", "npc", "story_engine", "game", "messaging_frame",
               "game_calendar", "game_seasons", "memory"]
TABLE_MIXED = ["skills"]
TABLE_VIRTUAL = ["llm_simple"]


def part_b(schema, has_searx):
    for s in TABLE_INSTANCE:
        check(schema.get(s, {}).get("scope") == "instance", f"B: section {s} must be instance")
    for s in TABLE_WORLD:
        check(schema.get(s, {}).get("scope") == "world", f"B: section {s} must be world")
    for s in TABLE_MIXED:
        check(schema.get(s, {}).get("scope") == "mixed", f"B: section {s} must be mixed")
    known = set(TABLE_INSTANCE + TABLE_WORLD + TABLE_MIXED + TABLE_VIRTUAL)
    for s in schema:
        check(s in known, f"B: section {s} is not in the scope table — classify it")
    mem = schema["memory"]["fields"]["chat_retention_days"]
    check(mem.get("scope") == "instance", "B: memory.chat_retention_days must declare instance")
    uc = schema["image_generation"]["sub_arrays"]["use_cases"]
    check(uc.get("scope") == "world", "B: image_generation.use_cases must declare world")
    oc = schema["skills"]["subsections"]["outfit_change"]
    check(oc.get("scope") == "world", "B: skills.outfit_change must declare world")
    if has_searx:
        url = schema["skills"]["subsections"]["searx"]["fields"]["url"]
        check(url.get("scope") == "instance", "B: skills.searx.url must declare instance")
    else:
        skip("B: skills.searx.url — searx package not discoverable")


# ---------------------------------------------------------------------------
# Part C — endpoint rule over plugin fields
# ---------------------------------------------------------------------------

def part_c():
    from app.plugins.registry import packages
    pkgs = packages()
    check(len(pkgs) > 0, "C: no plugin package discovered — the endpoint rule would be vacuous")
    for pkg in pkgs:
        for sub, sdef in (pkg.config_subsections or {}).items():
            for fname, fdef in ((sdef or {}).get("fields") or {}).items():
                if is_endpoint_field(fname, fdef):
                    where = f"{pkg.id}: skills.{sub}.{fname}"
                    if pkg.dir.is_symlink():
                        where += " (private pack — fix in anima-verse-packs)"
                    check((fdef or {}).get("scope") == "instance",
                          f"C: {where} is an endpoint/key field without scope: instance")


# ---------------------------------------------------------------------------
# Part D/E — scope_of and child_scopes_differ
# ---------------------------------------------------------------------------

HAND_TABLE = [
    ("server.log_level", "instance"),
    ("providers", "instance"),
    ("image_generation", "mixed"),
    ("image_generation.backends", "instance"),
    ("image_generation.routing", "instance"),
    ("image_generation.use_cases", "world"),
    ("image_generation.enabled", "instance"),
    ("memory", "mixed"),
    ("memory.max_messages", "world"),
    ("memory.chat_retention_days", "instance"),
    ("chat.chattiness", "world"),
    ("skills", "mixed"),
    ("skills.searx", "mixed"),
    ("skills.searx.url", "instance"),
    ("skills.searx.enabled", "world"),
    ("skills.outfit_change.language", "world"),
    ("decision.points", "instance"),
    ("llm_task_state.disabled_tasks", "instance"),
    ("game_seasons", "world"),
    ("telegram", None),
    ("llm_lanes_migrated", None),
]

DIFFER_TABLE = [
    ("memory", True),
    ("image_generation", True),
    ("skills", True),
    ("skills.searx", True),
    ("server", False),
    ("image_generation.backends", False),
    ("chat.chattiness", False),
    ("llm_task_state", False),
    ("telegram", False),
]


def _needs_searx(path):
    # ``skills`` is only mixed BECAUSE of searx.url: without the package every
    # skills subsection is world and the section resolves to world (rule 4).
    return path == "skills" or path.startswith("skills.searx")


def part_d_e(cs, has_searx):
    check(cs.INSTANCE == "instance" and cs.WORLD == "world" and cs.MIXED == "mixed",
          "D: INSTANCE/WORLD/MIXED constants")
    check(cs.EXTRA_ROOTS == {"llm_task_state": cs.INSTANCE},
          f"D: EXTRA_ROOTS must be {{'llm_task_state': 'instance'}}, got {cs.EXTRA_ROOTS!r}")
    for path, want in HAND_TABLE:
        if _needs_searx(path) and not has_searx:
            skip(f"D: scope_of({path!r}) — searx package not discoverable")
            continue
        got = cs.scope_of(path)
        check(got == want, f"D: scope_of({path!r}) = {got!r}, expected {want!r}")
        check((got == cs.MIXED) == cs.child_scopes_differ(path),
              f"D: scope_of({path!r}) == mixed must equal child_scopes_differ")
    for path, want in DIFFER_TABLE:
        if _needs_searx(path) and not has_searx:
            skip(f"E: child_scopes_differ({path!r}) — searx package not discoverable")
            continue
        got = cs.child_scopes_differ(path)
        check(got is want, f"E: child_scopes_differ({path!r}) = {got!r}, expected {want!r}")


def _plugin_modules():
    return {m for m in sys.modules
            if m.startswith("plugins.") or m.startswith("plugins_onload_")}


def part_p_before_discovery():
    """Part P, first half — runs before discover_packages()."""
    from app.plugins import loader, registry
    from app.core import config_scope as cs
    check(loader.is_discovered() is False, "P: is_discovered() must be False before discovery")
    check(registry.packages() == [], "P: registry must be empty before discovery")
    before = _plugin_modules()
    subs = loader.manifest_config_schemas()
    new_mods = _plugin_modules() - before
    check(not new_mods, f"P: the manifest scan imported package code: {sorted(new_mods)}")
    check(registry.packages() == [], "P: the manifest scan must not touch the registry")
    check(isinstance(subs, dict) and subs, "P: manifest_config_schemas() returned nothing")
    if "searx" not in subs:
        skip("P: skills.searx before discovery — searx not among the manifests")
        return False
    for path, want in (("skills.searx.url", "instance"), ("skills.searx", "mixed"),
                       ("skills.searx.enabled", "world")):
        got = cs.scope_of(path)
        check(got == want, f"P: before discovery scope_of({path!r}) = {got!r}, expected {want!r}")
    check(_plugin_modules() - before == set(),
          "P: scope_of before discovery imported package code")
    check(loader.is_discovered() is False, "P: scope_of must not trigger discovery")
    return True


def part_p_after_discovery(had_searx):
    """Part P, second half — after discover_packages()."""
    from pathlib import Path as _P
    from app.plugins import loader, registry
    from app.plugins.registry import Package
    from app.core import config_scope as cs
    check(loader.is_discovered() is True, "P: is_discovered() must be True after discovery")
    if had_searx:
        check(cs.scope_of("skills.searx.url") == "instance",
              "P: after discovery scope_of('skills.searx.url') must stay instance")
        check(cs.scope_of("skills.searx") == "mixed",
              "P: after discovery scope_of('skills.searx') must stay mixed")
    probe = Package(id="zz_probe", dir=_P(_TMP), manifest={"name": "zz_probe"},
                    config_subsections={"zz_probe": {
                        "label": "probe",
                        "fields": {"a": {"type": "str", "scope": "instance", "default": ""}}}})
    registry.register_package(probe)
    try:
        got = cs.scope_of("skills.zz_probe.a")
        check(got == "instance", f"P: registered probe: scope_of('skills.zz_probe.a') = {got!r}, "
                                 "expected 'instance' (view not rebuilt?)")
    finally:
        registry.unregister_package("zz_probe")
    got = cs.scope_of("skills.zz_probe.a")
    check(got == "world", f"P: unregistered probe: scope_of('skills.zz_probe.a') = {got!r}, "
                          "expected 'world'")


# ---------------------------------------------------------------------------
# Part 2 — shipped defaults, prune, split by scope
# ---------------------------------------------------------------------------

SCHEMA_DEFAULTS = [
    (("server", "log_level"), "INFO"),
    (("server", "time_format"), "24h"),
    (("game_calendar", "day_bucket_noon"), 12),
    (("tts", "xtts", "url"), "http://localhost:8020"),
    (("image_generation", "enabled"), True),
    (("memory", "max_messages"), 100),
]
SEARX_DEFAULTS = [
    (("skills", "searx", "url"), "http://localhost:8888"),
    (("skills", "searx", "enabled"), False),
]
FAMILIES = ("natural", "keywords")


def _seed():
    return {"styles": {fam: {"prompt_style": "", "prompt_negative": "",
                             "prompt_instruction": ""} for fam in FAMILIES},
            "llm_compose": False}


def _has_api(cs, *names):
    missing = [n for n in names if not hasattr(cs, n)]
    check(not missing, f"2: config_scope lacks {missing}")
    return not missing


def part_2_before_discovery():
    """S4 — runs before discover_packages()."""
    from app.core import config_scope as cs
    if not _has_api(cs, "split_by_scope", "shipped_default"):
        return
    from app.plugins import loader
    if "searx" not in loader.manifest_config_schemas():
        skip("S4: searx not among the manifests")
        return
    inst, world, unknown = cs.split_by_scope(
        {"skills": {"searx": {"url": "u", "enabled": True}}})
    check(inst == {"skills": {"searx": {"url": "u"}}},
          f"S4: pre-discovery instance part = {inst!r}")
    check(world == {"skills": {"searx": {"enabled": True}}},
          f"S4: pre-discovery world part = {world!r}")
    check(unknown == [], f"S4: pre-discovery unknown = {unknown!r}")
    got = cs.shipped_default("skills.searx.url")
    check(got == (True, "http://localhost:8888"),
          f"S4: pre-discovery shipped_default('skills.searx.url') = {got!r}")
    check(loader.is_discovered() is False, "S4: split/default must not trigger discovery")


def part_2(cs, has_searx):
    if not _has_api(cs, "shipped_default", "prune", "split_by_scope"):
        return
    from app.core import config as cfgmod
    from app.core.config_schema import field_default
    from app.core.game_time import default_calendar_config, default_seasons_config

    # S0 — the docstring constants are the schema's
    for keys, want in SCHEMA_DEFAULTS + (SEARX_DEFAULTS if has_searx else []):
        try:
            got = field_default(*keys)
        except KeyError:
            got = "<no default>"
        check(got == want, f"S0: schema default {'.'.join(keys)} = {got!r}, docstring says {want!r}")
    try:
        field_default("server", "api_key")
        check(False, "S0: server.api_key must have no schema default")
    except KeyError:
        pass
    cal_schema = {}
    from app.core.config_schema import SECTIONS
    for name, fdef in SECTIONS["game_calendar"]["fields"].items():
        try:
            cal_schema[name] = field_default("game_calendar", name)
        except KeyError:
            pass
    check(cal_schema == default_calendar_config(),
          f"S0: game_calendar schema defaults {cal_schema!r} != default_calendar_config() "
          f"{default_calendar_config()!r}")
    check(list(cfgmod._PROMPT_STYLE_FAMILIES) == list(FAMILIES),
          f"S0: prompt style families {cfgmod._PROMPT_STYLE_FAMILIES!r}")

    # S1 — shipped_default
    sd = cs.shipped_default
    rows = [
        ("server.log_level", (True, "INFO")),
        ("server.api_key", (False, None)),
        ("server._grp_x", (False, None)),
        ("game_calendar._calendar_note", (False, None)),
        ("game_calendar.day_bucket_noon", (True, 12)),
        ("tts.xtts.url", (True, "http://localhost:8020")),
        ("providers", (False, None)),
        ("providers.0.name", (False, None)),
        ("game_seasons", (True, default_seasons_config())),
        ("game_seasons.0", (False, None)),
        ("content_marketplace.catalogs", (True, cfgmod._DEFAULT_MARKETPLACE_CATALOGS)),
        ("image_generation.backends", (True, cfgmod._default_mesh_backend_entries())),
        ("image_generation.use_cases.scene", (True, _seed())),
        ("image_generation.use_cases.my_uc", (False, None)),
        ("telegram.x", (False, None)),
    ]
    if has_searx:
        rows.append(("skills.searx.url", (True, "http://localhost:8888")))
    else:
        skip("S1: skills.searx.url — searx package not discoverable")
    for path, want in rows:
        got = sd(path)
        check(got == want, f"S1: shipped_default({path!r}) = {got!r:.120}, expected {want!r:.120}")
    has, val = sd("content_marketplace.catalogs")
    val.append({"name": "mutated"})
    check(sd("content_marketplace.catalogs")[1] == cfgmod._DEFAULT_MARKETPLACE_CATALOGS,
          "S1: shipped_default must return a copy")

    # S2 — prune
    seasons_changed = default_seasons_config()
    seasons_changed[0]["name"] = "Renamed"
    prop = _seed()
    prop["styles"]["natural"]["prompt_style"] = "x"
    cases = [
        ({"server": {"log_level": "INFO", "time_format": "12h"}},
         {"server": {"time_format": "12h"}}),
        ({"server": {"log_level": "INFO", "time_format": "24h"}}, {}),
        ({"content_marketplace": {"catalogs": copy.deepcopy(cfgmod._DEFAULT_MARKETPLACE_CATALOGS)}}, {}),
        ({"content_marketplace": {"catalogs": []}}, None),
        ({"image_generation": {"backends": cfgmod._default_mesh_backend_entries()}}, {}),
        ({"image_generation": {"backends": []}}, None),
        ({"game_seasons": default_seasons_config()}, {}),
        ({"game_seasons": seasons_changed}, None),
        ({"game_calendar": {"day_bucket_noon": 10}}, None),
        ({"game_calendar": {"day_bucket_noon": 12}}, {}),
        ({"game_calendar": default_calendar_config()}, {}),
        ({"providers": [{"name": "a", "type": "openai", "extra": {}, "_x": 1}]}, None),
        ({"image_generation": {"routing": {}, "use_cases": {"scene": _seed(), "prop": prop}}},
         {"image_generation": {"use_cases": {"prop": prop}}}),
        ({"image_generation": {"use_cases": {"my_uc": _seed()}}}, None),
        ({"image_generation": {"routing": {"scene": []}}}, None),
        ({"image_generation": {"routing": {"_x": ["a"]}}}, None),
        ({"image_generation": {"enabled": 1}}, None),
        ({"server": {"_grp_x": 1}}, {}),
        ({"tts": {"xtts": {"_note": 1, "url": "http://localhost:8020"}}}, {}),
        ({"decision": {"points": {}}, "knowledge": {}}, {}),
        ({"telegram": {"x": 1}}, None),
        ({"telegram": {}}, {}),
    ]
    if has_searx:
        cases.append(({"skills": {"searx": {"url": "http://localhost:8888", "enabled": True}}},
                      {"skills": {"searx": {"enabled": True}}}))
    for cfg, want in cases:
        if want is None:
            want = copy.deepcopy(cfg)
        before = copy.deepcopy(cfg)
        got = cs.prune(cfg)
        check(got == want and type(got) is dict,
              f"S2: prune({cfg!r:.160}) = {got!r:.160}, expected {want!r:.160}")
        check(cfg == before, f"S2: prune mutated its input {before!r:.120}")
    got = cs.prune({"image_generation": {"enabled": 1}})
    check(type(got.get("image_generation", {}).get("enabled")) is int,
          "S2: the int 1 must survive as int, not be matched against the bool default")

    # S3 — split_by_scope
    src = {
        "server": {"log_level": "DEBUG"},
        "chat": {"chattiness": 0.7},
        "image_generation": {"backends": [{"name": "b"}],
                             "use_cases": {"scene": {"llm_compose": True}},
                             "routing": {"scene": ["b"]}},
        "memory": {"max_messages": 5, "chat_retention_days": 9},
        "llm_task_state": {"disabled_tasks": ["x"]},
        "game_seasons": [{"id": "s"}],
        "telegram": {},
    }
    want_inst = {
        "server": {"log_level": "DEBUG"},
        "image_generation": {"backends": [{"name": "b"}], "routing": {"scene": ["b"]}},
        "memory": {"chat_retention_days": 9},
        "llm_task_state": {"disabled_tasks": ["x"]},
    }
    want_world = {
        "chat": {"chattiness": 0.7},
        "image_generation": {"use_cases": {"scene": {"llm_compose": True}}},
        "memory": {"max_messages": 5},
        "game_seasons": [{"id": "s"}],
    }
    if has_searx:
        src["skills"] = {"searx": {"url": "u", "enabled": True},
                         "outfit_change": {"language": "de"}}
        want_inst["skills"] = {"searx": {"url": "u"}}
        want_world["skills"] = {"searx": {"enabled": True}, "outfit_change": {"language": "de"}}
    else:
        skip("S3: skills rows of split_by_scope — searx package not discoverable")
    before = copy.deepcopy(src)
    inst, world, unknown = cs.split_by_scope(src)
    check(inst == want_inst, f"S3: instance part = {inst!r}")
    check(world == want_world, f"S3: world part = {world!r}")
    check(unknown == ["telegram"], f"S3: unknown roots = {unknown!r}")
    inst["image_generation"]["backends"].append({"name": "mutated"})
    world["memory"]["max_messages"] = 99
    check(src == before, "S3: split_by_scope must return copies (input changed)")


def main():
    had_searx = part_p_before_discovery()
    part_2_before_discovery()
    from app.plugins.loader import discover_packages
    discover_packages()
    part_p_after_discovery(had_searx)
    from app.core.config_schema import get_schema
    schema = get_schema()
    has_searx = "searx" in (schema.get("skills", {}).get("subsections") or {})

    self_test()
    part_a(schema)
    part_b(schema, has_searx)
    part_c()
    try:
        from app.core import config_scope as cs
    except ImportError as e:
        check(False, f"D: app.core.config_scope not importable: {e}")
    else:
        part_d_e(cs, has_searx)
        part_2(cs, has_searx)

    print()
    for s in _skips:
        print(f"SKIP {s}")
    if _failures:
        print(f"FAILED {len(_failures)} of {_checks} checks:")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"OK — {_checks} checks passed, {len(_skips)} skipped")


if __name__ == "__main__":
    main()
