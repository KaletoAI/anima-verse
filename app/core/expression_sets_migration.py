"""One-time expression metadata and candidate-key migrations; never renders."""
import json


def migrate_candidates(conn):
    from app.core.world_db_schema import POSE_CANDIDATES_TABLE_SQL
    info = conn.execute("PRAGMA table_info(pose_candidates)").fetchall()
    primary = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
    if primary == ["axis", "set_id", "raw_text"]:
        return
    conn.execute("SAVEPOINT expression_candidates")
    try:
        conn.execute("ALTER TABLE pose_candidates RENAME TO pose_candidates_old")
        conn.execute(POSE_CANDIDATES_TABLE_SQL)
        conn.execute("INSERT INTO pose_candidates(axis,set_id,raw_text,nearest_key,distance,count,status,first_seen,last_seen) "
                     "SELECT axis,CASE WHEN axis='expression' THEN 'humanoid' ELSE '' END,"
                     "raw_text,nearest_key,distance,count,status,first_seen,last_seen FROM pose_candidates_old")
        conn.execute("DROP TABLE pose_candidates_old")
        conn.execute("RELEASE expression_candidates")
    except BaseException:
        conn.execute("ROLLBACK TO expression_candidates")
        conn.execute("RELEASE expression_candidates")
        raise


def migrate_catalog_metadata():
    from app.core.db import transaction
    from app.core.expression_sets import _documents, _snapshot, _write_world, validate_expression_catalog, ExpressionSetError
    from app.core.pose_catalog_edit import catalog_txn, after_write
    with catalog_txn("expression"):
        with transaction() as conn:
            if conn.execute("SELECT 1 FROM schema_meta WHERE key='expression_sets_v1'").fetchone():
                return
            shared, world = _documents()
            effective = _snapshot(shared, world)
            humanoid = effective.sets.get("humanoid")
            if humanoid is None:
                raise ExpressionSetError("Expression catalog needs shipped set metadata before migration")
            members = set(k for spec in effective.sets.values() for k in spec.members)
            extra = sorted(set(effective.entries) - members)
            # Existing world entries that collide with shipped animal keys may
            # be unrelated user content. Never silently assign those to animals.
            animal_members = set(effective.sets["animal"].members)
            if animal_members.intersection(world["entries"]):
                raise ExpressionSetError("Legacy World entries collide with shipped animal expression keys; rename them before migrating", 409)
            legacy_defaults = [k for k, e in {**shared["entries"], **world["entries"]}.items()
                               if e.get("_default") and k in (*humanoid.members, *extra)]
            if extra or legacy_defaults:
                group = {"label": humanoid.label, "default": legacy_defaults[0] if len(legacy_defaults) == 1 else humanoid.default,
                         "pose_prompt": humanoid.pose_prompt, "members": [*humanoid.members, *extra]}
                world["groups"]["humanoid"] = group
            problems = validate_expression_catalog(_snapshot(shared, world))
            if problems:
                raise ExpressionSetError("; ".join(problems), 409)
            _write_world(conn, "group", world["groups"])
            shared_members = {key for group in shared["groups"].values() for key in group["members"]}
            legacy_shared = sorted(set(shared["entries"]) - shared_members)
            conn.execute("INSERT INTO schema_meta(key,value) VALUES('expression_sets_v1',?)", (json.dumps(legacy_shared),))
        after_write()
