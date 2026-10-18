#!/usr/bin/env python3
"""Smoke: a config field's schema default IS the default its consumers use.

Usage:  ./.venv/bin/python scripts/smoke_config_defaults_consistent.py

No server, no world DB. The storage root is a throwaway temp dir (set before
any app import); the plugin packages are discovered so their config
subsections are part of the schema. Nothing under ``worlds/`` is read.

WHY

The server config moves out of the per-world ``config.json`` into an instance
layer, and stored values equal to the schema default get PRUNED. Pruning a
value is only behaviour-neutral when "field absent" and "field = schema
default" act the same — i.e. when every consumer falls back to exactly the
schema default. On 2026-10-03 seven fields did not (the table below). This
check pins that the schema default and the consumer default are one value.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

0) SELF-TEST of the scanner: an inline source with one matching read, one
   mismatching read, one ``or NAME`` read against a module constant and one
   non-config ``.get`` must yield exactly the mismatch — so a green run
   means the scanner looked, not that it looked away.

A) AST scan over ``app/**/*.py`` and ``plugins/**/*.py`` (symlinked private
   packs are NOT followed, ``plugins/installed`` — local marketplace installs,
   not repo code — is skipped). Collected are reads of a literal dotted path
   through the config module (``config.get``/``_cfg.get``/…, the
   ``from app.core.config import get as X`` alias, the lazy-accessor pattern
   ``cfg = _config()``) and through the plugin context
   (``ctx.get_config``):
     1. ``get("<path>", <default>)`` — the default is a literal or a module
        constant (``NAME`` / ``mod.NAME`` resolved through the imports);
     2. ``get("<path>")`` without a default whose result is replaced in the
        same expression: ``get("<path>") or <literal|NAME>``.
   With both (``get("p", D) or L``) the value used when the field is absent
   is ``D or L``. An explicit ``None`` default without an ``or`` is not a
   default (the consumer decides later) and is skipped. A default that IS a
   ``field_default(...)`` call is the schema default by construction.
   Expected: for every read whose field has a schema default, the
   effective consumer default == the schema default, except the paths in
   ``INTENTIONAL`` (each with its reason). A default that cannot be resolved
   statically is a failure, not a skip.

B) The env bridge, ``config._flatten_to_env``. Its AST yields every
   ``_set(env, "X", <var>.get("<field>", …))`` leaf (``x = config.get("sec",
   …)`` / ``y = x.get("sub", …)`` / ``for …, prov in enumerate(config.get(
   "providers", …))`` build the path). For every leaf whose field has a
   schema default, ``_flatten_to_env({"providers": [{}]})`` must put the
   ``_set`` string form of the schema default into ``os.environ["X"]`` — or
   leave X unset when that form is empty (``_set`` skips ""). Conversions:
   ``EVENT_BASE_PROBABILITY`` is the percent field / 100.
   Then every env consumer of such an X in ``app/`` and ``plugins/``
   (``os.environ.get``/``os.getenv``/``ctx.get_env*``) must be listed in
   ``ENV_CONSUMERS`` (file + hand-written expected default), the hand value
   must equal the schema default (after conversion, compared by the field's
   type: bool by truthiness of "1/true/yes", numbers numerically), and the
   consumer's own default must be that value too — as a literal, or as a
   ``field_default(...)`` call naming the bridged field.
   Only LITERAL env names are in scope, on both sides: a name built at run
   time — the numbered provider / backend blocks, e.g.
   ``f"PROVIDER_{n}_API_KEY"`` in ``app/imagegen/backends/together_video.py``
   — is neither a bridge leaf this reader renders past index 1 nor an env
   consumer the scan can match, so its default is not compared here.

C) The table rows explicitly, values written down BY HAND from the
   2026-10-03 table of the task (AD = the world "Anima Divide", which stores
   none of these fields, so its effective value is the consumer default):

     path                                     schema default (expected)
     server.timezone                          ""      timeutils: empty -> UTC
     chat.top_p                               0       history_manager: "0 or
                                                      absent" -> no override
     thoughts.min_per_char_cooldown_minutes   5       agent_loop constant 5
     image_generation.outfit_image_width      832     bridge 832 (AD effective)
     image_generation.outfit_image_height     1216    bridge 1216
     random_events.base_probability           5       bridge 5 -> "0.05"
     image_generation.image_analysis_prompt   the schema prompt -> bridged
     tts.xtts.url / magpie.url / f5.url       http://localhost:8020 / :9000
                                              / :7860 -> bridged

   Plus behaviour: ``_world_tz()`` with the field stored at its default is
   ``timezone.utc``; ``anti_repetition_overrides`` with ``chat.top_p`` stored
   at its default sends no ``top_p``, the same as with the field absent;
   ``agent_loop._get_per_char_cooldown_min()`` returns 5 both ways. The
   agent_loop fallback constant is itself ``field_default(...)`` since
   2026-10-03, so "constant == schema default" is no separate check any more
   (part A already proves the read names field_default of the SAME field);
   the hand value 5 stays pinned by the behaviour check.
   C is self-contained: it runs the bridge itself before reading
   ``IMAGE_ANALYSIS_PROMPT`` instead of relying on part B having run.

FAILS BEFORE / PASSES AFTER
---------------------------
On the code of commit 21a1cc40 the import of ``field_default`` fails. With
only ``field_default`` added to that code, 39 of 335 checks FAIL: the seven
table rows in A/B/C, plus mismatches the table did not list —
``server.time_format`` / ``image_generation.scene_render_mode`` /
``image_generation.scene_render_cooldown_s`` (an empty-string sentinel in
the read, the real fallback a few lines below), ``skills.searx.engines`` /
``categories`` (plugin schema "google,duckduckgo,bing" / "general", reader
""), the bridge's ``providers[*].timeout`` 120 / ``api_key`` "" (schema 600 /
"not-needed"), ``rebuild_llm_system_template`` "" (schema text), and the
env readers ``STORY_ENGINE_ENABLED`` "true" / ``TTS_CHUNK_SIZE`` "0" (schema
false / 300). After the alignment: all PASS.
"""
import ast
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_TMP = tempfile.mkdtemp(prefix="smoke_cfg_defaults_")
os.environ["STORAGE_DIR"] = _TMP

from app.core import paths  # noqa: E402

paths.init(_TMP)

# Keep the public packages' schema coverage under default-deny activation.
# These are the repository manifests that contribute config subsections.
from app.core import config  # noqa: E402

_CONFIG_PATH = Path(_TMP) / "config.json"
_CONFIG_PATH.write_text(
    '{"packages":{"enabled":"instagram,interact,markdown_writer,searx,'
    'send_message,set_pose,talk_to,wet"}}',
    encoding="utf-8",
)
config.load(_CONFIG_PATH)

from app.core.config_schema import field_default  # noqa: E402

# Paths whose consumer default deliberately differs from the schema default.
INTENTIONAL = {
}

# Env consumers whose default deliberately differs from the bridged schema default.
# (STORAGE_DIR left this list on 2026-10-03: server.storage_dir is gone and the
# bridge no longer writes it — it is a pure path override, not config.)
ENV_INTENTIONAL = {
}

# Every env consumer of a bridged field with a schema default:
# X -> [(file, expected default as the consumer sees it, written by hand)].
ENV_CONSUMERS = {
    "LOG_LEVEL": [("app/core/log.py", "INFO")],
    "MEMORY_SHORT_TERM_DAYS": [("app/utils/history_manager.py", "3")],
    "MEMORY_MID_TERM_DAYS": [("app/utils/history_manager.py", "30")],
    "MEMORY_LONG_TERM_DAYS": [("app/utils/history_manager.py", "90")],
    "CHAT_HISTORY_MAX_MESSAGES": [("app/utils/history_manager.py", "100")],
    "CHAT_SESSION_GAP_HOURS": [("app/utils/history_manager.py", "4")],
    "OUTFIT_IMAGE_WIDTH": [("app/core/expression_regen.py", "832")],
    "OUTFIT_IMAGE_HEIGHT": [("app/core/expression_regen.py", "1216")],
    "LOCATION_IMAGE_WIDTH": [("app/core/world_ops.py", "1280"),
                             ("app/skills/describe_room_skill.py", "1280")],
    "LOCATION_IMAGE_HEIGHT": [("app/core/world_ops.py", "720"),
                              ("app/skills/describe_room_skill.py", "720")],
    "IMAGE_ANALYSIS_PROMPT": [("app/imagegen/service.py",
                               field_default("image_generation", "image_analysis_prompt"))],
    "TTS_ENABLED": [("app/core/tts_service.py", "false")],
    "TTS_AUTO": [("app/core/tts_service.py", "false")],
    "TTS_CHUNK_SIZE": [("app/core/tts_service.py", "300")],
    "TTS_BACKEND": [("app/core/tts_service.py", "xtts")],
    "TTS_FALLBACK_BACKEND": [("app/core/tts_service.py", "")],
    "TTS_XTTS_URL": [("app/core/tts_service.py", "http://localhost:8020")],
    "TTS_XTTS_LANGUAGE": [("app/core/tts_service.py", "de")],
    "TTS_MAGPIE_URL": [("app/core/tts_service.py", "http://localhost:9000")],
    "TTS_MAGPIE_LANGUAGE": [("app/core/tts_service.py", "de-DE")],
    "TTS_F5_URL": [("app/core/tts_service.py", "http://localhost:7860")],
    "TTS_F5_SPEED": [("app/core/tts_service.py", "1.0")],
    "TTS_F5_REMOVE_SILENCE": [("app/core/tts_service.py", "false")],
    "TTS_F5_NFE_STEPS": [("app/core/tts_service.py", "32")],
    "SKILL_KNOWLEDGE_BATCH_SIZE": [("plugins/knowledge/skill_extract.py", "5")],
    "SKILL_KNOWLEDGE_MAX_INPUT_TOKENS": [("plugins/knowledge/skill_extract.py", "12000")],
    "SKILL_KNOWLEDGE_MAX_OUTPUT_TOKENS": [("plugins/knowledge/skill_extract.py", "1500")],
    "SKILL_KNOWLEDGE_SEARCH_MAX_CANDIDATES": [("plugins/knowledge/skill_search.py", "50")],
    "SKILL_KNOWLEDGE_SEARCH_MAX_RETURN": [("plugins/knowledge/skill_search.py", "8")],
    "STORY_ENGINE_ENABLED": [("app/core/story_engine.py", "false")],
    "STORY_ENGINE_MAX_ACTIVE_ARCS": [("app/core/story_engine.py", "2")],
    "STORY_ENGINE_COOLDOWN_HOURS": [("app/core/story_engine.py", "6")],
    "STORY_ENGINE_MAX_BEATS": [("app/core/story_engine.py", "5")],
    "STORY_ENGINE_BEAT_IMAGES": [("app/core/story_engine.py", "true")],
    "EVENT_GENERATION_ENABLED": [("app/core/random_events.py", "true"),
                                 ("app/core/random_events.py", "true")],
    "EVENT_BASE_PROBABILITY": [("app/core/random_events.py", "0.05")],
    "EVENT_RESOLUTION_COOLDOWN_MINUTES": [("app/core/random_events.py", "15")],
    "EVENT_RESOLUTION_PROACTIVE": [("app/core/random_events.py", "true")],
    "EVENT_RESOLVED_IMAGE_LINGER_MINUTES": [("app/core/event_images.py", "30")],
}

# Bridge values that are a conversion of the field, not the field itself.
BRIDGE_CONVERSIONS = {
    "EVENT_BASE_PROBABILITY": lambda v: v / 100,
}

# Hand-written table of the task (section C).
TABLE = {
    ("server", "timezone"): "",
    ("chat", "top_p"): 0,
    ("thoughts", "min_per_char_cooldown_minutes"): 5,
    ("image_generation", "outfit_image_width"): 832,
    ("image_generation", "outfit_image_height"): 1216,
    ("random_events", "base_probability"): 5,
    ("tts", "xtts", "url"): "http://localhost:8020",
    ("tts", "magpie", "url"): "http://localhost:9000",
    ("tts", "f5", "url"): "http://localhost:7860",
}

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def _short(v, n=60):
    s = repr(v)
    return s if len(s) <= n else s[:n] + "…"


def schema_default(dotted):
    """(found, value) for a dotted config path."""
    if "[" in dotted:
        return False, None
    parts = dotted.split(".")
    if len(parts) < 2:
        return False, None
    try:
        return True, field_default(parts[0], *parts[1:])
    except KeyError:
        return False, None


def same(a, b):
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


# ---------------------------------------------------------------------------
# Static resolution helpers
# ---------------------------------------------------------------------------

_UNRESOLVED = object()
_FIELD_DEFAULT = object()   # marker: the default is a field_default() call


def iter_sources():
    for root in ("app", "plugins"):
        base = REPO / root
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            rel_dir = Path(dirpath).relative_to(REPO)
            dirnames[:] = [d for d in dirnames
                           if d != "__pycache__"
                           and not (Path(dirpath) / d).is_symlink()
                           and not (rel_dir == Path("plugins") and d == "installed")]
            for fn in filenames:
                p = Path(dirpath) / fn
                if fn.endswith(".py") and not p.is_symlink():
                    yield p


_MODULE_CACHE = {}


def module_file(modname):
    rel = Path(*modname.split("."))
    for cand in (REPO / rel.with_suffix(".py"), REPO / rel / "__init__.py"):
        if cand.exists():
            return cand
    return None


class ModuleInfo:
    def __init__(self, tree, path=None):
        self.tree = tree
        self.path = path
        self.consts = {}        # top-level NAME -> ast value
        self.imported = {}      # local name -> (module, name) for from-imports
        self.mod_alias = {}     # local name -> module (import x as y / from pkg import mod)
        self.config_names = set()   # names bound to app.core.config
        self.get_funcs = set()      # names bound to app.core.config.get
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                self.consts[node.targets[0].id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                    and node.value is not None:
                self.consts[node.target.id] = node.value
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for a in node.names:
                    local = a.asname or a.name
                    full = f"{node.module}.{a.name}"
                    if full == "app.core.config":
                        self.config_names.add(local)
                    elif node.module == "app.core.config" and a.name == "get":
                        self.get_funcs.add(local)
                    if module_file(full):
                        self.mod_alias[local] = full
                    else:
                        self.imported[local] = (node.module, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        if a.name == "app.core.config":
                            self.config_names.add(a.asname)
                        self.mod_alias[a.asname] = a.name
        # Lazy accessor: `def _config(): from app.core import config as X; return X`
        accessors = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                rets = [n for n in ast.walk(node) if isinstance(n, ast.Return)
                        and isinstance(n.value, ast.Name)]
                if any(r.value.id in self.config_names for r in rets):
                    accessors.add(node.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name) \
                    and isinstance(node.value, ast.Call) \
                    and isinstance(node.value.func, ast.Name) \
                    and node.value.func.id in accessors:
                self.config_names.add(node.targets[0].id)
        # Names assigned from an expression that contains field_default(...)
        self.fd_names = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name) \
                    and contains_field_default(node.value):
                self.fd_names[node.targets[0].id] = node.value


def field_default_path(node, info):
    """The dotted path a field_default(...) default names, or None."""
    if isinstance(node, ast.Name) and node.id in info.fd_names:
        node = info.fd_names[node.id]
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if name == "field_default" and all(
                    isinstance(a, ast.Constant) and isinstance(a.value, str) for a in n.args):
                return ".".join(a.value for a in n.args)
    return None


def contains_field_default(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if name == "field_default":
                return True
    return False


def load_module(modname):
    if modname in _MODULE_CACHE:
        return _MODULE_CACHE[modname]
    path = module_file(modname)
    info = None
    if path:
        info = ModuleInfo(ast.parse(path.read_text(encoding="utf-8")), path)
    _MODULE_CACHE[modname] = info
    return info


def resolve(node, info, depth=0):
    """Literal value of a default expression, _FIELD_DEFAULT, or _UNRESOLVED."""
    if depth > 5:
        return _UNRESOLVED
    if contains_field_default(node):
        return _FIELD_DEFAULT
    try:
        return ast.literal_eval(node)
    except Exception:
        pass
    if isinstance(node, ast.Name):
        if node.id in info.fd_names:
            return _FIELD_DEFAULT
        if node.id in info.consts:
            return resolve(info.consts[node.id], info, depth + 1)
        if node.id in info.imported:
            mod, name = info.imported[node.id]
            other = load_module(mod)
            if other and name in other.consts:
                return resolve(other.consts[name], other, depth + 1)
        return _UNRESOLVED
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        mod = info.mod_alias.get(node.value.id)
        if mod:
            other = load_module(mod)
            if other and node.attr in other.consts:
                return resolve(other.consts[node.attr], other, depth + 1)
    return _UNRESOLVED


# ---------------------------------------------------------------------------
# A) config reads
# ---------------------------------------------------------------------------

def config_reads(tree, info):
    """Yield (lineno, dotted, effective default | marker) for every config read."""
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        f = node.func
        is_read = False
        if isinstance(f, ast.Attribute) and f.attr == "get" \
                and isinstance(f.value, ast.Name) and f.value.id in info.config_names:
            is_read = True
        elif isinstance(f, ast.Attribute) and f.attr == "get_config":
            is_read = True
        elif isinstance(f, ast.Name) and f.id in info.get_funcs:
            is_read = True
        if not is_read:
            continue
        a0 = node.args[0]
        if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str)):
            continue
        dotted = a0.value
        d_node = node.args[1] if len(node.args) > 1 else next(
            (k.value for k in node.keywords if k.arg == "default"), None)
        parent = parents.get(node)
        l_node = None
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or) \
                and parent.values[0] is node and len(parent.values) > 1:
            l_node = parent.values[1]
        if d_node is None and l_node is None:
            continue
        d = resolve(d_node, info) if d_node is not None else None
        l = resolve(l_node, info) if l_node is not None else None
        if d_node is not None and l_node is None:
            if d is None:
                continue      # explicit None: the consumer decides later
            eff = d
        elif d_node is None:
            eff = l
        else:
            if d is _UNRESOLVED or d is _FIELD_DEFAULT:
                eff = d
            else:
                eff = d if d else l
        if eff is _FIELD_DEFAULT:
            fd_node = d_node if d is _FIELD_DEFAULT else l_node
            eff = (_FIELD_DEFAULT, field_default_path(fd_node, info))
        yield node.lineno, dotted, eff


def scan_reads(source, path_label):
    tree = ast.parse(source)
    info = ModuleInfo(tree)
    return [(path_label, ln, dotted, eff) for ln, dotted, eff in config_reads(tree, info)]


def judge_reads(reads):
    """[(label, ok, detail)] for every read whose field has a schema default."""
    out = []
    for path_label, ln, dotted, eff in reads:
        found, sd = schema_default(dotted)
        if not found:
            continue
        where = f"{path_label}:{ln}"
        if isinstance(eff, tuple) and eff[0] is _FIELD_DEFAULT:
            out.append((f"{dotted} @ {where} = field_default() of the same field",
                        eff[1] == dotted, f"names {eff[1]}"))
        elif eff is _UNRESOLVED:
            out.append((f"{dotted} @ {where} default resolvable", False,
                        "default is not a literal / module constant"))
        elif dotted in INTENTIONAL:
            out.append((f"{dotted} @ {where} INTENTIONAL ({INTENTIONAL[dotted]})", True, ""))
        else:
            out.append((f"{dotted} @ {where} consumer {_short(eff, 30)} == schema",
                        same(eff, sd), f"schema {_short(sd)}"))
    return out


def self_test():
    print("0) scanner self-test")
    src = (
        "from app.core import config as _cfg\n"
        "LIMIT = 30\n"
        "a = _cfg.get('thoughts.min_turn_gap_seconds', 30)\n"
        "b = _cfg.get('memory.max_messages', 7)\n"
        "c = int(_cfg.get('memory.short_term_days') or LIMIT)\n"
        "d = other.get('memory.max_messages', 99)\n"
    )
    res = judge_reads(scan_reads(src, "selftest"))
    bad = [r for r in res if not r[1]]
    check("self-test sees three config reads (not the foreign .get)", len(res) == 3,
          f"got {len(res)}")
    check("self-test flags exactly the two mismatches (7, LIMIT=30 vs 3)",
          sorted(r[0].split(" @ ")[0] for r in bad)
          == ["memory.max_messages", "memory.short_term_days"],
          f"got {[r[0] for r in bad]}")


def part_a():
    print("A) config reads: consumer default == schema default")
    n = 0
    for p in sorted(iter_sources()):
        rel = str(p.relative_to(REPO))
        try:
            src = p.read_text(encoding="utf-8")
            reads = scan_reads(src, rel)
        except SyntaxError as e:
            check(f"{rel} parses", False, str(e))
            continue
        for label, ok, detail in judge_reads(reads):
            n += 1
            check(label, ok, detail)
    check("A found at least 60 schema-backed reads (lower bound, not a snapshot)",
          n >= 60, f"found {n}")


# ---------------------------------------------------------------------------
# B) env bridge
# ---------------------------------------------------------------------------

def bridge_leaves():
    """[(env name, (section, *keys))] from the AST of _flatten_to_env."""
    src = (REPO / "app/core/config.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_flatten_to_env")
    var_path = {}
    str_vars = {}

    def get_call(call):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get" and isinstance(call.func.value, ast.Name)
                and call.args and isinstance(call.args[0], ast.Constant)):
            return call.func.value.id, call.args[0].value
        return None

    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            g = get_call(node.value)
            tgt = node.targets[0].id
            if g and g[0] == "config":
                var_path[tgt] = (g[1],)
            elif g and g[0] in var_path:
                var_path[tgt] = var_path[g[0]] + (g[1],)
            elif isinstance(node.value, ast.JoinedStr):
                str_vars[tgt] = node.value
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Tuple) \
                and isinstance(node.iter, ast.Call) and node.iter.args:
            g = get_call(node.iter.args[0])
            if g and g[0] == "config":
                var_path[node.target.elts[-1].id] = (g[1],)

    def render(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.JoinedStr):
            out = ""
            for v in node.values:
                if isinstance(v, ast.Constant):
                    out += v.value
                elif isinstance(v.value, ast.Name) and v.value.id == "i":
                    out += "1"
                elif isinstance(v.value, ast.Name) and v.value.id in str_vars:
                    out += render(str_vars[v.value.id])
                else:
                    return None
            return out
        return None

    # A string var (`p = f"PROVIDER_{i}_"`, later `p = f"SKILL_IMAGEGEN_{i}_"`)
    # is rebound per loop, so a _set call sees the LAST binding before it in
    # source order — not the last one in the function.
    str_bindings = sorted(
        (n.lineno, n.targets[0].id, n.value) for n in ast.walk(fn)
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.JoinedStr))

    leaves = []
    for node in sorted((n for n in ast.walk(fn) if isinstance(n, ast.Call)),
                       key=lambda n: n.lineno):
        if not (isinstance(node.func, ast.Name)
                and node.func.id == "_set" and len(node.args) == 3):
            continue
        str_vars.clear()
        for ln, var, val in str_bindings:
            if ln < node.lineno:
                str_vars[var] = val
        name = render(node.args[1])
        if not name:
            continue
        for sub in ast.walk(node.args[2]):
            g = get_call(sub)
            if g and g[0] in var_path and isinstance(g[1], str):
                leaves.append((name, var_path[g[0]] + (g[1],)))
                break
    return leaves


def set_form(value):
    """What config._set writes for a value (None = nothing written)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def norm_for(ref, value):
    """Compare an env-side default with a reference value of the field's type."""
    if isinstance(ref, bool):
        return str(value).strip().lower() in ("1", "true", "yes")
    if isinstance(ref, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return "" if value is None else str(value)


def env_consumers(names):
    """[(name, file, line, default node | None, info)] for os.environ/getenv/get_env* reads."""
    out = []
    for p in sorted(iter_sources()):
        rel = str(p.relative_to(REPO))
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        info = ModuleInfo(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value in names):
                continue
            f = node.func
            is_env = (f.attr == "get" and isinstance(f.value, ast.Attribute)
                      and f.value.attr == "environ") \
                or f.attr == "getenv" or f.attr in ("get_env", "get_env_int", "get_env_bool")
            if not is_env:
                continue
            d = node.args[1] if len(node.args) > 1 else None
            out.append((node.args[0].value, rel, node.lineno, d, info))
    return out


def part_b():
    print("B) env bridge: _flatten_to_env({}) bridges the schema default")
    from app.core import config as cfg
    leaves = bridge_leaves()
    check("bridge reader finds at least 50 leaves (lower bound)", len(leaves) >= 50,
          f"found {len(leaves)}")
    with_default = []
    for name, path in leaves:
        try:
            sd = field_default(*path)
        except KeyError:
            continue
        with_default.append((name, path, sd))
    for name, _, _ in with_default:
        os.environ.pop(name, None)
    cfg._flatten_to_env({"providers": [{}]})
    expected_env = {}
    for name, path, sd in with_default:
        conv = BRIDGE_CONVERSIONS.get(name, lambda v: v)(sd)
        expected_env[name] = (path, sd, conv)
        want = set_form(conv)
        got = os.environ.get(name)
        check(f"{name} <- {'.'.join(path)} bridges {_short(want, 30)}", got == want,
              f"bridge wrote {_short(got)}")
    # Env consumers
    names = set(expected_env)
    found = env_consumers(names)
    seen = {}
    for name, rel, ln, d_node, info in found:
        if name in ENV_INTENTIONAL:
            check(f"{name} consumer {rel}:{ln} INTENTIONAL ({ENV_INTENTIONAL[name][:50]}…)", True)
            continue
        seen.setdefault(name, []).append(rel)
        path, sd, conv = expected_env[name]
        listed = [e for e in ENV_CONSUMERS.get(name, []) if e[0] == rel]
        check(f"{name} consumer {rel}:{ln} listed in ENV_CONSUMERS", bool(listed))
        if not listed:
            continue
        hand = listed[0][1]
        check(f"{name} hand default {_short(hand, 30)} == schema default (converted)",
              norm_for(conv, hand) == norm_for(conv, conv), f"schema {_short(conv)}")
        if d_node is None:
            check(f"{name} consumer {rel}:{ln} has a default", False, "no default argument")
            continue
        val = resolve(d_node, info)
        if val is _FIELD_DEFAULT:
            fd_path = field_default_path(d_node, info)
            check(f"{name} consumer {rel}:{ln} default = field_default({fd_path})",
                  fd_path == ".".join(path), f"bridged field is {'.'.join(path)}")
        elif val is _UNRESOLVED:
            check(f"{name} consumer {rel}:{ln} default resolvable", False, ast.dump(d_node)[:80])
        else:
            check(f"{name} consumer {rel}:{ln} literal {_short(val, 30)} == schema",
                  norm_for(conv, val) == norm_for(conv, conv), f"schema {_short(conv)}")
    for name, entries in ENV_CONSUMERS.items():
        if name not in expected_env:
            continue
        check(f"{name}: ENV_CONSUMERS lists only consumers that exist ({len(entries)})",
              sorted(e[0] for e in entries) == sorted(seen.get(name, [])),
              f"scan found {sorted(seen.get(name, []))}")
    for must in ("EVENT_BASE_PROBABILITY", "OUTFIT_IMAGE_WIDTH", "OUTFIT_IMAGE_HEIGHT",
                 "TTS_XTTS_URL", "TTS_MAGPIE_URL", "TTS_F5_URL"):
        check(f"{must} is a checked env consumer", must in seen and must in ENV_CONSUMERS)


# ---------------------------------------------------------------------------
# C) table rows + behaviour
# ---------------------------------------------------------------------------

def part_c():
    print("C) the 2026-10-03 table, by hand")
    from datetime import timezone
    from app.core import config as cfg
    for path, want in TABLE.items():
        try:
            got = field_default(*path)
        except KeyError as e:
            check(f"schema default {'.'.join(path)} == {want!r}", False, f"KeyError {e}")
            continue
        check(f"schema default {'.'.join(path)} == {want!r}", same(got, want), f"schema {got!r}")
    os.environ.pop("IMAGE_ANALYSIS_PROMPT", None)
    cfg._flatten_to_env({})
    check("image_analysis_prompt bridges the schema prompt",
          os.environ.get("IMAGE_ANALYSIS_PROMPT")
          == field_default("image_generation", "image_analysis_prompt"),
          _short(os.environ.get("IMAGE_ANALYSIS_PROMPT")))

    from app.core import timeutils, agent_loop
    from app.utils.history_manager import anti_repetition_overrides
    saved = cfg._CONFIG
    try:
        cfg._CONFIG = {}
        tz_absent = timeutils._world_tz()
        top_absent = "top_p" in anti_repetition_overrides([], 0.7)
        cd_absent = agent_loop._get_per_char_cooldown_min()
        cfg._CONFIG = {
            "server": {"timezone": field_default("server", "timezone")},
            "chat": {"top_p": field_default("chat", "top_p")},
            "thoughts": {"min_per_char_cooldown_minutes":
                         field_default("thoughts", "min_per_char_cooldown_minutes")},
        }
        tz_stored = timeutils._world_tz()
        top_stored = "top_p" in anti_repetition_overrides([], 0.7)
        cd_stored = agent_loop._get_per_char_cooldown_min()
    finally:
        cfg._CONFIG = saved
    check("timeutils: absent timezone -> UTC", tz_absent is timezone.utc, repr(tz_absent))
    check("timeutils: timezone stored at schema default -> UTC", tz_stored is timezone.utc,
          repr(tz_stored))
    check("chat.top_p absent -> no top_p override", top_absent is False)
    check("chat.top_p stored at schema default -> no top_p override (same as absent)",
          top_stored is False)
    check("per-char cooldown: absent == stored at default == 5",
          cd_absent == cd_stored == 5, f"absent {cd_absent}, stored {cd_stored}")


def part_field_default_contract():
    print("field_default contract")
    check("field_default('server','log_level') == 'INFO'",
          field_default("server", "log_level") == "INFO")
    check("field_default('tts','xtts','language') == 'de' (subsection)",
          field_default("tts", "xtts", "language") == "de")
    check("field_default('skills','searx','num_results') == 5 (plugin subsection)",
          field_default("skills", "searx", "num_results") == 5)
    for args, why in ((("server", "nope"), "missing field"),
                      (("tts", "xtts", "speaker_wav"), "field without default"),
                      (("memory", "_grp_situational"), "pseudo field"),
                      (("nope", "x"), "missing section")):
        try:
            field_default(*args)
            check(f"field_default{args} raises KeyError ({why})", False, "no KeyError")
        except KeyError:
            check(f"field_default{args} raises KeyError ({why})", True)


def main():
    from app.plugins.loader import discover_packages
    discover_packages()
    self_test()
    part_field_default_contract()
    part_a()
    part_b()
    part_c()
    print()
    if _failures:
        print(f"FAILED {len(_failures)} of {_checks} checks:")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"OK — {_checks} checks passed")


if __name__ == "__main__":
    main()
