#!/usr/bin/env python3
"""Smoke: every config section and field has a scope (instance / world).

Usage:  ./.venv/bin/python scripts/smoke_config_scope.py

No server, no world DB. The storage root is a throwaway temp dir (set before
any app import); two bundled public packages are explicitly enabled for the
runtime schema checks. Installed manifest inventory supplies dormant settings'
scope ownership too. Nothing under ``worlds/`` or ``instance/`` is read or
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
   world settings. Covers every inventoried package, whether or not enabled
   in the temporary world.

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
     providers                             (True, _DEFAULT_PROVIDERS)  E11 example seed
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

PART 3 — the two config layers: config.load / save / migrate_file
-----------------------------------------------------------------

``config.load(world, instance)`` reads each layer (file + the secrets.json
of THE SAME layer), keeps only the part whose scope that layer owns, joins
the two, runs the load-time migrations once and keeps the result in memory.
``save`` and ``migrate_file`` split by scope, prune, split out the secrets
and write a file only when its JSON content differs from what is on disk.
Every case runs in its own ``tempfile.TemporaryDirectory()``: ``<tmp>/w`` is
the world directory, ``<tmp>/i`` the instance directory, each with a
``config.json``. "Unchanged" is measured by mtime: before the step, every
file's mtime is set to a fixed old value (``os.utime``) — any write moves it
to now, however fast the step runs.

Expectations by hand from the scope table (Part 1 D) and the shipped
defaults (Part 2):

6.1 UNION. World ``{"chat": {"chattiness": 0.3}, "providers": [{"name": "w"}]}``,
    instance ``{"providers": [{"name": "i"}], "server": {"log_level": "DEBUG"}}``.
    providers is instance, so the world's copy is a foreign key and ignored:
    ``providers[0].name == "i"``, ``chat.chattiness == 0.3`` (world),
    ``server.log_level == "DEBUG"`` (instance).
6.2 SAVE SPLITS. ``save(get_all())``: the world file has no ``providers``,
    the instance file no ``chat``; the world file is exactly
    ``{"chat": {"chattiness": 0.3}}`` and the instance file exactly the two
    instance keys — every seeded block (use cases, catalogs, mesh backends,
    the routing dict, the calendar) equals its shipped default and is pruned.
6.3 IDEMPOTENT. A second ``save(get_all())`` and then ``migrate_file`` leave
    both mtimes unchanged; ``migrate_file`` returns False. Counter-check (the
    handover finding): ``_apply_file_migrations`` over a fresh read of the
    same two files DOES report a change — ``routing: {}`` is pruned on disk
    and re-seeded on every load — so the "no write" above comes from the
    content comparison, not from the migration flag.
6.4 START GUARD. ``check_instance_ready``: world
    ``{"providers": [{"name": "x", "api_base": "u"}]}`` without an instance
    file raises ``InstanceConfigMissing`` whose message names
    ``scripts/migrate_instance_config.py --from "<world dir name>"``. A world
    with only ``chat`` does not raise; a world with
    ``server.log_level = "INFO"`` (= the schema default -> pruned to nothing)
    does not raise; a missing world file never raises. An EXISTING instance
    file blocks the same way when it prunes to nothing: the providers world
    with instance ``{}`` raises (message "holds no settings") — a half-run
    migration or a world restored from a backup would otherwise lose those
    providers on the next save. An instance with a setting of its own
    (``server.log_level = "DEBUG"`` ≠ the default "INFO") does not raise, and
    instance ``{}`` with a chat-only world does not raise either (nothing to
    lose — the fresh-clone state after the migration).
6.5 NO INSTANCE. ``paths.instance_initialised()`` is False in this script.
    ``load(w)`` with the world of 6.1 seeds ``_DEFAULT_PROVIDERS`` (E11);
    the world's providers are foreign. ``save`` with ``server.log_level`` changed
    raises ``RuntimeError`` and writes nothing. ``save`` with only
    ``chat.chattiness`` changed to 0.7 writes the world (0.7 on disk) and
    creates no other file. (Not 0.5: that is the schema default and would be
    pruned to an empty world file.)
6.6 SECRETS PER LAYER. Instance config ``{"providers": [{"name": "i"}]}`` +
    instance secrets ``{"providers": [{"api_key": "k"}]}``:
    ``get("providers")[0]["api_key"] == "k"``; after ``save`` "k" is in
    ``i/secrets.json`` and not in ``i/config.json``. A world secrets.json
    ``{"providers": [{"api_key": "WELT"}]}``: "WELT" is nowhere in
    ``get("providers")``; after ``save`` ``w/secrets.json`` is gone.
6.7 SEEDS. Instance ``{}``: ``content_marketplace.catalogs`` equals
    ``config._DEFAULT_MARKETPLACE_CATALOGS``, ``image_generation.backends``
    has 13 entries (12 in ``_DEFAULT_MESH_BACKENDS`` + 1 shrink alias). After
    ``migrate_file`` the instance file is still ``{}`` with the old mtime.
    Counter-check: an instance with ``image_generation.backends: []`` keeps
    the empty list (the seed hangs on a MISSING key only).
6.8 RELOAD. ``load(w, i)``, then ``reload()``:
    ``get("server.log_level") == "DEBUG"`` — the instance path is remembered.
6.9 ADMIN PAYLOAD. The settled 6.1 pair; the effective config goes through
    ``config_admin.apply_schema_defaults`` (a copy — what
    ``/settings/raw`` hands out), then ``merge_sensitive(payload,
    get_all())`` (what ``/settings/save`` does), then ``save``: the world
    file keeps its mtime. Every bool/select default the payload materialised
    into a world section equals its shipped default and is pruned.
6.10 FRESH STATE. Empty directories: ``check_instance_ready`` does not
    raise, ``migrate_file`` creates both files as ``{}`` and returns True, a
    second ``migrate_file`` returns False and writes nothing.
6.11 CORRUPT LAYER FILE (review fix round 1). The instance config.json
    holds real providers but has a syntax error (trailing comma). A
    non-strict ``load`` logs it and reads that layer as empty —
    E11 seeds ``_DEFAULT_PROVIDERS`` — then ``save(get_all())`` raises
    ``RuntimeError`` ("refusing to overwrite unreadable") and leaves BOTH
    files byte-identical (the world is checked before anything is written,
    so a refusal never leaves one layer rewritten). ``migrate_file`` returns
    False and writes nothing; ``load(..., strict=True)`` (the server boot)
    raises ``ValueError``; ``check_instance_ready`` raises too (strict read).
    The same for a corrupt WORLD secrets.json: a save that would delete it
    (no world secrets left) raises instead, and the file stays.

PART 4 — secrets and unsent fields keyed by entry NAME, not list position
-------------------------------------------------------------------------

A NAMED LIST is a list whose entries are ALL dicts with a non-empty, unique
``name`` (``providers``, ``image_generation.backends``, ``decision.endpoints``,
``content_marketplace.catalogs``). ``config.named_entries(lst)`` is the one
detector: ``{name: entry}`` for a named list, else None. In ``secrets.json`` a
named list is a dict by name; every other list stays by index. The admin save
(``merge_sensitive`` / ``_preserve_unsent_subarray_fields``) pairs the
entries of two named lists by name; a RENAME (payload[i] has a name current
does not know AND current[i] has a name the payload does not know) pairs by
index; otherwise an entry has no counterpart. Symptom of the old index rule:
inserting a backend mid-list shifted every key after it (401 on an unrelated
backend). Expectations by hand:

8.0 DETECTOR. ``named_entries`` of ``[{"name":"a"},{"name":"b"}]`` has the
    keys a, b; ``[]`` -> ``{}``; None for a duplicate name, an empty name, a
    missing name, a non-dict entry.
8.1 INSERT, SAVE, RELOAD. Instance ``image_generation.backends`` =
    ``[a, b, c]`` (``{"name": ...}`` each) + an INDEX-format instance
    secrets.json ``{"image_generation": {"backends": [{}, {"api_key": "KB"},
    {"api_key": "KC"}]}}`` (the old format is still read): after ``load``
    b has "KB", c has "KC", a none. ``x`` is inserted at position 1 and saved:
    ``i/secrets.json`` is exactly ``{"image_generation": {"backends":
    {"b": {"api_key": "KB"}, "c": {"api_key": "KC"}}}}``, neither key is in
    ``i/config.json``. ``load`` again: a, x without a key, b "KB", c "KC".
    Then a SECOND insert directly in ``i/config.json`` (``y`` at position 0,
    secrets.json untouched) and ``load``: still b "KB", c "KC", y none — the
    by-name file does not depend on the position (the old index file
    would hand y the key of a, a that of x, ...).
8.2 UNKNOWN NAME. A by-name secret for ``zz`` (no such backend) is ignored:
    the backend list keeps its 4 names and "ZZ" is nowhere in it.
8.3 MASKED KEY AT A NEW POSITION. current backends ``[a, b(KB), c(KC)]``,
    payload ``[a, x, b("***"), c("***")]``: ``merge_sensitive`` gives
    b "KB", c "KC" (old code: b got KC, c nothing), x keeps no api_key.
8.4 UNSENT FIELD. current ``[a, b(category "img2img"), c]``, payload
    ``[a, x, b, c]`` without any category: ``_preserve_unsent_subarray_fields``
    gives b "img2img" (its own field back) and x NO category (old code: x
    inherited b's, b inherited c's absence).
8.5 RENAME. current ``[a, b, c(KC, category "inpaint")]``, payload
    ``[a, b, c2("***")]`` without category: ``merge_sensitive`` keeps "KC" on
    c2 and ``_preserve_unsent_subarray_fields`` carries "inpaint" to c2.
8.6 UNNAMED LIST STAYS BY INDEX. ``_split_secrets({"l": [{"api_key": "k0"},
    {"x": 1}]})`` -> secrets ``{"l": [{"api_key": "k0"}, {}]}``; the same with
    a duplicate name (``[{"name":"d","api_key":"k"},{"name":"d"}]``) -> a
    list, not a dict. ``merge_sensitive`` over an unnamed list pairs index
    1 with index 1 (``[{}, {"api_key": "***"}]`` against ``[{}, {"api_key":
    "K1"}]`` -> "K1"). ``_deep_merge`` of a list overlay stays by index.

Review fix round 1 — the secrets overlay knows the shape ``_split_secrets``
writes: a key MISSING from config.json is set only when it is a sensitive
string; any other value without a counterpart (a by-name dict, a list) is
dropped with one warning naming the secrets.json. Expectations by hand:

8.7 NO LIST IN config.json. Instance ``{"server": {"log_level": "DEBUG"}}``
    + secrets ``{"providers": {"p": {"api_key": "KP"}}}``: ``load`` and
    ``load(strict=True)`` raise nothing; E11 seeds ``_DEFAULT_PROVIDERS``. A
    warning names ``i/secrets.json`` and ``providers``.
8.8 CORRUPT config.json + by-name secrets. Instance config.json with a
    syntax error + the secrets of 8.7: a non-strict ``load`` raises nothing
    and reads the layer as empty: E11 seeds ``_DEFAULT_PROVIDERS`` and
    ``get("server.log_level")`` is not "DEBUG".
8.9 PARTLY NAMED BASE. Instance backends ``[{"name": "a"}, {"name": ""}]``
    (not a named list: one empty name) + secrets ``{"image_generation":
    {"backends": {"a": {"api_key": "KA"}}}}``: a still gets "KA" (its name is
    unique and non-empty), and ONE warning names ``i/secrets.json`` and says
    the list has entries without a unique name. The next ``save`` writes the
    list in the index format (``[{"api_key": "KA"}, {}]``) — the key is kept.
8.10 MASK WITHOUT PARTNER. current ``[a, b(KB), c(KC)]``, payload
    ``[a, c("***"), b2("***")]`` (rename b -> b2 plus a reorder in one save):
    c gets "KC"; b2 has no partner (its index 2 holds c, which the payload
    knows) and its ``"***"`` becomes ``""`` — a mask is never persisted
    literally.

PART 5 — final review fixes (guard command, season flag, one warning per file)
-----------------------------------------------------------------------------

9.1 GUARD COMMAND (M1). World ``<tmp>/w/config.json`` with providers,
    instance ``<tmp>/i/config.json`` missing: the message holds
    ``--from "w" --instance "<tmp>/i" --worlds-dir "<tmp>"`` (the world's
    grandparent ``<tmp>`` is not ``<repo>/worlds``, so --worlds-dir is
    named). For a world path ``<repo>/worlds/demo/config.json``
    ``_migration_command`` names ``--from "demo"`` and ``--instance`` but
    NOT ``--worlds-dir`` (the tool's default). Pure path arithmetic — no
    file under ``<repo>`` is read.
9.2 SEASON FLAG (M2). World ``{"game_seasons": default_seasons_config()}``
    (the shipped list, written out): ``load(w, i)`` sees a list ->
    ``game_seasons_are_defaults()`` is False. ``migrate_file(w, i)`` prunes
    the default-equal list from the file (returns True, the file has no
    ``game_seasons``) and the flag follows the disk: True — the same value
    ``save()`` sets and the next ``load()`` would read. Counter-check: a
    ``migrate_file`` of ANOTHER world (not the loaded one) with the same list
    leaves the flag alone (set it False first, it stays False).
9.3 ONE WARNING PER FILE (M8). World with seven instance roots in this
    order — providers, server, embedding, decision, content_marketplace,
    tts, llm_routing — plus chat: ``load(w, i)`` logs exactly ONE warning
    about foreign keys for the world file, reading
    ``7 key(s) belong to the instance config and are ignored (providers,
    server, embedding, decision, content_marketplace and 2 more)`` (limit 5)
    and naming ``scripts/migrate_instance_config.py``; at DEBUG the seven
    single keys are logged, one record each. An instance file with a world
    key (``chat``) gets one warning ``1 key(s) belong to the world config``
    that says the next save drops it (the migration script is no remedy
    there).

KNOWN LIMIT. Pairing by name needs BOTH lists to be named lists. A payload
entry without a name (or two entries with the same name) makes the whole list
fall back to index pairing — including the neighbour inheritance in
``_preserve_unsent_subarray_fields`` that the name pairing prevents. The next
save after the entry got its name pairs and writes by name again.
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
TABLE_WORLD = ["extension_motion", "chat", "thoughts", "intents", "relationships", "social_reactions",
               "random_events", "npc", "story_engine", "game", "messaging_frame",
               "game_calendar", "game_seasons", "memory", "packages"]
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
    from app.plugins.loader import manifest_config_schemas
    schemas = manifest_config_schemas()
    check(bool(schemas), "C: no package schema inventoried — the endpoint rule would be vacuous")
    for subsection, sdef in schemas.items():
        for fname, fdef in ((sdef or {}).get("fields") or {}).items():
            if is_endpoint_field(fname, fdef):
                where = f"skills.{subsection}.{fname}"
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
    ("packages.enabled", "world"),
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
        ("providers", (True, cfgmod._DEFAULT_PROVIDERS)),
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


# ---------------------------------------------------------------------------
# Part 3 — the two config layers
# ---------------------------------------------------------------------------

_OLD_NS = 1_000_000_000  # 1970-01-01T00:00:01 — any write moves past it


def _write(path, data):
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _read(path):
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def _age(*files):
    """Set every existing file's mtime to the fixed old value."""
    for f in files:
        if f.exists():
            os.utime(f, ns=(_OLD_NS, _OLD_NS))


def _untouched(f):
    return f.exists() and f.stat().st_mtime_ns == _OLD_NS


def _layers(tmp):
    w = Path(tmp) / "w" / "config.json"
    i = Path(tmp) / "i" / "config.json"
    w.parent.mkdir(parents=True, exist_ok=True)
    i.parent.mkdir(parents=True, exist_ok=True)
    return w, i


WORLD_61 = {"chat": {"chattiness": 0.3}, "providers": [{"name": "w"}]}
INSTANCE_61 = {"providers": [{"name": "i"}], "server": {"log_level": "DEBUG"}}


def part_3():
    from app.core import config as cfg
    missing = [n for n in ("check_instance_ready", "InstanceConfigMissing", "migrate_file")
               if not hasattr(cfg, n)]
    if missing:
        check(False, f"3: app.core.config lacks {missing}")
        return
    from app.core import paths as p
    check(not p.instance_initialised(),
          "3: precondition — this script never initialises an instance directory")

    # 6.1 / 6.2 / 6.3 / 6.8 / 6.9 on one settled pair
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        _write(w, WORLD_61)
        _write(i, INSTANCE_61)
        try:
            cfg.load(w, i)
        except TypeError as e:
            check(False, f"6.1: load(world, instance) not supported: {e}")
            return
        check(cfg.get("providers.0.name") == "i",
              f"6.1: providers come from the instance (got {cfg.get('providers')!r})")
        check(cfg.get("chat.chattiness") == 0.3, "6.1: chat.chattiness 0.3 from the world")
        check(cfg.get("server.log_level") == "DEBUG", "6.1: server.log_level DEBUG from the instance")

        cfg.save(cfg.get_all())
        wd, idd = _read(w), _read(i)
        check("providers" not in wd, f"6.2: world file has no providers ({wd!r:.120})")
        check("chat" not in idd, f"6.2: instance file has no chat ({idd!r:.120})")
        check(wd == {"chat": {"chattiness": 0.3}}, f"6.2: world file = {wd!r:.200}")
        check(idd == INSTANCE_61, f"6.2: instance file = {idd!r:.200}")

        _age(w, i)
        cfg.save(cfg.get_all())
        check(_untouched(w) and _untouched(i), "6.3: a second save writes neither file")
        wrote = cfg.migrate_file(w, i)
        check(wrote is False, f"6.3: migrate_file on the settled pair returns False (got {wrote!r})")
        check(_untouched(w) and _untouched(i), "6.3: migrate_file writes neither file")
        union = _read(i)
        union.update(_read(w))
        check(cfg._apply_file_migrations(union) is True,
              "6.3: counter-check — the migrations DO report a change on the settled "
              "files (routing {} re-seeded), so the no-write is the content comparison")

        cfg.load(w, i)
        cfg.reload()
        check(cfg.get("server.log_level") == "DEBUG",
              f"6.8: reload keeps the instance (log_level {cfg.get('server.log_level')!r})")
        check(cfg.get("providers.0.name") == "i", "6.8: reload keeps the instance providers")

        from app.core import config_admin
        from app.core.config_schema import get_schema
        payload = copy.deepcopy(cfg.get_all())
        config_admin.apply_schema_defaults(payload, get_schema())
        merged = config_admin.merge_sensitive(payload, cfg.get_all())
        _age(w, i)
        cfg.save(merged)
        check(_untouched(w), f"6.9: the admin payload leaves the world file alone "
                             f"(now {_read(w)!r:.300})")

    # 6.4 start guard
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        _write(w, {"providers": [{"name": "x", "api_base": "u"}]})
        try:
            cfg.check_instance_ready(w, i)
            check(False, "6.4: a world with providers and no instance file must raise")
        except cfg.InstanceConfigMissing as e:
            msg = str(e)
            check("scripts/migrate_instance_config.py" in msg and '--from "w"' in msg,
                  f"6.4: the message names the migration command for world 'w' ({msg!r:.200})")
        for label, data in (("only chat", {"chat": {"chattiness": 0.3}}),
                            ("server.log_level at its default", {"server": {"log_level": "INFO"}})):
            _write(w, data)
            try:
                cfg.check_instance_ready(w, i)
            except cfg.InstanceConfigMissing as e:
                check(False, f"6.4: {label} must not raise ({e})")
        _write(w, {"providers": [{"name": "x"}]})
        _write(i, {})
        try:
            cfg.check_instance_ready(w, i)
            check(False, "6.4: an instance that prunes to nothing must block like a missing one")
        except cfg.InstanceConfigMissing as e:
            check("holds no settings" in str(e), f"6.4: message says the instance is empty ({e})")
        _write(i, {"server": {"log_level": "DEBUG"}})
        try:
            cfg.check_instance_ready(w, i)
        except cfg.InstanceConfigMissing as e:
            check(False, f"6.4: an instance with own settings must not raise ({e})")
        _write(w, {"chat": {"chattiness": 0.3}})
        _write(i, {})
        try:
            cfg.check_instance_ready(w, i)
        except cfg.InstanceConfigMissing as e:
            check(False, f"6.4: instance {{}} with a chat-only world must not raise ({e})")
        w.unlink()
        i.unlink()
        try:
            cfg.check_instance_ready(w, i)
        except cfg.InstanceConfigMissing as e:
            check(False, f"6.4: a missing world file must not raise ({e})")

    # 6.5 no instance
    with tempfile.TemporaryDirectory() as tmp:
        w, _i = _layers(tmp)
        _write(w, WORLD_61)
        cfg.load(w)
        check(cfg.get("providers") == cfg._DEFAULT_PROVIDERS,
              f"6.5: without an instance E11 seeds example providers (got {cfg.get('providers')!r})")
        data = copy.deepcopy(cfg.get_all())
        data.setdefault("server", {})["log_level"] = "DEBUG"
        _age(w)
        try:
            cfg.save(data)
            check(False, "6.5: saving an instance value without an instance path must raise")
        except RuntimeError as e:
            check("no instance path" in str(e), f"6.5: RuntimeError names the cause ({e})")
        check(_untouched(w), "6.5: the refused save wrote nothing")
        data = copy.deepcopy(cfg.get_all())
        data["chat"]["chattiness"] = 0.7
        cfg.save(data)
        check(_read(w) == {"chat": {"chattiness": 0.7}}, f"6.5: world written ({_read(w)!r:.200})")
        files = sorted(str(f.relative_to(tmp)) for f in Path(tmp).rglob("*") if f.is_file())
        check(files == ["w/config.json"], f"6.5: no other file created ({files})")

    # 6.6 secrets per layer
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        _write(w, {"chat": {"chattiness": 0.3}})
        _write(w.parent / "secrets.json", {"providers": [{"api_key": "WELT"}]})
        _write(i, {"providers": [{"name": "i", "api_key": ""}]})
        _write(i.parent / "secrets.json", {"providers": [{"api_key": "k"}]})
        cfg.load(w, i)
        check(cfg.get("providers.0.api_key") == "k",
              f"6.6: the instance secret is overlaid (got {cfg.get('providers')!r})")
        check("WELT" not in repr(cfg.get("providers")),
              "6.6: the world secrets.json smuggles no instance value in")
        cfg.save(cfg.get_all())
        isec = (i.parent / "secrets.json").read_text(encoding="utf-8")
        check('"k"' in isec, f"6.6: the key is in i/secrets.json ({isec!r})")
        check('"k"' not in i.read_text(encoding="utf-8"), "6.6: the key is not in i/config.json")
        check(not (w.parent / "secrets.json").exists(), "6.6: w/secrets.json is gone after save")

    # 6.7 seeds
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        _write(w, {})
        _write(i, {})
        cfg.load(w, i)
        check(cfg.get("content_marketplace.catalogs") == cfg._DEFAULT_MARKETPLACE_CATALOGS,
              "6.7: the marketplace catalog is seeded in memory")
        backends = cfg.get("image_generation.backends") or []
        check(len(backends) == 13 == len(cfg._DEFAULT_MESH_BACKENDS) + 1,
              f"6.7: 13 mesh backends seeded in memory (got {len(backends)})")
        _age(w, i)
        wrote = cfg.migrate_file(w, i)
        check(wrote is False, f"6.7: migrate_file writes nothing (got {wrote!r})")
        check(_read(i) == {} and _untouched(i), "6.7: the instance stays {} with its old mtime")
        check(_untouched(w), "6.7: the world stays untouched")
        _write(i, {"image_generation": {"backends": []}})
        cfg.load(w, i)
        check(cfg.get("image_generation.backends") == [],
              "6.7: counter-check — an emptied backend list is not re-seeded")

    # 6.10 fresh state
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        try:
            cfg.check_instance_ready(w, i)
        except cfg.InstanceConfigMissing as e:
            check(False, f"6.10: empty directories must not raise ({e})")
        wrote = cfg.migrate_file(w, i)
        check(wrote is True, f"6.10: migrate_file creates the files (got {wrote!r})")
        check(w.exists() and _read(w) == {} and i.exists() and _read(i) == {},
              "6.10: both files exist as {}")
        _age(w, i)
        wrote = cfg.migrate_file(w, i)
        check(wrote is False and _untouched(w) and _untouched(i),
              f"6.10: a second migrate_file writes nothing (got {wrote!r})")

    # 6.11 corrupt layer file
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        _write(w, {"chat": {"chattiness": 0.3}})
        i.write_text('{"providers": [{"name": "real"}], "server": {"log_level": "DEBUG"},}',
                     encoding="utf-8")
        before = {f: f.read_bytes() for f in (w, i)}
        cfg.load(w, i)
        check(cfg.get("providers") == cfg._DEFAULT_PROVIDERS, "6.11: a non-strict load reads the broken layer as empty and seeds E11 examples")
        try:
            cfg.save(cfg.get_all())
            check(False, "6.11: save over an unreadable instance file must raise")
        except RuntimeError as e:
            check("refusing to overwrite unreadable" in str(e), f"6.11: save refusal names the cause ({e})")
        check(all(f.read_bytes() == b for f, b in before.items()),
              "6.11: both files byte-identical after the refused save")
        check(cfg.migrate_file(w, i) is False and all(f.read_bytes() == b for f, b in before.items()),
              "6.11: migrate_file skips and writes nothing")
        try:
            cfg.load(w, i, strict=True)
            check(False, "6.11: a strict load of a broken layer must raise")
        except ValueError:
            pass
        _write(w, {"providers": [{"name": "x"}]})
        try:
            cfg.check_instance_ready(w, i)
            check(False, "6.11: check_instance_ready must not read a broken instance as empty")
        except ValueError:
            pass
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        _write(w, {"chat": {"chattiness": 0.3}})
        _write(i, INSTANCE_61)
        ws = w.parent / "secrets.json"
        ws.write_text('{"broken": ', encoding="utf-8")
        cfg.load(w, i)
        try:
            cfg.save(cfg.get_all())
            check(False, "6.11: deleting an unreadable world secrets.json must raise")
        except RuntimeError:
            pass
        check(ws.read_text(encoding="utf-8") == '{"broken": ', "6.11: the broken secrets.json is kept")


# ---------------------------------------------------------------------------
# Part 4 — secrets and unsent fields keyed by entry name
# ---------------------------------------------------------------------------

def _keys_by_name(backends):
    return {b.get("name"): b.get("api_key") for b in backends or []}


def part_4():
    from app.core import config as cfg
    from app.core import config_admin as adm
    from app.core.config_schema import get_schema

    # 8.0 detector
    ne = getattr(cfg, "named_entries", None)
    if ne is None:
        check(False, "8.0: app.core.config lacks named_entries")
    else:
        got = ne([{"name": "a"}, {"name": "b"}])
        check(got is not None and list(got) == ["a", "b"], f"8.0: named list (got {got!r})")
        check(ne([]) == {}, f"8.0: empty list is named and empty (got {ne([])!r})")
        for label, lst in (("duplicate", [{"name": "a"}, {"name": "a"}]),
                           ("empty name", [{"name": "a"}, {"name": ""}]),
                           ("missing name", [{"name": "a"}, {"x": 1}]),
                           ("non-dict", [{"name": "a"}, "b"])):
            check(ne(lst) is None, f"8.0: {label} -> not a named list (got {ne(lst)!r})")

    # 8.1 / 8.2 insert, save, reload
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        _write(w, {"chat": {"chattiness": 0.3}})
        _write(i, {"image_generation": {"backends": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}})
        isec = i.parent / "secrets.json"
        _write(isec, {"image_generation": {"backends": [{}, {"api_key": "KB"}, {"api_key": "KC"}]}})
        cfg.load(w, i)
        got = _keys_by_name(cfg.get("image_generation.backends"))
        check(got == {"a": None, "b": "KB", "c": "KC"}, f"8.1: index-format secrets are read ({got!r})")
        data = copy.deepcopy(cfg.get_all())
        data["image_generation"]["backends"].insert(1, {"name": "x"})
        cfg.save(data)
        want = {"image_generation": {"backends": {"b": {"api_key": "KB"}, "c": {"api_key": "KC"}}}}
        check(_read(isec) == want, f"8.1: secrets.json by name (got {_read(isec)!r})")
        itext = i.read_text(encoding="utf-8")
        check("KB" not in itext and "KC" not in itext, "8.1: no key in i/config.json")
        cfg.load(w, i)
        got = _keys_by_name(cfg.get("image_generation.backends"))
        check(got == {"a": None, "x": None, "b": "KB", "c": "KC"}, f"8.1: reload after insert ({got!r})")
        conf = _read(i)
        conf["image_generation"]["backends"].insert(0, {"name": "y"})
        _write(i, conf)
        cfg.load(w, i)
        got = _keys_by_name(cfg.get("image_generation.backends"))
        check(got == {"y": None, "a": None, "x": None, "b": "KB", "c": "KC"},
              f"8.1: a hand insert in config.json keeps every key on its entry ({got!r})")

        # 8.2 unknown name
        _write(i, {"image_generation": {"backends": [{"name": "a"}, {"name": "x"},
                                                      {"name": "b"}, {"name": "c"}]}})
        _write(isec, {"image_generation": {"backends": {"b": {"api_key": "KB"},
                                                        "zz": {"api_key": "ZZ"}}}})
        cfg.load(w, i)
        bes = cfg.get("image_generation.backends")
        check([b.get("name") for b in bes] == ["a", "x", "b", "c"] and "ZZ" not in repr(bes),
              f"8.2: an unknown name is ignored ({bes!r})")
        check(_keys_by_name(bes).get("b") == "KB", "8.2: the known name still gets its key")

    def section(backends):
        return {"image_generation": {"backends": backends}}

    # 8.3 masked key at a new position
    current = section([{"name": "a"}, {"name": "b", "api_key": "KB"}, {"name": "c", "api_key": "KC"}])
    payload = section([{"name": "a"}, {"name": "x"}, {"name": "b", "api_key": "***"},
                       {"name": "c", "api_key": "***"}])
    merged = adm.merge_sensitive(payload, current)
    got = _keys_by_name(merged["image_generation"]["backends"])
    check(got == {"a": None, "x": None, "b": "KB", "c": "KC"}, f"8.3: masked keys by name ({got!r})")

    # 8.4 unsent field
    current = section([{"name": "a"}, {"name": "b", "category": "img2img"}, {"name": "c"}])
    merged = section([{"name": "a"}, {"name": "x"}, {"name": "b"}, {"name": "c"}])
    adm._preserve_unsent_subarray_fields(merged, current, get_schema())
    bes = {b["name"]: b for b in merged["image_generation"]["backends"]}
    check(bes["b"].get("category") == "img2img", f"8.4: b keeps its own unsent field ({bes['b']!r})")
    check("category" not in bes["x"], f"8.4: x inherits nothing from b ({bes['x']!r})")
    check("category" not in bes["c"], f"8.4: c inherits nothing ({bes['c']!r})")

    # 8.5 rename
    current = section([{"name": "a"}, {"name": "b"},
                       {"name": "c", "api_key": "KC", "category": "inpaint"}])
    payload = section([{"name": "a"}, {"name": "b"}, {"name": "c2", "api_key": "***"}])
    merged = adm.merge_sensitive(payload, current)
    adm._preserve_unsent_subarray_fields(merged, current, get_schema())
    c2 = merged["image_generation"]["backends"][2]
    check(c2.get("api_key") == "KC", f"8.5: the key survives the rename ({c2!r})")
    check(c2.get("category") == "inpaint", f"8.5: the unsent field follows the rename ({c2!r})")

    # 8.6 unnamed lists stay by index
    _, sec = cfg._split_secrets({"l": [{"api_key": "k0"}, {"x": 1}]})
    check(sec == {"l": [{"api_key": "k0"}, {}]}, f"8.6: unnamed list secrets by index ({sec!r})")
    _, sec = cfg._split_secrets({"l": [{"name": "d", "api_key": "k"}, {"name": "d"}]})
    check(sec == {"l": [{"api_key": "k"}, {}]}, f"8.6: duplicate names -> by index ({sec!r})")
    got = adm.merge_sensitive({"l": [{}, {"api_key": "***"}]}, {"l": [{}, {"api_key": "K1"}]})
    check(got == {"l": [{}, {"api_key": "K1"}]}, f"8.6: merge_sensitive by index ({got!r})")
    base = {"l": [{"a": 1}, {"a": 2}]}
    cfg._deep_merge(base, {"l": [{}, {"api_key": "K"}]})
    check(base == {"l": [{"a": 1}, {"a": 2, "api_key": "K"}]}, f"8.6: _deep_merge by index ({base!r})")

    # Review fix round 1 — capture the config logger's warnings
    import logging

    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.msgs = []

        def emit(self, record):
            self.msgs.append(record.getMessage())

    grab = _Grab()
    cfg.logger.addHandler(grab)
    try:
        # 8.7 no list in config.json
        with tempfile.TemporaryDirectory() as tmp:
            w, i = _layers(tmp)
            _write(w, {"chat": {"chattiness": 0.3}})
            _write(i, {"server": {"log_level": "DEBUG"}})
            isec = i.parent / "secrets.json"
            _write(isec, {"providers": {"p": {"api_key": "KP"}}})
            for strict in (False, True):
                grab.msgs.clear()
                try:
                    cfg.load(w, i, strict=strict)
                except Exception as e:  # noqa: BLE001
                    check(False, f"8.7: load(strict={strict}) raised {type(e).__name__}: {e}")
                    continue
                check(cfg.get("providers") == cfg._DEFAULT_PROVIDERS,
                      f"8.7: strict={strict} — E11 example providers ({cfg.get('providers')!r})")
                check(any(str(isec) in m and "providers" in m for m in grab.msgs),
                      f"8.7: strict={strict} — a warning names the secrets file ({grab.msgs!r:.300})")

            # 8.8 corrupt config.json + by-name secrets
            i.write_text('{"server": {"log_level": "DEBUG"},}', encoding="utf-8")
            try:
                cfg.load(w, i)
                check(cfg.get("providers") == cfg._DEFAULT_PROVIDERS, "8.8: corrupt layer -> E11 example providers")
                check(cfg.get("server.log_level") != "DEBUG", "8.8: corrupt layer read as empty")
            except Exception as e:  # noqa: BLE001
                check(False, f"8.8: load raised {type(e).__name__}: {e}")

        # 8.9 partly named base
        with tempfile.TemporaryDirectory() as tmp:
            w, i = _layers(tmp)
            _write(w, {"chat": {"chattiness": 0.3}})
            _write(i, {"image_generation": {"backends": [{"name": "a"}, {"name": ""}]}})
            isec = i.parent / "secrets.json"
            _write(isec, {"image_generation": {"backends": {"a": {"api_key": "KA"}}}})
            grab.msgs.clear()
            cfg.load(w, i)
            bes = cfg.get("image_generation.backends") or []
            check(bes and bes[0].get("api_key") == "KA", f"8.9: a keeps its key ({bes!r})")
            hits = [m for m in grab.msgs if str(isec) in m and "unique name" in m]
            check(len(hits) == 1, f"8.9: one warning about the unpairable entries ({grab.msgs!r:.300})")
            check(not any("no list entry named 'a'" in m for m in grab.msgs),
                  "8.9: no misleading 'no entry named a' warning")
            cfg.save(cfg.get_all())
            got = _read(isec) if isec.exists() else None
            check(got == {"image_generation": {"backends": [{"api_key": "KA"}, {}]}},
                  f"8.9: the next save keeps the key (index format) ({got!r})")
    finally:
        cfg.logger.removeHandler(grab)

    # 8.10 mask without partner
    current = section([{"name": "a"}, {"name": "b", "api_key": "KB"}, {"name": "c", "api_key": "KC"}])
    payload = section([{"name": "a"}, {"name": "c", "api_key": "***"}, {"name": "b2", "api_key": "***"}])
    merged = adm.merge_sensitive(payload, current)
    got = _keys_by_name(merged["image_generation"]["backends"])
    check(got == {"a": None, "c": "KC", "b2": ""}, f"8.10: unpartnered mask -> '' ({got!r})")


def part_5():
    import logging
    from app.core import config as cfg
    from app.core.game_time import default_seasons_config

    # 9.1 guard command
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        _write(w, {"providers": [{"name": "x", "api_base": "u"}]})
        try:
            cfg.check_instance_ready(w, i)
            check(False, "9.1: the guard must raise")
        except cfg.InstanceConfigMissing as e:
            want = (f'--from "w" --instance "{Path(tmp).resolve() / "i"}" '
                    f'--worlds-dir "{Path(tmp).resolve()}"')
            check(want in str(e), f"9.1: the command fits world + instance ({e})")
    cmd = cfg._migration_command(REPO / "worlds" / "demo" / "config.json",
                                 Path("/nonexistent/inst/config.json"))
    check('--from "demo"' in cmd and '--instance "/nonexistent/inst"' in cmd
          and "--worlds-dir" not in cmd,
          f"9.1: a world in <repo>/worlds needs no --worlds-dir ({cmd})")

    # 9.2 season flag after migrate_file
    with tempfile.TemporaryDirectory() as tmp:
        w, i = _layers(tmp)
        _write(w, {"game_seasons": default_seasons_config()})
        _write(i, {})
        cfg.load(w, i)
        check(cfg.game_seasons_are_defaults() is False,
              "9.2: a written-out list loads as not materialized")
        wrote = cfg.migrate_file(w, i)
        check(wrote is True and "game_seasons" not in _read(w),
              f"9.2: migrate_file prunes the default list ({wrote!r}, {_read(w)!r:.120})")
        check(cfg.game_seasons_are_defaults() is True,
              "9.2: the flag follows the disk after migrate_file, as after save()")
        other = Path(tmp) / "other" / "config.json"
        _write(other, {"game_seasons": default_seasons_config()})
        cfg._note_seasons_on_disk({"game_seasons": []})
        cfg.migrate_file(other, i)
        check(cfg.game_seasons_are_defaults() is False,
              "9.2: migrate_file of another world leaves the flag alone")

    # 9.3 one warning per file
    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append((record.levelno, record.getMessage()))

    grab = _Grab()
    old_level = cfg.logger.level
    cfg.logger.addHandler(grab)
    cfg.logger.setLevel(logging.DEBUG)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            w, i = _layers(tmp)
            _write(w, {"providers": [{"name": "a"}], "server": {"log_level": "DEBUG"},
                       "embedding": {"backend": "external"}, "decision": {"enabled": True},
                       "content_marketplace": {"catalogs": []}, "tts": {"enabled": True},
                       "llm_routing": [], "chat": {"chattiness": 0.3}})
            _write(i, {"chat": {"chattiness": 0.9}})
            cfg.load(w, i)
            warn_w = [m for lv, m in grab.records if lv == logging.WARNING
                      and str(w) in m and "belong to the" in m]
            check(len(warn_w) == 1, f"9.3: ONE warning for the world file ({warn_w!r:.400})")
            want = ("7 key(s) belong to the instance config and are ignored (providers, "
                    "server, embedding, decision, content_marketplace and 2 more)")
            check(bool(warn_w) and want in warn_w[0]
                  and "scripts/migrate_instance_config.py" in warn_w[0],
                  f"9.3: count, first five names, the hint ({warn_w!r:.400})")
            dbg = [m for lv, m in grab.records if lv == logging.DEBUG
                   and str(w) in m and "belongs to the instance config" in m]
            check(len(dbg) == 7, f"9.3: seven single keys at DEBUG (got {len(dbg)})")
            warn_i = [m for lv, m in grab.records if lv == logging.WARNING
                      and str(i) in m and "belong to the" in m]
            check(len(warn_i) == 1 and "1 key(s) belong to the world config" in warn_i[0]
                  and "next save drops" in warn_i[0],
                  f"9.3: the instance file's one warning ({warn_i!r:.300})")
    finally:
        cfg.logger.removeHandler(grab)
        cfg.logger.setLevel(old_level)


def main():
    had_searx = part_p_before_discovery()
    part_2_before_discovery()
    from app.plugins.loader import discover_packages
    from app.core import config
    boot_world, boot_instance = _layers(Path(_TMP) / "boot")
    _write(boot_world, {"packages": {"enabled": "searx,outfit_change"}})
    _write(boot_instance, {})
    config.load(boot_world, boot_instance)
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
    part_3()
    part_4()
    part_5()

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
