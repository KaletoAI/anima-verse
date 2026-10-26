"""Expression-set metadata and atomic Shared/World editing.

Expression groups are not pose place types. One immutable effective snapshot
is shared by mood matching, rendering and maintenance.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Mapping
from app.core.pose_catalog_edit import CatalogEditError

from app.core import pose_catalog

SHIPPED_SETS = frozenset({"humanoid", "animal"})

class ExpressionSetError(CatalogEditError, ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(status=status, detail=message)

    def __str__(self):
        return self.detail


@dataclass(frozen=True)
class ExpressionSet:
    id: str
    label: str
    default: str
    pose_prompt: str
    members: tuple[str, ...]
    store: str


@dataclass(frozen=True)
class ExpressionCatalog:
    revision: str
    sets: Mapping[str, ExpressionSet]
    entries: Mapping[str, Mapping]


def _documents():
    shared = deepcopy(pose_catalog._read_shared("expression"))
    world = {"entries": pose_catalog.world_entries("expression"),
             "groups": pose_catalog._world_rows("expression", "group")}
    for doc in (shared, world):
        doc.setdefault("entries", {})
        doc.setdefault("groups", {})
    return shared, world


def _snapshot(shared, world) -> ExpressionCatalog:
    entries = {}
    groups = {}
    for store, doc in (("shared", shared), ("world", world)):
        for key, entry in doc["entries"].items():
            entries[key] = MappingProxyType({
                "prompt": str(entry.get("prompt") or "").strip(),
                "label": str(entry.get("label") or key.replace("_", " ").title()),
                "synonyms": tuple(str(s).strip().lower() for s in entry.get("synonyms", [])),
                "_store": store,
            })
        for key, group in doc["groups"].items():
            groups[key] = ExpressionSet(
                key, str(group.get("label") or key), str(group.get("default") or ""),
                str(group.get("pose_prompt") or "").strip(),
                tuple(group.get("members") or ()), store)
    raw = json.dumps([shared, world], sort_keys=True, ensure_ascii=False)
    return ExpressionCatalog(hashlib.sha256(raw.encode()).hexdigest(),
                             MappingProxyType(groups), MappingProxyType(entries))


def catalog_snapshot() -> ExpressionCatalog:
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("pose_catalog", "expression"):
        result = _snapshot(*_documents())
        problems = validate_expression_catalog(result)
        if problems:
            raise ExpressionSetError("; ".join(problems), 409)
        return result


def validate_expression_catalog(catalog: ExpressionCatalog, *, legacy_shared_keys=()) -> list[str]:
    problems = []
    owners = {}
    for sid, spec in catalog.sets.items():
        if not spec.members or not spec.pose_prompt:
            problems.append(f"Expression set '{sid}' needs members and a fixed pose")
        if spec.default not in spec.members:
            problems.append(f"Expression set '{sid}' default is not a member")
        aliases = {}
        for key in spec.members:
            if key in owners:
                problems.append(f"Expression '{key}' belongs to multiple sets")
            owners[key] = sid
            entry = catalog.entries.get(key)
            if entry is None:
                problems.append(f"Expression set '{sid}' references missing '{key}'")
                continue
            if not entry["prompt"]:
                problems.append(f"Expression '{key}' needs a prompt")
            for alias in (key, *entry["synonyms"]):
                if alias in aliases and aliases[alias] != key:
                    problems.append(f"Alias '{alias}' is ambiguous in set '{sid}'")
                aliases[alias] = key
    for key in catalog.entries:
        if key not in owners and key not in legacy_shared_keys:
            problems.append(f"Expression '{key}' has no set")
    for sid in SHIPPED_SETS:
        if sid not in catalog.sets:
            problems.append(f"Shipped expression set '{sid}' is missing")
    return problems


def set_for_character(name: str, *, profile=None, catalog=None) -> ExpressionSet:
    from app.models.character import get_character_profile
    from app.models.character_template import is_feature_enabled
    profile = get_character_profile(name) if profile is None else profile
    catalog = catalog_snapshot() if catalog is None else catalog
    selected = str((profile or {}).get("expression_set") or "").strip()
    if not selected:
        from app.models.character_template import get_template
        template = get_template((profile or {}).get("template") or "") if profile else None
        humanoid = (template.get("features", {}).get("humanoid", True) if template
                    else is_feature_enabled(name, "humanoid"))
        selected = "humanoid" if humanoid else "animal"
    if selected not in catalog.sets:
        raise ExpressionSetError(f"Unknown expression set '{selected}'; choose a valid set in character settings", 409)
    return catalog.sets[selected]


def sets_payload(catalog=None):
    from dataclasses import asdict
    cat = catalog_snapshot() if catalog is None else catalog
    return {key: asdict(spec) for key, spec in cat.sets.items()}


def _write_world(conn, kind, documents):
    from app.core.timeutils import utc_now_iso
    conn.execute("DELETE FROM pose_catalog_world WHERE axis='expression' AND kind=?", (kind,))
    for key, doc in documents.items():
        conn.execute("INSERT INTO pose_catalog_world(axis,kind,key,doc,updated_at) VALUES('expression',?,?,?,?)",
                     (kind, key, json.dumps(doc, ensure_ascii=False), utc_now_iso()))


def _edit(change):
    from app.core.pose_catalog_edit import catalog_txn, after_write
    from app.core.db import transaction
    with catalog_txn("expression"):
        shared, world = _documents()
        original = deepcopy(shared)
        shared_written = False
        try:
            with transaction() as conn:
                result = change(shared, world, conn)
                marker = conn.execute("SELECT value FROM schema_meta WHERE key='expression_sets_v1'").fetchone()
                legacy_shared = json.loads(marker[0]) if marker else []
                problems = validate_expression_catalog(
                    _snapshot(shared, {"entries": {}, "groups": {}}), legacy_shared_keys=legacy_shared)
                problems += validate_expression_catalog(_snapshot(shared, world))
                if problems:
                    raise ExpressionSetError("; ".join(problems))
                if shared != original:
                    pose_catalog.write_shared_document("expression", shared)
                    shared_written = True
                _write_world(conn, "entry", world["entries"])
                _write_world(conn, "group", world["groups"])
        except BaseException:
            if shared_written:
                pose_catalog.write_shared_document("expression", original)
            raise
        after_write()
        return result


def _store(value):
    if value not in pose_catalog.STORES:
        raise ExpressionSetError("Store must be shared or world")
    return value


def _key(value):
    from app.core.pose_catalog_edit import validate_key
    return validate_key(value)


def _membership_groups(shared, world, set_id, store, spec):
    """Keep Shared membership valid independently of the current World override."""
    if store == "shared":
        if set_id not in shared["groups"]:
            raise ExpressionSetError("Publish the World-only expression set to Shared before publishing individual members")
        groups = [shared["groups"][set_id]]
        if set_id in world["groups"]:
            groups.append(world["groups"][set_id])
        return groups
    group = world["groups"].setdefault(set_id, {
        "label": spec.label, "default": spec.default,
        "pose_prompt": spec.pose_prompt, "members": list(spec.members)})
    return [group]


def replace_set(set_id: str, document: Mapping, *, store: str) -> None:
    sid, store = _key(set_id), _store(store)
    def change(shared, world, conn):
        doc = world if store == "world" else shared
        members = list(document.get("members") or [])
        for key, entry in (document.get("entries") or {}).items():
            key = _key(key)
            if key in _snapshot(shared, world).entries:
                raise ExpressionSetError(f"Expression '{key}' already exists", 409)
            doc["entries"][key] = {"label": str(entry.get("label") or key),
                                     "prompt": str(entry.get("prompt") or "").strip(),
                                     "synonyms": list(entry.get("synonyms") or [])}
            if key not in members:
                members.append(key)
        doc["groups"][sid] = {"label": str(document.get("label") or sid),
                              "default": str(document.get("default") or ""),
                              "pose_prompt": str(document.get("pose_prompt") or "").strip(),
                              "members": members}
        if store == "shared":
            for key in members:
                if key not in shared["entries"] and key in world["entries"]:
                    shared["entries"][key] = world["entries"].pop(key)
            world["groups"].pop(sid, None)
    _edit(change)


def delete_set(set_id: str, *, store: str) -> None:
    sid, store = _key(set_id), _store(store)
    def change(shared, world, conn):
        doc = world if store == "world" else shared
        if sid not in doc["groups"]:
            raise ExpressionSetError("Expression set not found", 404)
        revealed = store == "world" and sid in shared["groups"]
        if not revealed:
            if sid in SHIPPED_SETS:
                raise ExpressionSetError("Shipped expression sets cannot be deleted")
            for row in conn.execute("SELECT name, profile_json FROM characters"):
                if json.loads(row[1] or "{}").get("expression_set") == sid:
                    raise ExpressionSetError(f"Expression set is selected by '{row[0]}'", 409)
        old = doc["groups"].pop(sid)
        if revealed:
            for key in set(old["members"]) - set(shared["groups"][sid]["members"]):
                world["entries"].pop(key, None)
        else:
            members = set(old["members"])
            if store == "shared":
                override = world["groups"].pop(sid, None)
                if override:
                    members.update(override["members"])
            for layer in (shared, world):
                for key in members:
                    layer["entries"].pop(key, None)
    _edit(change)


def edit_entry(action: str, key: str, body: Mapping, *, set_id: str):
    key = _key(key)
    def change(shared, world, conn):
        effective = _snapshot(shared, world)
        spec = effective.sets.get(set_id)
        if spec is None:
            raise ExpressionSetError("Unknown expression set")
        old = effective.entries.get(key)
        if action != "create" and (old is None or key not in spec.members):
            raise ExpressionSetError("Expression is not in the selected set", 404)
        if action == "create" and old is not None:
            raise ExpressionSetError("Expression already exists", 409)
        store = _store(body.get("store") or (old["_store"] if old else "shared"))
        layer = world if store == "world" else shared
        if action == "delete":
            actual_store = old["_store"]
            actual_layer = world if actual_store == "world" else shared
            groups = _membership_groups(shared, world, set_id, actual_store, spec)
            actual_layer["entries"].pop(key)
            if key not in _snapshot(shared, world).entries:
                for group in groups:
                    if key in group["members"]:
                        group["members"].remove(key)
        elif action == "rename":
            new = _key(body.get("new_key"))
            if new in effective.entries:
                raise ExpressionSetError("Expression already exists", 409)
            if key in shared["entries"]:
                for group in _membership_groups(shared, world, set_id, "shared", spec):
                    if key not in group["members"]:
                        group["members"].append(key)
            for document in (shared, world):
                if key in document["entries"]:
                    document["entries"][new] = document["entries"].pop(key)
                for g in document["groups"].values():
                    g["members"] = [new if k == key else k for k in g["members"]]
                    if g["default"] == key:
                        g["default"] = new
            conn.execute("UPDATE pose_candidates SET nearest_key=? WHERE axis='expression' AND set_id=? AND nearest_key=?", (new, set_id, key))
            return new
        else:
            entry = dict(old or {})
            entry.pop("_store", None)
            for field in ("label", "prompt", "synonyms"):
                if field in body:
                    entry[field] = list(body[field]) if field == "synonyms" else str(body[field]).strip()
            if not entry.get("prompt"):
                raise ExpressionSetError("Expression prompt is required")
            entry["synonyms"] = [str(s).strip().lower() for s in entry.get("synonyms", [])]
            groups = _membership_groups(shared, world, set_id, store, spec)
            layer["entries"][key] = entry
            for group in groups:
                if key not in group["members"]:
                    group["members"].append(key)
            if store == "shared" and old and old["_store"] == "world":
                world["entries"].pop(key, None)
        return key
    return _edit(change)


_embedding_maps = {}


def alias_embeddings(catalog, spec, embed_fn):
    """Cache one set's vectors under its captured catalog/model identity."""
    cache_key = (catalog.revision, spec.id, pose_catalog._embed_model_key(embed_fn))
    cached = _embedding_maps.get(cache_key)
    if cached is not None:
        return cached
    aliases = {alias for key in spec.members for alias in (key, *catalog.entries[key]["synonyms"])}
    vectors = {alias: vector for alias in sorted(aliases) if (vector := embed_fn(alias))}
    if vectors:
        if len(_embedding_maps) >= 64:
            _embedding_maps.clear()
        _embedding_maps[cache_key] = vectors
    return vectors


def resolve_text(text: str, *, set_id: str, embed_fn=None):
    """Resolve within one immutable set, rejecting stale decision answers."""
    import uuid
    from app.core import decision, decision_points, embedding
    cat = catalog_snapshot()
    spec = cat.sets.get(set_id)
    if spec is None:
        raise ExpressionSetError("A valid expression set is required")
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return spec.default, "empty"
    aliases = {alias: key for key in spec.members
               for alias in (key, *cat.entries[key]["synonyms"])}
    if cleaned in aliases:
        return aliases[cleaned], "exact"
    point = decision_points.CATALOG_POINTS["expression"]
    dkey = f"expression:{set_id}:{uuid.uuid4().hex}"
    if decision.is_active(point):
        questions, then = decision_points.catalog_questions("expression", set_id=set_id)
        answer = decision.decide(point, {"text": cleaned, "expression_set": set_id},
                                 questions, key=dkey, then=then)
        chosen = answer.answers.get("entry") if answer else None
        if chosen is not None and catalog_snapshot().revision == cat.revision:
            if chosen.value in spec.members:
                decision.mark_taken(point, dkey)
                return chosen.value, "decision"
            if chosen.value == decision_points.NONE_KEY:
                decision.mark_taken(point, dkey)
                pose_catalog.record_candidate("expression", cleaned, "", None, set_id=set_id)
                return spec.default, "decision_none"
    fn = embed_fn or embedding.embed
    query = fn(cleaned)
    vectors = alias_embeddings(cat, spec, fn)
    best_alias, score = "", 0.0
    if query:
        for alias, vector in vectors.items():
            similarity = embedding.cosine_similarity(query, vector)
            if similarity > score:
                best_alias, score = alias, similarity
    current = catalog_snapshot()
    if current.revision != cat.revision:
        current_spec = current.sets.get(set_id)
        if current_spec is None:
            raise ExpressionSetError("Expression set changed during matching", 409)
        return current_spec.default, "fallback"
    hit = aliases.get(best_alias)
    if hit and score >= pose_catalog.CATALOG_THRESHOLD:
        result, how = hit, "embedding"
    else:
        pose_catalog.record_candidate("expression", cleaned, hit or "", 1.0 - score if query else None, set_id=set_id)
        result, how = spec.default, "fallback"
    if decision.is_active(point):
        decision.record_outcome(point, dkey, {"entry": result if how == "embedding" else decision_points.NONE_KEY})
    return result, how


def approve_candidate(body):
    """Absorb one set-scoped candidate and its catalog update in one commit."""
    sid = str(body.get("set_id") or "")
    raw = str(body.get("raw_text") or "").strip().lower()
    def change(shared, world, conn):
        cat = _snapshot(shared, world)
        spec = cat.sets.get(sid)
        if spec is None or not raw:
            raise ExpressionSetError("Expression set and candidate text are required")
        if conn.execute("SELECT 1 FROM pose_candidates WHERE axis='expression' AND set_id=? AND raw_text=?", (sid, raw)).fetchone() is None:
            raise ExpressionSetError("Candidate not found in the selected set", 404)
        target = str(body.get("as_synonym_of") or "")
        if target:
            if target not in spec.members:
                raise ExpressionSetError("Target is not in the selected expression set")
            store = cat.entries[target]["_store"]
            layer = world if store == "world" else shared
            entry = layer["entries"][target]
            entry["synonyms"] = list(dict.fromkeys([*entry.get("synonyms", []), raw]))
            key = target
        else:
            key = _key(body.get("key"))
            if key in cat.entries:
                raise ExpressionSetError("Expression already exists", 409)
            store = _store(body.get("store") or "shared")
            layer = world if store == "world" else shared
            layer["entries"][key] = {"label": str(body.get("label") or key),
                                      "prompt": str(body.get("prompt") or "").strip(),
                                      "synonyms": list(dict.fromkeys([*body.get("synonyms", []), raw]))}
            for group in _membership_groups(shared, world, sid, store, spec):
                if key not in group["members"]:
                    group["members"].append(key)
        conn.execute("DELETE FROM pose_candidates WHERE axis='expression' AND set_id=? AND raw_text=?", (sid, raw))
        return {"status": "success", "axis": "expression", "set_id": sid, "key": key, "store": store}
    return _edit(change)
