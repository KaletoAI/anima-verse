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

## Tool results and ordering — `app.skills.base`

Plugins may import `ToolRefusal` from `app.skills.base` and return it when a
tool refuses the requested action. Its constructor is
`ToolRefusal(reason: str, *, correction_tools: tuple[str, ...] = ())`.
The result is a `str` subclass: ordinary tool consumers receive readable
`Error: <reason>` text, while the room-chat dispatcher can inspect its
`correction_tools` tuple without interpreting prose.

`correction_tools` contains public tool names that could correct this refusal;
derive optional capability names from the existing provider registry rather
than naming another package in core code. The dispatcher offers only declared
tools that are actually available, for at most one intent-LLM correction round.
It does not repeat any tool already attempted in the original batch, including
terminal refusals. Inferred solo pose markers and state extraction cannot undo
an active pair interaction; an explicit new action can still end it. An unavailable
correction or a refused correction remains visible through the existing failure
feedback; returning this result is not a guarantee that another tool will run.
Declare nonempty `correction_tools` only when the refused call made **no side
effects**. A terminal refusal may have recorded bookkeeping (such as a failed
invitation row); it must leave `correction_tools` empty and is not retried.
Do not report a successfully completed requested action as a refusal.

`ToolSpec.run_before: tuple[str, ...] = ()` declares public peer-tool names
that must execute after this tool when both occur in the same room-chat reply.
The dispatcher stably orders matching calls; it does not suppress either action
or carry the ordering into later turns. Resolve optional peer names through the
existing capability provider rather than hardcoding package dependencies.

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

RP chat uses a separate, event-addressed contract: `stat_results`, documented
in [LLM templates](llm-templates.md#chat-state-extraction-contract). The generic
`stat_effects` task still returns flat `{"stats": {"<key>": delta}}` for
activity/nonchat situations. Hourly drift, activity ticks, item effects, rewards
and skill costs do not acquire Influence multipliers or the chat budget.

## Stat rules — `app.core.stat_rules` ⚠

Rules resolve template seeds, whole-entry world overrides and character config.
Only keys declared by the character's template are returned. Character config
`<key>_hourly` and `<key>_baseline` numbers (numeric strings accepted) override the corresponding values;
empty or null baseline values keep the resolved default. Settings use the shared
`shared/stats/settings.json` seed and whole-value world overrides.

| Function | Semantics |
|---|---|
| `field_rule(field) -> dict` | Normalize `bar_hourly`, `bar_baseline`, `bar_pull` (clamped 0..1), `bar_rates`, and `hint_thresholds` |
| `template_rules(template) -> dict` | Template seeds keyed by stat |
| `rules_for_template(template) -> dict` | Seeds replaced by world entries for declared keys |
| `rules_for_character(name, *, profile=None, config=None) -> dict` | Effective rules including character config |
| `seed_rule(key) -> dict | None` | Seed from the first declaring template, sorted by name |
| `world_stat_overrides() -> dict` | Normalized world entries |
| `save_stat_override(key, rule) -> bool` | Save a complete replacement entry |
| `delete_stat_override(key) -> bool` | Restore the template seed |
| `shipped_settings() -> dict` | Shared settings seed |
| `get_setting(name)` | Effective setting; unknown names raise `ValueError` |
| `settings_with_source() -> dict` | Each setting's `value`, `shipped`, and `source` (`shared` or `world`) |
| `save_setting(name, value) -> bool` | Save a whole-value override; reject unknown names |
| `delete_setting(name) -> bool` | Restore the shared setting; reject unknown names |
| `round_half_away(x) -> int` | Nearest integer, ties away from zero |
| `invalidate()` | Clear the storage-directory/shared-file snapshot; saves and deletes call this automatically |

## Active states — `app.core.prompt_filters` ⚠

| Function | Semantics |
|---|---|
| `is_state_active(name, state_id, *, profile=None) -> bool` | Enabled state active through its profile tag OR expression, using the same evaluator as triggered filters. A ContextVar guard returns false for a state already being evaluated, including indirect cycles. |

Condition expressions also accept `at_home`, `offmap`, `travelling`,
`location_danger>N` (also `<` and `=`), and `state:<id>`. Location atoms read the
character's own current location/position, even during target access checks.

A state never fires on a stat the character does not have (inside
`app.core.activity_engine.missing_stats_fail()` a missing stat is "not met"); rule
conditions keep "missing counts as 100".

## Strict conditions and held snapshots — `app.core.activity_engine`

| Function / value | Semantics |
|---|---|
| `validate_condition_expression(condition) -> list[ConditionIssue]` | Validate the existing OR/AND/NOT grammar without world reads; each immutable issue has `code` and `message` |
| `evaluate_condition_strict(condition, character_name, location_id="", room_id="", *, profile=None) -> ConditionResult` | Immutable `available`, `passed`, `reason`; reuse a held profile instead of loading it again |

Strict evaluation distinguishes available/true, available/false and unavailable.
It checks the whole expression: an unknown stat/reference, failed storage read,
missing required context or cyclic state is unavailable, including beneath NOT
or in another OR branch. Negation cannot turn a read failure into permission,
and a true OR branch cannot hide it. An empty expression is available/true.
This opt-in path does not change ordinary `evaluate_condition` or the legacy
missing-value defaults described above.

## Skill gate — `app.core.skill_gate` ⚠

Rules of type `block` with `target.scope = "skill"` and the world setting
`skill_costs` decide whether a character may use a skill right now. The core
applies the gate to the tool list and every execution path; a package only needs
it for its own direct calls.

| Function | Semantics |
|---|---|
| `blocked_reason(name, skill_id, *, profile=None, rules=None) -> str` | Rule message or cost shortfall; `""` = allowed |
| `blocked_skills(name, skill_ids) -> dict` | Reasons for the blocked ids only (one rules load) |
| `run_gated(name, skill_id, call) -> result` | Recheck, run, charge the cost after a non-error result; blocked → `"Error: <reason>"` |
| `charge(name, skill_id) -> dict` | Deduct the configured cost (source `skill:<id>`) |
| `stat_costs_shortfall(profile, costs) -> str|None` | Generic "needs N <stat>" check; stats the character lacks are free |

The shared `streaming.is_error_result` boundary recognizes legacy
`Error`/`Fehler` prose and dictionary/serialized-JSON failures: explicit
`success:false`, `ok:false`, a nonempty `error`, or `status` equal to
`refused`, `failed`, or `error`. Structured tools may retain their machine-readable
contract without paying success-only costs on refusals. Cancellation is not
classified as failure merely because its status is terminal.


## Modifiers — `app.core.modifiers` ⚠

Rules of type `modify` (`{"modify": {"quantity", "factor"}}`, factor 0.1..5)
scale a registered quantity while their condition holds; matching rules multiply.
Core quantities: `travel_speed`, `discovery`, `spell_success`, `thought_frequency`.

| Function | Semantics |
|---|---|
| `register_quantity(qid, label, description)` | Register a package quantity (call in `on_load`); appears in the Rules tab |
| `factor(name, qid, *, profile=None, rules=None) -> float` | Product of matching rules (1.0 without); a missing stat never fires; cached 30 s, cleared on every rule change |
| `modify_rules() -> list` | Load once when asking about many characters |

## RP Influence — `app.core.stat_influence`

Influence is a subtype of the existing Rules library, not a modifier quantity
or a separate store. Its persisted discriminator is `type: "influence"`:

```json
{
  "id": "encouragement",
  "name": "Trusted encouragement",
  "type": "influence",
  "condition": "",
  "actor_condition": "",
  "pair_conditions": [
    {"kind": "relationship", "op": ">", "value": 40},
    {"kind": "attraction", "observer": "recipient"}
  ],
  "influence": {
    "actor": "",
    "recipient": "",
    "stat": "<template-declared stat key>",
    "direction": "increase",
    "factor": 2
  }
}
```

`actor` and `recipient` are exact names or empty strings for any eligible actor
or recipient; both fields are present. `condition` binds only the recipient,
`actor_condition` only the actor, using strict evaluation. Pair conditions are
ANDed: `relationship` compares the exact actor/recipient pair's strength with
`>`, `<` or `=` and a number from 0 to 100 (a successful no-row read means 0);
`attraction` asks whether its selected observer is attracted to the other role.
These are structured pair tests, not legacy "any partner" condition searches.
Unavailable references/providers leave a stored rule intact but inactive.

`direction` is `increase`, `decrease` or `both`, selected from the original
base delta's sign. Factors are finite numbers from 0.1 to 5, not booleans.
Each matching rule ID contributes once, matching factors multiply, and only
the final product is clamped to 0.1..5. Traces are sorted by ID. Self/unattributed
effects, zero deltas and missing/undeclared recipient stats have factor 1.
Stat names and authoring choices come from character templates, never core lists.

| Function | Semantics |
|---|---|
| `validate_influence_rule(rule) -> list[dict]` | Shape/syntax errors as `{path, code, message}`; missing current-world references are diagnostics, not destructive rewrites |
| `influence_rule_status(rule) -> dict` | `{available, reasons}` for current references/capabilities; a valid but false condition is not an availability error |
| `influence_options() -> dict` | Template stats, pair-condition availability, directions and factor bounds |
| `influence_factor(actor, recipient, stat, base_delta, *, rules, profiles) -> dict` | Local `{factor, rules: [{id, name, factor}]}` from held profiles and rules; no write, model call or network request |
| `project_stat_metadata(metadata, *, include_rule_details=False) -> dict` | Copy metadata; default removes root `event_id` and private per-stat rule traces while retaining valid numeric cause fields, observed actor and unrelated root metadata |

`app.models.rules.load_rules(*, strict=False)` keeps ordinary permissive loading;
`strict=True` raises `RuleWriteError` for a failed/malformed layer instead of
exposing a partial shared/world ruleset. Authoring uses the existing admin Rules
surface. `GET /rules/influence-options` supplies choices;
`POST /rules/influence-validate` with `{"rule": ...}` returns
`{errors, warnings, available}`. Definition reads/exports are admin-only for
Influence. Shared baselines and whole-entry world overrides retain their existing
Rules semantics; cross-layer Influence import overwrite is refused rather than
silently moving a private rule.

The shared RP application owns this order: validate all source/target results,
snapshot profiles/config/rules and the current apply clock, compute local
factors, reserve the recipient/stat/current-game-hour budget against the ORIGINAL
base delta, multiply the admitted base, round half away from zero, then clamp
stored values to 0..100. Both signs consume the same absolute BASE budget;
`chat_cap_per_hour = 0` disables it. Turning points are classified by the
ORIGINAL `abs(base_delta) >= 30` and bypass that budget even when damped.
An amplified ordinary change may exceed the base budget; amplification never
creates a turning-point exemption. The budget is current-hour RAM state.

Each canonical `(event_id, recipient)` commits status, actual-change history
and a durable receipt atomically. Empty, zero and fully clamped valid results
also commit receipts; failed/duplicate commits spend no budget. A receipt
survives history trimming, so re-reading context cannot reapply an old event.
Independent pairs apply in canonical source order and can fail independently.
History `cause[stat]` captures `actor`, `base_delta`, `capped_base_delta`,
`modified_delta` (uncapped potential), `capped_delta` (admitted base × factor,
rounded), `factor` and matched `rules`; `changes` records actual clamped old/new
values. Historical records without `capped_base_delta` retain their original
post-influence cap interpretation; no stored history is rewritten. Hourly
history supplies `stat_labels` from each stat's own contributions, not a
combined explanation from unrelated values. Admin Mind shows event/rule snapshots. Player
history, debug and ZIP exports retain only their own permitted numeric effects
and observed actor, never private rule names/IDs or canonical event IDs.

## Rewards — `app.core.stat_rewards`

| Function | Semantics |
|---|---|
| `apply_reward(name, occasion) -> dict` | Apply the world setting `rewards[occasion]` (fixed deltas) |

## Body-Slots — `app.core.body_slots` ✅ (Spezies-Pakete)

| Funktion | Semantik |
|---|---|
| `slots_for_character(character_name, profile=None)` | Anwendbare Slot-Deklarationen (Spezies-Template + `applies_to`) |
| `slot_values(character_name, *, profile=None)` / `set_slot_value(character_name, slot_id, attr, value)` | Stored attribute values; a held `profile` avoids a second character read |
| `prompt_fragments(character_name, face_only=False, profile=None, back_view=False, mesh_input=False, neutral_state=False)` | `{general, exposed}` fragments; `face_only` selects face slots, `back_view` selects rear-view text, `mesh_input` uses T-pose text, and `neutral_state` ignores state-driven modifiers |
| `appearance_suffix(character_name, face_only=False, profile=None, back_view=False, mesh_input=False, include_exposed=True, neutral_state=False) -> str` | Combined appearance text from the same fragment policy; `include_exposed=False` leaves exposed fragments to a caller that already renders them, and `neutral_state` ignores state-driven modifiers |
| `is_slot_exposed(spec, profile) -> bool` | Unbedeckt? Piece-Garderobe: kein Piece in `covered_by`; Freitext-Garderobe: `outfit_worn` aus |
| `attribute_default(decl, profile) -> Optional[str]` | Template-gebundener Fallback eines Attributs (`default`), `None` = keiner |
| `piece_slots_for_character(character_name) -> Tuple[str, ...]` | Kleidungs-Slot-Topologie der Spezies (Fallback `inventory.VALID_PIECE_SLOTS`). Konsumenten: Paper-Doll/Belongings, `inventory.equip_piece`-Validierung, `CreateOutfit`-Slot-Liste, Decency-required-Slots |
| `declared_piece_slots(character_name)` | `(slots, labels)` NUR wenn eine Spezies deklariert, sonst `None` — Aufrufer behalten dann ihren Core-Default |
| `silhouette_for_character(character_name)` | Silhouetten-Deklaration des Spezies-Pakets (UI) |
| `interest_alias_tables(character_name, *, profile=None)` | Declarative body-slot `interest_aliases` tables from the held subject profile |
| `slot_attr_values(character_name, *, profile=None, config=None) -> Dict[str, str]` | Flat lowercased `slot.attr` values; held profile/config preserve the subject snapshot and humanoid feature policy |

`app.core.height.height_word(profile, character_name="", *, config=None)`
uses the same held config for humanoid resolution and returns the existing
height descriptor (empty when unavailable/non-humanoid). Directed matching must
pass its strict profile/config snapshots through these public helpers; it must
not perform permissive hidden rereads or import private core helpers.

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
| `app.core.outfit_renderer.is_free_text_wardrobe(profile) -> bool` | Template ohne Outfit-System (`outfit_system_enabled: false`) — Kleidung = `outfit_description` + `outfit_worn` |
| `app.core.outfit_renderer.undressed_text(profile) -> str` | Was ein Ausgezogener trägt: `undressed_prompt` eines passenden Spezies-Pakets, sonst „no clothes" |
| `app.core.outfit_renderer.undressed_line(character_name="", profile=None) -> str` | LLM-Zeile eines AUSGEZOGENEN Freitext-Charakters: `undressed_text` + unbedeckte Body-Slot-Fragmente, ohne Kleidungsbeschreibung; "" für Angezogene und Piece-Garderoben |

## Beziehung — `app.models.relationship` ⚠

| Funktion | Semantik |
|---|---|
| `get_relationship(char_a, char_b, *, strict=False) -> Optional[Dict]` | Exact pair data; strict storage/decoding failures propagate, while a successful absent row remains `None` |
| `record_interaction(char_a, char_b, …)` | Eine Interaktion verbuchen (Sentiment/Stärke) |
| `get_address(speaker, addressee) -> str` | Anrede-Freitext DIESER Richtung des Paares (`""` wenn nichts gesetzt) |
| `address_line(speaker, addressee) -> str` | Dieselbe Angabe als fertige Prompt-Zeile `Form of address: …` (`""` wenn nichts gesetzt) |
| `get_romantic_interests(character_name) -> str` | Freitext-Interessen aus dem Profil |
| `are_romantically_compatible(char_a, char_b) -> bool` | Fragt den Capability-Provider `romantic_compatibility` (siehe „Hooks"); ohne Paket immer `True` |
| `interest_aliases`-Feld-Property | Attraction-Matching liest Alias-Blöcke aus Body-Slot-Attributen — vollständig deklarations-getrieben |

Die **LLM-Extraktion** der romantischen Interessen ist NICHT im Core: sie lebt im
attraction-Paket (Provider `romantic_interests_help`, siehe „Hooks").

## Inventar — `app.models.inventory` ✅ (consume_item) / ⚠ (Rest)

Used by the **consume_item package** and stable: `resolve_item_id(token, *, strict=False)` (token to item ID),
`get_item(item_id, *, strict=False)`, `has_item(character_name, item_id, *, strict=False)`,
`consume_item(character_name, item_id)` (Konsum-Pipeline: qty-Decrement + effects +
apply_condition; liefert `{success, changes, condition_applied}`). `consume_item` ist
Core-Vokabular — Routen rufen sie direkt, ohne Skill-Bezug.

Weiter (⚠, heute nur Built-ins): `equip_piece`/`unequip_piece`,
`equip_item`/`unequip_item`, `add_to_inventory`,
`find_inventory_piece_by_name_slot`, `VALID_PIECE_SLOTS`.

Public discovery helpers (stable):

| Function | Contract |
|---|---|
| `discovery_value(viewer: str, *, profile=None) -> int` | Effective stat selected by world config `inventory.discovery_stat` (default `"attention"`). A missing stat counts as 0. An existing profile can be passed to avoid another load. |
| `placement_visible_to(viewer: str, location_id: str, room_id: str, placement: dict, *, profile=None) -> bool` | Visible placements return True. Hidden placements return True if already found by this viewer, or if the discovery value meets their integer difficulty (0–999). The first find records game time in `item_discoveries` and creates a personal, localized `item_discovered` notice after releasing locks. Repeated reads do not notify again. Call without holding the world lock. Changes neither world generation nor scene fingerprints. |
| `discovered_by(location_id: str, room_id: str, item_id: str) -> list[str]` | Alphabetically sorted names that found this placement. Full removal through `remove_item_from_room` clears these rows; partial removal and edits retain them. Moving an item by removing and placing it in another room requires discovering it again. |

Public item placement helpers (stable):

| Function | Contract |
|---|---|
| `add_item(name, ..., item_id="", owner="", pages_source="", portable=True, extra_fields=None) -> dict` | Create a world item. `document` is a valid category. Reading fields persist in meta; `extra_fields` accepts localized `name_<lang>` and `description_<lang>` fields only. `update_item` accepts those fields and `owner`, `pages_source`, `portable`. Nonportable items fail pickup with translated `That cannot be taken`. |
| `add_item_to_room(location_id, room_id, item_id, quantity=1, hidden=False, discovery_difficulty=0, note="") -> bool` | Place an item in a room; difficulty is clamped to 0–999. Uses the world write lock. |
| `find_item_location(item_id, exclude_character="") -> dict \| None` | Search inventories first (excluding the named holder), then room placements. Returns `{kind: "character", character}` or `{kind: "room", location_id, room_id}`, or None. |

## Item reading — `app.core.item_reading` ✅

Provider contract:

```python
hooks.register_provider("item_pages.<source>", fn)
# fn(item: dict, reader: str) -> list[dict]
```

Pages are chronological (oldest first),
with `{ref: str, heading: str, text: str, secret_id: str = ""}`. A missing provider
or a provider exception makes the item unreadable; an empty list is a readable
empty book. Providers may perform blocking work and are called without locks.
Optional presentation fields: `date_label: str` and `image: str | Callable[[], str]`
(empty by default). An image is a data URI; a lazy image loader is evaluated only
for the selected human page, after room visibility and owner-catching checks.
Images never reach NPC responses. Providers must not publish private images under
public static URLs. Neither `secret_id` nor `ref` is included in the public page.
The shared reader keeps headings to one line (ellipsis with the full title on hover),
renders date separately and scrolls image/text above fixed page controls.
The image opens in the shared zoom lightbox. Sources may offer regeneration by
registering `item_page_image.<source>` alongside their page provider. Each
regenerable page supplies `image_ref` (an immutable identity, not an array index)
and `image_regenerable: bool | Callable[[], bool]`. The selected human page exposes
the token and resulting boolean; NPC responses contain neither these fields nor
image bytes. Preparation must receive the token of the already displayed page.

```python
hooks.register_provider("item_page_image.<source>", provider)
# provider(item, reader, page, *, action, page_ref="", prompt="", backend="",
#          loras=None, negative_prompt="", task_id="", admit=None) -> dict
```

For `action="prepare"`, return `{prompt, subjects, available, page_ref, backend_options}`;
the core adds `avatar`. Resolve `backend_options` with the actual scene references,
so Auto and its LoRA list match the render. For `action="enqueue"`, preflight
outside access/profile locks, then invoke the provided `admit` callback with a
short persistence operation. The core rechecks the original reader/session,
item source and exact page before admission. Return `{task_id, page_ref,
status: "queued"}` once the durable task exists; never render in that callback.

An admitted job is independent of the read session: closing the book, moving or
reopening does not cancel its render or deny publication. The source-owned worker
must still guard immutable entry identity, deletion/reset and atomic image/meta
replacement, retaining the previous image on failure. Private scene/prompt
snapshots belong in source-owned world storage, not globally visible queue
payloads, labels, results or errors. Preserve the minimal submitter identity at
the GPU handoff, so background work does not bypass the existing user limit.

For `action="status"`, verify that the opaque `task_id` belongs to this reader,
item and immutable page. Return `{status, detail?}`; the core supplies `reading`
only after completion and a fresh authorized read. Pending/running/failed/
cancelled status contains no image bytes.

`POST /play/read/image-prepare {item_id, index, page_ref}` requires an active
authorized session. `POST /play/read/image-regenerate` accepts
`{item_id, index, page_ref, prompt, backend?, loras?, negative_prompt?}` and returns
HTTP 202 `{task_id, page_ref, status: "queued"}` without waiting for generation.
`POST /play/read/image-status {item_id, index, page_ref, task_id}` returns
`{status, detail?, reading?}` only for the authorized reader/page/job. Its completed
`reading` includes `avatar` and the selected page, never an image after closing,
moving or being caught. Admission errors remain HTTP errors; background failures
are reported by status while the existing image remains readable. Poll only
while the reader is mounted and authorized; never block page or game controls.
The shared dialog offers backend-scoped LoRAs with global `scene_view` Auto routing;
an explicit backend choice has no fallback. Existing person reference images stay
part of the render, independently of changing the prompt or backend.



| Function | Contract |
|---|---|
| `has_pages(item: dict) -> bool` | A provider is registered for the item's `pages_source`; does not call it (used by the polled room listing). |
| `pages_of(item: dict, reader: str) -> list[dict] \| None` | Get pages; None for absent source/provider or a logged provider failure. |
| `readable_here(reader: str, item_id: str) -> bool` | Requires a placement in the reader's current room, `placement_visible_to` (stable above), and non-None pages. Carried items do not qualify. |
| `read_page(reader: str, item_id: str, index: int, *, opening: bool = False) -> dict` | Returns `{avatar, item_name, index, total, page: {heading, date_label, text, image, image_regenerable, image_ref}}`, or `{error}` / `{caught_by}`. Index clamps to the book; an empty book has index 0 and page None. Learns the returned page. `opening=True` starts a session; later pages extend it. A pending owner catch returns no page and learns nothing. |
| `npc_read(reader: str, item_id: str) -> dict` | Once daily, returns `{item_name, pages}` with up to two newest unknown linked secrets (newest first), otherwise the newest page; returned text is at most 600 characters per page. Invalid/missing secrets and pages without a secret ID are not unknown. Repeat calls that day return `{error}`. Starts a full-duration session without changing pose; a catch returns `{caught_by}` before learning. |
| `npc_read_today(reader: str, item_id: str) -> bool` | Whether the NPC path was used on this GameTime day. |
| `start_session(reader: str, item_id: str, location_id: str, room_id: str) -> dict` | Replaces this reader's session; started=now, until=now + world `inventory.reading_minutes` (int, default 10). Callers invoke `reading_watch.on_session_started` after return, outside locks. |
| `extend_session(reader: str, item_id: str) -> dict \| None` | Matching live session gets until=now + duration; otherwise None. |
| `active_session(reader: str) -> dict \| None` | Live means not caught, until >= game now, reader still in the stored location/room. Deletes dead rows on read. |
| `sessions_in_room(location_id: str, room_id: str) -> list[dict]` | Live sessions only, with dead rows pruned. |
| `end_session(reader: str, reason: str) -> None` | Deletes the reader's session. |
| `heartbeat(reader: str, item_id: str) -> dict` | Returns `{caught_by: owner}` for a matching pending catch, otherwise `{caught_by: ""}` and extends a live matching session. Does not start a session. |
| `prepare_page_image(reader: str, item_id: str, index: int, *, page_ref: str) -> dict` | Prepare a regenerable page only in the reader's current authorized session and with the displayed immutable page token. A shifted index never selects a different page. Does not load image bytes or learn another secret. |
| `enqueue_page_image(reader: str, item_id: str, index: int, *, page_ref: str, prompt: str, backend: str = "", loras=None, negative_prompt: str = "") -> dict` | Validate current read authority and admit a durable, source-owned replacement. Returns `{task_id, page_ref, status: "queued"}` or an access/catch result; it never waits for the image. |
| `page_image_status(reader: str, item_id: str, index: int, *, page_ref: str, task_id: str) -> dict` | Check reader/item/page/job ownership and current read permission, then return job status and, only on completed authorized reads, the refreshed selected page. |

Sessions persist in `item_reading_sessions(reader PRIMARY KEY, item_id,
location_id, room_id, started_game_ts, until_game_ts, session_id, caught DEFAULT 0,
noticed_by DEFAULT '[]')`. Every start gets a fresh UUID `session_id`, including
when the game clock is frozen; old watcher callbacks cannot match a reopened
session by timestamp. Admitted image jobs deliberately outlive that session.
Returned dictionaries decode `noticed_by` to a list.
Caught rows are inactive but remain available to heartbeat/page turns until
`active_session` prunes them or they are replaced/closed. Room/tick scans leave caught rows available for heartbeat.

`app.core.world_ops.build_imagegen_options(occasion: str = "", character: str = "", *, use_source_as_reference: bool = False, has_reference: Optional[bool] = None) -> dict`
returns the existing backend/LoRA options and effective Auto resolution. A prepared
historical scene supplies `has_reference` from its actual people rather than
borrowing the avatar's photo routing or assuming no references.
Queued user-initiated media may read the submitter through
`app.core.auth_dependency.get_current_user_from_ctx()`. Persist only the minimal
user identity/role needed for the GPU limit, not session tokens, profiles or
permission lists. A worker restores that identity with the module's
`current_user_ctx` ContextVar and resets its token in a finally block.



`app.core.reading_watch.on_session_started(session: dict) -> dict` is the
watcher entry point called by both read paths after starting a session and before
learning. Returns `{caught_by: owner}` when the owner catches, otherwise `{}`.

`app.core.reading_watch.register() -> None` idempotently registers room entry,
world tick and `respond_finished` handlers. Startup calls it once.
`app.core.reading_watch.check_session(session: dict, watchers: list[str]) -> dict` checks live room
presence, distraction and `inventory.notice_reading_difficulty` (default 60),
claims each notice once, then dispatches effects outside locks/transactions.
`app.core.reading_watch.watching_owner(reader: str, item: dict) -> str` returns the present owner when
a same-day catch blocks reopening, otherwise an empty string.

Owner catches mark sessions caught and narrate in the reader's language. The
primary key (reader, item_id, game_day) of the `item_caught_today` table limits memories,
relationship changes and reply chains to once per game day. Owner sentiment
toward reader drops by 0.3. NPC owners reply first; `respond_finished` (except
`superseded`) triggers the NPC reader's free response. Avatars never get LLM
turns. Witnesses silently remember and discover one reader secret per item
(`source_ref=caught_reading:<item_id>`); avatar witnesses also get a notice.
Reopening while the owner remains present returns the localized watching error.

`MEMORIES_PER_DAY = 2`, `NPC_PAGES = 2`, `NPC_PAGE_CHARS = 600`.
Both read paths share learning: for a valid, newly learned secret of another
owner, `app.models.secrets.add_known_by(..., discovered=True)` records knowledge. At most two
memories per reader/item/game day are reserved atomically in `item_reads`
(`reader, item_id, game_day, memories, npc_read`; day keys such as `Y0002-D109`).
Memory text goes through the translation helper with a
localized item name:

```python
t("Read in {item}: {secret}", reader_lang)
```

Memories use episodic type, importance 3, tags `["item", "read"]`,
related_character=owner and extra_meta `{item_id, owner, secret_id, ref}`.
Owners learn nothing from their own pages. Call these helpers without holding
any lock: providers and `add_memory` execute outside every lock/transaction.

`POST /play/read` accepts `{item_id, index, opening}` for the active avatar
(409 without one). Room items expose `readable` and `portable`; avatars can read
with other characters present. `POST /play/read/heartbeat {item_id}` extends the avatar session and returns
`{caught_by}` (empty string when not caught). `POST /play/read/close {item_id}`
ends the matching session and returns `{ok: true}`. Both require an active
avatar (409 without one) and an object body (400 otherwise). A stale close for
another item does not end a newer book session. Modal heartbeat wiring is a
separate task.

## Welt & Ortskenntnis — `app.models.world` / `app.models.rules` ⚠

| Funktion | Semantik |
|---|---|
| `list_locations(*, strict=False)` / `get_location(identifier)` / `get_location_by_id(location_id, *, strict=False)` | All locations or one location; strict readers propagate actual storage/decoding failures |
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

Cross-location NPC movement is normally a timed journey. Do not write a position to
simulate travel. Ordinary SetLocation preserves direct avatar movement and initial
placement; destination-bound shared trips always use timed cross-location travel.

| Funktion | Semantik |
|---|---|
| `start_journey(character_name, target_id, target_room="", target_pose="", journey_id="", execution_ref="") -> (journey \| None, reason)` | Start a timed journey to a named location. `target_room` / `target_pose` apply on arrival, subject to access checks. Optional `journey_id` / `execution_ref` link it to the owning execution. `reason`: `''` = started · `unknown_target` (missing or unknown to this character) · `unplaced_target` (not on the map) · `no_route` |
| `start_journey_to_point(character_name, x, z) -> (journey \| None, reason)` | Reise zu einem freien Punkt. Setzt **kein** `movement_target`, nur die `journey` — Ankunfts-/Abbruchlogik muss beides abfragen |
| `get_journey(character_name, profile=None)` | Die laufende Reise vom Profil (oder `None`) |
| `journey_state(waypoints, started_at_game, now_game, offset_s=0.0) -> Dict` | Pure polyline position from start and game clock with an optional elapsed-time offset in seconds; no state/tick, so all clients derive the same position |
| `cancel_journey(character_name, *, journey_id=None, execution_ref=None)` | Cancel travel; supplied ownership selectors must match the current journey |
| `get_travel_speed_m_s() -> float` | Welt-Tempo (`game.travel_speed_m_s`, Default 1.4 m/s, geklemmt 0.1…20); beim Start auf die Reise geschrieben |
| `app.models.character.list_active_journeys() -> List[Dict]` | EINE Query über alle reisenden Charaktere (`{name, journey, movement_target, current_location}`) — nie über alle Profile iterieren |

## Authoritative movement — `app.core.movement_authority`

| Function | Semantics |
|---|---|
| `movement_allowed(character_name, location_id, room_id="") -> (bool, reason)` | Shared leave, danger, destination condition, location access and room access gates; no denial-history side effects |
| `move_character(character_name, location_id, room_id="", target_pose="", *, participants=None, journey_id="", execution_ref="", timed=True) -> Dict` | Validate every explicit participant before moving. Start timed cross-location travel or set the local room. Outcomes: `travelling`, `arrived`, `blocked`; rule denial includes its gate and participant. `timed=False` is only for the ordinary caller's existing direct-placement policy, never shared trips |


## Charakter-Profil & Ort — `app.models.character` ✅/⚠

| Funktion | Semantik |
|---|---|
| `get_character_profile(character_name, *, strict=False) -> Dict` | Profile with runtime state and metadata; strict storage/decoding failures propagate and missing required profile/state rows raise `LookupError` |
| `get_character_config(character_name, *, profile=None, strict=False) -> Dict` | Reuse a held profile; strict mode never repairs/writes failed config reads. Valid empty config gets defaults in memory; malformed/null/non-object JSON or missing rows fail |
| `save_character_profile(character_name, profile, create_new=False) -> bool` | Schreibt den GANZEN Blob. **Wirft nie** — `False` heißt: nichts gespeichert (reservierter/unbekannter Name oder fehlgeschlagener Write). Rückgabe prüfen. Bei Neuanlage `create_new=True` Pflicht — der Name muss dann die Namensregel erfüllen, sonst `False`. Nur unter `keyed_lock("character_profile", name)` (siehe „Sperren") |
| `app.core.character_name.validate_character_name(name) -> str` | Die EINE Namensregel für NEUE Charaktere: Buchstaben jeder Schrift, Ziffern, einfache Leerzeichen, `-`, `'`, `.`, `_` (nicht am Anfang), 1–60 Zeichen. Gibt den NFC-normalisierten Namen zurück oder wirft `CharacterNameError` (Feld `code`). Gilt nur beim Anlegen/Import — bestehende Namen werden nie geprüft, nie umbenannt |
| `save_character_current_location(character_name='', location='', …)` | ZENTRALE Bewegung — löst Entry-Room, Compliance, Party-Drag, Flag-Location-Resets, Discovery aus. Nie umgehen |
| `get_character_current_location(character_name='', profile=None) -> str` / `get_character_current_room(character_name, profile=None) -> str` | Aufenthaltsort/-raum. Bei laufender Reise ist das die NÄCHSTE Position, nicht das Reiseziel; unterwegs im freien Gelände ist `current_location` leer |
| `is_character_sleeping(character_name, profile=None) -> bool` | Schläft der Charakter? (nicht erreichbar) |
| `is_temporary_npc(character_name) -> bool` | Temporärer NPC — hat keine Thought-Turns, `bump` lehnt ihn ab |
| `list_available_characters(include_pooled=False, *, strict=False) -> List[str]` | Available character names; strict mode propagates roster read failures |
| `get_character_language(character_name) -> str` | Sprache des Charakters (für Texte, die er selbst schreibt) |
| `get_character_dir(character_name, *, create=False) -> Path` | Per-Charakter-Storage-Verzeichnis — für Pakete mit eigenen Dateien (markdown_writer schreibt nach `<dir>/documents/<folder>/`) |
| `get_character_skill_config(character_name, skill_name) -> Dict` / `save_character_skill_config(character_name, skill_name, config)` | Per-Charakter-Skill-Config. Normalerweise nicht direkt rufen — `BaseSkill._get_effective_config` liefert Defaults + Overrides typisiert |
| `record_access_denied(character_name, location_id, location_name, reason, rule_name='', action='enter')` | Abgewiesenen Zutritt vermerken (Gedächtnis + UI-Hinweis) |
| `record_state_change(character_name, change_type, value, metadata=None) -> bool` | Eine Zustandsänderung (Ort, Raum, Outfit, Entdeckung, fehlgeschlagene Reise …) in die `state_history` schreiben — die Quelle des Tagebuchs und der „Zuletzt erlebt"-Zeilen; `False` heißt: nichts geschrieben (Rückgabe prüfen), Ringpuffer 200 Einträge pro Charakter |

**Viele Leser nehmen `profile=`.** Wer das Profil ohnehin geladen hat, reicht es durch
und spart den zweiten DB-Zugriff: `get_character_current_location`,
`get_character_current_room`, `get_movement_target`, `get_character_pose_key`,
`get_effective_pose_key`, `get_effective_activity`, `is_character_sleeping`,
`get_character_profile_image`, `travel_engine.get_journey`,
`interaction_engine.get_interaction`, `body_slots.slots_for_character`.

### Optional strict reader leaves

All strict flags below are keyword-only and default to `False`. Existing
permissive callers, normal defaults and successful empty/absent data semantics
remain unchanged; strict mode propagates actual read/decoding failures.

| Module | Public calls |
|---|---|
| `app.models.character` | `app.models.character.get_character_pos(character_name="", *, strict=False)`, `app.models.character.get_character_daily_schedule(character_name, *, strict=False)` |
| `app.models.secrets` | `app.models.secrets.list_secrets(character_name, *, strict=False)` |
| `app.models.inventory` | `app.models.inventory.get_item(item_id, *, strict=False)`, `app.models.inventory.get_shared_item(item_id, *, strict=False)`, `app.models.inventory.resolve_item_id(token, *, strict=False)`, `app.models.inventory.has_item(character_name, item_id, *, strict=False)`, `app.models.inventory.get_room_items(location_id, room_id, *, strict=False)` |
| `app.models.world` | `app.models.world.get_location_by_id(location_id, *, strict=False)`, `app.models.world.list_locations(*, strict=False)`, `app.models.world.get_world_setting(key, default="", *, strict=False)`, `app.models.world.is_world_frozen(*, strict=False)` |
| `app.core.prompt_filters` | `app.core.prompt_filters.load_filters(*, strict=False)` |
| `app.core.stat_boosts` | `app.core.stat_boosts.effective_stat(profile, key, *, strict=False)`, `app.core.stat_boosts.active_boosts(profile, *, now=None, strict=False)` |
| `app.core.motion_item_cache` | `app.core.motion_item_cache.item_snapshot(*, strict=False)`, `app.core.motion_item_cache.passive_bonus_snapshot(*, strict=False)` |
| `app.core.timeutils` | `app.core.timeutils.game_time(*, strict=False)`, `app.core.timeutils.game_time_exact(*, strict=False)` |

A legitimate null map position is still absent, not a failed state query.
Strict room inventory distinguishes an existing empty room from a missing
location/room. Strict state/item/clock snapshots do not trust a cached
permissive fallback as a successful read. Boost arithmetic and game-clock
arithmetic are unchanged.

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
| `app.core.room_entry.characters_in_room(location_id, room_id, exclude="", *, strict=False, profiles=None) -> List[str]` | The existing room-ID/name membership algorithm; empty room means the whole location. Strict mode validates context and reuses a held name-to-profile mapping |
| `app.core.agent_loop.get_agent_loop().bump(character_name, hint='', perception_template='', perception_vars=None, tool_whitelist=None) -> bool` ✅ | Charakter für einen zeitnahen Thought-Turn vormerken. `hint` ist die Zeile, die er dabei liest; `tool_whitelist` schränkt die angebotenen Verben ein. Liefert `False`, wenn er keinen Turn bekommen kann (z.B. temporärer NPC) |
| `app.core.agent_loop.get_agent_loop().bump_respond(character_name, speaker, content, volume='normal', obligatory=True, hint='', winding_down=False, on_demand=False, request_id='') -> bool` | Queue a visible direct chat/tool answer independently of autonomous thoughts and HOT-chat gating. Explicit `on_demand=True` requests may answer during freeze, but not queue pause or world sleep. Optional opaque `request_id` correlates a `respond_finished` event when the turn completes, is cancelled, superseded or dropped; callers may request another unanswered question on their next regular check. Ordinary room reactions leave `on_demand=False`. |
| `app.models.memory.add_memory(character_name, content, memory_type='semantic', importance=3, tags=None, context='', related_character='', …)` | Erinnerung anlegen |
| `app.models.account.is_player_controlled(character_name)` / `get_active_character()` ✅ / `get_player_identity(default='user')` ✅ | Avatar-Erkennung, Anzeigename des Spielers. Einen festen 1:1-Gesprächspartner gibt es nicht mehr — wer gerade beisammen ist, sagt `app.core.perception.addressable_for(character_name)` |

## Chat & Messaging ✅ (talk_to / send_message / notify_user)

| Funktion | Semantik |
|---|---|
| `app.models.chat.save_message(message, character_name='', partner_name='') -> bool` | Eine Zeile in die Chat-History schreiben (Inbox-Modell: Sender als `assistant`, Empfänger als `user`). **Wirft nie** — `False` heißt: nicht gespeichert. Rückgabe prüfen, sonst verschwindet eine Nachricht lautlos |
| `app.models.chat.get_chat_history(character_name='', partner_name='', limit=None, medium=None) -> List[Dict]` | History; `medium` filters the communication channel **before** deduplication and the last-N limit. Phone readers use `"messaging"`; omitted means all channels. |
| `app.models.chat.get_messaging_partners(character_name, limit=10) -> List[str]` | Partners of the character's phone threads (`medium="messaging"`), most recently active first. Read each thread with `get_chat_history(..., medium="messaging")`. |
| `app.models.chat.save_direct_message(sender, recipient, content, *, channel="web", metadata=None) -> str \| None` | Atomically save both phone-history mirrors and return their canonical `dm:<uuid>` ID; `None` means no delivered pair. Preserve metadata including image/game_ts, generate a missing game stamp and snapshot recipient avatar ownership |
| `app.models.unified_chat.UnifiedChatManager.get_direct_message_event(event_id) -> dict \| None` | Resolve only two matching sender/recipient mirrors with the shared ID, content, channel, timestamp and metadata; never infer provenance from old history |
| `app.core.pending_reports.add_report(reporter, initiator, initiator_type, target, trigger_type='talk_to_response', trigger_message_id='', ttl_hours=24) -> str` | Chain-of-Command-Follow-up anlegen |
| `app.core.pending_reports.list_open(character_name)` / `mark_resolved(reporter, report_id) -> bool` | Offene Rückmeldungen lesen / schließen |
| `app.models.notifications.create_notification(character, content, notification_type='message', metadata=None) -> str` | User-Notification anlegen |

The phone and agent inbox consume only `medium="messaging"`. `talk_to` stores
`"in_person"` and reaches room perception, never the phone. `notify_user`
creates only a system notification; delivering a DM requires `send_message`.

## Authoritative RP sources — `app.core.stat_sources`

Normal room speech, TalkTo and DM integrations collect canonical sources
automatically. Do not construct an attributed source from model prose, a model
name, a tool argument naming someone, old history or a synthetic notification.
An utterance source uses `room:<utterance_id>` and only persisted content-bearing
perceptions, excluding contentless overhearing kinds. TalkTo uses that same
room event, not another history-shadow event. A DM source requires its complete
atomic mirror pair; old messages without a shared canonical ID are not replayed.

`StatSource` is immutable: `event_id`, `actor`, `content`, `medium`, `order`,
`game_ts`, `allowed_targets`, required `avatar_audience`, `avatar_targets`,
`location_id`, `room_id`. `avatar_audience` freezes **every content-bearing
avatar listener**, including unaddressed listeners; `avatar_targets` is only
the directly addressed subset eligible for the sender's stat round.
Changing the active avatar later never turns an old avatar-listener event
into NPC-owned input. Room sources without a complete, valid persisted role
snapshot are unavailable; the resolver does not reconstruct live roles.
A DM's complete single-recipient role snapshot supplies both avatar sets.
An originally non-avatar recipient evaluates new input in its own turn.
The sender's shared round owns addressed avatar effects, not passive listeners.
A private self source has no actor and may affect only its owning character; transmitted
consequences must not be counted again as self effects.

| Function / object | Semantics |
|---|---|
| `StatSourceCollector()` | Thread-safe event-ID deduplication, stable `self_event_id`, start/system and game stamps |
| `app.core.stat_sources.StatSourceCollector.add(source)` / `app.core.stat_sources.StatSourceCollector.snapshot()` | Add a canonical source; snapshot is canonically ordered |
| `bind_stat_sources(collector)` | Context manager binding a collector outside JSON tool arguments; restore the previous binding on exit |
| `get_stat_source_collector() -> StatSourceCollector \| None` | Capture the current turn collector before starting deferred work |
| `collect_stat_source(source)` | Add to the currently bound collector; `None` or an unbound collector is a no-op |
| `source_from_utterance(utterance_id) -> StatSource \| None` | Read canonical utterance and delivered perceptions |
| `source_from_dm(event_id) -> StatSource \| None` | Resolve the canonical mirrored DM |
| `self_source(character, content, event_id, *, started_at=None, game_ts=None) -> StatSource` | Unattributed owner-only narrative source |
| `extraction_context(character, sources, *, narrative, self_event_id=None, started_at=None, game_ts=None) -> StatExtractionContext` | Freeze delivered sources plus an optional new private narrative; `StatExtractionContext` has `sources`, `self_event_id`, `character` |
| `source_only_context(character, collector) -> StatExtractionContext \| None` | Pending eligible outgoing avatar communication only; no private self source or unread-input-only trigger |
| `stat_source_turn(function)` | Scope a collector to a synchronous or asynchronous turn |

A speech-producing deferred worker must capture the collector, call
`app.core.stat_sources.StatSourceCollector.start_source_work()` BEFORE spawning,
explicitly rebind it with `bind_stat_sources`, and call
`app.core.stat_sources.StatSourceCollector.finish_source_work(completion)` on success,
failure or worker-start failure.
`app.core.stat_sources.StatSourceCollector.wait_for_source_work()` runs outside
collector/profile locks before extraction input is frozen. Do not inherit
unrelated request context or serialize collectors into model/tool JSON.
`ReplyReceipt(source)` carries the canonical publication result (possibly
`None`) for reply/cascade handling.

Supporting public reads are
`app.models.perception_store.get_utterance_delivery(utterance_id)` and
`app.core.agent_inbox.load_unread_stat_sources(character_name)`.
The latter resolves genuine newly unread incoming DMs, not historic/context
lines. Merely finding unread input, passive presence, an aura or a SKIP does
not start another extraction round. A successful tool-only/silent turn may
finish the ONE existing extraction phase for eligible delivered outgoing avatar
sources; the old separate avatar wardrobe-only call is not a stat round.

## Party — `app.core.party_engine` ✅ (party-Paket)

Party membership is a core primitive (R5): leader movement propagates through
`app/models/character.py`, `/play` exposes membership and movement verbs honor roles.
The party package owns destination-bound intent execution and consent, not the core.

| Funktion | Semantik |
|---|---|
| `get_party_of(character) -> Optional[Dict]` / `is_in_party(character)` / `is_party_follower(character)` | Party-Zustand/Rolle (Basis für `visible_for`) |
| `add_to_party(leader, member) -> Optional[str]` / `leave_party(character) -> Dict` | Beitritt / Austritt (Follower steigt aus, Leader = Auflösung) |
| `create_pending_invite(inviter, invitee, intent_id="") -> Optional[str]` / `clear_invites_for(character)` | Persist an invitation for consent; `intent_id` optionally links an existing shared-trip plan. Clear open invitations |
| `get_invite(invite_id)` / `find_pending_invite(inviter, invitee, max_age_minutes=INVITE_MAX_AGE_MINUTES)` / `invite_is_fresh(invite, max_age_minutes=INVITE_MAX_AGE_MINUTES)` | Read the exact question; freshness uses system time |
| `resolve_pending_invite(invite_id, accept: bool) -> Dict` | The common avatar, NPC-tool and decision-model answer path. Linked plans revalidate their exact question, group, origin and game-time expiry before membership changes |
| `settle_pending_invite(invite_id, accept: bool) -> Dict` | Atomic membership/consent primitive; callers normally use the validated resolver |
| `close_intent_invites(intent_id, status="cancelled")` | Close only the questions belonging to that plan |

## Paar-Interaktionen — `app.core.interaction_engine` ✅ (interact-Paket)

Zwei anwesende Charaktere spielen einen Paar-Clip an einem gemeinsamen Anker. Die
Zustimmung ist immer ein Tool-Call, nie ein Keyword-Match auf Prosa.

| Funktion | Semantik |
|---|---|
| `partner_poses() -> List[Tuple[str, str]]` | Welche Paar-Posen es gibt (Key + Anzeige) |
| `get_interaction(character_name, profile=None)` | Läuft gerade eine? |
| `create_invite(inviter, invitee, pose_key, *, request_id=None) -> Optional[str]` | Ask through the ordinary consent flow. A supplied id atomically creates/reuses only the exact inviter/invitee/pose row, emits the offer once, and never replaces another pending question. A mismatching existing id is rejected. Ordinary same-pose repeats reuse the fresh question; replacements mark old questions cancelled instead of deleting their identity |
| `resolve_invite(invite_id, accept) -> Dict` | Answer an invitation. `status` `cannot` ends an accepted yes as `failed` with its saved reason |
| `get_invite(invite_id)` / `cancel_invite(invite_id) -> bool` / `clear_invites_for(character)` | Read/close invitations. Cancellation conditionally claims only a pending/approaching row; an answer that already claimed it wins. A live pair's accepted invitation survives housekeeping |
| `last_answer_of(inviter) -> Optional[dict]` / `dismiss_answer(invite_id, inviter) -> bool` | Read the newest fresh own declined/failed answer (`invite_id`, `invitee`, `pose_key`, `status`, `reason`); dismiss only an own declined/failed row as cancelled |
| `end_interaction(character_name, reason='ended', *, interaction_id='') -> bool` | End the pair for both participants. An optional ownership id is rechecked under the removal locks; a different live pair is never ended |
| `pair_profile_locks(a, b)` | Der EINZIGE sanktionierte Weg, zwei Profil-Locks zu halten (sortierte Namensreihenfolge, siehe „Sperren") |

The core emits `interaction.invited` for the question and
`interaction.invite_started` only after consent has actually started its pair
(including arrival after an approach). `interaction.ended` follows the actual
ending. Consumers persist the exact start receipt in their existing intent meta;
neither an accepted row without its live pair nor a same-pose unrelated pair proves
completion. Offer wording belongs to the package (`pair_verb_name`).
The pair's originating `invite_id` is also persisted with both live profile blobs.
That exact provenance can recover a lost start hook or identify cancellation;
matching pose/participants alone is never ownership. An actual end can correlate
by this invitation identity before the intent's start receipt is written.

## Möbel-Aktionen aus Paketen — `app.core.prop_action_sources` ✅

Ein Paket bringt Möbel-Aktionen mit, ohne ein Prop zu verändern: Es meldet beim
Laden (`on_load`) eine Quelle an, und der Kern hängt deren Definitionen zur
LAUFZEIT an jedes passende Möbel (`prop_actions.effective_document`). Die
`sidecar.json`, die Autoren-Revision und jeder Export bleiben unverändert — fehlt
das Paket, ist die Aktion weg (plan-pack-prop-actions.md).

| Funktion | Semantik |
|---|---|
| `register_source(owner, fn)` | Quelle des Pakets `owner` anmelden/ersetzen. `fn` liefert eine Liste von Definitionen, läuft bei jedem Laufzeit-Lesen und muss billig sein (geladene Config, keine Datei, keine DB). Wirkt nur, solange das Paket geladen ist |
| `unregister_source(owner)` | Quelle abmelden |
| `pack_action_id(owner, key) -> str` | Die stabile ID einer Paket-Aktion (`pack-` + UUIDv5): gleiche Eingabe, gleiche ID über Neustarts. Das Präfix ist für Paket-Aktionen reserviert |
| `pack_actions() -> List[dict]` | Alle gültigen Definitionen aller geladenen Quellen als `{owner, action, match}` (Kopien) |
| `signature() -> str` | Ändert sich mit jeder Änderung der Paket-Aktionen; leer ohne welche |

Eine Definition hat genau das Schema einer Autoren-Aktion (`validate_document`,
auch `name_<lang>`/`description_<lang>`) plus optional
`match = {"categories": [...], "tags": [...]}` gegen `category`/`tags` des Props
(leer = jedes Möbel mit passendem Platz). Eine ungültige Definition wird einmal
geloggt und übersprungen. Ein Prop schließt eine Paket-Aktion mit
`exclude_actions: [id]` auf Dokument-Ebene aus, ein Platz mit dem
`exclude_actions` seines Markers; beides darf IDs eines gerade inaktiven Pakets nennen.

## Pose — `app.models.character` ✅ (set_pose-Paket)

| Funktion | Semantik |
|---|---|
| `set_pose_key_detail(character_name, key, detail, *, unknown='resolve') -> str` | **Der Setter für ein Verb, das den Katalog-Key schon kennt:** schreibt Key + Anzeige-Detail exakt. `unknown='resolve'` lässt einen unbekannten Key noch über den Resolver laufen |
| `set_pose_intent(character_name, pose, prefer='', flavor=None)` | Kanonischer Setter für FREITEXT („Character macht jetzt X"): ordnet dem Pose-Katalog zu (`pose_key`), bereinigt die Würze (`pose_flavor`), matcht die Bild-Variante und schreibt alles ins Profil. No-op wenn Key und Flavor unverändert; leerer Text setzt zurück. Beendet eine laufende Paar-Interaktion. Bleibt Core (R5 — mehrere Schreiber) |
| `get_character_pose_key(character_name, profile=None)` / `get_character_pose_flavor(character_name)` | Gespeicherter Katalog-Key bzw. bereinigter Freitext |
| `get_effective_pose_key(character_name, profile=None)` / `get_effective_activity(character_name, profile=None)` | Render-Key bzw. Anzeigetext, beide inkl. Schlaf-Override |
| `app.core.pose_catalog.split_key_detail(text, axis='pose') -> (key, detail)` | Zerlegt eine `key: detail`-Eingabe |
| `app.core.pose_catalog.resolve_to_catalog(text, axis, _embed=None, *, set_id="") -> (key, detail)` | Map free text to the catalog (embedding match with alias fallback). `set_id` selects an expression set for `axis="expression"`; a nonempty set for pose matching raises `ValueError` |
| `app.core.pose_catalog.pose_label(key, lang="en") -> str` | Returns the localized pose label (`label_<lang>`, then `label`), falling back to the stripped key. Lookup ignores key case; unknown keys and catalog failures never raise. |
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

Skills deklarieren ihre Intent-Typen selbst (`INTENT_TYPES` +
`INTENT_PAYLOAD_KEYS` als Klassenattribute bzw. `intents`/`intent_payload_keys` im
Manifest) und führen sie über `handle_intent(intent_type, payload)` aus (Default:
JSON-Durchreichung an `execute()`). Die Methode `BaseSkill.tool_intent_payload(raw_input)`
liefert den Vergleichs-Inhalt eines Tool-Aufrufs für den Redundanz-Skip.

The engine handles the core types `remind` and `execute_tool`; other types are
provided by loaded skills. Unknown types are rejected. `remind` bumps the
character's thought turn with `Reminder: <note>` as its hint; deferred reminders
use the scheduler. Extracted promises use `app.models.intents.create_own_intent`
and the intent's own trigger scheduling. The unified marker grammar lives in
`shared/templates/llm/chat/intent_markers.md`.
`app.core.intent_engine.strip_intent_tags(text)` removes markers before persistence.

Vorhaben/Aufgaben als Datensatz: `app.models.intents.create_intent(*, owner, title, …)`,
`app.models.intents.list_intents(owner, status, source)`,
`app.models.intents.progress_type_for_tool(tool_name)`.
`app.models.intents.find_duplicate(owner, title)` liefert das aktive Vorhaben von `owner`, das
`title` schon abdeckt (normalisierte Wortmengen, unabhängig von der Reihenfolge: gleich oder
alle Wörter des kürzeren Titels im längeren; der kürzere normalisierte Titel ≥ 6 Zeichen,
auch bei Gleichheit), sonst `None`. Wer vor dem Anlegen prüft, hält
`keyed_lock("intents", owner)` um `find_duplicate` UND `create_intent` — so legen zwei Turns
derselben Figur kein Vorhaben doppelt an (Muster: `plugins/retrospect/skill.py`).

`app.models.intents.create_own_intent(character_name, title, *, description="", trigger=None, priority=3, source="character", extra_participants=None) -> Optional[Dict[str, Any]]`
creates a plan under the owner's keyed lock, deduplicates its title, enforces owned
caps and schedules its trigger outside the lock. Defaults to a standing trigger;
returns `None` for a duplicate. Extra participants see and may complete the plan.
`app.models.intents.complete_intent_as(character_name, intent_id) -> bool` completes
only a plan owned by the character or one they participate in. Both extraction
and the marker paths use these helpers.
`app.models.memory.delete_commitment_memories() -> int` deletes obsolete promise
memory rows at boot and returns the number removed; repeated calls return zero.

`app.models.intents.expire_intent(intent_id, reason) -> bool` expires only an active intent,
merging `meta.expired_reason` (`cap`, `deadline`, or `replaced`) into its existing metadata.
`app.models.intents.enforce_active_caps(owner, keep_ids=()) -> int` expires excess owned
marker/legacy intents by priority (5 first), then oldest creation stamp; protected ids go last.
Managed, admin and other package origins are exempt. Core defaults: six self plans, four player
tasks, with zero meaning unlimited. Hold `keyed_lock("intents", owner)` across duplicate lookup,
creation and cap enforcement. The return value counts successful expirations.

`app.models.intents.cleanup_intents(owner="", *, merge_duplicates=True, set_deadlines=True,
end_all=False, dry_run=True) -> Dict` previews or applies cleanup under each owner's
`keyed_lock("intents", owner)`. Empty owner selects all owners; participant membership is
not ownership. Marker/legacy rows merge by equal normalized title (newest creation stamp,
then larger id wins; empty titles stay separate), and missing deadlines use
`default_intent_expiry` from the current game clock. Admin, managed and package-origin rows
are exempt. `end_all=True` requires an owner and expires every owned active row except
managed actions. Caps run after cleanup, also in preview simulation. Returns
`{"dry_run": bool, "items": [{"id", "owner", "title", "action"}], "counts": {action: n}}`;
actions are `duplicate`, `deadline` (also includes `expires_at`), `cleanup`, or `cap`.
Preview writes nothing. `expire_intent` additionally accepts `duplicate` and `cleanup`,
preserving metadata as for the other reasons.

Executable actions are package-provided capabilities on the existing intent row,
not a second workflow store. Successful CRUD writes emit `intent_created`,
`intent_changed` and `intent_deleted`; execution is serialized by
`keyed_lock("intent_execution", intent_id)`. Managed actions are excluded from
generic tool-count/location progress, and `complete_intent` checks the package's
completion predicate instead of accepting an early narrative claim.
`GET /intents/action-types` lists currently available action descriptors. Without
the owning package, its action is not offered. The party action is
`{"type":"travel_together","destination":{"location_id":"…","room_id":"…"},"scope":"pair"}`:
one explicit leader and one proposed follower; existing followers require `party`
scope. Runtime `meta.travel` is server-owned, and a live plan is cancelled rather
than retargeted. Linked `join_party` answers must include the exact `invite_id`.
`app.models.intents.default_intent_expiry(trigger, source)` supplies the existing
GAME-time deadline policy for structured proposals too; an explicitly disabled
self-intent TTL remains disabled. NPC invitations persist their announcement
before execution; consent waits for its speech write. Recovery uses
`app.models.perception_store.utterance_exists(speaker, ts, content)` with the
persisted technical timestamp to avoid repeating an already recorded line.
For travel-only intents, arrival completes the intent, not party membership.
Optional `after_arrival={"type":"pair","pose_key":"<exact available catalog key>"}`
extends that same intent through the existing pair invitation after arrival.
Exactly two participants are required. `GET /intents/shared-activity-options`
lists the installed capability's keys. Both initial consent and the player UI
show the activity; its own invitation can still be declined at the destination.
Runtime phases are `waiting_activity`, `activity` and `completed`. Only the exact
interaction's normal end signal completes the undertaking; interruptions cancel
it and missing capabilities/receipts block without inventing success or replaying.
Package skills may override `app.plugins.base.PluginSkill.default_enabled_for(character_name)`
to offer a state-bound verb when no character activation setting exists.
Explicit `enabled=False` always wins. The party package uses this for a live
linked Join answer and for leaving an existing party; it does not enable
autonomous thoughts or write character configuration.


## Act-Engine — `app.core.act_engine` ✅

`perform_act(actor, text, scope, *, overflow=False) -> Dict` (async) = die komplette
Storyteller-Pipeline (Szenen-Kontext, Storyteller-LLM, Event-Verdikt, Erzähler-Zeile
in den Stream, Memories/Diary/Bumps). Konsumenten: das Act-VERB (`plugins/act`) und
der Storyteller-Fallback in `routes/play.py`. Die Storyteller-Whitelist
(`app.models.storyteller.list_skill_keys()`) ist dynamisch = alle geladenen Skills.

| Funktion | Semantik |
|---|---|
| `extract_text_and_scope(ctx) -> tuple` | Aktionstext + Reichweite (`here`/`location`) aus dem Tool-JSON ziehen — die EINE Lesart des Act-Inputs, damit Verb und Route denselben Text sehen |
| `sender_on_cooldown(actor, scope) -> bool` | Hat der Akteur in den letzten `SENDER_COOLDOWN_MIN` Minuten in dieser Reichweite schon gehandelt? |

## Bild-/Video-/Mesh-Service — `app.imagegen.service` ✅

| Funktion | Semantik |
|---|---|
| `get_image_service() -> ImageService` | Singleton der Medien-Engine (Backend-Pool, Auswahl, Pipeline, Vision-Analyse). `svc.enabled` prüfen; `generate_from_input(prompt)` = voller Generierungslauf. Das JSON-Payload nennt seinen Anlass im Feld `occasion` (Katalog `app/imagegen/occasions.py`, z. B. `photo`, `instagram`; fehlt es: `photo`) — ohne `backend` wird der Anlass geroutet (Kette + Neuanlauf + Markierung, siehe Bild-Routing), mit `backend` = eine EXPLIZITE Wahl: genau dieses Backend, kein Rückfall. Ein Fehlschlag kommt als String mit Präfix `Error: ` zurück |
| `ImageService.run_on_backend_channel(backend, gen_fn, *, task_type, agent_name='', label='', priority=-1)` | **Jeder** Backend-Lauf geht hier durch: der Aufruf wird auf dem GPU-/Backend-Kanal serialisiert und zählt gegen das Job-Budget. Nie `backend.generate` direkt rufen |
| `ImageService.run_on_backend(backend, op, character_name="")` | Run an operation against a resolved backend with the service's busy/failure/cooldown semantics. The operation must use `run_on_backend_channel` for generation. |
| `reset_image_service()` | Pool-Neuaufbau beim nächsten Zugriff (ruft `skill_manager.reload_skills` automatisch) |
| `app.imagegen.base.BackendBusyError` | **Last, kein Defekt.** Überlebt die Queue-Grenze als typisierte Exception und wird ohne Cooldown erneut versucht. Ein Paket darf sie nicht in ein generisches „Fehler" umschreiben |
| `app.imagegen.base.BackendFailedError` | **Ausfall** eines Backends (nach Cooldown) — das EINE Signal, auf das das Bild-Routing neu anläuft. Ein Paket fängt es nicht, um selbst ein anderes Backend zu versuchen |

Das TakePhoto-VERB (`plugins/take_photo`, SKILL_ID `image_generation`) ist nur die
LLM-Tool-Oberfläche — Pakete, die Bilder brauchen, rufen den Service.
## Image prompt construction

| Function | Contract |
|---|---|
| `app.core.prompt_builder.person_description(name, *, include_outfit=False, apply_state_modifiers=True, ...) -> str` | The shared appearance description, including template/body-slot resolution and optionally the current outfit. Capture the returned text before queuing historical-scene work; do not read a later outfit as historical evidence. |
| `app.core.prompt_compose.compose(*, use_case, subject, backend, hints=None, negative_extra="", style_override=None, conditions="")` | Compose the selected backend family's use-case style and negative prompt. Returns `.prompt`, `.negative`, `.warnings`, `.meta`. Call inside the routing callback so each fallback backend gets its own composition. |
| `app.core.llm_json.parse_json(raw: str) -> dict \| None` | Extract a JSON object from a queued LLM answer, tolerating code fences; returns None when it cannot be parsed. A bare array is returned under `_list`. Validate task-specific fields in the caller. |


## Bild-Routing — `app.imagegen.routing` ✅

Pro Render-Anlass EINE geordnete Backend-Kette (Admin → Media Generation → Routing), die Figur als Position 0.
Pakete rufen normalerweise nur `generate_from_input` mit `occasion`; wer selbst rendert, übergibt einen
Callback `render`, der mit dem aufgelösten Backend gerufen wird und Prompt/Stil/LoRAs/Referenzen für GENAU
dieses Backend baut.

Die Garderoben-Default-Pose (`model_refs`, Art `pose`) nutzt den Anlass `expression`:
normaler Character Match (`outfit_imagegen.workflow`) und normale Charakter-LoRAs.
Nur Mesh-Eingaben — T-Pose und zusätzliche Ansichten — nutzen `tpose`
mit `tpose_workflow` (falls leer: `workflow`) und `tpose_loras` (falls leer: normale LoRAs).

| Funktion | Semantik |
|---|---|
| `resolve_image_route(occasion, *, character='', has_ref=False, exclude=(), probe=False, pool=None, not_applicable=None, advance_rotation=True) -> Route` | Resolve one backend before composing its prompt. Empty chain selects the cheapest eligible backend; a configured unusable chain raises `NoRouteError`. `advance_rotation=False` peeks at the current equal-cost round-robin choice without consuming it, for admission checks; actual renders keep the default rotation and normal fallback behavior. |
| `explain_image_routing(character='', pool=None) -> Dict` | Je Anlass die Kette mit Status pro Eintrag und dem Backend, das ein Render nähme — reine Anzeige, prüft **nie** aktiv (kein Probe) |
| `run_routed(occasion, render, *, character='', has_ref=False, pool=None, on_route=None) -> Tuple[Any, Route]` | Löst auf und ruft den Callback `render` mit dem Backend; läuft nur dann auf dem nächsten Ketteneintrag neu an, wenn `render` einen `BackendFailedError` **des gerouteten Backends** wirft (Last, 4xx, Abbruch, Hauptschalter: kein Neuanlauf), höchstens `MAX_REENTRIES` = 2 Mal. `render` baut alles Backend-Abhängige selbst. `on_route` (optional) bekommt jede Route direkt vor dem `render`-Aufruf — ein Hub-Vorgang speichert so die Routing-Meta mit dem Job, den er abschickt |
| `route_meta(route)` | `{"routing": {...}, "fallback_from": {...}?}` — gehört in die Meta/Sidecar jedes gerouteten Ergebnisses; `fallback_from` nur, wenn ein Laufzeit-Ausfall (Cooldown/nicht erreichbar/Neuanlauf) den vorgesehenen Eintrag übersprang. Eine explizite Wahl schreibt keines der beiden |

## Queue — `app.core.task_queue` ✅

Es gibt **eine** Queue. Sie ist persistent (SQLite, `task_queue.db`): eingereichte
Tasks überleben einen Neustart, sind im Admin-Panel und in `queue_cli.py` sichtbar
und werden von einem festen Worker-Pool (`_NUM_WORKERS`, heute 2) in
Prioritätsreihenfolge abgearbeitet — es laufen also bis zu zwei Tasks gleichzeitig.

| Funktion | Semantik |
|---|---|
| `get_task_queue()` | Singleton der Queue |
| `TaskQueue.submit(task_type, payload, queue_name, priority, agent_name, max_retries, deduplicate)` | Task einreihen, gibt die `task_id` zurück. `queue_name` ist nur ein Label (UI + Pause-Schalter), kein eigener Worker; `priority` niedriger = früher (Default 20); `deduplicate=True` überspringt die Einreichung, solange ein Task desselben `task_type` (mit demselben `agent_name`, falls gesetzt) pending/running ist, und gibt dann `""` zurück |
| `TaskQueue.register_handler(task_type, handler)` | Registriert den Handler eines `task_type` — eine Funktion, die das `payload`-Dict bekommt und ein Ergebnis-Dict zurückgibt. Beim Start des Pakets aufrufen, sonst scheitert ein eingereihter Task mit „kein Handler" |
| `TaskQueue.is_paused(queue_name="default") -> bool` | Read the persisted pause gate through the public interface |

Ein Verb blockiert nie minutenlang im `execute()`. Lange Arbeit wandert in die
Queue; das Verb antwortet dem LLM sofort, was es angestoßen hat.

## Attention — `app.core.attention`

| Function | Semantics |
|---|---|
| `is_distracted(name: str, *, profile: dict \| None = None) -> bool` | True while sleeping, in a pair interaction, in a conversation derived from recent room utterances, or with a set profile flag declared `distracting`. Reuses the supplied profile; conversation expiry uses game time. |

## Hooks — `app.core.hooks` ✅ (F5-light)

| Funktion | Semantik |
|---|---|
| `register(event, fn, tag='')` | Paket abonniert ein Core-Event (idempotent pro `(event, tag)` — Reload-sicher). Typisch im `on_load`-Modul oder im Skill-`__init__` |
| `emit(event, **kwargs) -> int` | Core feuert generisch; Fehler in Callbacks erreichen den Core-Pfad nie |
| `register_provider(capability, fn, *, owner=None)` | Replace the one named capability implementation; `owner` binds its lifetime to a package |
| `unregister_owned_providers(owner) -> None` | Remove only providers still owned by this package; a replacement owned by someone else is retained |
| `get_provider(capability) -> Optional[Callable]` | Look up the implementation; absence handling belongs to each capability contract |

Event subscriptions have no `unregister`; keep their `(event, tag)`
registration idempotent. Capability providers do support owner-bound removal.
Register package providers with their package ID as owner; discovery/registry
cleanup removes disappeared/disabled owners without clearing unrelated imported
package runtime state. Pending configuration changes retain the existing
activation/restart policy, not a new hot-toggle contract.

Events, die der Core heute feuert:

| Event | Kwargs |
|---|---|
| `startup` | — (nach dem Boot, aus `app/server.py`) |
| `character.entered_room` | `character`, `location_id`, `room_id`; once after a successful actual room change, including a location change into its arrival room. Same-room saves, departures to no room and failed writes emit nothing. Delivery waits until the emitting thread releases all world/keyed locks, including caller-held locks; multiple changes are delivered in order without coalescing. |
| `interaction.invited` | `invite_id`, `inviter`, `invitee`, `pose_key` |
| `interaction.invite_started` | `invite_id`, `interaction`, `inviter`, `invitee`; emitted after the ordinary answer/approach starts the real pair |
| `interaction.ended` | `character`, `partner`, `interaction_id`, `reason`, `invite_id` (empty for a direct start); emitted after the real pair is cleared. The originating invitation identity is persisted in both pair profiles before start hooks, so a concurrent end cannot lose its ownership |
| `prop_action.pair_started` | `execution_id`, `interaction`, `actor`, `partner`; emitted after a furniture pair action has started the real pair (consent was the run's, so there is no `invite_started`); delivered after all locks. Its end is the ordinary `interaction.ended` |
| `interaction.invite_failed` | `invite_id`, `inviter`, `invitee`, `pose_key`, `reason`; emitted by the core on every failed yes, retaining the actual cause for an owned undertaking |
| `instagram.post_created` | `poster_name`, `post` |
| `instagram.user_comment` | `character_name`, `post_id`, `commenter_name`, `comment_text`, `comment_id`, `post` |
| `character.prompt_context` | `character_name`, `mode` (`chat`, `npc_action`, `npc_scene`), mutable `blocks: List[str]`; packages append volatile state/policy text. Chat renders it only in the scene-state moment, never in the stable system prefix. |
| `chat.moment_facts` | `character_name`, `uncovered: List[Tuple[str, str]]` (`("you", …)` for the speaking character, then each person in sight — `(name, text)` from `outfit_renderer.uncovered_summary`, only non-empty ones), mutable `facts: List[str]`; emitted only when something is uncovered. Each appended fact renders as a `- ` line under "This moment:" at the end of the chat scene state — the last thing the model reads before it answers. The core only collects what is uncovered; how a character treats it is the package's line. |
| `npc.action_execute` | `character_name`, `action: Dict`, mutable `result: Dict`; a package claims its namespaced solo action by setting `handled=True`, then `success` and `text`. Core checks placement, home, lifecycle and travel under the character profile lock before dispatch. Callbacks may update that profile, but must not take place/pair locks or call external services. A handled action does not speak, invite or start a home-area walk. Revalidate capability/state, check writes and ignore callbacks of removed/replaced skills; unhandled actions retain the existing party proposal path. |
| `intent_created` / `intent_changed` / `intent_deleted` | `intent`; changed also supplies `previous`; successful durable writes only |
| `world_tick` | —; ordinary periodic world gates apply |
| `party_membership_changed` / `party_invites_cleared` | `character`; departure/removal invalidates affected plans |
| `party_invite_closed` | `invite`, `reason` |
| `respond_finished` | `character_name`, opaque `request_id`, `outcome`; completion/cancellation or pending request superseded/ineligible |

Capabilities, die der Core heute abfragt:

| Capability | Fragt | Ohne Paket |
|---|---|---|
| `pair_verb_name` | `routes/play.py`, `plugins/set_pose` | `/play/interact/options` bietet nichts an, die Player-UI schlägt keine Paare vor |
| `shared_activity_options`, `shared_activity_validate`, `shared_activity_request`, `shared_activity_status`, `shared_activity_cancel` | Structured intent continuation and exact pair ownership | No pair continuation; available options are empty. The action is only `{type:"pair", pose_key:"<exact available key>"}`. Request/status return `pending`, `approaching`, `running`, `declined` or `blocked` with `invite_id` and optional `interaction_id`/`reason`; status never starts anything. Initial unsubmitted requests alone may return `not_found`; missing questions without exact live pair provenance and accepted-but-not-live requests block, never replay. Exact provenance reports a running pair even before `accepted` or start hooks persist. Cancel's optional `interaction_id` restricts actual receipt/provenance ownership; it never grants ownership or ends another pair |
| `tool_decision.open_questions` | `streaming.tool_state_note` / `open_questions_note`: the rp_first tool decision (both paths) and, for a `single` character, the chat turn's scene state. `fn(agent_name, tool_names) -> list[str]`: one line per question someone put to the character that an offered verb answers, with the exact yes and no call (`interact`: open pair invitations) | No open-question block; the invitee only hears the question in prose |
| `romantic_compatibility` | `models/relationship.are_romantically_compatible` | immer kompatibel |
| `romantic_attraction` | `stat_influence` invokes the registered callback with observer and subject names, returning a bool for that exact directed pair | Unavailable: attraction-dependent Influence rules do not match. This is NOT symmetric compatibility and does not inherit its default `True`. Only the observer's preferences/block list determine direction; subject profile/config supplies appearance |
| `romantic_interests_help` | `/admin/settings` | der Hilfe-Button fehlt |
| `intent_action_types`, `intent_action_validate`, `intent_action_change_validate`, `intent_action_managed`, `intent_completion_allowed` | Intent API, progress and completion | No executable action descriptors; ordinary intents remain available |
| `npc_action_available`, `npc_action_context`, `npc_action_execute` | NPC background selection, prompt and typed action | Ordinary NPC behavior |
| `party_invite_respond`, `party_invite_projection` | Party resolver and player invitation payload | Ordinary membership/question behavior |
| `journey_execution_context`, `journey_arrival_validate` | Owned travel tick and exact arrival | Ordinary journey behavior |

## Skill-Hooks (Deklarationen an der Klasse / im Manifest) ✅

| Hook | Semantik |
|---|---|
| `TURN_KINDS: tuple = ()` | Class flag: empty allows every turn; a non-empty tuple requires an explicit matching `turn`. For example, `("thought",)` excludes the verb from default/chat calls. `get_agent_tools(character_name, check_limits=True, turn="")` applies this filter even when limits are skipped; thought tools, their usage lines (`get_agent_usage_instructions(..., turn=)`) and thought-context blocks pass `turn="thought"`. |
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
`PLAYER_ACTION` (class attribute, e.g. `"travel"`, `"scene_photo"`) names the
/play action a skill stands behind, so the player route is gated and charged
by that skill without the core naming it.

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
| `app.core.timeutils.game_time(*, strict=False) -> GameTime` | GAME time for world logic, never `datetime.now()`; strict mode propagates persisted clock-read failures |
| `app.core.timeutils.utc_now()` / `utc_now_iso()` / `parse_iso(s)` | SYSTEM-Zeit — nur technische Stempel (Persistenz, Reihenfolge, Cooldowns, Logs) |
| `app.core.i18n.t(en, lang=None) -> str` | Übersetzbare Zeichenkette; die Quelle bleibt Englisch |
| `PluginContext`: `ctx.get_config(path, default)`, `ctx.http`, `ctx.logger` | Welt-Config per Dot-Pfad (Beispiel `skills.markdown_writer.max_size_kb` seedet die Per-Character-`_defaults`), HTTP, Logging |

## Decision models — `app.core.decision` ✅

Optionale typisierte Entscheidungen (Ja/Nein, Auswahl, Skala) über das Jev-Protokoll
(`docs/decision-models.md`). **Vertrag:** `None` heißt immer „nimm deinen bisherigen Weg" — ein
Paket bringt für jede Entscheidungsstelle einen Weg ohne Entscheider mit. Pakete melden ihre Stellen
im `on_load`-Modul an.

| Funktion | Semantik |
|---|---|
| `register_point(point_id, *, label, description, default_min_confidence=0.7, default_timeout_s=2.0, origin='core')` | Stelle anmelden; ein Paket übergibt seinen Paketnamen als `origin`. Nicht angemeldet = entscheidet nie |
| `is_active(point_id) -> bool` | Hauptschalter an und Modus shadow/on — Fragen nur dann bauen |
| `decide(point_id, state, questions, *, key=None, then=None) -> Optional[Decision]` | Wirft nie. `questions`: `{name: Noul/Choice/Score}`; `Decision.answers` enthält nur sichere Antworten. `key` verknüpft mit `record_outcome`; `then` bekommt die sicheren Antworten eines Schritts und liefert Folgefragen oder `None`. Synchron — auf dem Event-Loop per `asyncio.to_thread` |
| `record_outcome(point_id, key, actual)` | Was der bisherige Weg tatsächlich entschied — für den Schattenvergleich |
| `mark_taken(point_id, key)` | Modus `on` hat gehandelt, kein Vergleich möglich |
| `Noul(instructions)` / `Choice(instructions, options)` / `Score(instructions, anchors)` | Fragetypen; `Choice` 2–255 Optionen |
| `app.core.decision_points.invite_state(invitee, inviter, offer) -> Dict[str, str]` | Zustand für eine Einladungs-Entscheidung (annehmen/ablehnen) eines eingeladenen NPC: seine eigene Lage (`thought_state`), das Angebot (`"<inviter> invites <invitee> <offer>"`) und wie er zum Einladenden steht (Typ, Stärke als Wort, Gefühl in SEINER Richtung). Wirft beim Beziehungsteil nie |
| `app.core.decision_points.invite_questions(invitee, inviter) -> Dict[str, Choice]` | Eine `Choice` `answer` mit den neutralen Schlüsseln `accept` / `decline` — dieselbe Frage für jede Einladungs-Stelle eines Pakets |

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
| `params_schema: List[ParamField]` | The form the admin fills in when creating an entry. `ParamField(key, label, kind, options=None, required=True, default='', show_if=None)` (`default` = the value the form starts with); `kind` ∈ `mesh_backend` \| `image_backend` \| `subject_kind` \| `enum` \| `text` — `enum`/`subject_kind` carry their own `options` (`[{"value","label"}]`), the backend kinds fall back to the world's full list when they carry none. A backend field that MAY not use every backend fills its own `options` (`subjects.mesh_backend_options()`) — and then `params_schema` has to be a `@property`, so the offered list is read live instead of freezing at server start |
| `validate(params) -> params` | Normalised parameters, or `ValueError(message)`. The base class checks required fields and option membership; override it (calling `super().validate`) for rules between fields — e.g. "source and target backend must differ" |
| `find_candidates(params) -> List[Candidate]` | Every subject NOT yet done, in a stable order (`(label.lower(), key)`). `Candidate(key, label)`: the key is unique per type and is what a step row stores (`"character:<name>"`, `"location:<id>:<file>"`). A subject that could not be worked at all (nothing to generate FROM) is not a candidate |
| `is_done(candidate, params) -> bool` | The type's own "is this subject finished" test — read the persisted asset, never a cached answer. The engine never calls it; `find_candidates` uses it to decide what to list, and a subject that drops off that list is closed as done |
| `apply(candidate, params, task_id)` | Does the work SYNCHRONOUSLY: it returns only once whatever it made is persisted. It runs in a queue worker thread (no event loop of its own, and `user_activity` is suppressed for the duration), so it calls the blocking producer directly — never a `trigger_*` thread wrapper, which would report success while nothing had been generated |

`ParamField.show_if` maps earlier parameter keys to allowed string values, for
example `{"subject": ["prop_images"]}`. All conditions must match the already
normalised values, so referenced fields must precede dependent fields in schema
order. `ParamField.to_dict()` emits `{}` when there is no condition. Hidden fields are stored
as `""`, skip required/options validation, and do not render or contribute to the
dialog's required-field check or generated label. The dialog stays type-agnostic.

`fill_missing` has a live schema: `subject`, optional `mesh_backend` (character,
building and prop models), and optional `image_backend` (prop and clothing images).
Both backend fields default to `""` / **Auto (routing)**; explicit picks go directly
to the producer without a route prerequisite or fallback. Stored entries without
these keys keep automatic routing. Enabled configured mesh and image backends stay
selectable while offline. **Prop images** (`prop_images`) scans every variant for a
missing front source image, including index 0 in its candidate key. Multiple
variants use `name · variant N`; a single variant uses the prop name. Image
creation uses the variant's description (or prop name when empty) and the normal
prop prompt composition. Clothing passes its explicit backend through the item
producer's `overrides`. The prop producer currently converts unavailable routes
and explicit offline picks to `ok: false`; those count as failed attempts. An
escaping `NoRouteError` without an underlying render failure maps to
`CandidateBusy`, while any `ok: false` result raises `RuntimeError`.

`face_retexture` offers a live character dropdown with **All characters** as the
empty selection. Its `scope` is `all` (**All stored meshes**, the default also for
older entries) or `current` (**Current mesh only**): the currently worn outfit's
signature intersected with stored character mesh signatures.

A clean `one_shot` is deleted with its steps when its scan/work finishes, including
zero-candidate creates. Skipped or failed steps retain the entry as `done` for
inspection and retry; retry reopens a done entry. Each engine tick sweeps legacy
clean done one-shots in its existing entry-list pass. Create returns the created
row with `removed: true` when its initial scan deleted it. `POST
/improvements/clear-finished` cancels queued tasks and deletes every done entry;
the admin list exposes this through **Remove finished** with confirmation.

**Run now** forces an entry (`improvements.forced`): the click submits its next
pending step at once, and every following tick submits the next one, past the
idle window, the engine switch, a world freeze and a task-queue pause (the admin
tick runs the engine through both). The media switch, an improvement step
already in flight and a busy deferral still hold it back. The flag clears itself
once the entry has nothing pending or running, and on **Pause** or **Stop run**.

**Failure vocabulary of `apply`.** A defect is a plain exception (its message lands in
the step's `error`; the step is retried once, then skipped).
`app.imagegen.base.BackendBusyError` and `app.core.improvements.base.CandidateBusy`
mean LOAD, not a defect: the step stays pending and keeps both its attempts. Raise
`CandidateBusy` when the subject is already being generated somewhere else — most
producers keep an in-flight set that a direct caller has to honour itself — or when
the backend the step needs is not available yet (check that BEFORE calling the
producer, whose own refusal would be a plain exception).

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
| `fill_missing` | Generates missing models, expressions, clothing images, and prop variant front images; optional explicit mesh/image backends |
| `face_retexture` | Corrects stored character meshes for all or one character, scoped to all stored meshes or the current outfit |
| `image_rerender` | Re-renders portraits/gallery images of one image backend on another |
| `surface_bake` | Bakes the walkable-surface lattice of room and prop models |
| `mesh_from_tpose` | Generates the character mesh of every stored outfit combination that has a T-pose render but no model |
| `fallback_rerender` | Re-renders every image a fallback backend made (image meta `fallback_from`) EXPLICITLY on the backend its intended spec resolves to; while that spec resolves to nothing the step raises `CandidateBusy` and stays pending |

## Extension rig declarations (P1)

`app.core.extension_rig` provides these public readers:

- `rig_groups_for(character_name, profile=None)` returns applicable declaration
  dictionaries with resolved package physics defaults and ordered chains.
- `extension_bone_names(character_name, profile=None)` returns the validation
  context `{full_name: {parent, group}}` for `model_validate.validate_glb`.
- `resolved_extension_groups(character_name, profile=None)` returns applicable
  groups with `enabled`/`flip` from model options, including disabled groups.
- `extension_rig_fingerprint(groups, overrides=None)` hashes applicable
  declarations and overrides with an explicit operation-schema version.
- `motion_payload(character_name, profile=None)` returns `{rev, groups}` with
  stable resolved-content revision and `rest_deg=0`.
- `extension_metadata(character_name, profile=None)` returns the reserved
  sidecar shape `{fingerprint, groups, status, reason, metrics, per_tier}`. It does not
  run an operation or claim `applied`; its `attempted` flag is false.

`app.core.model3d` provides synchronous retrofit callables:

- `rebuild_extension_rig(character_name, signature=None, *, tier="full", force=False)`
  rebuilds one stored model/tier from its clean source, returning its extension
  result. Omitted signature selects the currently served model (including outfit fallback). A matching
  fingerprint is a no-op only for completed attempts (`attempted=true`); `force` retries unsuccessful attempts.
  A missing or stale low tier is repaired independently of a current full tier.
- `rebuild_character_extension_rigs(character_name)` processes every stored
  model for a character and is the extension-bones Improvements worker entry.
- `get_model3d_options(character_name)` and
  `set_model3d_options(character_name, updates)` read/write the existing
  `model3d_opts` block, including `extension_rig` boolean enabled/flip maps.
  Profile read-modify-write is locked; invalid override shapes raise `ValueError`.
- `set_model3d_rig(character_name, rig, *, signature=None)` updates the captured
  model sidecar under the same publication lock; an explicit signature selects
  a stored outfit model.

`app.blender.refine.apply_script(..., base_joints_only=False)` and
`app.core.model_validate.rig_frames_preserved(..., base_joints_only=False)` can restrict their
frame-preservation gate to the canonical 52 base joints when an operation
adds declared extension joints. Other refinement callers retain the complete
joint gate. Rebuild HTTP routes require administrator access.

Pass an existing profile when available to avoid another DB read. These
readers use package/template and slot/rig applicability conditions; they
contain no concrete group, slot or extension joint identifiers. See
[plugin rig declarations](plugins.md#optional-rig-declaration-p1) and
[the model/payload contract](schnittstellen-3d.md#extension-rig-contract-p1).

P1 processing uses a worker-local staging transaction for generation, uploads,
job retrieval, retrofit and low derivation. Nested operations share one hidden
same-filesystem stage. Publication checks the captured signature revision and
replaces meshes/textures/backups, tier sidecars, then the full sidecar under
short signature/directory locks. Readers capture metadata/revisions or response
bytes under the directory lock. `save_uploaded_model(..., signature=None)` is
blocking and the async upload adapter calls it through `asyncio.to_thread`.
A stale result returns `ok=false`, `status="stale"` and an explanatory error.
Rebuild preparation requires a normalized base-only clean source; operation
parameters (including reference checks and poses) are all declaration-required.

## Package LLM task catalog

`app.core.llm_tasks.register_plugin_task(task_id: str, spec: dict, package: str) -> bool`
registers `{label, category, priority?, fallback?}` in `TASK_TYPES`. Categories are
`chat|tool|helper|image`; priority is `low|normal|high`, default `normal`.
Invalid specs and core ID collisions return `False` and log a warning.
Unknown fallback parents are dropped with a warning. Prefer the `llm_tasks`
manifest mapping, which calls this API during parsing.

`app.core.llm_tasks.plugin_task_fallback(task_id: str) -> Optional[str]` returns
the declared parent. Routing consumers use `app.core.llm_router.fallback_parent(task)`
so declared parents and built-in routing rules stay in one place.

## Perception window reader

`app.models.perception_store.get_character_stream_between(perceiver: str,
start_game_ts: str, end_game_ts: str, limit: int = 400) -> List[Dict]` reads
one character's subjective perceptions using inclusive canonical game-time
bounds. Equal bounds include lines at that instant; unstamped utterances are
skipped. Rows contain `game_ts`, `speaker`, `content`, `kind`, `location_id`,
`room_id`, oldest first with perception ID as a tie breaker. The earliest
`limit` rows are returned; a non-positive limit returns no rows. Content comes
from the perception, so canonical speech that the character did not hear is
never exposed by this reader.


## Diary sources

`app.models.diary.register_diary_source(source_id, collect, *, type_label, icon,
delete=None, summary_input=False)` registers or replaces a source at plugin load.
Use a nonempty source id without colons that does not collide with a core type.
`collect(character_name, day_key)` returns entry dictionaries with `type`
(the source id), `content`, `timestamp` (system ISO for ordering), `game_ts`
(canonical game stamp), `id` (local id), and optional `metadata`.
The core copies each row, prefixes its id with `<source_id>:`, and sets
`deletable` according to whether the source supplies a delete callback.
GET `/diary/{user_id}/{character_name}` merges source labels and icons into
`types` and `icons`; the existing type filter applies to source entries.

`generate_for_day(character_name, day_key=None, *, for_summary=False)` includes
registered sources in the day view. `build_daily_summary_input` uses
`for_summary=True`, excluding sources unless they explicitly opt in with
`summary_input=True`. Display-only text therefore never feeds daily summaries.

DELETE `/diary/{user_id}/{character_name}/entries/{entry_id}` requires
`Depends(require_admin)`, including when the caller owns the character.
It calls `delete(character_name, local_id)` for the named source: unknown
source or a callback returning `False` yields 404, no callback yields 405,
and success returns `{"deleted": "<source_id>:<local_id>"}`. The callback must
scope deletion to the supplied character. The `user_id` segment is ignored,
so clients can use `me`. Existing diary read authorization remains in force.


## Effective stats (`app.core.stat_boosts`)

- `active_boosts(profile, *, now=None, strict=False)`
  returns each stat's active condition contributions with `condition`, `label`,
  integer `amount`, and `remaining_hours`. Only enabled definitions attached to
  `active_conditions` contribute. Expression triggers never contribute boosts.
  Conditions expire strictly after their duration; an unreadable start remains active.
- `effective_stat(profile, key, *, strict=False)` returns the base plus
  active boosts, floored at zero with no upper cap; missing stats return `None`.
- `effective_stats(profile)` returns every base stat with
  `base`, summed `boost`, effective `value`, and the contribution list `boosts`.

These helpers read without mutating profiles. Use them for decisions and display;
stat writers and LLM stat adjustments continue to use the base values (0–100).


## Secrets — `app.models.secrets` ✅

- `list_secrets(character_name, *, strict=False)` → all stored secrets owned by a character.
- `get_secret(character_name, secret_id)` → secret dict or `None`.
- `add_secret(character_name, content, category="personal", severity=2, related_characters=None, related_location=None, consequences_if_revealed="", source="manual", known_by=None, source_ref="")` → created secret dict.
- `add_known_by(character_name, secret_id, knower_name, discovered=False)` → whether the secret exists; adds the knower and stamps first learning with `game_time().canonical()` in `known_at`. Repeated learning preserves that stamp.
- `delete_secrets_by_ref(character_name, source_ref)` → number deleted with the exact reference, scoped to this owner.
- `known_about_others_block(character_name: str) -> str` → known-about-others prompt text, or `""`; shared by chat and both thought templates (thoughts require `secrets_enabled`). Own secrets are excluded.
- `is_record(secret)` → whether `source == "record"`.

The owner's `[known by: …]` annotation omits every name in `discovered_by`;
if no visible knowers remain, the annotation is omitted.

Record secrets keep their creator-assigned `source_ref` through edits. They are
excluded from the owner's own prompt, secret generation context, random hint
candidates and `has_secret`. They remain available to readers who know them.
`created_at` retains its existing timestamp format. Initial or manually edited
`known_by` entries have no learning stamp and use `created_at` for legacy ordering.

`KNOWN_PER_OWNER = 3` and `KNOWN_TOTAL = 8` bound only the known-about-others
prompt block. Stamped entries come first in descending learning order, followed
by unstamped entries in descending `created_at` order. Storage and `list_secrets`
remain unlimited. All secret read-modify-write operations serialize through
`keyed_lock("secrets", character_name)`.


## Character reset stores

`app.core.character_reset.register_reset_store(key, fn, scopes=SCOPES, *, what, lock=None)`
registers a package-owned store from its manifest `on_load` module. `SCOPES` is
`("memory", "reinit")`; use `(SCOPE_REINIT,)` for fresh-start-only state. Keys
must be unique, nonempty and must not collide with core stores/result fields.
Reloading the same key replaces its handler. Registration and snapshots are
protected by a registry lock; register before serving reset requests. Optional
`lock(name)` returns a context manager held around the handler AND its commit;
use the same keyed locks as ordinary writers, acquired before the DB transaction.

`fn(conn, character_name) -> int` runs synchronously in its own world-DB
transaction and returns a count of deleted/changed records. It must raise on
failure, must not commit the supplied connection, and must preserve other
characters' shared state. File cleanup must be idempotent and enforce resolved
path containment. The handler must guard any queued work that could recreate
its records (for example using a persisted reset generation).

`reset_character(name, scope="memory")` includes per-key counts and
`errors: [{"store": key, "error": message}]`; a failed key has value `None`,
never a fabricated zero. Other stores still run. `describe_scope(scope)` lists
registered keys and their `what` descriptions. The HTTP wipe returns that same
result. Core never imports package implementations. Both scopes also reset
derived beliefs/lessons/goals and `retrospect.last_at:<name>`.
