"""Schema-Definitionen fuer die Welt-DB.

Alle CREATE TABLE / CREATE INDEX Statements zentral verwaltet. Migrations-
Philosophie: idempotent, IF NOT EXISTS ueberall — Schema-Aenderungen laufen
bei jedem init_schema() durch.

Konventionen:
- Primary Keys als explizites PK, keine ROWID-Abhaengigkeiten
- Timestamps als ISO-Strings (TEXT) fuer Sort-Ordering
- Komplexe/variable Strukturen als JSON-Blobs (TEXT + json_valid Check)
- IDs fuer Welt-Items mit Praefix `w_`, Shared mit `s_` (Shared bleibt JSON)
- Foreign Keys: AN, ON DELETE CASCADE wo sinnvoll
"""

SCHEMA_VERSION = 8  # 8: seamless world — metre positions, terrain tables


# Room ids are unique PER LOCATION, not globally — that is the documented
# model (plan-grundflaeche.md § 3) and what makes ONE reserved ground-room id
# work in every location. The table said something else for a long time
# (`id TEXT PRIMARY KEY`), which let a save of location A steal the physical
# row of location B. Defined as its own constant because db.py needs the very
# same statement to rebuild existing worlds — one definition, no drift.
ROOMS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS rooms (
        id            TEXT NOT NULL,
        location_id   TEXT NOT NULL,
        name          TEXT NOT NULL,
        outfit_type   TEXT DEFAULT '',
        decency       TEXT DEFAULT '',
        style_hint    TEXT DEFAULT '',
        swim_allowed  INTEGER NOT NULL DEFAULT 0,
        activity_hint TEXT DEFAULT '',
        meta          TEXT DEFAULT '{}',
        PRIMARY KEY (location_id, id),
        FOREIGN KEY(location_id) REFERENCES locations(id) ON DELETE CASCADE
    )"""

# The columns the rebuild copies over, in one place: the CREATE above and the
# INSERT ... SELECT in db.py have to agree.
ROOMS_COLUMNS = ("id", "location_id", "name", "outfit_type", "decency",
                 "style_hint", "swim_allowed", "activity_hint", "meta")


def rooms_rebuild_needed(table_info) -> bool:
    """Whether the ``rooms`` table still carries the OLD single-column key.

    ``table_info`` are the rows of ``PRAGMA table_info(rooms)``:
    ``(cid, name, type, notnull, dflt_value, pk)``, where ``pk`` is the
    1-based position of the column in the PRIMARY KEY and 0 means "not part
    of it". The key has to be exactly (location_id, id); anything else is the
    old shape. No columns at all means there is no such table yet — nothing
    to rebuild.

    Pure, so ``scripts/smoke_ground_room.py`` can check it by hand.
    """
    pk_cols = {str(row[1]) for row in table_info if int(row[5] or 0) > 0}
    if not pk_cols:
        return False
    return pk_cols != {"location_id", "id"}


SCHEMA_STATEMENTS = [
    # ── Kern / Welt ────────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS world_kv (
        key   TEXT PRIMARY KEY,
        value TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS locations (
        id               TEXT PRIMARY KEY,
        name             TEXT NOT NULL,
        description      TEXT DEFAULT '',
        pos_x            REAL,
        pos_z            REAL,
        yaw_deg          REAL NOT NULL DEFAULT 0,
        outfit_type      TEXT DEFAULT '',
        decency          TEXT DEFAULT '',
        style_hint       TEXT DEFAULT '',
        swim_allowed     INTEGER NOT NULL DEFAULT 0,
        activity_hint    TEXT DEFAULT '',
        image_prompt_day TEXT DEFAULT '',
        image_prompt_night TEXT DEFAULT '',
        image_prompt_map TEXT DEFAULT '',
        visible_when     TEXT DEFAULT '[]',
        accessible_when  TEXT DEFAULT '[]',
        background_images TEXT DEFAULT '[]',
        meta             TEXT DEFAULT '{}',
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL
    )""",
    ROOMS_TABLE_SQL,
    """CREATE TABLE IF NOT EXISTS rules (
        id       TEXT PRIMARY KEY,
        text     TEXT NOT NULL,
        category TEXT DEFAULT '',
        meta     TEXT DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS status_modifiers (
        id     TEXT PRIMARY KEY,
        name   TEXT NOT NULL,
        effect TEXT DEFAULT '{}'
    )""",
    # Prompt-Filter: pro Zustand (drunk, exhausted, ...) wird definiert
    # welche Bloecke aus dem Thought-Prompt rausfliegen + welcher Modifier-
    # Text dem LLM stattdessen gezeigt wird. Ueberschreibt by id den
    # gleichnamigen Eintrag aus shared/prompt_filters/filters.json.
    """CREATE TABLE IF NOT EXISTS prompt_filters (
        id              TEXT PRIMARY KEY,
        condition       TEXT NOT NULL,
        label           TEXT DEFAULT '',
        drop_blocks     TEXT DEFAULT '[]',
        prompt_modifier TEXT DEFAULT '',
        enabled         INTEGER NOT NULL DEFAULT 1,
        meta            TEXT DEFAULT '{}',
        icon            TEXT DEFAULT '',
        image_modifier  TEXT DEFAULT ''
    )""",

    # ── Characters ─────────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS characters (
        name         TEXT PRIMARY KEY,
        template     TEXT DEFAULT '',
        profile_json TEXT DEFAULT '{}',   -- Stamm+Config als Blob (bewusst)
        config_json  TEXT DEFAULT '{}',   -- Stamm+Config als Blob (bewusst)
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS character_state (
        character_name    TEXT PRIMARY KEY,
        current_location  TEXT DEFAULT '',
        current_room      TEXT DEFAULT '',
        current_activity  TEXT DEFAULT '',
        current_feeling   TEXT DEFAULT '',
        pose_key          TEXT DEFAULT '',
        pose_flavor       TEXT DEFAULT '',
        pose_variant_id   INTEGER,         -- RETIRED (Aug 2026), never written
        location_changed_at TEXT DEFAULT '',
        activity_changed_at TEXT DEFAULT '',
        last_thought_at   TEXT DEFAULT '',
        pos_x             REAL,            -- free metre position (seamless world)
        pos_z             REAL,            -- NULL = no position yet / unplaced location
        meta              TEXT DEFAULT '{}',
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",

    # ── Chat-Historie ──────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS chat_messages (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        partner        TEXT NOT NULL,
        ts             TEXT NOT NULL,
        role           TEXT NOT NULL,          -- user | assistant | system
        content        TEXT NOT NULL,
        channel        TEXT DEFAULT 'web',
        channel_message_id TEXT DEFAULT NULL,
        metadata       TEXT DEFAULT '{}',
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_chat_char_partner_ts ON chat_messages (character_name, partner, ts)",
    "CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_messages (ts)",

    # ── Raum-Konversation: Wahrnehmungs-Stream ─────────────────────────
    # plan-room-conversation Phase 1. `utterances` = kanonische Wahrheit
    # (eine Zeile pro Sprechakt), `perceptions` = Fan-Out (eine Zeile pro
    # Wahrnehmendem, beim Schreiben bereits gefiltert). Geheimer Inhalt
    # liegt NUR in `utterances`; whisper_meta-Perceptions tragen keinen Inhalt.
    """CREATE TABLE IF NOT EXISTS utterances (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ts           TEXT NOT NULL,
        speaker      TEXT NOT NULL,
        location_id  TEXT DEFAULT '',
        room_id      TEXT DEFAULT '',
        volume       TEXT NOT NULL,            -- whisper | normal | shout
        addressees   TEXT DEFAULT '[]',        -- json-Liste ([] = an den Raum)
        content      TEXT NOT NULL,
        meta         TEXT DEFAULT '{}',        -- meta.source = shadow | inject | ...
        pos_x        REAL,                     -- speaker's metre point, wilderness only
        pos_z        REAL                      -- NULL for every utterance inside a location
    )""",
    "CREATE INDEX IF NOT EXISTS idx_utterances_room_ts ON utterances (location_id, room_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_utterances_ts ON utterances (ts)",
    """CREATE TABLE IF NOT EXISTS perceptions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        perceiver    TEXT NOT NULL,
        utterance_id INTEGER NOT NULL,
        ts           TEXT NOT NULL,
        kind         TEXT NOT NULL,            -- spoken_self | in_room | whisper_meta | distant_shout | nearby
        content      TEXT NOT NULL DEFAULT '', -- fuer diesen Perceiver gefiltert; '' bei whisper_meta
        meta         TEXT DEFAULT '{}',
        FOREIGN KEY(utterance_id) REFERENCES utterances(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_perceptions_perceiver_ts ON perceptions (perceiver, ts)",
    "CREATE INDEX IF NOT EXISTS idx_perceptions_utterance ON perceptions (utterance_id)",

    # Szenen (plan-room-conversation §7): eine offene Szene pro Raum, getouched
    # bei jeder Äußerung. Beim Verebben (Idle) schließt der Loop sie, konsolidiert
    # die Roh-Wahrnehmungen in eine Szenen-Summary (→ Teilnehmer-Gedächtnis) und
    # prunt die Perceptions. status: open | consolidated.
    """CREATE TABLE IF NOT EXISTS scenes (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        location_id    TEXT NOT NULL,
        room_id        TEXT NOT NULL DEFAULT '',
        started_ts     TEXT NOT NULL,
        last_activity_ts TEXT NOT NULL,
        participants   TEXT NOT NULL DEFAULT '[]',  -- JSON-Liste Charakternamen
        status         TEXT NOT NULL DEFAULT 'open', -- open | consolidated
        summary        TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_scenes_open ON scenes (status, location_id, room_id)",
    "CREATE INDEX IF NOT EXISTS idx_scenes_activity ON scenes (status, last_activity_ts)",

    # ── Gedanken-Journal (plan-thought-journal.md) ─────────────────────
    # Das Narrativ eines Thought-Turns — PRIVAT. Genau drei Konsumenten:
    # der eigene naechste Thought-Prompt, die eigene Tages-Konsolidierung,
    # das Admin-Panel. Es fliesst NIE in den Perception-Stream, in fremde
    # Prompts, in Chat-Historien oder in Notifications; Speichern ist
    # Lagerung, keine Zustellung (der Verbs-only-Vertrag bleibt). Roh ist
    # transient: nach der Tages-Konsolidierung wird geprunt.
    """CREATE TABLE IF NOT EXISTS thoughts (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        ts             TEXT NOT NULL,           -- SYSTEM time (utc_now_iso)
        location_id    TEXT DEFAULT '',
        room_id        TEXT DEFAULT '',
        content        TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_thoughts_char_ts ON thoughts (character_name, ts)",

    # ── Memories / Summaries ───────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS memories (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        tier           TEXT NOT NULL,          -- episodic | daily | weekly | monthly | relationship | ...
        ts             TEXT NOT NULL,
        content        TEXT NOT NULL,
        source_ids     TEXT DEFAULT '[]',
        tags           TEXT DEFAULT '[]',
        meta           TEXT DEFAULT '{}',
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_memories_char_tier_ts ON memories (character_name, tier, ts)",
    """CREATE TABLE IF NOT EXISTS summaries (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        kind           TEXT NOT NULL,          -- daily | weekly | monthly | history
        date_key       TEXT NOT NULL,          -- YYYY-MM-DD oder ISO-Week
        partner        TEXT NOT NULL DEFAULT '', -- Konversationspartner (Charaktername) — leer fuer kind='history' (sliding window)
        content        TEXT NOT NULL,
        meta           TEXT DEFAULT '{}',
        UNIQUE(character_name, kind, date_key, partner),
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",

    # ── Histories (Zeit-Serien) ────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS mood_history (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        ts             TEXT NOT NULL,
        mood           TEXT NOT NULL,
        source         TEXT DEFAULT '',
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_mood_char_ts ON mood_history (character_name, ts)",
    """CREATE TABLE IF NOT EXISTS state_history (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        ts             TEXT NOT NULL,
        state_json     TEXT NOT NULL,
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_state_char_ts ON state_history (character_name, ts)",
    """CREATE TABLE IF NOT EXISTS evolution_history (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        ts             TEXT NOT NULL,
        field          TEXT NOT NULL,
        old_value      TEXT,
        new_value      TEXT,
        reason         TEXT DEFAULT '',
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    # social_dialog_history ist entfernt — Social-Dialog laeuft als forced_thought
    # ueber die normale Chat-History (plan-thoughts-and-conversation).
    """CREATE TABLE IF NOT EXISTS diary_entries (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        ts             TEXT NOT NULL,
        content        TEXT NOT NULL,
        tags           TEXT DEFAULT '[]',
        meta           TEXT DEFAULT '{}',
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",

    # ── Content (Welt-Level) ───────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS items (
        id            TEXT PRIMARY KEY,         -- w_... (Welt) / s_... (nur referenziert, liegt in shared)
        name          TEXT NOT NULL,
        category      TEXT DEFAULT '',
        prompt_fragment TEXT DEFAULT '',
        pieces        TEXT DEFAULT '{}',
        slots         TEXT DEFAULT '[]',
        meta          TEXT DEFAULT '{}',
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS activities (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        category     TEXT DEFAULT '',
        meta         TEXT DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        topic          TEXT DEFAULT '',
        content        TEXT NOT NULL,
        tier           TEXT DEFAULT '',
        ts             TEXT NOT NULL,
        meta           TEXT DEFAULT '{}',
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_char ON knowledge (character_name)",
    """CREATE TABLE IF NOT EXISTS secrets (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name TEXT NOT NULL,
        content        TEXT NOT NULL,
        visibility     TEXT DEFAULT '{}',
        meta           TEXT DEFAULT '{}',
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS assignments (
        id             TEXT PRIMARY KEY,
        character_name TEXT,
        task           TEXT NOT NULL,
        status         TEXT DEFAULT 'open',
        due            TEXT DEFAULT '',
        meta           TEXT DEFAULT '{}',
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL
    )""",
    # Vereinheitlichte Intents (plan-intents-unified.md): EIN Eintrag für alles,
    # was ein Character tun soll/will — vom Menschen gesetzt (source=human, frühere
    # Assignments) ODER vom Character (source=character: Versprechen, Retrospect-
    # Ziele). trigger/action/participants/meta als JSON.
    """CREATE TABLE IF NOT EXISTS intents (
        id             TEXT PRIMARY KEY,
        source         TEXT NOT NULL DEFAULT 'character',
        owner          TEXT NOT NULL DEFAULT '',
        participants   TEXT NOT NULL DEFAULT '{}',
        title          TEXT NOT NULL DEFAULT '',
        description    TEXT NOT NULL DEFAULT '',
        trigger        TEXT NOT NULL DEFAULT '{}',
        action         TEXT NOT NULL DEFAULT '{}',
        priority       INTEGER NOT NULL DEFAULT 3,
        status         TEXT NOT NULL DEFAULT 'active',
        location_id    TEXT NOT NULL DEFAULT '',
        target_count   INTEGER NOT NULL DEFAULT 0,
        outfit_hint    TEXT NOT NULL DEFAULT '',
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL,
        expires_at     TEXT NOT NULL DEFAULT '',
        meta           TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS stories (
        id             TEXT PRIMARY KEY,
        title          TEXT NOT NULL,
        content        TEXT DEFAULT '',
        character_name TEXT,
        meta           TEXT DEFAULT '{}',
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS story_arcs (
        id           TEXT PRIMARY KEY,
        title        TEXT NOT NULL,
        state        TEXT DEFAULT 'active',
        beats        TEXT DEFAULT '[]',
        participants TEXT DEFAULT '[]',
        meta         TEXT DEFAULT '{}',
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS outfits_sets (
        id             TEXT PRIMARY KEY,
        character_name TEXT NOT NULL,
        name           TEXT NOT NULL,
        pieces         TEXT DEFAULT '{}',
        image          TEXT DEFAULT '',
        meta           TEXT DEFAULT '{}',
        created_at     TEXT NOT NULL,
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",

    # ── Events / Notifications / Relations ─────────────────────────────
    """CREATE TABLE IF NOT EXISTS events (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        ts             TEXT NOT NULL,
        kind           TEXT NOT NULL,
        character_name TEXT,
        payload        TEXT DEFAULT '{}'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts)",
    "CREATE INDEX IF NOT EXISTS idx_events_kind ON events (kind, ts)",
    """CREATE TABLE IF NOT EXISTS character_action_log (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name       TEXT NOT NULL,
        scope                TEXT NOT NULL,
        location_id          TEXT DEFAULT '',
        room_id              TEXT DEFAULT '',
        user_input           TEXT NOT NULL,
        storyteller_response TEXT DEFAULT '',
        event_resolved       INTEGER NOT NULL DEFAULT 0,
        event_id             TEXT DEFAULT '',
        created_at           TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_action_log_char ON character_action_log (character_name, created_at DESC)",
    """CREATE TABLE IF NOT EXISTS notifications (
        id     INTEGER PRIMARY KEY AUTOINCREMENT,
        ts     TEXT NOT NULL,
        kind   TEXT NOT NULL,
        title  TEXT DEFAULT '',
        body   TEXT DEFAULT '',
        read   INTEGER NOT NULL DEFAULT 0,
        meta   TEXT DEFAULT '{}'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_notifications_ts ON notifications (ts)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications (read, ts)",
    """CREATE TABLE IF NOT EXISTS relationships (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        from_char    TEXT NOT NULL,
        to_char      TEXT NOT NULL,
        content      TEXT NOT NULL,
        ts           TEXT NOT NULL,
        meta         TEXT DEFAULT '{}'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_relationships_pair ON relationships (from_char, to_char, ts)",
    """CREATE TABLE IF NOT EXISTS group_chats (
        id           TEXT PRIMARY KEY,
        participants TEXT DEFAULT '[]',
        messages     TEXT DEFAULT '[]',
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    )""",

    # ── Inventar ──────────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS inventory_items (
        character_name TEXT NOT NULL,
        item_id        TEXT NOT NULL,
        quantity       INTEGER NOT NULL DEFAULT 1,
        acquired_at    TEXT NOT NULL,
        meta           TEXT DEFAULT '{}',
        PRIMARY KEY (character_name, item_id),
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS equipped_pieces (
        character_name TEXT NOT NULL,
        slot           TEXT NOT NULL,
        item_id        TEXT NOT NULL,
        color_meta     TEXT DEFAULT '{}',
        PRIMARY KEY (character_name, slot),
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS equipped_items (
        character_name TEXT NOT NULL,
        item_id        TEXT NOT NULL,
        PRIMARY KEY (character_name, item_id),
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",

    # ── Scheduler ──────────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS scheduler_jobs (
        id             TEXT PRIMARY KEY,
        character_name TEXT,
        action         TEXT NOT NULL,
        trigger        TEXT NOT NULL,
        source         TEXT DEFAULT '',
        meta           TEXT DEFAULT '{}',
        created_at     TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_scheduler_char ON scheduler_jobs (character_name)",
    """CREATE TABLE IF NOT EXISTS scheduler_logs (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id  TEXT NOT NULL,
        ts      TEXT NOT NULL,
        status  TEXT NOT NULL,
        result  TEXT DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_scheduler_logs_job_ts ON scheduler_logs (job_id, ts)",
    """CREATE TABLE IF NOT EXISTS daily_schedules (
        character_name TEXT PRIMARY KEY,
        enabled        INTEGER NOT NULL DEFAULT 0,
        slots          TEXT DEFAULT '[]',
        meta           TEXT DEFAULT '{}'
    )""",

    # ── Telegram / Session / Account ───────────────────────────────────
    """CREATE TABLE IF NOT EXISTS telegram_mapping (
        chat_id        TEXT PRIMARY KEY,
        character_name TEXT NOT NULL,        -- NPC (Bot-Character) dieses Chats
        avatar         TEXT NOT NULL DEFAULT '',  -- gebundener Avatar (Telegram-User = Character, Option B)
        created_at     TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS account (
        id            INTEGER PRIMARY KEY CHECK (id = 1),    -- single-row
        user_name     TEXT NOT NULL DEFAULT 'admin',
        password_hash TEXT DEFAULT '',
        theme         TEXT DEFAULT '',
        settings      TEXT DEFAULT '{}',
        updated_at    TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS session_kv (
        key   TEXT PRIMARY KEY,
        value TEXT
    )""",

    # ── Image-Metadaten (redundant zum Sidecar-JSON auf Disk) ──────────
    """CREATE TABLE IF NOT EXISTS image_metadata (
        filename       TEXT PRIMARY KEY,
        character_name TEXT,
        directory      TEXT NOT NULL,          -- images | outfits | instagram | world_gallery | ...
        prompt         TEXT DEFAULT '',
        negative_prompt TEXT DEFAULT '',
        seed           INTEGER,
        backend        TEXT DEFAULT '',
        model          TEXT DEFAULT '',
        workflow       TEXT DEFAULT '',
        created_at     TEXT NOT NULL,
        sidecar_json   TEXT DEFAULT '{}'       -- voller Sidecar-Inhalt als Blob fuer Queries
    )""",
    "CREATE INDEX IF NOT EXISTS idx_image_char ON image_metadata (character_name, directory)",
    "CREATE INDEX IF NOT EXISTS idx_image_created ON image_metadata (created_at)",

    # ── Model-Capabilities (Cache) ─────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS model_capabilities (
        model        TEXT PRIMARY KEY,
        capabilities TEXT DEFAULT '{}'
    )""",

    # ── Multiuser / Auth (Phase 1) ─────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS users (
        id                 TEXT PRIMARY KEY,          -- UUID
        username           TEXT NOT NULL UNIQUE,
        password_hash      TEXT NOT NULL,
        role               TEXT NOT NULL,             -- admin | user
        allowed_characters TEXT NOT NULL DEFAULT '[]',
        theme              TEXT DEFAULT '',
        settings           TEXT DEFAULT '{}',
        created_at         TEXT NOT NULL,
        last_login         TEXT DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_users_username ON users (username)",

    """CREATE TABLE IF NOT EXISTS user_sessions (
        token         TEXT PRIMARY KEY,               -- opaque session ID
        user_id       TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        expires_at    TEXT NOT NULL,
        last_activity TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON user_sessions (expires_at)",

    """CREATE TABLE IF NOT EXISTS character_locks (
        character_name TEXT PRIMARY KEY,
        user_id        TEXT NOT NULL,
        acquired_at    TEXT NOT NULL,
        last_activity  TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",

    # ── Pose variants (step 5, May 2026) — RETIRED (Aug 2026) ────────────
    # The per-character pose-variant cache is gone: expression images are
    # keyed by the pose/expression catalog keys directly, so nothing reads or
    # writes this table any more. Kept as an empty shell because this stream
    # ships no DB migrations; drop it when a migration pass comes along.
    """CREATE TABLE IF NOT EXISTS character_pose_variants (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        character_name  TEXT NOT NULL,
        canonical_pose  TEXT NOT NULL,
        embedding       BLOB,
        example_image   TEXT DEFAULT '',
        use_count       INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT NOT NULL,
        last_used_at    TEXT NOT NULL,
        FOREIGN KEY(character_name) REFERENCES characters(name) ON DELETE CASCADE
    )""",
    # RETIRED with the table above — no reader, no writer.
    "CREATE INDEX IF NOT EXISTS idx_cpv_char ON character_pose_variants (character_name)",
    "CREATE INDEX IF NOT EXISTS idx_cpv_lru ON character_pose_variants (character_name, last_used_at)",

    # ── Pose/Expression catalog candidates (plan-pose-katalog.md) ─────────
    # Free text that could NOT be mapped onto a catalog entry is logged here
    # instead of silently becoming a render key. The admin reviews the list
    # and either extends the catalog or dismisses the entry.
    """CREATE TABLE IF NOT EXISTS pose_candidates (
        axis        TEXT NOT NULL CHECK(axis IN ('pose','expression')),
        raw_text    TEXT NOT NULL,
        nearest_key TEXT NOT NULL DEFAULT '',
        distance    REAL,
        count       INTEGER NOT NULL DEFAULT 1,
        status      TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','dismissed')),
        first_seen  TEXT NOT NULL,
        last_seen   TEXT NOT NULL,
        PRIMARY KEY (axis, raw_text)
    )""",

    # ── LLM Call Statistik (fuer Dauer-Schaetzung + Admin-Auswertung) ──
    """CREATE TABLE IF NOT EXISTS llm_call_stats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          TEXT NOT NULL,
        model       TEXT NOT NULL,
        task        TEXT NOT NULL,
        provider    TEXT DEFAULT '',
        agent_name  TEXT DEFAULT '',
        in_tokens   INTEGER NOT NULL,
        out_tokens  INTEGER NOT NULL,
        max_tokens  INTEGER DEFAULT 0,
        duration_s  REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_llm_call_stats_lookup ON llm_call_stats (model, task, provider, ts DESC)",

    # ── Party-System (gemeinsam reisen) ───────────────────────────────────
    # Eine Party = ein Leader + N Follower (JSON-Liste). Nur der Leader bewegt
    # sich selbst; Follower werden mitgezogen (siehe save_character_current_*).
    # Ein Character ist in hoechstens einer Party. Siehe app/core/party_engine.py.
    """CREATE TABLE IF NOT EXISTS parties (
        party_id   TEXT PRIMARY KEY,
        leader     TEXT NOT NULL,
        members    TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    )""",
    # Offene Party-Einladungen an den Avatar (NPC laedt Avatar ein -> Frage im
    # Chat-Fenster). NPC->NPC braucht keine Row (Entscheidung laeuft synchron).
    """CREATE TABLE IF NOT EXISTS party_invites (
        invite_id  TEXT PRIMARY KEY,
        inviter    TEXT NOT NULL,
        invitee    TEXT NOT NULL,
        created_at TEXT NOT NULL,
        status     TEXT NOT NULL DEFAULT 'pending'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_party_invites_invitee ON party_invites (invitee, status)",

    # ── Room furnishing job (plan-room-furnish.md) ────────────────────────
    # ONE active "✨ Furnish" job per room. The job is the persisted state
    # machine behind the dialog (selecting -> proposal_ready -> generating ->
    # placing -> review_ready | error); accept/discard/reset DELETE the row,
    # so the table only ever holds jobs in flight. See app/core/room_furnish.py.
    # ── LLM prompt composition cache (prompt_compose_llm.py) ─────────────
    # Same input -> same composed prompt: a regenerate series and a batch run
    # cost ONE call, not one per image. Key = sha256 over style, subject,
    # shape hint, family and the template's mtime (editing the template in
    # /admin/templates starts a new generation of keys). No eviction.
    """CREATE TABLE IF NOT EXISTS prompt_compose_cache (
        key        TEXT PRIMARY KEY,
        prompt     TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",

    """CREATE TABLE IF NOT EXISTS room_furnish (
        room_id     TEXT PRIMARY KEY,
        location_id TEXT NOT NULL,
        state       TEXT NOT NULL,
        proposal    TEXT,
        placements  TEXT,
        error       TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""",

    # ── Seamless world / terrain ─────────────────────────────────────────
    # Per-world overrides of the terrain-type catalog. The shared seed lives
    # in shared/terrain/types.json; a row here REPLACES the whole shared
    # entry of the same kind (override-replace, the activity-library rule).
    # Deleting a row brings the shared entry back. See app/core/terrain_types.py.
    """CREATE TABLE IF NOT EXISTS terrain_types (
        kind         TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        color        TEXT DEFAULT '',
        passable     INTEGER NOT NULL DEFAULT 1,
        speed_factor REAL NOT NULL DEFAULT 1.0,
        meta         TEXT DEFAULT '{}',
        updated_at   TEXT NOT NULL
    )""",

    # One painted terrain polygon on the free world map: a `kind` from the
    # catalog above plus its outline in world metres (JSON [[x, z], ...]).
    # Areas may overlap; z_order (then paint order = created_at) decides
    # which one answers a point query. See app/models/terrain.py.
    """CREATE TABLE IF NOT EXISTS terrain_areas (
        id         TEXT PRIMARY KEY,
        kind       TEXT NOT NULL,
        polygon    TEXT NOT NULL,
        z_order    INTEGER NOT NULL DEFAULT 0,
        meta       TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",

    # ── World relief (E8 task 2) ─────────────────────────────────────────
    # One authored HEIGHT AREA: an outline in world metres (JSON [[x, z], ...])
    # that lifts (or sinks) the ground inside it to `height_m`, ramping there
    # linearly over the last `falloff_m` metres before its edge. This is the
    # authoring SOURCE; the grid below is derived from it and nothing else.
    # See app/models/heightfield.py.
    """CREATE TABLE IF NOT EXISTS height_areas (
        id         TEXT PRIMARY KEY,
        polygon    TEXT NOT NULL,
        height_m   REAL NOT NULL DEFAULT 0,
        falloff_m  REAL NOT NULL DEFAULT 0,
        meta       TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",

    # The RASTERED world heightfield — one row (id = 1), the derived cache of
    # the height areas above. Origin and step travel WITH the data: the grid
    # lattice is anchored at the world origin (0, 0) and never at world_bounds,
    # so growing the world moves no sample point. `sig` is the signature of the
    # areas this raster was built from; a mismatch means "re-raster".
    # See app/core/heightfield.py.
    """CREATE TABLE IF NOT EXISTS world_heightfield (
        id         INTEGER PRIMARY KEY CHECK (id = 1),
        origin_x   REAL NOT NULL,
        origin_z   REAL NOT NULL,
        step_m     REAL NOT NULL,
        n_rows     INTEGER NOT NULL,
        n_cols     INTEGER NOT NULL,
        heights    TEXT NOT NULL,
        sig        TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
]


# ALTER TABLE migrations — laufen nach allen CREATEs idempotent durch.
# Pattern: pro Tabelle die fehlenden Spalten hinzufuegen, OperationalError = existiert schon.
ALTER_MIGRATIONS = [
    # thoughts: characters present at the time of the thought (JSON name list)
    # — context for the admin journal (user feedback 2026-07-29). Old rows
    # stay empty.
    ("thoughts", "present", "TEXT DEFAULT ''"),
    # thoughts: game time at thought creation (the game clock cannot be derived
    # from ts retroactively — anchors re-anchor on set/factor/freeze).
    # Stored as ISO WITH world-timezone offset (game_local_now().isoformat()).
    ("thoughts", "game_ts", "TEXT DEFAULT ''"),
    # thoughts: characters in OTHER rooms of the location at thought time
    # (JSON list of "Name (room)" snapshots, room names frozen at write time).
    # Makes "same building, different room" visible in the admin journal.
    ("thoughts", "nearby", "TEXT DEFAULT ''"),
    # telegram_mapping: avatar column — the Telegram user is represented by an
    # avatar character (option B). character_name stays the chat's NPC (bot).
    ("telegram_mapping", "avatar", "TEXT NOT NULL DEFAULT ''"),
    # llm_call_stats: agent_name + max_tokens added for the admin stats tab
    ("llm_call_stats", "agent_name", "TEXT DEFAULT ''"),
    ("llm_call_stats", "max_tokens", "INTEGER DEFAULT 0"),
    # character_state: last_thought_at for agent loop / inbox tracking — the
    # time of the last processed thought turn; every chat_messages row with
    # role='user' and ts > last_thought_at counts as "unread".
    ("character_state", "last_thought_at", "TEXT DEFAULT ''"),
    # prompt_filters: icon + image_modifier for the merged "conditions" tab
    # (formerly status_modifiers.json). The icon is rendered in the character
    # header badge, image_modifier goes into the image-generation prompt of
    # active conditions.
    ("prompt_filters", "icon", "TEXT DEFAULT ''"),
    ("prompt_filters", "image_modifier", "TEXT DEFAULT ''"),
    # summaries: partner column for character-vs-character daily summaries
    # (one summary per (character, partner) per day instead of one per day).
    # The UNIQUE-constraint change runs separately in db.py (table rebuild).
    ("summaries", "partner", "TEXT NOT NULL DEFAULT ''"),
    # Outfit + Pose Rethink (May 2026, plan-outfit-system-rethink.md):
    # rooms/locations get a decency model instead of the outfit_type container.
    # decency: public | private | nude_ok (hard, compliance-relevant)
    # style_hint: free-text recommendation, LLM hint only
    # swim_allowed: 0/1, decency modifier when char.is_wet
    # activity_hint: free text, "what one normally does here" (soul style)
    # outfit_type stays readable in parallel for now — it is removed in step 8
    # (cleanup) once compliance has fully moved to decency.
    ("locations", "decency",       "TEXT DEFAULT ''"),
    ("locations", "style_hint",    "TEXT DEFAULT ''"),
    ("locations", "swim_allowed",  "INTEGER NOT NULL DEFAULT 0"),
    ("locations", "activity_hint", "TEXT DEFAULT ''"),
    ("rooms",     "decency",       "TEXT DEFAULT ''"),
    ("rooms",     "style_hint",    "TEXT DEFAULT ''"),
    ("rooms",     "swim_allowed",  "INTEGER NOT NULL DEFAULT 0"),
    ("rooms",     "activity_hint", "TEXT DEFAULT ''"),
    # Step 5 (May 2026): the pose concept replaces the activity library.
    # Pose catalog (Aug 2026, plan-pose-katalog.md): what the character is
    # doing is stored as pose_key (catalog key, the ONE render/animation key)
    # plus pose_flavor (sanitized free text, prompt spice only). They replace
    # the free-text pose_intent column, which the pose_catalog_fields_v1
    # migration in db.py drops. pose_variant_id is RETIRED (Aug 2026) — it
    # pointed at character_pose_variants; the column is only kept so old and
    # new worlds keep the same shape until a migration pass drops both.
    ("character_state", "pose_key",        "TEXT DEFAULT ''"),
    ("character_state", "pose_flavor",     "TEXT DEFAULT ''"),
    ("character_state", "pose_variant_id", "INTEGER"),
    # Step 6 (May 2026): three orthogonal state flags replace the activity
    # effects. Compliance reads them:
    #   is_sleeping  → off-map, no compliance
    #   is_wet       → with swim_allowed: swim exemption for top/bottom
    #   is_intimate  → decency override to nude_ok
    ("character_state", "is_sleeping",  "INTEGER NOT NULL DEFAULT 0"),
    ("character_state", "is_wet",       "INTEGER NOT NULL DEFAULT 0"),
    ("character_state", "is_intimate",  "INTEGER NOT NULL DEFAULT 0"),
    # June 2026: decency_exempt → decency override to nude_ok, independent of
    # presence/strangers. Settable via toggle (UI), the set_flags rule and an
    # LLM skill — the manual/rule-based counterpart to is_intimate.
    ("character_state", "decency_exempt", "INTEGER NOT NULL DEFAULT 0"),
    # Seamless world (Aug 2026, plan-freie-weltkarte.md): a location sits at a
    # free metre position with its own rotation instead of on a grid cell.
    # Deliberately NO migration of the old grid_x/grid_y values — a grid world
    # is not converted, it is re-placed. The orphaned grid columns stay behind
    # in old DBs (SQLite cannot drop them cheaply) and no SQL touches them.
    ("locations", "pos_x",   "REAL"),
    ("locations", "pos_z",   "REAL"),
    ("locations", "yaw_deg", "REAL NOT NULL DEFAULT 0"),
    # Seamless world (Aug 2026): a character stands at a free metre point,
    # its current_location is DERIVED from it (location_at_point). NULL means
    # "no metre position" — either never set or the character sits in an
    # unplaced location, which has no centre to stand on.
    ("character_state", "pos_x", "REAL"),
    ("character_state", "pos_z", "REAL"),
    # Wilderness perception (Aug 2026, E6): a speaker outside every location
    # has no room to name, so the utterance carries the metre point it was
    # spoken from. NULL means "spoken inside a location" — the walls, not a
    # radius, decided who heard it, and the room columns already say where.
    ("utterances", "pos_x", "REAL"),
    ("utterances", "pos_z", "REAL"),
]


# Indexes that touch migrated columns — they run AFTER ALTER_MIGRATIONS, or
# CREATE INDEX fails on old DBs ("no such column: agent_name").
POST_MIGRATION_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_llm_call_stats_agent_ts ON llm_call_stats (agent_name, ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_llm_call_stats_ts ON llm_call_stats (ts DESC)",
]
