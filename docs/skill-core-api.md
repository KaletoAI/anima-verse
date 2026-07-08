# Core-Schnittstellen für Skill-Pakete

Kuratierte Referenz der Core-APIs, die Skill-Pakete aufrufen dürfen. Gegenstück zu
`docs/plugins.md` (deklaratives Paketformat): Dieses Dokument beschreibt die
**imperative** Seite — was ein Verb zur Laufzeit rufen kann.

Regeln (plan-skill-plugin-architecture.md):
- **Richtung:** Pakete rufen Core — das Core referenziert niemals ein Paket (R1).
- **Pflege-Pflicht:** Jede Skill-Migration ergänzt hier die Schnittstellen, die sie
  nutzt oder neu schafft (Verfahren §4.2). Jeder R5-Entscheid „bleibt Core-Engine"
  bekommt hier seinen Eintrag. Die Liste ist kuratiert, nicht automatisch vollständig.
- Skills interagieren untereinander NIE direkt, nur über dieses Core-Vokabular (R6).

Status-Legende: ✅ = von migrierten Paketen genutzt und stabil · ⚠ = existiert,
wird von Built-ins genutzt, aber noch nicht als Paket-API gehärtet/geprüft.

## Deklarativ (Manifest, kein Code)

Siehe `docs/plugins.md`: Verben (`skills`), LLM-Templates (`templates.llm`),
Character-Template-Fragmente (`templates.character` + `apply_to`), Admin-Config
(`config_schema`), Flag-Lebenszyklen (`state_flags`), UI-Paarung (`pair_with`),
Default-Aktivierung (`default_enabled`).

## Zustands-Flags — `app.models.character` ✅

| Funktion | Semantik |
|---|---|
| `set_state_flag(name, flag, value)` | Generischer Setter; stempelt `state_flag_since[flag]` (Basis für TTL-Zerfall) |
| `get_state_flags(name)` | Alle Kern-Flags als Dict (is_sleeping/is_wet/is_intimate/decency_exempt) |
| `stamp_state_flag_since(name, flag)` | Baseline-Stempel für ein bereits gesetztes Flag |
| `set_is_wet / set_is_intimate / set_decency_exempt / set_is_sleeping` | Flag-spezifische Delegates (Kern-Vokabular; auch von Rules/Routen genutzt) |

Lebenszyklus (Prompt-Zeile, TTL, Location-Reset) NICHT selbst bauen — deklarativ über
`state_flags` im Manifest; der Executor (`app/core/flag_lifecycle.py`) ruft zum
Auto-Clear das `cleared_by`-Verb des Pakets.

## Stats — `app.core.stat_effects` + Template-Deklaration ✅

Stats sind vollständig template-getrieben (`store=status_effects`-Felder; Pakete
steuern eigene Stats per Character-Template-Fragment bei — Beispiel Lust im
intimacy-Paket). Der Core kennt keinen Stat-Namen.

| Mechanismus | Semantik |
|---|---|
| Feld-Deklaration `bar_hourly` (+`bar_hourly_sleeping`) | Natürliche Steigung/Senkung pro Stunde — führt der stündliche Status-Tick aus (`activity_engine.apply_hourly_status_tick`) |
| Feld-Deklaration `hint` / `hint_thresholds` | Semantik für den LLM-Evaluator und Prompt-Hinweise |
| `evaluate_stat_effects(name, situation_text, source=…, per_hour=…, elapsed_min=…)` | EINE LLM-Runde gegen alle deklarierten Stats; Text = Paket-Policy (Beispiel: Klimax-Runde des intimacy-Pakets). `per_hour=True` skaliert auf die verstrichene Zeit |
| Aktivitäts-Tick (automatisch) | Der Agent-Loop bewertet die LAUFENDE Freitext-Aktivität gegen alle Stats — kein Library-Lookup; wiederverwendbar für jedes Paket (Workout ⇒ Stamina/Fitness-Deklaration + Hints genügt) |
| `app.models.character.adjust_status_effects(name, deltas, source)` | Direkte Deltas ohne LLM-Runde (clamped 0–100) |

## Body-Slots — `app.core.body_slots` ✅ (Spezies-Pakete)

| Funktion | Semantik |
|---|---|
| `slots_for_character(name)` | anwendbare Slot-Deklarationen (Spezies-Template + applies_to) |
| `slot_values(name)` / `set_slot_value(name, slot, attr, value)` | gespeicherte Attribut-Werte (Profil, Stammdaten) |
| `prompt_fragments(name)` | `{general, exposed}` — general = always+covered (Personenbeschreibung, F1), exposed nur unbedeckt |
| `appearance_suffix(name)` | kombinierter Text; hängt der PromptBuilder automatisch an die Appearance an |
| `piece_slots_for_character(name)` | Kleidungs-Slot-Topologie der Spezies (Fallback `VALID_PIECE_SLOTS`). Konsumenten: Paper-Doll/Belongings, `inventory.equip_piece`-Validierung, `CreateOutfit`-Slot-Liste, Decency-required-Slots (`PUBLIC_REQUIRED_SLOTS ∩ Topologie`) |
| `declared_piece_slots(name)` | `(slots, labels)` NUR wenn eine Spezies deklariert (sonst None — Aufrufer behalten ihren Core-Default) |
| `silhouette_for_character(name)` | Silhouetten-Deklaration des Spezies-Pakets (UI) |

Deklaration ausschließlich über das Manifest (`body_slots`/`piece_slots`/
`silhouette` + `apply_to`) — siehe docs/plugins.md. UI-Endpunkte:
`GET/POST /characters/<c>/body-slots[/<slot>]` (generischer Editor im
WardrobeTab), `GET /characters/<c>/silhouette` (Paket-Asset); Belongings
liefert `slot_order`/`slot_labels`/`slot_anchors`/`silhouette_url` spezies-getrieben.

## Outfit / Decency — `app.core.outfit_compliance` ✅

| Funktion | Semantik |
|---|---|
| `apply_outfit_compliance(name)` | Decency/Style des aktuellen Raums gegen equipped_pieces abgleichen — nach JEDER Zustandsänderung rufen, die die Kleiderordnung beeinflusst |

## Beziehung — `app.models.relationship` ⚠ (Ziel-API der geplanten attraction/romantic_interests-Pakete)

| Funktion | Semantik |
|---|---|
| `get_relationship(a, b)` | Beziehungsdaten zweier Charaktere |
| `get_romantic_interests(name)` | Freitext-Interessen aus der Char-Config |
| `extract_romantic_interests()` | LLM-Extraktion in die Char-Config |
| `interest_aliases`-Feld-Property | Attraction-Matching liest Alias-Blöcke aus Template-Feldern — vollständig template-getrieben, Pakete können Felder mit Aliases beisteuern |

## Inventar — `app.models.inventory` ✅ (consume_item-Paket) / ⚠ (Rest)

Vom **consume_item-Paket** genutzt und stabil: `resolve_item_id` (Token→Item-ID),
`get_item`, `has_item`, `consume_item` (Konsum-Pipeline: qty-Decrement + effects +
apply_condition; liefert `{success, changes, condition_applied}`). Die Model-Funktion
`consume_item` ist Core-Vokabular — Routen (`play.py`, `inventory.py`) rufen sie direkt,
kein Skill-Bezug.

Weiter (⚠, heute nur Built-ins): `equip_piece`/`unequip_piece`,
`equip_item`/`unequip_item`, `add_item`, `add_to_inventory`,
`find_inventory_piece_by_name_slot`, `VALID_PIECE_SLOTS`.

## Welt & Bewegung — `app.models.world` ⚠

Abfragen: `list_locations`, `get_location_by_id`, `get_location_rooms`,
`get_room_by_name`, `get_entry_room_id`, `get_location_name`.
Pathfinder (Core-Engine, R5): `find_path_through_known`, `next_step_toward`.
Zugangs-/Verlass-Regeln: `app.models.rules.check_access`/`check_leave` (⚠ — heute
über die Movement-Built-ins; wird mit deren Migration gehärtet).

## Charakter-Profil & Ort — `app.models.character` ✅/⚠

| Funktion | Semantik |
|---|---|
| `get_character_profile(name)` / `save_character_profile(name, prof)` | Profil inkl. Runtime-State (character_state) und Meta-Keys; bei Neuanlage `create_new=True` Pflicht |
| `save_character_current_location(name, loc)` | ZENTRALE Bewegung — löst Entry-Room, Compliance, Party-Drag, Flag-Location-Resets, Discovery aus. Nie umgehen |
| `get_character_skill_config` / per-Char-Config | über `BaseSkill._get_effective_config` (Defaults + Overrides, typisiert) |
| `get_character_dir(name)` ✅ | Per-Charakter-Storage-Verzeichnis — für Pakete, die eigene Dateien pro Charakter persistieren (Beispiel: markdown_writer schreibt nach `<dir>/documents/<folder>/`) |
| `list_available_characters()` ✅ | Alle bespielbaren Charakternamen (talk_to löst darüber den Ziel-Namen auf) |
| `get_character_current_location(name)` ✅ | Aktueller Aufenthaltsort (Präsenz-Check: TalkTo nur bei gleichem Ort) |
| `is_character_sleeping(name)` ✅ | Schläft der Ziel-Charakter? (nicht erreichbar) |
| `app.core.activity_engine.is_character_interruptible(name)` ✅ | `(bool, busy_activity)` — ob der Charakter gerade unterbrechbar ist |

## Wahrnehmung & Loop ⚠

| Funktion | Semantik |
|---|---|
| `app.core.perception.record_utterance(…)` | Erzähler-/Sprechakt-Zeile in den Raum-Stream |
| `app.core.agent_loop.agent_loop().bump(name, reason=…)` ✅ | Charakter für einen zeitnahen Thought-Turn vormerken (talk_to bump'ed den Empfänger) |
| `app.models.memory.add_memory(…)` | Erinnerung anlegen |
| `app.models.account.is_player_controlled(name)` / `get_active_character(…)` ✅ / `get_chat_partner()` ✅ | Avatar-Erkennung; `get_chat_partner` = aktueller Gesprächspartner (talk_to schließt ihn als Ziel aus) |

## Chat & Messaging — `app.models.chat` / `app.core.pending_reports` ✅ (talk_to-Paket)

| Funktion | Semantik |
|---|---|
| `app.models.chat.save_message(msg, character_name=…, partner_name=…)` | Eine Zeile in die Chat-History eines Charakters schreiben (Inbox-Modell: Sender als `assistant`, Empfänger als `user`) |
| `app.core.pending_reports.add_report / list_open / mark_resolved` | Chain-of-Command-Follow-ups: wer wem noch eine Rückmeldung schuldet (talk_to legt bei Fremd-Initiator einen Report an und löst offene beim Antworten) |

## Pose-Engine — `app.core.pose_engine` ✅ (set_pose-Paket)

| Funktion | Semantik |
|---|---|
| `resolve_pose_variant(name, raw_pose, activity_hint="")` | End-to-End: roher `pose_intent` → Variant-Dict (`{id, canonical_pose, …}`), normalisiert + gegen bestehende Bild-Varianten gematcht; `None` bei leerem Input. Die Engine bleibt Core (R5 — 5+ weitere `pose_intent`-Schreiber). Das set_pose-Paket schreibt danach `pose_intent`/`pose_variant_id` ins Profil |

## Instagram — `app.models.instagram` ✅ (instagram-Paket) / ⚠ (Rest)

| Funktion | Semantik |
|---|---|
| `get_post(post_id)` | Post-Dict (oder None) — Präsenz-/Besitz-Check vor Comment/Reply |
| `add_comment(post_id, commenter_name, text)` | Kommentar/Reply an einen Post anhängen (Reply = `@commenter …`-Body) |
| `add_character_like(post_id, name)` | Auto-Like des Kommentators (Default an) |
| `create_post(name, image_filename, caption, …)` | Post anlegen — Core-Datenmodell (Feed/Route/`InstagramSkill` bleiben Core bis F6/Welle 5) |

## Intents — `app.core.intent_engine` ✅ (F6, deklarationsbasiert)

Skills deklarieren ihre `[INTENT: <typ>]`-Marker selbst (`INTENT_TYPES` +
`INTENT_PAYLOAD_KEYS` als Klassenattribute bzw. `intents`/`intent_payload_keys`
im Manifest) und führen sie über `handle_intent(intent_type, payload)` aus
(Default: JSON-Durchreichung an `execute()`). `tool_intent_payload(raw_input)`
liefert den Vergleichs-Inhalt eines Tool-Aufrufs für den Redundanz-Skip.
Die Engine kennt nur die Core-Typen remind/execute_tool; alles andere kommt
aus den geladenen Skills — ein nicht geladener Skill macht seinen Intent-Typ
unbekannt (→ Commitment-Memory statt Fehler-Handler).

## Hooks — `app.core.hooks` ✅ (F5-light)

| Funktion | Semantik |
|---|---|
| `hooks.register(event, fn)` | Paket abonniert ein Core-Event (idempotent pro (event, tag) — Reload-sicher). Aufruf typischerweise im Skill-`__init__` |
| `hooks.emit(event, **kwargs)` | Core feuert generisch; Fehler in Callbacks erreichen den Core-Pfad nie |

Events bisher: `instagram.post_created(poster_name, post)` ·
`instagram.user_comment(character_name, post_id, commenter_name, comment_text, comment_id, post)`.

## Prompt-Beiträge — `thought_context_block` ✅

Skills liefern per `thought_context_block(character_name)` eine
selbst-enthaltene Prompt-Sektion (eigener `=== Header ===` + Inhalt +
Verb-Anweisungen) — der Thought-Context joint die Blöcke der beim Charakter
aktiven Skills generisch (`skill_context_blocks` in agent_thought.md).
Beispiel: der Instagram-Pending-Block des instagram-Pakets.

## LLM & Templates ✅

| Funktion | Semantik |
|---|---|
| `app.core.llm_router.llm_call(task=…, system_prompt=…, user_prompt=…, agent_name=…)` | IMMER über die Provider-Queue — nie direkt zum Provider |
| `app.core.prompt_templates.render_task/render` | Jinja-Templates; Paket-Templates liegen im Suchpfad |
| `app.core.tool_formats.format_example(fmt, tool_name, example_json)` ✅ | Baut ein Tool-Nutzungs-Beispiel im aktiven Tool-Format (für `get_usage_instructions`-Override) |
| `PluginContext`: `ctx.get_config(path, default)`, `ctx.http`, `ctx.logger` | Welt-Config (Dot-Pfad; Beispiel `skills.markdown_writer.max_size_kb` seedet Per-Character-`_defaults`), HTTP, Logging |
