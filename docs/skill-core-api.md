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

## Inventar — `app.models.inventory` ⚠

`resolve_item_id`, `get_item`, `has_item`, `consume_item`, `equip_piece`/`unequip_piece`,
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

## Wahrnehmung & Loop ⚠

| Funktion | Semantik |
|---|---|
| `app.core.perception.record_utterance(…)` | Erzähler-/Sprechakt-Zeile in den Raum-Stream |
| `app.core.agent_loop.agent_loop().bump(name, reason=…)` | Charakter für einen zeitnahen Thought-Turn vormerken |
| `app.models.memory.add_memory(…)` | Erinnerung anlegen |
| `app.models.account.is_player_controlled(name)` / `get_active_character(…)` | Avatar-Erkennung |

## LLM & Templates ✅

| Funktion | Semantik |
|---|---|
| `app.core.llm_router.llm_call(task=…, system_prompt=…, user_prompt=…, agent_name=…)` | IMMER über die Provider-Queue — nie direkt zum Provider |
| `app.core.prompt_templates.render_task/render` | Jinja-Templates; Paket-Templates liegen im Suchpfad |
| `PluginContext`: `ctx.get_config(path)`, `ctx.http`, `ctx.logger` | Welt-Config (Dot-Pfad), HTTP, Logging |
