"""
Unified Chat Manager - Multi-Channel Chat Verwaltung

Verwaltet Chat-Verlauf über mehrere Kanäle (Web, Telegram, WhatsApp, etc.)
Alle Nachrichten werden in einem einheitlichen Format gespeichert.

Storage: world.db — Tabelle chat_messages
"""
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from app.core.timeutils import utc_now_iso
import json

from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("unified_chat")

# get_user_name absichtlich nicht importiert — Login-Name wuerde sonst als
# Partner-Key in chat_messages leaken. Stattdessen wird get_player_identity
# in _resolve_partner_key benutzt (lazy import dort).
from app.models.channel import Message, ChannelType, ChannelInterface


class ChannelManager:
    """
    Verwaltet registrierte Kanäle und Kommunikation zwischen Kanälen
    """
    
    def __init__(self):
        self._channels: Dict[ChannelType, ChannelInterface] = {}
    
    def register_channel(self, channel: ChannelInterface) -> None:
        """Registriere einen neuen Kanal"""
        self._channels[channel.channel_type] = channel
    
    def get_channel(self, channel_type: ChannelType) -> Optional[ChannelInterface]:
        """Hole einen registrierten Kanal"""
        return self._channels.get(channel_type)
    
    def list_channels(self) -> List[ChannelType]:
        """Liste alle verfügbaren Kanäle auf"""
        return list(self._channels.keys())


class UnifiedChatManager:
    """
    Verwaltet Chat-Verlauf über mehrere Kanäle
    
    Alle Nachrichten werden im gleichen Format gespeichert, unabhängig vom Kanal.
    Dies ermöglicht:
    - Konsistente Chat-Historie über alle Kanäle
    - Kanalübergreifenden Nachrichtenverlauf
    - Explizites Routing an bestimmte Kanäle
    """
    
    def __init__(self, channel_manager: ChannelManager):
        self.channel_manager = channel_manager
    
    @staticmethod
    def get_chat_dir(character_name: str) -> Path:
        """Legacy-Kompatibilitaet: Gibt das Chat-Verzeichnis zurueck (existiert noch fuer Backups)."""
        from app.core.paths import get_storage_dir
        chat_dir = get_storage_dir() / "characters" / character_name / "chats"
        chat_dir.mkdir(parents=True, exist_ok=True)
        return chat_dir

    @staticmethod
    def _resolve_partner_key(partner_name: str = "", character_name: str = "") -> str:
        """Bestimmt den Partner-Key (fuer Logging und Legacy-Compat).

        Neues System: Character-Name des Partners.
        Fallback: aktiver Character des Users, dann Username.
        """
        if partner_name:
            return partner_name
        try:
            from app.models.account import get_player_identity
            active = get_player_identity("")
            if active and active != character_name:
                return active
        except Exception:
            pass
        # Login-Name (z.B. "admin") taugt nicht als Partner-Key — wuerde
        # neue Chats unter dem Login speichern statt unter dem Avatar.
        # Leerer String bedeutet hier: kein Partner-Filter.
        return ""

    @staticmethod
    def _pair_cutoff_ts(conn, character_name: str, partner: str,
                        limit: int) -> Optional[str]:
        """The oldest ``ts`` the last ``limit`` messages of the pair can have.

        The pair view merges BOTH storage directions and then drops duplicates
        on ``(ts, role, content)`` — a TalkTo turn is written into both
        buckets — so a plain ``LIMIT`` on either direction could cut a row the
        merged view still needs. ``UNION`` (not ``UNION ALL``) dedups on
        exactly those three columns, so the ``limit``-th largest ``ts`` among
        the DISTINCT messages is a cutoff the merged tail never reaches below:
        the merge sorts by ``ts`` first, so its last ``limit`` entries are the
        ``limit`` distinct messages with the largest ``ts``. Reading
        ``ts >= cutoff`` therefore yields a superset of the tail, and the
        existing merge/dedup/tail below trims it to exactly the same result.

        None when the pair has no messages at all or when the probe fails —
        the caller then reads the full history. Fewer messages than ``limit``
        simply yield the oldest ``ts``, which cuts nothing.
        """
        try:
            row = conn.execute(
                "SELECT MIN(ts) FROM ("
                "  SELECT ts, role, content FROM chat_messages"
                "   WHERE character_name=? AND partner=?"
                "  UNION"
                "  SELECT ts, CASE WHEN role='assistant' THEN 'user'"
                "                  ELSE 'assistant' END, content"
                "   FROM chat_messages WHERE character_name=? AND partner=?"
                "  ORDER BY ts DESC LIMIT ?"
                ")",
                (character_name, partner, partner, character_name, limit),
            ).fetchone()
        except Exception as e:
            logger.debug("_pair_cutoff_ts failed for %s/%s: %s",
                         character_name, partner, e)
            return None
        return row[0] if row and row[0] else None

    @staticmethod
    def get_chat_history(character_name: str = "",
        channel: Optional[ChannelType] = None,
        limit: Optional[int] = None,
        partner_name: str = "") -> List[Message]:
        """Laedt Chat-History aus der DB.

        Args:
            character_name: Character-Name (der Character dessen History geladen wird)
            channel: Wenn gesetzt, nur Nachrichten von diesem Kanal filtern
            limit: Maximale Anzahl von Nachrichten (letzte N)
            partner_name: Expliziter Partner-Character-Name (fuer Character-zu-Character)

        Returns:
            Liste von Message-Objekten

        ``limit`` is applied IN SQL whenever it can be (DATA-12): the history
        of a pair is never pruned, so after months of play a chat turn read,
        parsed and object-ified tens of thousands of rows for a prompt that
        keeps the last ~100. It stays a Python tail only when ``channel``
        filters as well — a SQL ``LIMIT`` would then cut before the filter and
        return fewer messages than asked for. Without ``limit`` nothing
        changes: the full history is read as before.
        """
        if not character_name:
            return []

        partner = UnifiedChatManager._resolve_partner_key(partner_name, character_name)
        # A channel filter runs AFTER the rows are built, so a SQL LIMIT would
        # cut the wrong end of the list — only an unfiltered read is bounded.
        sql_limit = limit if (limit and limit > 0 and channel is None) else None

        try:
            conn = get_connection()
            if partner:
                # Konversation A↔B kann je nach damaligem Avatar als
                # (A, partner=B) ODER (B, partner=A) gespeichert sein —
                # je nachdem wer der "antwortende" Character war. Beim
                # Avatar-Wechsel wuerde sonst die alte Richtung versteckt
                # bleiben. Wir vereinen beide Richtungen und tauschen die
                # Rollen im flipped-Batch, damit aus Sicht des aktuellen
                # character_name role=assistant immer DIESEN Character
                # bedeutet.
                base_q = (
                    "SELECT id, ts, role, content, channel, "
                    "channel_message_id, metadata FROM chat_messages "
                    "WHERE character_name=? AND partner=?")
                since = (UnifiedChatManager._pair_cutoff_ts(
                    conn, character_name, partner, sql_limit)
                    if sql_limit else None)
                tail = " AND ts >= ?" if since is not None else ""
                args_direct = ((character_name, partner, since) if since is not None
                               else (character_name, partner))
                args_flipped = ((partner, character_name, since) if since is not None
                                else (partner, character_name))
                rows_direct = conn.execute(base_q + tail, args_direct).fetchall()
                rows_flipped = conn.execute(base_q + tail, args_flipped).fetchall()

                merged = list(rows_direct)
                for r in rows_flipped:
                    # role swap: was als (B,A) gespeichert wurde, sieht aus
                    # A's Sicht andersrum aus.
                    new_role = "user" if r[2] == "assistant" else "assistant"
                    merged.append((r[0], r[1], new_role, r[3], r[4], r[5], r[6]))
                merged.sort(key=lambda x: (x[1] or "", x[0]))
                # Dedup: TalkTo-Konversationen (NPC↔NPC) werden in BEIDE
                # Buckets geschrieben, damit jeder Char eine vollstaendige
                # eigene History hat. Nach role-swap kollidiert das im
                # merged-View. Eindeutiger Schluessel: (ts, role, content).
                # Avatar↔NPC-Messages haben unique ts/content kombiniert,
                # werden also nicht entfernt.
                seen: set = set()
                deduped: List[tuple] = []
                for r in merged:
                    key = (r[1] or "", r[2] or "", r[3] or "")
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(r)
                rows = deduped
                # Frueher gab es einen Fallback auf den Account-Login-Namen
                # (get_user_name) als Partner — der hat aber nur bestehende
                # Admin-Chats sichtbar gemacht und neue Avatar-Chats blieben
                # leer wenn jemand kurzzeitig keinen Avatar gewaehlt hatte.
                # Entfernt: Login-Name ist kein gueltiger Partner-Key.
            elif sql_limit:
                # Newest N in SQL (idx_chat_char_ts), turned back into
                # chronological order — the same last N the Python tail below
                # would have produced, without reading the rest.
                rows = conn.execute("""
                    SELECT id, ts, role, content, channel, channel_message_id, metadata
                    FROM chat_messages
                    WHERE character_name=?
                    ORDER BY ts DESC, id DESC
                    LIMIT ?
                """, (character_name, sql_limit)).fetchall()
                rows.reverse()
            else:
                rows = conn.execute("""
                    SELECT id, ts, role, content, channel, channel_message_id, metadata
                    FROM chat_messages
                    WHERE character_name=?
                    ORDER BY ts ASC
                """, (character_name,)).fetchall()

            history: List[Message] = []
            for r in rows:
                row_id, ts, role, content, ch, ch_msg_id, meta_json = r
                try:
                    meta = json.loads(meta_json or "{}")
                except Exception:
                    meta = {}
                ch_type = ChannelType.WEB
                if ch:
                    try:
                        ch_type = ChannelType(ch)
                    except (ValueError, KeyError):
                        pass
                msg = Message(
                    content=content,
                    role=role,
                    timestamp=ts,
                    channel=ch_type,
                    channel_message_id=ch_msg_id,
                    id=row_id,
                    **{k: v for k, v in meta.items()
                       if k not in ("content", "role", "timestamp", "channel",
                                    "channel_message_id", "id")},
                )
                if channel is None or msg.channel == channel:
                    history.append(msg)

            if limit and len(history) > limit:
                history = history[-limit:]
            return history

        except Exception as e:
            logger.error("get_chat_history DB-Fehler fuer %s/%s: %s",
                         character_name, partner_name, e)
            return []

    @staticmethod
    def save_message(message: Message,
        character_name: str = "",
        partner_name: str = "") -> bool:
        """Speichert eine Nachricht in der DB.

        Args:
            message: Message-Objekt
            character_name: Character-Name (in dessen History die Nachricht gespeichert wird)
            partner_name: Expliziter Partner-Character-Name (fuer Character-zu-Character)

        Returns:
            True when the row is committed, False when it is NOT (DATA-13).
            The failure used to be logged and then reported as a success: a
            ``database is locked`` during a chat turn dropped the reply while
            the turn carried on and the UI showed it — until the next reload.
            A caller that tells anyone the message was stored has to check
            this; ``False`` with no character name means nothing was even
            attempted.
        """
        if not character_name:
            return False

        if not message.timestamp:
            message.timestamp = utc_now_iso()

        partner = UnifiedChatManager._resolve_partner_key(partner_name, character_name)

        # Meta: alle Felder ausser Standard-Felder
        msg_dict = message.to_dict()
        meta = {k: v for k, v in msg_dict.items()
                if k not in ("content", "role", "timestamp", "channel",
                             "channel_message_id")}

        ch_value = (message.channel.value if hasattr(message.channel, "value")
                    else str(message.channel or "web"))

        try:
            with transaction() as conn:
                conn.execute("""
                    INSERT INTO chat_messages
                    (character_name, partner, ts, role, content,
                     channel, channel_message_id, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    character_name,
                    partner,
                    message.timestamp,
                    message.role,
                    message.content,
                    ch_value,
                    getattr(message, "channel_message_id", None),
                    json.dumps(meta, ensure_ascii=False),
                ))
        except Exception as e:
            logger.error("save_message DB-Fehler fuer %s/%s: %s",
                         character_name, partner_name, e, exc_info=True)
            return False

        # Shadow-Write in den Wahrnehmungs-Stream (additiv, nie blockierend).
        # plan-room-conversation Phase 1 — faellt ab Phase 3 weg.
        try:
            from app.core import perception_shadow
            perception_shadow.from_chat_message(message, character_name, partner)
        except Exception:
            pass
        return True
    
    async def send_message_to_channel(
        self, character_name: str,
        content: str,
        target_channel: ChannelType,
        **kwargs
    ) -> Optional[str]:
        """
        Sende eine Nachricht an einen bestimmten Kanal
        
        Dies ermöglicht Anweisungen wie:
        "Suche Fußballergebnisse und sende sie an Telegram"
        
        Args:
            user_id: Benutzer-ID
            character_name: Agent-Name
            content: Nachrichteninhalt
            target_channel: Zielkanal (z.B. ChannelType.TELEGRAM)
            **kwargs: Kanal-spezifische Optionen
        
        Returns:
            Kanal-spezifische Message-ID falls verfügbar
        """
        channel = self.channel_manager.get_channel(target_channel)
        if not channel:
            raise ValueError(f"Kanal {target_channel.value} nicht registriert")
        
        # Sende Nachricht über den Kanal
        channel_message_id = await channel.send_message(character_name, content, **kwargs
        )
        
        # Speichere im einheitlichen Chat-Format
        message = Message(
            content=content,
            role="assistant",
            channel=target_channel,
            channel_message_id=channel_message_id
        )
        if not self.save_message(message, character_name):
            # The channel already has the message — it is out there. Only the
            # local history is missing, and that is worth a loud line rather
            # than a silent hole in the transcript (DATA-13).
            logger.error("send_message_to_channel: %s -> %s sent but NOT stored",
                         character_name, target_channel)

        # Rufe Channel Hook auf
        await channel.on_message_sent(character_name, content, channel_message_id
        )
        
        return channel_message_id


# Globale Channel Manager Instanz
_channel_manager = None


def get_channel_manager() -> ChannelManager:
    """Hole die globale Channel Manager Instanz"""
    global _channel_manager
    if _channel_manager is None:
        _channel_manager = ChannelManager()
    return _channel_manager


def get_unified_chat_manager() -> UnifiedChatManager:
    """Hole die globale Unified Chat Manager Instanz"""
    return UnifiedChatManager(get_channel_manager())
