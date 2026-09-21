# Core-Schnittstellen für Skill-Pakete

Kuratierte Referenz der Core-APIs, die Skill-Pakete aufrufen dürfen. Gegenstück zu
`docs/plugins.md` (deklaratives Paketformat): Dieses Dokument beschreibt die
**imperative** Seite — was ein Verb zur Laufzeit rufen kann.

Regeln (`development_instructions/done/plan-skill-plugin-architecture.md`):
- **Richtung:** Pakete rufen Core — das Core referenziert niemals ein Paket (R1).
- **Nur öffentliche Namen.** Ein `_privater_name` aus einem Core-Modul ist kein
  Vertrag. Wer einen braucht, lässt ihn zuerst öffentlich machen und hier eintragen.
- **Pflege-Pflicht:** Jede Migration ergänzt hier die Schnittstellen, die sie nutzt
  oder neu schafft. Jeder R5-Entscheid „bleibt Core-Engine" bekommt hier seinen
  Eintrag. Die Liste ist kuratiert, nicht automatisch vollständig.
- Skills interagieren untereinander NIE direkt, nur über dieses Core-Vokabular (R6).

Die Signaturen unten sind gegen den Code geprüft; `scripts/smoke_docs_skill_core_api.py`
importiert jeden genannten Namen und vergleicht die dokumentierten Parameternamen mit
`inspect.signature`.

Status-Legende: ✅ = von Paketen genutzt und stabil · ⚠ = existiert, wird von
Built-ins genutzt, aber noch nicht als Paket-API gehärtet.

## Deklarativ (Manifest, kein Code)

Siehe `docs/plugins.md`: Verben (`skills`), LLM-Templates (`templates.llm`),
Character-Template-Fragmente (`templates.character` + `apply_to`), Admin-Config
(`config_schema`), Flag-Lebenszyklen (`state_flags`), UI-Bündelung
(`capability_label`), Default-Aktivierung (`default_enabled`), Spezies-Inhalte
(`body_slots`/`piece_slots`/`silhouette`), Abhängigkeiten (`requires`/`conflicts`).

## Sperren — `app.core.keyed_lock` ✅ (Pflicht für Profil-Schreiber)

`save_character_profile` schreibt den **ganzen** `profile_json`-Blob. Seit die Routen
im Threadpool laufen, serialisiert nichts mehr zwei Threads im selben Handler — ein
ungesichertes Read-Modify-Write verschluckt stillschweigend die Felder, die ein
anderer Thread dazwischen geschrieben hat.

```python
from app.core.keyed_lock import keyed_lock

with keyed_lock("character_profile", name):
    profile = get_character_profile(name)
    profile["is_training"] = True
    save_character_profile(name, profile)
```

`keyed_lock(namespace, key)` liefert eine **re-entrante** `threading.RLock` pro
(Namespace, Key). Derselbe Thread darf denselben Key erneut betreten, ein anderer
wartet weiter. Re-Entranz macht zwei VERSCHIEDENE Keys nicht sicher — deshalb die
**Lock-Reihenfolge**:

1. Plätze vor Profil: `keyed_lock("places", location_id)` wird VOR
   `keyed_lock("character_profile", name)` genommen, nie umgekehrt.
2. Zwei Charakter-Profile nur in **sortierter Namensreihenfolge** — und dafür gibt es
   genau einen sanktionierten Weg: `app.core.interaction_engine.pair_profile_locks(a, b)`.
3. Ein Profil-Lock wird **nie über einen LLM-/HTTP-/Bild-Call oder ein `sleep`**
   gehalten. Wer danach noch schreiben muss, nimmt das Lock erneut.

Durchgesetzt von `scripts/smoke_profile_rmw_lock.py` (reiner AST-Check, keine DB):
ein `get_character_profile(X)` mit folgendem `save_character_profile(X, …)` in
derselben Funktion muss innerhalb eines `with keyed_lock("character_profile", …)`
stehen. Ausnahmen stehen dort in einer `ALLOWLIST`, jede mit Begründung.

## Zustands-Flags — `app.models.character` ✅

| Funktion | Semantik |
|---|---|
| `set_state_flag(character_name, flag, value)` | Generischer Setter; stempelt `state_flag_since[flag]` (Basis für TTL-Zerfall) |
| `get_state_flags(character_name) -> Dict[str, bool]` | Alle Kern-Flags als Dict (is_sleeping/is_wet/is_intimate/decency_exempt) |
| `stamp_state_flag_since(character_name, flag)` | Baseline-Stempel für ein bereits gesetztes Flag |
| `set_is_wet / set_is_intimate / set_decency_exempt / set_is_sleeping(character_name, value)` | Flag-spezifische Delegates (Kern-Vokabular; auch von Rules/Routen genutzt) |
| `enter_offmap_sleep(character_name) -> bool` / `wake_from_offmap(character_name) -> bool` | Sleep-Paket: Off-Map-Übergang (Rückkehr zum Vor-Schlaf-Ort beim Wecken). Auto-Sleep im Agent-Loop und die B1-Wake-Regel schreiben dasselbe Vokabular — das Paket ist nur ein Auslöser |

Lebenszyklus (Prompt-Zeile, TTL, Location-Reset) NICHT selbst bauen — deklarativ über
`state_flags` im Manifest; der Executor (`app/core/flag_lifecycle.py`) ruft zum
Auto-Clear das `cleared_by`-Verb des Pakets.

## Stats — `app.core.stat_effects` + Template-Deklaration ✅

Stats sind vollständig template-getrieben (`store=status_effects`-Felder; Pakete
steuern eigene Stats per Character-Template-Fragment bei). Der Core kennt keinen
Stat-Namen.

| Mechanismus | Semantik |
|---|---|
| Feld-Deklaration `bar_hourly` (+`bar_hourly_sleeping`) | Natürliche Steigung/Senkung pro Stunde — führt der stündliche Status-Tick aus (`app.core.activity_engine.apply_hourly_status_tick(character_name)`) |
| Feld-Deklaration `hint` / `hint_thresholds` | Semantik für den LLM-Evaluator und Prompt-Hinweise |
| `evaluate_stat_effects(character_name, situation_text, *, source, per_hour=False, elapsed_min=0.0) -> Dict[str, int]` | EINE LLM-Runde gegen alle deklarierten Stats; der Text ist Paket-Policy. `per_hour=True` skaliert auf die verstrichene Zeit |
| Aktivitäts-Tick (automatisch) | Der Agent-Loop bewertet die LAUFENDE Freitext-Aktivität gegen alle Stats — kein Library-Lookup; für jedes Paket nutzbar (Workout ⇒ Stamina-Deklaration + Hints genügen) |
| `app.models.character.adjust_status_effects(character_name, deltas, source='')` | Direkte Deltas ohne LLM-Runde (clamped 0–100) |

## Body-Slots — `app.core.body_slots` ✅ (Spezies-Pakete)

| Funktion | Semantik |
|---|---|
| `slots_for_character(character_name, profile=None)` | Anwendbare Slot-Deklarationen (Spezies-Template + `applies_to`) |
| `slot_values(character_name)` / `set_slot_value(character_name, slot_id, attr, value)` | Gespeicherte Attribut-Werte (Profil, Stammdaten) |
| `prompt_fragments(character_name, face_only=False, profile=None, back_view=False)` | `{general, exposed}` — general = always+covered (Personenbeschreibung, F1), exposed nur unbedeckt; `face_only` filtert auf `face: true`-Slots, `back_view` auf die Rückansicht |
| `appearance_suffix(character_name, face_only=False, profile=None, back_view=False) -> str` | Kombinierter Text; hängt der PromptBuilder automatisch an die Appearance an |
| `piece_slots_for_character(character_name) -> Tuple[str, ...]` | Kleidungs-Slot-Topologie der Spezies (Fallback `inventory.VALID_PIECE_SLOTS`). Konsumenten: Paper-Doll/Belongings, `inventory.equip_piece`-Validierung, `CreateOutfit`-Slot-Liste, Decency-required-Slots |
| `declared_piece_slots(character_name)` | `(slots, labels)` NUR wenn eine Spezies deklariert, sonst `None` — Aufrufer behalten dann ihren Core-Default |
| `silhouette_for_character(character_name)` | Silhouetten-Deklaration des Spezies-Pakets (UI) |

Deklaration ausschließlich über das Manifest (`body_slots`/`piece_slots`/
`silhouette` + `apply_to`) — siehe `docs/plugins.md`. UI-Endpunkte:
`GET/POST /characters/<c>/body-slots[/<slot>]` (generischer Editor im
WardrobeTab), `GET /characters/<c>/silhouette` (Paket-Asset); Belongings
liefert `slot_order`/`slot_labels`/`slot_anchors`/`silhouette_url` spezies-getrieben.

## Outfit / Decency — `app.core.outfit_compliance` ✅

| Funktion | Semantik |
|---|---|
| `apply_outfit_compliance(character_name, *, is_intimate=None, is_wet=None, is_sleeping=None) -> Dict` | Decency/Style des aktuellen Raums gegen `equipped_pieces` abgleichen — nach JEDER Zustandsänderung rufen, die die Kleiderordnung beeinflusst. Die drei Kwargs geben den Zustand mit, wenn er gerade geschrieben wurde und noch nicht im Profil steht |
| `app.core.outfit_renderer.is_outfit_worn(profile) -> bool` | Binärer „angezogen?"-Zustand für Freitext-Garderoben (undress-Paket) |

## Beziehung — `app.models.relationship` ⚠

| Funktion | Semantik |
|---|---|
| `get_relationship(char_a, char_b) -> Optional[Dict]` | Beziehungsdaten zweier Charaktere (u.a. `strength`) |
| `record_interaction(char_a, char_b, …)` | Eine Interaktion verbuchen (Sentiment/Stärke) |
| `get_romantic_interests(character_name) -> str` | Freitext-Interessen aus dem Profil |
| `are_romantically_compatible(char_a, char_b) -> bool` | Fragt den Capability-Provider `romantic_compatibility` (siehe „Hooks"); ohne Paket immer `True` |
| `interest_aliases`-Feld-Property | Attraction-Matching liest Alias-Blöcke aus Body-Slot-Attributen — vollständig deklarations-getrieben |

Die **LLM-Extraktion** der romantischen Interessen ist NICHT im Core: sie lebt im
attraction-Paket (Provider `romantic_interests_help`, siehe „Hooks").

## Inventar — `app.models.inventory` ✅ (consume_item) / ⚠ (Rest)

Vom **consume_item-Paket** genutzt und stabil: `resolve_item_id(token)` (Token→Item-ID),
`get_item(item_id)`, `has_item(character_name, item_id)`,
`consume_item(character_name, item_id)` (Konsum-Pipeline: qty-Decrement + effects +
apply_condition; liefert `{success, changes, condition_applied}`). `consume_item` ist
Core-Vokabular — Routen rufen sie direkt, ohne Skill-Bezug.

Weiter (⚠, heute nur Built-ins): `equip_piece`/`unequip_piece`,
`equip_item`/`unequip_item`, `add_item`, `add_to_inventory`,
`find_inventory_piece_by_name_slot`, `VALID_PIECE_SLOTS`.

## Welt & Ortskenntnis — `app.models.world` / `app.models.rules` ⚠

| Funktion | Semantik |
|---|---|
| `list_locations()` / `get_location(identifier)` / `get_location_by_id(location_id)` | Alle Orte bzw. einer |
| `list_locations_for_character(character_name)` | Nur die Orte, die dieser Charakter KENNT — dieselbe Quelle wie der Prompt-Block. Ein Verb, das einen Ortsnamen annimmt, prüft hiergegen und lehrt nie neues Wissen |
| `get_location_rooms(location)` / `get_room_by_name(location, room_name)` / `get_room_name(...)` | Räume eines Ortes |
| `get_entry_room_id(location)` / `get_arrival_room_id(location)` | Betret- bzw. Ankunftsraum |
| `get_location_name(location_id) -> str` | Anzeigename |
| `location_visible_to_character(character_name, location, context=None)` / `room_visible_to_character(character_name, location, room, context=None)` | Sichtbarkeit (Fog of War, `docs/schnittstellen-3d.md` § A12) |
| `app.models.rules.check_access(character_name, location_id, room_id='', action='enter') -> (bool, str)` | Zugangsregel |
| `app.models.rules.check_leave(character_name, *, room_only=False, target_location_id='', target_room_id='') -> (bool, str)` | Verlass-Regel |
| `app.core.danger_system.check_location_access(character_name, location) -> (bool, str)` | Event-gekoppelte Gefahren-Sperre |
| `app.core.world_ops.conditions_pass(conditions, character_name, location_id) -> bool` | Generischer Bedingungs-Evaluator (Rules/Intents) |

## Reise — `app.core.travel_engine` ✅ (movement-Paket)

Ein Ortswechsel über Ortsgrenzen ist eine **Reise**, kein Sprung. Nie selbst eine
Position schreiben, um jemanden woanders hin zu bringen.

| Funktion | Semantik |
|---|---|
| `start_journey(character_name, target_id) -> (journey \| None, reason)` | Startet die getaktete Reise zu einem benannten Ort. `reason`: `''` = läuft · `unknown_target` (Ort existiert nicht ODER der Charakter kennt ihn nicht) · `unplaced_target` (nicht auf der Karte) · `no_route` |
| `start_journey_to_point(character_name, x, z) -> (journey \| None, reason)` | Reise zu einem freien Punkt. Setzt **kein** `movement_target`, nur die `journey` — Ankunfts-/Abbruchlogik muss beides abfragen |
| `get_journey(character_name, profile=None)` | Die laufende Reise vom Profil (oder `None`) |
| `journey_state(waypoints, started_at_game, now_game) -> Dict` | Reine Funktion: Position aus Polylinie + Startzeit + **Spieluhr**. Kein Zustand, kein Tick — deshalb sehen alle Clients dieselbe Position |
| `cancel_journey(character_name)` | Reise abbrechen |
| `get_travel_speed_m_s() -> float` | Welt-Tempo (`game.travel_speed_m_s`, Default 1.4 m/s, geklemmt 0.1…20); beim Start auf die Reise geschrieben |
| `app.models.character.list_active_journeys() -> List[Dict]` | EINE Query über alle reisenden Charaktere (`{name, journey, movement_target, current_location}`) — nie über alle Profile iterieren |

## Charakter-Profil & Ort — `app.models.character` ✅/⚠

| Funktion | Semantik |
|---|---|
| `get_character_profile(character_name) -> Dict` | Profil inkl. Runtime-State (`character_state`) und Meta-Keys |
| `save_character_profile(character_name, profile, create_new=False) -> bool` | Schreibt den GANZEN Blob. **Wirft nie** — `False` heißt: nichts gespeichert (reservierter/unbekannter Name oder fehlgeschlagener Write). Rückgabe prüfen. Bei Neuanlage `create_new=True` Pflicht. Nur unter `keyed_lock("character_profile", name)` (siehe „Sperren") |
| `save_character_current_location(character_name='', location='', …)` | ZENTRALE Bewegung — löst Entry-Room, Compliance, Party-Drag, Flag-Location-Resets, Discovery aus. Nie umgehen |
| `get_character_current_location(character_name='', profile=None) -> str` / `get_character_current_room(character_name, profile=None) -> str` | Aufenthaltsort/-raum. Bei laufender Reise ist das die NÄCHSTE Position, nicht das Reiseziel; unterwegs im freien Gelände ist `current_location` leer |
| `is_character_sleeping(character_name, profile=None) -> bool` | Schläft der Charakter? (nicht erreichbar) |
| `is_temporary_npc(character_name) -> bool` | Temporärer NPC — hat keine Thought-Turns, `bump` lehnt ihn ab |
| `list_available_characters(include_pooled=False) -> List[str]` | Alle bespielbaren Charakternamen (Ziel-Auflösung) |
| `get_character_language(character_name) -> str` | Sprache des Charakters (für Texte, die er selbst schreibt) |
| `get_character_dir(character_name, *, create=False) -> Path` | Per-Charakter-Storage-Verzeichnis — für Pakete mit eigenen Dateien (markdown_writer schreibt nach `<dir>/documents/<folder>/`) |
| `get_character_skill_config(character_name, skill_name) -> Dict` / `save_character_skill_config(character_name, skill_name, config)` | Per-Charakter-Skill-Config. Normalerweise nicht direkt rufen — `BaseSkill._get_effective_config` liefert Defaults + Overrides typisiert |
| `record_access_denied(character_name, location_id, location_name, reason, rule_name='', action='enter')` | Abgewiesenen Zutritt vermerken (Gedächtnis + UI-Hinweis) |

**Viele Leser nehmen `profile=`.** Wer das Profil ohnehin geladen hat, reicht es durch
und spart den zweiten DB-Zugriff: `get_character_current_location`,
`get_character_current_room`, `get_movement_target`, `get_character_pose_key`,
`get_effective_pose_key`, `get_effective_activity`, `is_character_sleeping`,
`get_character_profile_image`, `travel_engine.get_journey`,
`interaction_engine.get_interaction`, `body_slots.slots_for_character`.

**Beim Löschen eines Charakters** löst `delete_character` selbst: Party verlassen +
Einladungen räumen, laufende Reise abbrechen, laufende Paar-Interaktion beenden +
deren Einladungen räumen. Ein Paket, das eigenen Zustand an einem Charakternamen
hängt, räumt ihn über denselben Weg auf (Check:
`scripts/smoke_delete_character_detach.py`).

## Wahrnehmung & Agent-Loop ⚠/✅

| Funktion | Semantik |
|---|---|
| `app.core.perception.record_utterance(*, speaker, content, volume='normal', addressees=None, location_id=None, room_id=None, source='', …) -> Optional[int]` | Erzähler-/Sprechakt-Zeile in den Raum-Stream |
| `app.core.perception.nearby_in_the_open(character_name, pos=None) -> List[str]` | Wer im Freien in Hörweite ist (Raum-Roster ∪ Radius) |
| `app.core.agent_loop.get_agent_loop().bump(character_name, hint='', perception_template='', perception_vars=None, tool_whitelist=None) -> bool` ✅ | Charakter für einen zeitnahen Thought-Turn vormerken. `hint` ist die Zeile, die er dabei liest; `tool_whitelist` schränkt die angebotenen Verben ein. Liefert `False`, wenn er keinen Turn bekommen kann (z.B. temporärer NPC) |
| `app.models.memory.add_memory(character_name, content, memory_type='semantic', importance=3, tags=None, context='', related_character='', …)` | Erinnerung anlegen |
| `app.models.account.is_player_controlled(character_name)` / `get_active_character()` ✅ / `get_chat_partner()` ✅ / `get_player_identity(default='user')` ✅ | Avatar-Erkennung, aktueller Gesprächspartner, Anzeigename des Spielers |

## Chat & Messaging ✅ (talk_to / send_message / notify_user)

| Funktion | Semantik |
|---|---|
| `app.models.chat.save_message(message, character_name='', partner_name='') -> bool` | Eine Zeile in die Chat-History schreiben (Inbox-Modell: Sender als `assistant`, Empfänger als `user`). **Wirft nie** — `False` heißt: nicht gespeichert. Rückgabe prüfen, sonst verschwindet eine Nachricht lautlos |
| `app.models.chat.get_chat_history(character_name='', partner_name='', limit=None) -> List[Dict]` | Verlauf; `limit` schneidet auf die letzten N Zeilen |
| `app.core.pending_reports.add_report(reporter, initiator, initiator_type, target, trigger_type='talk_to_response', trigger_message_id='', ttl_hours=24) -> str` | Chain-of-Command-Follow-up anlegen |
| `app.core.pending_reports.list_open(character_name)` / `mark_resolved(reporter, report_id) -> bool` | Offene Rückmeldungen lesen / schließen |
| `app.models.notifications.create_notification(character, content, notification_type='message', metadata=None) -> str` | User-Notification anlegen |

## Party — `app.core.party_engine` ✅ (party-Paket)

Gemeinsames Reisen als Core-Engine (R5 — Konsumenten: der Leader-Move-Drag-Hook in
`app/models/character.py`, die `/play`-Route und `visible_for` der Movement-Skills).
Das party-Paket ist nur der Auslöser.

| Funktion | Semantik |
|---|---|
| `get_party_of(character) -> Optional[Dict]` / `is_in_party(character)` / `is_party_follower(character)` | Party-Zustand/Rolle (Basis für `visible_for`) |
| `add_to_party(leader, member) -> Optional[str]` / `leave_party(character) -> Dict` | Beitritt / Austritt (Follower steigt aus, Leader = Auflösung) |
| `create_pending_invite(inviter, invitee) -> Optional[str]` / `clear_invites_for(character)` | Avatar-Einladung als UI-Frage; offene Einladungen räumen |

## Paar-Interaktionen — `app.core.interaction_engine` ✅ (interact-Paket)

Zwei anwesende Charaktere spielen einen Paar-Clip an einem gemeinsamen Anker. Die
Zustimmung ist immer ein Tool-Call, nie ein Keyword-Match auf Prosa.

| Funktion | Semantik |
|---|---|
| `partner_poses() -> List[Tuple[str, str]]` | Welche Paar-Posen es gibt (Key + Anzeige) |
| `get_interaction(character_name, profile=None)` | Läuft gerade eine? |
| `resolve_invite(invite_id, accept) -> Dict` | Einladung beantworten. `status` `cannot` = gerade nicht möglich (schläft, reist, Platz besetzt), die Frage bleibt offen |
| `get_invite(invite_id)` / `cancel_invite(invite_id) -> bool` / `clear_invites_for(character)` | Einladungen lesen/schließen |
| `end_interaction(character_name, reason='ended') -> bool` | Laufende Interaktion beenden — für BEIDE |
| `pair_profile_locks(a, b)` | Der EINZIGE sanktionierte Weg, zwei Profil-Locks zu halten (sortierte Namensreihenfolge, siehe „Sperren") |

Das Core feuert `interaction.invited`; wie die Antwort heißt, weiß nur das Paket
(Provider `pair_verb_name`).

## Pose — `app.models.character` ✅ (set_pose-Paket)

| Funktion | Semantik |
|---|---|
| `set_pose_key_detail(character_name, key, detail, *, unknown='resolve') -> str` | **Der Setter für ein Verb, das den Katalog-Key schon kennt:** schreibt Key + Anzeige-Detail exakt. `unknown='resolve'` lässt einen unbekannten Key noch über den Resolver laufen |
| `set_pose_intent(character_name, pose, prefer='', flavor=None)` | Kanonischer Setter für FREITEXT („Character macht jetzt X"): ordnet dem Pose-Katalog zu (`pose_key`), bereinigt die Würze (`pose_flavor`), matcht die Bild-Variante und schreibt alles ins Profil. No-op wenn Key und Flavor unverändert; leerer Text setzt zurück. Beendet eine laufende Paar-Interaktion. Bleibt Core (R5 — mehrere Schreiber) |
| `get_character_pose_key(character_name, profile=None)` / `get_character_pose_flavor(character_name)` | Gespeicherter Katalog-Key bzw. bereinigter Freitext |
| `get_effective_pose_key(character_name, profile=None)` / `get_effective_activity(character_name, profile=None)` | Render-Key bzw. Anzeigetext, beide inkl. Schlaf-Override |
| `app.core.pose_catalog.split_key_detail(text, axis='pose') -> (key, detail)` | Zerlegt eine `key: detail`-Eingabe |
| `app.core.pose_catalog.resolve_to_catalog(text, axis, _embed=None) -> (key, detail)` | Freitext auf den Katalog abbilden (Embedding-Match mit Alias-Fallback) |
| `app.core.pose_catalog.PairPoseWithoutPartner` | Exception: eine Paar-Pose ohne Partner — das Verb muss sie abfangen und den Nutzer/Charakter auf das Einladungs-Verb verweisen |

## Instagram — `app.models.instagram` ✅ (instagram-Paket)

| Funktion | Semantik |
|---|---|
| `get_post(post_id)` | Post-Dict (oder `None`) — Präsenz-/Besitz-Check vor Comment/Reply |
| `add_comment(post_id, commenter_name, text)` | Kommentar/Reply an einen Post anhängen |
| `add_character_like(post_id, character_name) -> bool` | Auto-Like des Kommentators |
| `create_post(character_name, image_filename, caption, hashtags=None, image_prompt='', image_meta=None)` | Post anlegen (Core-Datenmodell; Feed und Route bleiben Core) |

## Soul-Engine — `app.core.soul_writer` ✅ (retrospect-Paket)

Die Soul-Engine besitzt die editierbaren Soul-Dateien (beliefs/lessons/goals) UND den
Retrospect-Zeitstempel (zwei Konsumenten → Core, R5: das retrospect-Paket schreibt,
`thought_context` liest die „Zeit zu reflektieren"-Zeile).

| Funktion | Semantik |
|---|---|
| `list_categories(file_id) -> List[str]` | Gültige Kategorien einer Soul-Datei |
| `load_all_body_lines(character_name, file_id, limit=20) -> List[str]` | Letzte Nicht-Überschrift-Zeilen der ganzen Datei |
| `load_section_lines(character_name, file_id, category_id) -> List[str]` | Nur die Zeilen EINER Kategorie |
| `append_entry(character_name, file_id, category_id, line, language='en') -> bool` | Eintrag anhängen |
| `rewrite_file(character_name, file_id, entries, language='en') -> int` | Datei konsolidiert ersetzen |
| `get_last_retrospect_at(character_name) -> str` / `mark_retrospect_done(character_name)` | Letzten Retrospect-Zeitpunkt lesen/stempeln (`world_kv`, `retrospect.last_at:{char}`) |

## Intents — `app.core.intent_engine` ✅ (F6, deklarationsbasiert)

Skills deklarieren ihre `[INTENT: <typ>]`-Marker selbst (`INTENT_TYPES` +
`INTENT_PAYLOAD_KEYS` als Klassenattribute bzw. `intents`/`intent_payload_keys` im
Manifest) und führen sie über `handle_intent(intent_type, payload)` aus (Default:
JSON-Durchreichung an `execute()`). Die Methode `BaseSkill.tool_intent_payload(raw_input)`
liefert den Vergleichs-Inhalt eines Tool-Aufrufs für den Redundanz-Skip.

Die Engine kennt nur die Core-Typen `remind` und `execute_tool`; alles andere kommt aus
den geladenen Skills — ein nicht geladener Skill macht seinen Intent-Typ unbekannt
(→ Commitment-Memory statt Fehler-Handler). `app.core.intent_engine.strip_intent_tags(text)`
entfernt die Marker vor dem Speichern.

Vorhaben/Aufgaben als Datensatz: `app.models.intents.create_intent(*, owner, title, …)`,
`app.models.intents.list_intents(owner, status, source)`,
`app.models.intents.progress_type_for_tool(tool_name)`.

## Act-Engine — `app.core.act_engine` ✅

`perform_act(actor, text, scope) -> Dict` (async) = die komplette
Storyteller-Pipeline (Szenen-Kontext, Storyteller-LLM, Event-Verdikt, Erzähler-Zeile
in den Stream, Memories/Diary/Bumps). Konsumenten: das Act-VERB (`plugins/act`) und
der Storyteller-Fallback in `routes/play.py`. Die Storyteller-Whitelist
(`app.models.storyteller.list_skill_keys()`) ist dynamisch = alle geladenen Skills.

## Bild-/Video-/Mesh-Service — `app.imagegen.service` ✅

| Funktion | Semantik |
|---|---|
| `get_image_service() -> ImageService` | Singleton der Medien-Engine (Backend-Pool, Auswahl, Pipeline, Vision-Analyse). `svc.enabled` prüfen; `generate_from_input(prompt)` = voller Generierungslauf |
| `ImageService.run_on_backend_channel(backend, gen_fn, *, task_type, agent_name='', label='', priority=-1)` | **Jeder** Backend-Lauf geht hier durch: der Aufruf wird auf dem GPU-/Backend-Kanal serialisiert und zählt gegen das Job-Budget. Nie `backend.generate` direkt rufen |
| `reset_image_service()` | Pool-Neuaufbau beim nächsten Zugriff (ruft `skill_manager.reload_skills` automatisch) |
| `app.imagegen.base.BackendBusyError` | **Last, kein Defekt.** Überlebt die Queue-Grenze als typisierte Exception und wird ohne Cooldown erneut versucht. Ein Paket darf sie nicht in ein generisches „Fehler" umschreiben |

Das TakePhoto-VERB (`plugins/take_photo`, SKILL_ID `image_generation`) ist nur die
LLM-Tool-Oberfläche — Pakete, die Bilder brauchen, rufen den Service.

## Queues — `app.core.task_queue` / `app.core.background_queue` ✅

| Funktion | Semantik |
|---|---|
| `get_task_queue()` | Die persistente Task-Queue (überlebt Neustarts; Admin-Panel, `queue_cli.py`) — für Arbeit, die ein Ergebnis produziert |
| `get_background_queue()` | Die flüchtige In-Process-Queue — für Nacharbeit, deren Verlust beim Neustart egal ist (Beispiel: Social-Reaktionen) |

Ein Verb blockiert nie minutenlang im `execute()`. Lange Arbeit wandert in eine der
beiden Queues; das Verb antwortet dem LLM sofort, was es angestoßen hat.

## Hooks — `app.core.hooks` ✅ (F5-light)

| Funktion | Semantik |
|---|---|
| `register(event, fn, tag='')` | Paket abonniert ein Core-Event (idempotent pro `(event, tag)` — Reload-sicher). Typisch im `on_load`-Modul oder im Skill-`__init__` |
| `emit(event, **kwargs) -> int` | Core feuert generisch; Fehler in Callbacks erreichen den Core-Pfad nie |
| `register_provider(capability, fn)` | Ein Paket stellt die EINE Implementierung einer benannten Fähigkeit; der Core nennt nur den Capability-String (R1) |
| `get_provider(capability) -> Optional[Callable]` | Core holt den Provider; `None` ⇒ neutraler Default |

Es gibt **kein** `unregister` — der Weg zurück ist ein Reload (Registrierung
idempotent halten).

Events, die der Core heute feuert:

| Event | Kwargs |
|---|---|
| `startup` | — (nach dem Boot, aus `app/server.py`) |
| `interaction.invited` | `invite_id`, `inviter`, `invitee`, `pose_key` |
| `instagram.post_created` | `poster_name`, `post` |
| `instagram.user_comment` | `character_name`, `post_id`, `commenter_name`, `comment_text`, `comment_id`, `post` |

Capabilities, die der Core heute abfragt:

| Capability | Fragt | Ohne Paket |
|---|---|---|
| `pair_verb_name` | `routes/play.py`, `plugins/set_pose` | `/play/interact/options` bietet nichts an, die Player-UI schlägt keine Paare vor |
| `romantic_compatibility` | `models/relationship.are_romantically_compatible` | immer kompatibel |
| `romantic_interests_help` | `/admin/settings` | der Hilfe-Button fehlt |

## Skill-Hooks (Deklarationen an der Klasse / im Manifest) ✅

| Hook | Semantik |
|---|---|
| `visible_for(character_name) -> bool` | Per-Character-Sichtbarkeit jenseits der enabled-Config (z.B. Party-Rolle) — der skill_manager fragt generisch ab. Gilt für die RUNTIME-Toolliste; der Admin-Skills-Tab zeigt das Verb weiter an (Config-Fläche ≠ Laufzeit-Fläche) |
| `defer_for_attachment(raw_input) -> bool` | Call muss NACH den deferred Image-Tools desselben Turns laufen (Input referenziert ein erst dann existierendes Attachment) |
| `thought_context_block(character_name) -> str` | Selbst-enthaltene Prompt-Sektion (s.u.) |
| `handle_intent(intent_type, payload) -> Dict` | Ausführung eines deklarierten Intents |
| `tool_intent_payload(raw_input) -> str` | Vergleichs-Inhalt für den Redundanz-Skip |
| `get_usage_instructions(format_name='', character_name='') -> str` | Eigenes Tool-Beispiel; baut man mit `app.core.tool_formats.format_example(format_name, tool_name, example_input)`, damit es zum aktiven Tool-Format passt |

Flags, die der Core generisch liest (`skill_manager.tool_names_with_flag(flag)` liefert
alle Tool-Namen mit einem gesetzten Flag) — im Manifest setzbar:
`SINGLETON`, `SUPPRESS_IN_PERSON`, `CASCADE_BRAKE`, `SEARCH_INTENT`,
`DELIVERS_SPEECH`, `USER_NOTIFICATION`, `REMOTE_COMM`, `PROGRESS_TYPE`
(`skill_manager.progress_type_for_tool(tool_name)`).

Nur als **Klassenattribut** (sie ändern den Ausführungszeitpunkt, nicht bloß Metadaten):
`ALWAYS_LOAD`, `DEFERRED` (Tool läuft erst nach der Chat-Antwort),
`CONTENT_TOOL` (Ergebnis muss in die RP zurück — im `rp_first`-Modus mit Chat-Retry).

## Prompt-Beiträge — `thought_context_block` ✅

Skills liefern per `thought_context_block(character_name)` eine selbst-enthaltene
Prompt-Sektion (eigener `=== Header ===` + Inhalt + Verb-Anweisungen) — der
Thought-Context joint die Blöcke der beim Charakter aktiven Skills generisch
(`skill_context_blocks` in `chat/agent_thought.md`). Beispiel: der
Instagram-Pending-Block.

**Feingranulares Unterdrücken (drop_blocks).** `thought_context` legt die Blöcke
zusätzlich als `(package_id, text)`-Liste im internen ctx-Key `_skill_block_parts`
ab (`registry.package_of_skill`). Ein Prompt-Filter kann so ein einzelnes Paket
adressieren: der drop_blocks-Eintrag **`skill:<paket>`** entfernt nur dessen Block und
re-joint `skill_context_blocks` (`prompt_filters.apply_filters`); der grobe Key
`skill_context_blocks` unterdrückt weiterhin ALLE. Die verfügbaren
`skill:<paket>`-Keys liefert der States-Endpoint dynamisch je geladenem Paket mit
Block-Beitrag (`admin_settings._prompt_filter_block_keys`).

## LLM, Templates, Zeit & Sprache ✅

| Funktion | Semantik |
|---|---|
| `app.core.llm_router.llm_call(task, system_prompt, user_prompt, *, agent_name='', priority=None, label='', max_tokens=None)` | IMMER über die Provider-Queue — nie direkt zum Provider. `task` ist ein Eintrag aus `app/core/llm_tasks.py` |
| `app.core.llm_router.fallback_parent(task) -> Optional[str]` | Wohin ein nicht zugewiesener Task fällt — die EINE Stelle dieser Regel, nie nachbauen |
| `app.core.prompt_templates.render_task(task, **vars) -> (system, user)` / `render(template_path, **vars) -> str` | Jinja-Templates; die Paket-Templates liegen im Suchpfad (`StrictUndefined` — ein fehlender Platzhalter kracht laut) |
| `app.core.tool_formats.format_example(format_name, tool_name, example_input) -> str` | Tool-Nutzungs-Beispiel im aktiven Tool-Format |
| `app.core.timeutils.game_time() -> GameTime` | Die **Spielzeit**. Alles, was die Spielwelt sieht, rechnet damit — nie `datetime.now()` in Spiel-Logik (`scripts/smoke_game_time_lint.py` erzwingt das) |
| `app.core.timeutils.utc_now()` / `utc_now_iso()` / `parse_iso(s)` | SYSTEM-Zeit — nur technische Stempel (Persistenz, Reihenfolge, Cooldowns, Logs) |
| `app.core.i18n.t(en, lang=None) -> str` | Übersetzbare Zeichenkette; die Quelle bleibt Englisch |
| `PluginContext`: `ctx.get_config(path, default)`, `ctx.http`, `ctx.logger` | Welt-Config per Dot-Pfad (Beispiel `skills.markdown_writer.max_size_kb` seedet die Per-Character-`_defaults`), HTTP, Logging |

## Improvement types — `app.core.improvements` ✅

The idle improvements queue runs generation work while nobody is playing: the engine
picks ONE step at a time, hands it to a TaskQueue worker and never names a type — it
asks the registry. A package contributes its own kind of background work by
registering an improvement type; the core stays free of the package (R1).

**When it runs.** The engine ticks at the admin tick
(`server.world_admin_tick_interval_seconds`, default 60 s) with a sub-task floor of
30 s, and only submits when the user has been idle for `idle_minutes`. The idle stamp
has exactly ONE source: an HTTP request that writes (any method that is not
GET/HEAD/OPTIONS, except the `/improvements` admin API itself), stamped by the single
middleware in `app/server.py`. No route and no producer stamps by hand — a generation
is not activity in itself, or the queue's own autonomous renders would keep the window
closed forever.

**The class.** Subclass `app.core.improvements.base.ImprovementType`, set `id`
(stable, it is stored with every entry), `label` (admin UI) and `params_schema`, then
implement four methods:

| Member | Semantik |
|---|---|
| `params_schema: List[ParamField]` | The form the admin fills in when creating an entry. `ParamField(key, label, kind, options=None, required=True)`; `kind` ∈ `mesh_backend` \| `image_backend` \| `subject_kind` \| `enum` \| `text` — `enum`/`subject_kind` carry their own `options` (`[{"value","label"}]`), the backend kinds fall back to the world's full list when they carry none. A backend field that MAY not use every backend fills its own `options` (`subjects.mesh_backend_options(rigs)`) — and then `params_schema` has to be a `@property`, so the offered list is read live instead of freezing at server start |
| `validate(params) -> params` | Normalised parameters, or `ValueError(message)`. The base class checks required fields and option membership; override it (calling `super().validate`) for rules between fields — e.g. "source and target backend must differ" |
| `find_candidates(params) -> List[Candidate]` | Every subject NOT yet done, in a stable order (`(label.lower(), key)`). `Candidate(key, label)`: the key is unique per type and is what a step row stores (`"character:<name>"`, `"location:<id>:<file>"`). A subject that could not be worked at all (nothing to generate FROM) is not a candidate |
| `is_done(candidate, params) -> bool` | The type's own "is this subject finished" test — read the persisted asset, never a cached answer. The engine never calls it; `find_candidates` uses it to decide what to list, and a subject that drops off that list is closed as done |
| `apply(candidate, params, task_id)` | Does the work SYNCHRONOUSLY: it returns only once whatever it made is persisted. It runs in a queue worker thread (no event loop of its own, and `user_activity` is suppressed for the duration), so it calls the blocking producer directly — never a `trigger_*` thread wrapper, which would report success while nothing had been generated |

**Failure vocabulary of `apply`.** A defect is a plain exception (its message lands in
the step's `error`; the step is retried once, then skipped).
`app.imagegen.base.BackendBusyError` and `app.core.improvements.base.CandidateBusy`
mean LOAD, not a defect: the step stays pending and keeps both its attempts. Raise
`CandidateBusy` when the subject is already being generated somewhere else — most
producers keep an in-flight set that a direct caller has to honour itself.

**Registration** — in the package's `on_load` module (see `docs/plugins.md`), so a
package without a verb can contribute one too:

```python
from app.core.improvements import registry
from .my_type import MyType

registry.register(MyType())
```

Registering the same `id` twice simply replaces the entry, so a force reload is
harmless. An entry whose type is not registered (a package went away) is skipped with
a readable error instead of blocking the queue. The built-ins under
`app/core/improvements/types/` are the worked examples; `subjects.py` there is where
the "which subjects exist / how is one regenerated" knowledge lives, so a type stays a
declaration.

| Built-in | Was es tut |
|---|---|
| `model_replace` | Re-generates every model a given mesh backend made, on another one |
| `fill_missing` | Generates the asset a subject has none of at all (model, expressions) |
| `image_rerender` | Re-renders portraits/gallery images of one image backend on another |
| `surface_bake` | Bakes the walkable-surface lattice of room and prop models |
| `mesh_from_tpose` | Generates the character mesh of every stored outfit combination that has a T-pose render but no model |
