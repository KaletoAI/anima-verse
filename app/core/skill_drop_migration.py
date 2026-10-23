"""Remove obsolete skill-addressed state prompt drops once per world."""
import json


def migrate_skill_drop_blocks_once() -> int:
    """Keep unrelated drops and metadata; mark completion in the same transaction."""
    from app.core.db import transaction
    with transaction() as conn:
        marker = 'migration:skill_drop_blocks_removed'
        if conn.execute('SELECT 1 FROM world_kv WHERE key=?', (marker,)).fetchone():
            return 0
        count = 0
        for row in conn.execute('SELECT id, drop_blocks FROM prompt_filters').fetchall():
            drops = json.loads(row[1] or '[]')
            kept = [drop for drop in drops if not (isinstance(drop, str) and drop.startswith('skill:'))]
            if kept != drops:
                conn.execute('UPDATE prompt_filters SET drop_blocks=? WHERE id=?',
                             (json.dumps(kept), row[0]))
                count += 1
        conn.execute('INSERT INTO world_kv (key, value) VALUES (?, ?)', (marker, '1'))
    from app.core.prompt_filters import invalidate_filter_snapshot
    invalidate_filter_snapshot()
    return count
