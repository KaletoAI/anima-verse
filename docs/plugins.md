# Skill-Pakete (Plugin-System)

Referenz des **Paketformats v1** — was in eine `plugin.yaml` darf und was der Loader
damit macht. Gegenstück: `docs/skill-core-api.md` beschreibt die **imperative** Seite
(welche Core-Funktionen ein Verb zur Laufzeit rufen darf).

Ein Skill ist ein **selbst-enthaltenes Paket** unter `plugins/` — ohne Änderung am
Hauptcode. Es bringt alles mit, was sein Skill braucht: Verb-Klassen, LLM-Templates,
Admin-Config-Schema, Character-Template-Fragmente, State-Flag-Lebenszyklen und
Spezies-Inhalte. Regeln und Architektur (R1–R7):
`development_instructions/done/plan-skill-plugin-architecture.md`.

Der Migrationsstand ist am Dateisystem ablesbar: Was unter `plugins/` liegt, ist
regelkonform paketiert; was noch in `app/skills/*.py` liegt, ist unmigrierter
Altbestand — heute noch vier Verb-Klassen in `app/skills/`: `OutfitChangeSkill`,
`OutfitCreationSkill`, `DescribeRoomSkill`, `VideoGenerationSkill`.

## Architektur

```
plugins/                          # Paket-Verzeichnis (Projektroot)
  mein_paket/
    plugin.yaml                   # Manifest (Paketformat v1)
    skill.py                      # Verb-Klasse(n), erben von PluginSkill
    templates/
      llm/skills/<skill_id>.md    # Tool-Name + Beschreibung (LLM-Meta)
      llm/tasks/<task>.md         # optionale eigene Task-Prompts
      character/<fragment>.json   # Character-Template-Fragmente
  installed/                      # Marketplace-Installationen (gitignored)

app/plugins/                      # Paket-Infrastruktur
  loader.py                       # Discovery, Manifest-Parsing, Instanziierung
  registry.py                     # Package/SkillEntry/FlagSpec/BodySlotSpec + Aggregate
  context.py                      # PluginContext (Service-API)
  base.py                         # PluginSkill (erbt BaseSkill)
```

**Ladevorgang** (`app/plugins/loader.py`):

1. `SkillManager.load_skills()` ruft `load_all_plugins()`.
2. `discover_packages(force=True)` scannt zuerst `plugins/`, dann
   `plugins/installed/`. Jeder Ordner mit `plugin.yaml` wird geparst
   (`_parse_package`) und in `app/plugins/registry.py` registriert. Bei
   ID-Kollision gewinnt das Repo-Paket; das installierte wird mit einer Warnung
   übersprungen.
3. **Abhängigkeits-Durchlauf:** Ein Paket, dessen `requires` nicht alle vorhanden
   sind, wird wieder ausgetragen — in einer Schleife, bis nichts mehr wegfällt, damit
   sich Ketten auflösen. Es bleibt dann komplett inert (keine Verben, keine Beiträge).
4. Beiträge werden verdrahtet: Template-Suchpfad
   (`prompt_templates.register_package_template_dirs`), Character-Template-Cache
   (`character_template.clear_template_cache`). Admin-Config-Schema, Flag-Specs und
   Default-Skills liest der jeweilige Konsument selbst aus der Registry
   (`config_subsections()`, `flag_specs()`, `default_enabled_skill_ids()`).
5. `on_load`-Module werden importiert (siehe unten).
6. Pro Verb importiert `load_plugin()` die Skill-Klasse und instanziiert sie mit
   `({"enabled": True}, PluginContext(pkg.id), **params)`; danach stempelt der Loader
   die Manifest-Flags auf die Instanz und holt Tool-Name/Beschreibung aus
   `templates/llm/skills/<skill_id>.md`.
7. Der Skill hängt danach wie ein Built-in im SkillManager (Per-Character-Config,
   Tool-Formate, `reload_skills()` verhalten sich identisch).

### Pakete pro Welt aktivieren

**Game-Admin → Setup → Packages → Enabled packages** setzt `packages.enabled` in der
`config.json` der geöffneten Welt. Der Wert ist eine kommaseparierte Allowlist exakter Paket-IDs
(Ordnernamen), beispielsweise `human,movement,talk_to`. Leer bedeutet: **kein Paket aktiv**.
Auch noch nicht installierte IDs bleiben gespeichert. Die Installation allein aktiviert nichts.

Die Auswahl gilt **ab dem nächsten Serverstart**, nicht nach `reload_skills()`. Nur explizit
aufgeführte Pakete werden geladen. Ihre über `requires` benötigten Pakete müssen ebenfalls
aufgeführt sein; sonst bleibt das abhängige Paket vollständig inaktiv. Das betrifft auch
`always_load`-Verben, Character-Fragmente, Anatomie, Prompt-Templates, State-Flags und
`on_load`-Hooks. Gespeicherte Paket-Einstellungen bleiben ihrer bisherigen Welt-/Instanz-Schicht
zugeordnet; ihre Metadaten zu lesen aktiviert kein Paket. Die Auswahl wird pro Welt gespeichert.

Das ist unabhängig von `skills.<id>.enabled` (nur gewöhnliche Verben eines aktiven Pakets) und
der Skill-Aktivierung pro Character. Diese beiden Schalter aktivieren kein Paket.


## plugin.yaml — Manifest-Referenz (Paketformat v1)

```yaml
name: training                  # Pflicht — ohne name wird das Paket verworfen
version: "1.0.0"
description: Kurzbeschreibung des Pakets
capability_label: "Training"    # EIN UI-Toggle für alle Verben des Pakets

# Verben — Kurzform (skill_id/module top-level) oder Listenform:
skills:
  - skill_id: start_training
    module: skill.py            # Default: skill.py
    class: TrainingSkill        # Default: erste PluginSkill-Subklasse im Modul
    params: {active: true}      # Konstruktor-Kwargs (parametrisierte Verben)
    always_load: true           # immer laden, Aktivierung per Character
    default_enabled: false      # bei neuen Charakteren default-aktiv

templates:
  llm: templates/llm            # wird in den Prompt-Template-Suchpfad aufgenommen
  character:                    # Character-Template-Fragmente (siehe unten)
    - templates/character/courage.json

config_schema:                  # Admin-Settings-Subsections unter "Skills"
  training:
    label: Training
    fields:
      ttl_minutes: {type: int, label: "Auto-end after (min)", default: 120, min: 0}

state_flags:                    # Flag-Lebenszyklen (Flag-Lifecycle-Executor)
  - flag: is_training
    cleared_by: end_training    # skill_id des lösenden Verbs (Auto-Clear ruft es auf)
    prompt_when_set: "You are in a training session — end it with {clear_tool} when it is over."
    ttl_minutes: 120            # 0 = kein Zeit-Zerfall
    reset_on_location_change: true
    distracting: false           # true: a set flag occupies attention
```

### Paket-Ebene

| Feld | Pflicht | Beschreibung |
|---|---|---|
| `name` | ja | Ohne `name` verwirft der Loader das Paket. Die **ID** ist dagegen immer der Ordnername (`pkg.id`) — auf sie zeigen `requires`/`conflicts` und `skills.<id>.enabled` |
| `version` / `description` | nein | Reine Metadaten (Marketplace-Anzeige) |
| `skills` / `skill_id` | nein* | Listenform oder Single-Skill-Kurzform. *Ein Paket ohne Verben („Content-Pack") ist erlaubt, solange es mindestens einen Beitrag liefert (LLM-Templates, Character-Fragmente, `config_schema`, `state_flags`, `silhouette`, `body_slots`, `piece_slots` oder `on_load`). Beiträge gelten, sobald das Paket im Dateisystem liegt — das enabled-Gate betrifft nur Verben |
| `always_load` | nein | Default für `skills[].always_load` aller Verben des Pakets |
| `enabled_default` | nein | Lade-Gate-Default für Verben OHNE `always_load`, wenn weder `skills.<id>.enabled` in der Config noch die Env-Bridge etwas sagen (z.B. `true` für Kern-Verben wie `talk_to`, `movement`, `act`, `interact`, `take_photo`) |
| `env_prefix` | nein | Nur Altbestand: Präfix der Env-Bridge-Variable `<prefix>ENABLED` (Default `SKILL_<ID>_`). Neue Pakete nutzen `ctx.get_config` |
| `llm_tasks` | no | Mapping of task IDs to `{label, category, priority?, fallback?}`. Categories: `chat`, `tool`, `helper`, `image`; priorities: `low`, `normal` (default), `high`. Fallback names an existing task. Unknown parents are dropped with a warning; core task IDs cannot be replaced. Task declarations also count as a content contribution. Only active packages with satisfied dependencies contribute tasks; discovery rebuilds them after removal. Inventory scans do not register tasks. |
| `templates.llm` | nein | Ordner relativ zum Paket; gleiche Struktur wie `shared/templates/llm/`. Existiert er nicht, gibt es eine Warnung und keinen Beitrag |
| `templates.character` | nein | Liste von Fragment-JSONs (siehe unten) |
| `config_schema` | nein | Subsections für `/admin/settings → Skills` |
| `state_flags` | nein | Flag-Deklarationen mit Lebenszyklus. Flags können WERTE tragen (`training_focus: sparring`, gesetzt per Rule-Action `set_flags`, leerer Wert löscht) und stehen als optionale `{platzhalter}` in Body-Slot-Prompts sowie als Rule-Condition (`training_focus`, `stamina>50 AND is_training`) zur Verfügung |
| `requires` | nein | Paket-IDs, die vorhanden UND am Charakter aktiv sein müssen. Fehlt ein Paket im Dateisystem, bleibt dieses Paket komplett inert; ist es am Charakter inaktiv, lassen sich die Verben nicht aktivieren |
| `conflicts` | nein | Paket-IDs: solange eines davon am Charakter aktiv ist, sind die Verben dieses Pakets nicht aktivierbar (wirkt in beide Richtungen) |
| `capability_label` | nein | EIN UI-Toggle für ALLE Verben des Pakets (SkillsTab) — z.B. `"Party"` für invite/join/leave oder `"Sleep"` für sleep/wakeup |
| `capability_description` | nein | Menschenlesbarer UI-Text der Fähigkeit (SkillsTab-Detail) — die Verb-Beschreibungen sind LLM-Tool-Prosa („call FollowDressCode") und adressieren den Charakter, nicht den User |
| `on_load` | nein | Modul (Pfad relativ zum Paket, darf den Paketordner nicht verlassen), das beim Laden importiert wird — für Code-Beiträge OHNE Verb, z.B. `app.core.hooks.register_provider` oder ein Improvement-Typ. Zählt selbst als Paket-Beitrag; läuft bei jedem Force-Reload, Registrierung also idempotent halten |
| `being` | nein | Spezies-Nomen für die Szenen-Komposition (`person`/`animal`/…, Default `person`) — „Compose exactly one person and one animal…" statt Katzen als „people" zu zählen |
| `apply_to` | nein | Template-Selektor (Namen/`*`/`{feature}`) für die Spezies-Inhalte (`silhouette`/`body_slots`/`piece_slots`); ohne ihn zählen die Selektoren der Character-Fragmente |
| `silhouette` | nein | `{asset: <relpath>, anchors: {slot: [x%, y%]}}` — UI-Paper-Doll der Spezies |
| `body_slots` | nein | Körper-Slot-Deklarationen (s.u.) |
| `undressed_prompt` | nein | Text, den ein ausgezogener Freitext-Charakter (Template ohne Outfit-System, `outfit_worn` aus) in allen Prompts statt des Core-Texts „no clothes" trägt; gilt für die `apply_to`-Templates des Pakets. Zählt als Paket-Beitrag |
| `piece_slots` | nein | Kleidungs-Slot-Topologie der Spezies (String oder `{id, label}`); ohne Deklaration gilt der Core-Default (`inventory.VALID_PIECE_SLOTS`) inkl. Core-Reihenfolge/-Labels |

`state_flags[].distracting` is an optional boolean (default `false`), exposed
as `FlagSpec.distracting`. When true, a truthy value of that flag in the
character profile makes `app.core.attention.is_distracted` return true.
This declaration adds no lifecycle or pose changes.

### Verb-Ebene (`skills[]`)

Alle Flags sind optional und schalten nur **ein** — die Klassenattribute bleiben die
Grundlinie, der Loader setzt nie auf `False` zurück.

| Feld | Beschreibung |
|---|---|
| `skill_id` | Pflicht. Ein Eintrag ohne `skill_id` wird stillschweigend übersprungen |
| `module` | Datei im Paket (Default `skill.py`) |
| `class` | Explizite Klasse (nötig bei mehreren PluginSkill-Klassen pro Modul); ohne Angabe die erste gefundene |
| `params` | Konstruktor-Kwargs — EINE Klasse kann mehrere Verben bedienen |
| `always_load` | Immer laden, Aktivierung per Character (ignoriert das enabled-Gate) |
| `default_enabled` | Neue Charaktere bekommen den Skill aktiviert (`registry.default_enabled_skill_ids`) |
| `singleton` | State-setzendes Tool: nur der LETZTE Call pro Stream zählt (Dedupe) |
| `suppress_in_person` | Verb wird unterdrückt, solange die Gesprächspartner im selben Raum sind (Bewegungs-/Fernkommunikations-Verben) |
| `cascade_brake` | reply_only_to-Gate für Messaging-Kaskaden greift auf dieses Verb |
| `search_intent` | Der Search-Forcing-Hint (User fragt nach realen Infos) zielt auf dieses Tool |
| `delivers_speech` | Über dieses Verb erreicht wörtliche Rede jemanden (TalkTo/SendMessage) — das B-lite-Sprachnetz prüft Thought-Turns dagegen |
| `intents` | Intent-Typen, die dieses Verb ausführt (F6) — die Klasse implementiert `handle_intent()`; Default = Payload-Durchreichung an `execute()` |
| `intent_payload_keys` | Intent-Params mit dem vergleichbaren Inhalt (Redundanz-Skip: Intent vs. bereits ausgeführtes Tool im selben Turn) |
| `user_notification` | Tool-Ergebnis wird User-Notification — generisch gelesen via `skill_manager.tool_names_with_flag` |
| `remote_comm` | Verb erreicht NICHT anwesende Charaktere (World-Setup-Checkliste „Kommunikation") |
| `progress_type` | Generischer Fortschritts-Typ (`image`, `search`, `talkto`, …) für zählbasierte Intents |

**Nicht über das Manifest setzbar** (nur als Klassenattribut, weil sie den
Ausführungszeitpunkt ändern und nicht bloß Metadaten sind): `DEFERRED` (Tool läuft
erst NACH der Chat-Antwort) und `CONTENT_TOOL` (Ergebnis muss in die RP zurück, im
`rp_first`-Modus mit Chat-Retry). Beide liest der Core generisch per `getattr`.

**Abhängigkeits-Semantik (F9):** „Aktiv am Charakter" heißt für Verb-Pakete:
mindestens ein Verb ist für den Charakter aktiviert; für Content-Packs: mindestens ein
Template-Fragment greift auf das Template des Charakters. Durchsetzung: Lade-Zeit
(`requires`-Präsenz), Skills-API (`blocked_reason` in
`GET /characters/<c>/skills/available`), PUT-Enable (409) und SkillsTab (Toggle
deaktiviert + Begründung). Beispiel im Repo: `plugins/cat` deklariert
`conflicts: [human]`.

### LLM-Templates

`templates/llm/` wird dem Template-Suchpfad **angehängt**: gesucht wird erst der
Haupt-Tree `shared/templates/llm/`, dann die Paket-Ordner in Paket-ID-Reihenfolge
(`prompt_templates.template_search_dirs`). Ein Paket kann ein Haupt-Template also
NICHT überschreiben, nur eigene ergänzen.
`skills/<skill_id>.md` liefert Tool-Name + Beschreibung im bekannten Format
(Frontmatter `name:`, Body = Description) und wird vom Loader automatisch auf die
Skill-Instanz angewandt — die Klasse muss `name`/`description` nicht selbst setzen.
Weitere Frontmatter-Keys werden durchgereicht: `action_hint:` ist die kurze
„Character does X"-Zeile für den Constrained-Tool-Prompt (Fallback ohne Deklaration:
generische Trigger-Zeile). Leerer Body = die Beschreibung der Klasse/Config bleibt
erhalten. Ein Paket darf unter `templates/llm/tasks/` auch eigene Task-Prompts
mitbringen (Beispiel: `instagram_caption.md` im instagram-Paket).

### Character-Template-Fragmente

Ein Fragment ist ein Extension-Template (gleiche Merge-Semantik wie `base:`-Merges)
plus `apply_to`-Selektor:

```json
{
  "apply_to": ["human-roleplay"],
  "sections": [
    {"id": "traits", "fields": [
      {"key": "courage", "label": "Courage", "type": "number",
       "store": "status_effects", "default": 30, "hint": "0-100 ..."}
    ]}
  ]
}
```

`apply_to`: `"*"` (alle Templates) · Liste von Template-Namen · `{"feature": "<flag>"}`
(alle Templates mit diesem Feature). Wird das Paket entfernt, verschwinden seine
Felder aus den Templates — paketeigene Stats gehören damit dem Paket (R2). Ein
unlesbares Fragment wird geloggt und übersprungen, das Paket lädt trotzdem.

### Body-Slots (Spezies-Pakete)

Der Body-Slot-Core (`app/core/body_slots.py`) führt die Deklarationen aus — kein
Slot-/Spezies-Name im Core; eine neue Spezies ist ein neues Content-Paket
(`plugins/human`, `plugins/cat` sind die Vorlagen):

```yaml
apply_to: ["human-roleplay"]      # welche Templates diese Spezies sind
silhouette:
  asset: assets/silhouette.svg
  anchors: {top: [50, 33], bottom: [50, 55]}   # Slot-Marker-Positionen (x%, y%) im Bild
piece_slots: [top, bottom, underwear_top, underwear_bottom, feet]
body_slots:
  - id: hair
    face: true                            # Fragment gehört auch in Portrait-/Ausdrucks-Prompts
    attributes:
      color: {type: str}
    prompt:
      always: "{color} hair"
  - id: tail
    covered_by: [bottom]                  # verdeckende Kleidungs-Slots; ohne = immer sichtbar
    applies_to: {gender: [female, girl]}  # Profil-Feld-Bedingungen
    back: false                           # von hinten sichtbar? (Default false)
    attributes:
      size: {type: select, options: [small, medium, large], interest_aliases: {...}}
      lora: {type: lora_select}           # Mechanismus; das konkrete LoRA bleibt per-NPC-Config
    prompt:
      always: "…"                         # immer
      covered: "…"                        # nur bedeckt → fließt in die allgemeine Personenbeschreibung
      exposed: "…"                        # nur unbedeckt
```

| Slot-Feld | Beschreibung |
|---|---|
| `id` | Pflicht — ohne `id` wird der Eintrag übersprungen |
| `covered_by` | Kleidungs-Slots, die den Slot verdecken; leer = immer sichtbar |
| `applies_to` | `{profilfeld: [erlaubte Werte]}` — Slot gilt nur für passende Charaktere |
| `attributes` | `{name: {type: …, options: …}}`. Optional `default: {apply_to: <Template-Selektor>, value: <text>, by: {<profilfeld>: {<feldwert>: <text>}}}` — füllt einen UNGESETZTEN Wert nur im `exposed`-Fragment der passenden Templates (bedeckt spricht der eigene Aussehenstext) (`by` zuerst, sonst `value`; ohne Treffer und ohne `value` = ""); ein so vertretenes Attribut darf leer sein, das Wort entfällt dann statt des ganzen Fragments. Der Editor zeigt den Wert grau, gespeichert wird er nie. `interest_aliases` (`{kanonischer_wert: [phrase, …]}`) ist das Attraction-Matching: Phrasen im romantic_interests-Text der GEGENSEITE matchen gegen den Slot-Wert dieses Charakters — der Core hat keine Alias-Tabellen |
| `prompt` | `always` / `covered` / `exposed` (s.o.) |
| `face` | Fragment gehört auch in Portrait-/Ausdrucks-Prompts (`prompt_fragments(face_only=True)`) |
| `back` | Die Anatomie ist auch von HINTEN zu sehen. Rückansicht-Renders — die T-Pose-Back-Referenz der Bild→3D-Kette — behalten nur `exposed`-Fragmente solcher Slots und deren LoRAs; alles andere beschreibt die Vorderseite und zöge die Figur zur Kamera herum. `always`/`covered` sind nicht betroffen: sie beschreiben die ganze Person, nicht eine Seite. Default `false` |

Werte pro Charakter liegen im Profil (`body_slots: {<slot>: {<attr>: <wert>}}`).
Fragmente mit fehlenden Attribut-Werten entfallen komplett (kein halb gerendertes
`{size}`), außer ein `default` vertritt das Attribut. Die Fragmente gehen auch mit
Referenzbild mit (F3). Ein Freitext-Charakter (Template ohne Outfit-System) hat
keine Pieces: seine Slots mit `covered_by` sind bedeckt, solange er angezogen ist
(`outfit_worn`), und unbedeckt, sobald er ausgezogen ist.

#### Optional `rigs` declaration (P1)

A slot may carry a list of validated extension groups under `rigs`. All identifiers and operation
parameters come from the package. The core accepts any non-empty `op` string
and stores `params` as a mapping. The mesh runner validates supported
operations and parameters before changing geometry.

```yaml
body_slots:
  - id: example_slot
    attributes:
      example_attribute: {type: select, options: [enabled, disabled]}
    rigs:
      - id: example_group
        op: appendage_chain
        chains:
          - - {bone: ExampleBone1, parent: "<base Mixamo joint name>"}
            - {bone: ExampleBone2, parent: ExampleBone1}
        # Abbreviated: supply ALL operation and reference-frame params below.
        params: {anchor_bone: "<base joint>", anchor_offset: [0, 0, -0.09], cut: 0.15}
        applies_to:
          example_profile_field: [enabled]
          attributes.example_attribute: [enabled]
        freq_hz: 2.2
        zeta: 0.15
        gravity: 0.35
        spill: 0.0
        flatten: 0.0
        stretch: 0.0
        spread: 0.5 # Transverse compensation, capped at 1.6.
        flatten_floor: 0.6 # Omit to inherit effective squash_min.
        translate: 0.0
        sag_max_deg: 25 # Defaults to max_deg when omitted.
        spill_max_deg: 25 # Defaults to sag_max_deg when omitted.
        head_sag: 1.0
        attribute_profiles:
          example_attribute:
            enabled: {freq_hz: 0.8, zeta: 1.2, gravity: 1.1}
        gain: 1.0
        max_deg: 25
        axis_gain: [1, 1, 1]
        squash: [0.6, 1.4]
        rest_max_deg: 90
        straighten_deg: 0 # Off; positive values remove bends as rest increases.
        freetext_clothing_gain: 1 # Clothing factor without resolved item pieces.
```

Replace the base-joint placeholder with a name from
`shared/models/rig/joints.json` (the optional `mixamorig:` prefix is accepted).
Each chain is non-empty and ordered parent first: a link's parent must be a
base joint, an earlier full name in that same chain, or (first link only)
a link bone of another rig on the same slot. Extension names must
be non-empty and distinct after the same normalization as the base contract.
Group IDs must also be unique across loaded declarations.

`applies_to` is an AND of case-insensitive scalar comparisons against allowed
value lists. Profile-field keys inspect the profile. `attributes.<key>` keys
inspect `profile.body_slots[<this slot>][<key>]`; a bare declared attribute key
also selects that slot value. Explicit `attributes.` keys avoid ambiguity.
These conditions are available both on the slot and inside each `rigs` entry; the rig
must additionally pass the package/template and slot applicability filters
unless its own `rigs[].templates` selector replaces those filters.
An omitted condition map applies without further filtering. For both slot and
rig conditions, YAML `null` in an allowed list matches a missing or explicitly
null value only; it does not match `""` or the literal string `"none"`. Both
operands use the same normalization; other scalars compare as trimmed lowercase
strings.

max_deg is the whole-chain dynamic swing budget in degrees, applied independently to each root chain of an appendage. For links ordered root to tip, let span_j be the immutable bind length (joint to joint; twice the centroid lever for the final link) and R_j the sum of spans from link j to the tip. Each link receives share_j = R_j^2*span_j / sum_k(R_k^2*span_k) and a dynamic limit of max_deg*share_j. Equal spans yield 9:4:1 /14 for three links and 25:16:9:4:1 /55 for five. Shares come from bind geometry, never per frame, and govern soft swing saturation, the extreme-anchor guard and dynamic translation clamping. A one-link chain has share 1. Static sag_max_deg and spill_max_deg are unchanged.

`flatten`, `stretch`, `spill` and `translate` are finite in [0,1], default 0.
`flatten_floor` is finite in [0,1]; omission inherits effective `squash_min`
server-side, before attribute multipliers (an absolute character floor overrides them).
For unit world gravity `g_hat`, current rest lever `u` and immutable bind lever
`u_bind` under upright gravity, define
`f_in=clamp(-g_hat.dot(u)-max(0,-g_hat.dot(u_bind)),0,1)` and
`f_out=clamp(g_hat.dot(u)-max(0,g_hat.dot(u_bind)),0,1)`.
Upright in the bind posture gives exactly zero for either target, including
an upward 15-degree bind lever. Static length is the direct target
`s=1-flatten*(1-flatten_floor)*f_in+stretch*(squash_max-1)*f_out`,
independent of gravity, character gravity scale and frequency (including zero).
Outward stretch narrows both perpendicular axes by `1/sqrt(s)`; stretch=1,
squash_max=1.45 and f_out=1 give length 1.45 and transverse .8304547985.
Flatten=1, floor=.15 and f_in=1 give length .15 even with squash_min=.6.
Zero floor uses a positive numerical epsilon to keep transforms finite. Paired spill is the direct
outward rotation `spill*spill_max_deg*f_in` degrees along the projected lateral
`L`; single chains have no spill. For paired groups, define `L_bind` once
from this chain-root head minus the mean of the group's chain-root heads
in the bind pose: remove its bind-pose body-up component and normalize.
At runtime rotate `L_bind` with the anchor rotation, then project it
perpendicular to the current lever `u` and normalize (Gram-Schmidt).
Use this outward `L` for the spill rotation. Paired FLATTENING does not act
along the oblique lever: it presses along the BODY FRONT (bind-pose body front,
rotated with the anchor; where gravity presses when lying) and widens along the
body lateral axis, both expressed in the frame the bone scale acts in. The frame
(front, L ⟂ front, front × L) is orthonormal, so the scale has no shear; the
third axis keeps factor 1. Width = min(1.6, 1 + spread·(1/s − 1)). (An outward-
pointing lever would otherwise tilt the width axis into the height: measured on
a real rig the lying height grew with a lower floor.) Single chains keep the
symmetric lever-frame compensation. Degenerate L uses the symmetric fallback.
Remaining inward axial force is removed.
Non-axial static sag still uses `gravity*(m*g-R_anchor*R_rest*g_rest)/omega²`
and the static angle limit; upright m=1 has no additional sag, m=2 sags and
m=.5 lifts. The force-based static angle is capped by `sag_max_deg`; for chains it bounds the whole chain's static droop; the subsequent spill target uses its independent limit.
`spread` is finite in [0,1], default 0.5. For shortening (`s<1`), paired
transverse compensation along L is `c=min(spread_cap,1+spread*(1/s-1))`;
the third axis stays 1. Single chains use symmetric transverse compensation
`c=min(spread_cap,1+spread*(1/sqrt(s)-1))`. The documented constant
`spread_cap=1.6` bounds mesh widening, deliberately relaxing volume conservation.
At spread=.5, s=.15 gives c=1.6 and s=.8 gives paired c=1.125.
The scale is diagonal in the orthonormal bone frame `(u,L,u cross L)`;
L is projected perpendicular to u and normalized, so it introduces no shear.

`translate` applies that fraction of the perpendicular static and dynamic
rendered displacement to the bone head; the remainder supplies rotation.
Both components are projected perpendicular to the original rest lever, so
uncapped translate=1 leaves its direction unchanged even with combined sag
and bounce. Longitudinal behaviour means the rendered length scalar is preserved.
Dynamic axis gains, soft angle limits and gain are applied before this split.
Each translated component is capped before multiplying by `translate`:
static <= rest lever length * sin(sag_max_deg), dynamic <= static lever length
* sin(max_deg*share_j), with angles converted from degrees to radians for sine.
The dynamic cap uses each link's immutable share of the whole-chain budget.
Longitudinal displacement and
length scaling are unchanged by the split. Weighted borders blend into the
anchor. Supported layers are package defaults/attribute profiles, world overrides
and absolute character overrides; state `bone_pose` has no translate multiplier.
The mesh fingerprint excludes all physics fields. Preview category is `tilt`
for flatten/stretch/spread/flatten_floor/spill/translate: Tilt exposes posture targets and static translation;
play a clip for translate's bounce. Flatten/spill hints explicitly state that
these targets are independent of gravity and frequency.

`attribute_profiles` is optional: `{attribute_key: {value: {field: multiplier}}}`.
Attribute keys must be declared on the same slot; values are string keys matched
exactly against that character's stored slot value. Missing/unknown values are
ignored. Allowed multiplier fields: `freq_hz`, `zeta`, `gravity`, `gain`,
`max_deg`, `sag_max_deg`, `spill_max_deg`, `head_sag`, `flatten`, `stretch`, `spread`, `flatten_floor`, `spill`, `translate`. Multipliers must be finite and
nonnegative (`freq_hz` strictly positive); they may exceed 1. After multiplication,
unit-interval fields saturate at 1 and angle limits at 180. Multiple matching
attribute profiles multiply in declaration order. Profiles never enter mesh identity.

Every physics field is optional with the defaults shown above. All numbers
must be finite: `freq_hz > 0`; `zeta >= 0`, `gravity >= 0`; `gain`, `flatten`, `stretch`, `spread`, `flatten_floor`, `spill`, `translate` and `head_sag` in `[0,1]`;
`max_deg`, `sag_max_deg`, `spill_max_deg`, `rest_max_deg` and `straighten_deg` in `[0,180]`;
`freetext_clothing_gain` in `[0,1]`; `squash` is exactly two positive
numbers satisfying `min <= 1 <= max`. `params` must be a mapping. A malformed
rig is dropped with a warning, and its slot remains available. Duplicate
normalized extension names or group IDs cause a load error naming all owners.
Conflicts are detected over the complete declaration set before registration;
**every involved rig is dropped**, independent of package order, while slots
and packages remain available. Direct registry registration rejects conflicting packages
with `ValueError` before mutating the registry.

Removing the package removes its groups
and restores strict base-joint validation without any operation-specific
core change. Mesh overrides live in `profile.model3d_opts.extension_rig`:
`{<group_id>: {enabled: bool, flip: bool}}`. Missing flags mean `enabled=true`,
`flip=false`; flip swaps attachment and tip for an appendage chain. Overrides
change the mesh fingerprint. World settings, equipment damping and runtime
state compose independently through `motion` (see below).

#### Required mesh-operation parameters

All operations take all operation settings from `rigs[].params`. Core supplies
no anchors, shape thresholds, offsets, split positions or test poses. Every
parameter listed below is required; missing parameters produce step status
`failed` with a `missing required params` reason and no mesh output. The slot
loader validates the declaration shape; operation validation happens at execution.
The values below are neutral fixture examples, not defaults. Distances are meters, fractions dimensionless and
pose rotations degrees. Unknown keys, non-finite numbers, malformed vectors,
invalid ranges and incompatible chain shapes fail the whole request before
publication. Parent joints always come from `chains`, never a geometry heuristic.

Both operations additionally require declaration-driven reference checks:
`up_from_bone`, `up_to_bone`, `lateral_positive_bone`,
`lateral_negative_bone`, `front_from_bone`, `front_to_bone` (base joint names),
`up_distance_min`, `up_distance_max` (positive-Z separation bounds), and
`front_distance_min` (minimum negative-Y separation). No concrete reference
joint or size ratio is selected by core. Armature identity and metre scene
units use only generic numerical tolerances. The executable neutral declarations
in `scripts/smoke_extension_rig_p1.py` supply every parameter.

A first link may name an exact link bone of another rig on the same slot.
Later links must name a base joint or an earlier link in their own chain.
The loader derives `depends_on`; packages do not declare it. Missing parents,
cycles, and dependencies lost in conflict resolution drop the dependent rig.
Applicable groups are ordered by dependency depth, then id. A dependent group
is applicable only with its source, and enabled only when both overrides enable it.
Slot attributes and clothing coverage apply to every rig on that slot.
The retired singular manifest key is an error and loads no rigs for that slot.

Declared `length` defaults to 1 and accepts [0.5,3]. World and character overrides
replace it; state `bone_pose.length` values multiply it. The effective result is
clamped to [0.25,4]. Girth starts at 1 before state factors. These are motion-only
values; fingerprint version 14 identified the pair tip contract, version 16
the geometry-mode crest search and midline cap of `pair_protrusion`.

`pair_protrusion` requires two one-link chains: first `+X`, second `-X`.
Sides are measured from the body midline, the mean x of `lateral_positive_bone`
and `lateral_negative_bone`; `lateral_min`/`lateral_max` bound the candidate
cells and `side_margin` keeps every sample and weight on its own side.
The colour search starts from each side's smallest-Y vertex within the declared
height/lateral band. The tip comes from a colour marker when the texture shows one: a front
ray grid (`marker_grid_step`, disc `marker_search_radius`) samples the base
colour, converts it to CIE Lab and scores `(a-a_median) - marker_yellow_weight*(b-b_median)`;
cells above `marker_score_min` with lightness between `marker_dark_min*L_median`
and `L_median+marker_light_max` form 4-connected components. The largest one is
accepted when its area lies in `[marker_area_min, marker_area_max]` (m²) and its
RMS spread is at most `marker_spread_max`. Both sides must be accepted and
mirror each other within `marker_pair_dz`/`marker_pair_dx`; otherwise both use
geometry (`apex_source` in the metrics says which).
The attachment wall is measured from the tip in `boundary_directions` frontal
directions (a multiple of four; 0 = up): from `boundary_s_min` to `boundary_s_max`
in `boundary_step` steps, the boundary is the tangent point (largest
`(y - tip.y)/s`). Lateral directions mirror the medial ones. The pair uses
the smaller reach per direction and the deeper wall offset (occluders such as
hair lie in front of the surface), and a least-squares plane through the wall
points is each side's wall.

Geometry mode (no marker, e.g. under clothing) never uses single vertices: a
front ray grid at `marker_grid_step`, mirrored about the midline and extended by
3·`apex_context_radius` beyond the candidate cells, is blurred with Gaussians of
`apex_smooth_radius` (folds, seams, bows) and `apex_context_radius`
(surroundings). A cell's protrusion is how far the first stands in front of the
second, so torso tilt and rib cage curvature drop out. Both sides are scored
together (sum over mirrored cells); the tip is the mean of the 4-connected cells
within 2·`apex_plateau_depth` of the best sum. The wall is measured from there;
the tip then moves to the crest of distance in front of the wall, using only its
sagittal (y-z) normal and staying within `marker_search_radius`, and the wall is
measured once more. The tangent search rarely finds a real boundary on fabric,
so the outline becomes round with the median reach. The bone
runs from `head_wall_depth` behind the wall (at the wall points' mean) to
the tip. Weights combine a radial term over the star-shaped outline `R(angle)`
(linear between the directions): `smooth((1-r/(R*radius_scale))/(1-radius_plateau))`,
full through `radius_plateau*R*radius_scale`, zero at `R*radius_scale`; toward
the midline `R*radius_scale` is capped where the ray from the tip meets
`side_margin`, so weight fades to zero there even when fabric bridges the gap; a depth
ramp of `depth_ramp` that starts `front_margin` behind the wall; and
`1 - w/exclude_weight` for a vertex's current weight `w` on `exclude_bones` and
their descendants. Parameter changes alter the fingerprint and rebuild from the
clean prerig.

`pair_tip` requires two one-link chains, parented side by side to a
`pair_protrusion` group on the same slot. Geometry detection soft-skips the tip
group; colour placement supplies `marker_area` in square metres and one shared
radius R = sqrt((left_area + right_area)/(2*pi)). A rounded stub is baked after source re-planning.

| Required parameter | Example | Constraint / meaning |
|---|---|---|
| `subdivide_radii` | `[2.4, 1.8, 1.0]` | 1–4 positive non-increasing radii × R, one flat subdivision each |
| `normal_radius` | `2.0` | Positive face-centre radius × R for area-weighted normal |
| `fill_radius` | `1.7` | Positive replacement radius × R |
| `fill_ring` | `0.7` | Positive fit ring width × R |
| `fill_blend` | `0.3` | Positive inner edge blend width × R, less than fill_radius |
| `fill_depth` | `0.03` | Nonnegative depth in metres, ignores points behind the tip |
| `fill_tolerance` | `0.012` | Positive distance to fitted surface in metres |
| `fill_rms_max` | `0.0015` | Positive maximum fit residual in metres |
| `tip_diameter` | `0.009` | Positive stub diameter, metres; rc = diameter/2 |
| `tip_length` | `0.005` | Positive axial length including cap, metres |
| `tip_round` | `0.6` | Cap height / rc in (0,1]; 1 is a hemisphere |
| `tip_wall` | `0.0015` | Positive radial side-wall ramp width, metres |
| `tip_band` | `0.009` | Positive radial weight band beyond wall, metres |
| `tip_subdivide` | `0.009` | Nonnegative radius of one extra subdivision after fill; 0 disables it |
| `weight_depth` | `0.015` | Nonnegative depth cutoff behind filled tip, metres |
| `weight_min` | `0.003` | Weight threshold in [0,1) |
| `test_rotation_deg` | `[0,0,0]` | Three finite degrees |
| `test_scale` | `[1.4,1.6,1.4]` | Three positive factors; local Y is the axis |

The same required up, lateral and front reference parameters apply as above.
Every subdivision selects edges by world midpoint distance to either tip,
interpolates UVs and deform weights (new sums must be within 1e-4 of one), and
triangulates faces with more than four corners. Coincident seam copies remain aligned.
An area-weighted normal points toward front (-Y); its orthogonal plane gives u,w,h.
Unique ring positions fit h=c0+c1*u+c2*w+c3*u²+c4*u*w+c5*w² by least squares.
Fewer than 12 points or excessive RMS refuses fill while retaining the bone.
Accepted inner points blend to the quadric with smoothstep, subject to depth
and tolerance gates. Filled tip is t+n*c0, axis normalizes n-c1*a-c2*b;
without fill these remain t,n. After fill, one extra subdivision selects world
edge midpoints within `tip_subdivide` of either filled tip, with the same
interpolation, triangulation and deform-sum checks. No stub is baked yet: source
re-planning must ray-cast the filled surface with pinned markers.

After source re-planning, let cap=min(tip_round*rc,tip_length) and
lw=tip_length-cap. The baked axial height at perpendicular distance r is
H(r)=lw+cap*sqrt(1-(r/rc)²) for r<=rc,
H(r)=lw*smooth((rc+tip_wall-r)/tip_wall) through the wall, and 0 beyond.
Every skinned vertex no further than `weight_depth` behind the base plane moves
by axis*H(r). The positional rule preserves coincident copies and updates the
working coordinates before all later metrics and unification. The bone head is
the filled tip t' on the base plane; its tail is t'+axis*tip_length.

Weight w=1 through rc+tip_wall, then
w=smooth((rc+tip_wall+tip_band-r)/tip_band), zero beyond the band, subject to
the same depth gate. The tip takes T=w*S from the source; the source retains
S*(1-w), preserving the extension total before top-four export. Empty tip weights
soft-skip both tip bones and report that mesh edits remain.

Bone creation and runtime particles follow dependency order. Metrics include
head, tail, axis, tip, radius, fill outcome/RMS/moved/tolerance counts, density
within 5 mm and vertices before/after. `stub_height` is the maximum baked axial
offset from the base plane; `lift` measures test-pose displacement at the vertex
nearest the stub top. `diameter` is twice the mean posed radial distance of the
wall-top ring (|r-rc|<tip_wall/2 and H>lw/2).
`girth_fold_free_max` reports 1+1/max(0,-min(w+r*w')), or null for infinity.
The band uses the analytic smoothstep derivative sampled densely: with
x=(r-rc-tip_wall)/tip_band, w=1-3x²+2x³ and w'=-6x(1-x)/tip_band.
The example dimensions give 68/41, about 1.65854; above this factor the radial
mapping can fold. These metrics describe the test pose, including actual skin weights.
Absent groups in metrics-only inspection report `not_found`. GLB validation accepts
each group complete or absent, and checks non-base parents by exact name.

`pair_protrusion` declaration example values:

| Parameter | Example declaration value |
|---|---|
| `band_lower_bone` | `"Spine1"` |
| `band_upper_bone` | `"LeftArm"` |
| `band_lower_offset` | `0.02` |
| `band_upper_offset` | `-0.04` |
| `lateral_min` | `0.03` |
| `lateral_max` | `0.17` |
| `marker_search_radius` | `0.07` |
| `marker_grid_step` | `0.0025` |
| `marker_score_min` | `6` |
| `marker_yellow_weight` | `0.5` |
| `marker_dark_min` | `0.55` |
| `marker_light_max` | `3` |
| `marker_area_min` | `0.0001` |
| `marker_area_max` | `0.003` |
| `marker_spread_max` | `0.02` |
| `marker_pair_dz` | `0.02` |
| `marker_pair_dx` | `0.03` |
| `apex_smooth_radius` | `0.015` |
| `apex_plateau_depth` | `0.003` |
| `apex_context_radius` | `0.05` |
| `boundary_directions` | `8` |
| `boundary_s_min` | `0.03` |
| `boundary_s_max` | `0.13` |
| `boundary_step` | `0.0025` |
| `exclude_bones` | `[]` |
| `exclude_weight` | `0.3` |
| `head_wall_depth` | `0.04` |
| `radius_plateau` | `0.6` |
| `radius_scale` | `1.15` |
| `side_margin` | `0.005` |
| `front_margin` | `0.03` |
| `depth_ramp` | `0.04` |
| `weight_min` | `0.003` |
| `test_rotation_deg` | `[-15, 0, 0]` |
| `test_scale` | `[1, 1.12, 1]` |

`appendage_chain` requires one chain with N links. Per-slice lateral front
references lie beside the part, within the anchor-relative search window.
Candidate vertices protrude beyond that reference; covariance power iteration
finds the principal axis. The end nearest `anchor_bone.head + anchor_offset`
is the attachment; the character's `flip` flag swaps it with the tip.
Connectivity runs over position-welded vertices after the `cut` slab, bounded
by an axial window (`window_length_factor * length + window_margin` each side
of the midpoint) and `segment_radius_factor * measured_half_width`. The measured
half-width is half the lateral extent (max X minus min X), using the
axis candidate set. Pass 0 uses these candidate bounds. Each of up to `segment_passes` refinement
passes fits a principal axis through the bounded component centroid (one sample
per welded position), keeping its attachment-to-tip orientation and attachment
station. The initial axial length is held fixed so the cut does not drift as the
component excludes the attachment slab. The new radius is the linearly interpolated
`segment_radius_percentile` of radial distances to this axis, multiplied by
`segment_radius_margin`. Bounded welding and flood are repeated with the new axis
and radius. A symmetric vertex-set difference below 1% of the previous original
vertex count stops iteration. Radius growth above `segment_radius_growth_max`
times the preceding radius, or a component exceeding `leak_t_limit`, retains the
previous set, axis and radius and reports the reason. A refined component below
`segment_min_vertices` also retains the previous pass. After refinement, the
attachment grows backward through edge-connected, position-welded surface slices
of thickness `base_slice_size` metres. The acceptance tube uses the median of
the original protrusion candidate slices' centred radial p95 values, multiplied by
`base_radius_margin`; it never uses `segment_radius` or inflates as growth proceeds.
Each accepted slice's centroid supplies the next slice's centre. Its radial p95
and connected position count are compared to `base_growth_max` times the running
median of the latest `base_history_slices` measured part and accepted growth slices.
The first rejected slice is excluded, and growth also stops at
`base_extension_max` of the original detected length. The positive attachment
ring is recovered with the same connected tube before crossing t=0. This allows an attachment
behind the lateral front reference without admitting neighbouring side surfaces
outside the tube. Original source-joint weights do not veto an in-tube vertex:
the part itself may originally be weighted entirely to those joints.
Position welding additionally requires world-space normal dot product at least
`weld_normal_min`. Facing contact surfaces therefore remain separate even within
`weld_distance`; positional deduplication for geometry statistics does not join
their connectivity. Coincident seam copies within the `1e-6` metre float tolerance
also weld when their normals are perpendicular or aligned and a coincident
boundary edge supplies seam evidence; an isolated contact point does not.
Opposing normals
remain excluded. This retains sharp end caps. The bounded component with most original candidate support
is selected; nearest-tip distance breaks ties. This avoids selecting an isolated
sharp end face after the normal guard separates its UV copies.
For either non-leak path, only the first link head moves to the pivot.
Base point A is the measured `attachment_station` with successful backward
growth, or the existing `root_station`, including `attachment_inset`, without
growth. Intersect every mesh face with the sagittal plane x=A.x to obtain
(y,z) segments and their normalized outward face-normal projections; skip
degenerate projections. F is the front-most (minimum y) segment point within
A.z+0.02 <= z <= A.z+0.05, including intersections with these bounds.
To find K, build a BVH over the mesh and start at the unmoved `joints[1]`,
with x set to A.x. Cast +Y and require an exit E whose outward face normal
has positive dot with +Y. If the first hit is an entry (negative dot), walk
through subsequent hits to an exit. From E plus a `1e-6` metre +Y offset,
reject any next +Y surface within the remaining distance to 2 mm. An outward
exit followed by no intervening surface keeps the entire interval to
Q=E+(0,0.002,0) in air, including thin surfaces that a Q-only test could miss.
Cast +Z from Q to the first ceiling hit H. Map the BVH's input face index to
that face's section segment and insert H into that segment. Connect section
endpoints that share a mesh edge or coincide within `1e-6` metres; climb only
this connected contour. Before declaring a local maximum K, traverse connected
equal-height neighbours (`|dz| <= 1e-7`) with a visited set, then climb to the
highest rising neighbour. Self-neighbours and plateau cycles are harmless.
If an exit, clear interval or ceiling is unavailable, retry each subsequent
internal joint. Record each attempt's joint index, entry walk and failure
reason, plus `entry_walked` for the selected joint. If all attempts fail,
use s=`root_depth` and preserve the final reason in `gap_reason` and the pivot
reason (`gap ceiling not found` for a missing ceiling).
The line through F and K defines the chord; the side containing the
projection of the declared `anchor_bone` head is inward, with positive signed
distance d. Front is -Y and up is +Z. Along u=normalize((0,1,1)), choose the
smallest s >= `root_depth` for which d(A+s*u) >= `root_wall_margin`, solving
the linear distance in closed form. Cap s at the distance from A to the anchor
target (anchor head plus `anchor_offset`) and record whether it was capped.
If F or K is missing, or the direction is parallel to the chord
(absolute distance derivative < 1e-9), use s=`root_depth` and record the reason.
The anchor-distance cap applies after every solve or fallback branch, including
the fallback depth; it preserves the reason and sets `capped` when needed.
Set `joints[0]` to A+s*u. The leak path retains its existing placement.
Internal joints, tip, axis length, membership and growth use the original
unmoved polyline. `weight_joints` also keeps that polyline for both paths,
including the original `root_station` without growth; weights and contact
followers therefore do not change when the pivot moves. The grown weight
ramp stays anchored on its measured stop plane. Internal
joints sample welded part vertices in slabs of total
width `centerline_slab * length` around each declared axial fraction, where this
length is the attachment-to-far-slice extent projected onto the refined axis
for successful growth, or the existing root-to-far-slice extent otherwise. Their
cross-section centroids retain the axial station, and the tip is the far-slice centre. Bones follow this
polyline. Each vertex uses its nearest polyline segment to interpolate axial
`chain_split` coordinates. Linear blends span `split ± link_blend`; outside
these zones a vertex belongs to one link. The attachment `weight_ramp` acts only
over `0 <= t < weight_ramp` of the centreline, on link 1 only, shortened to at
most `attachment_ring_max` metres. With successful growth its distance is the
axial projection from the measured stop plane; otherwise it uses physical
polyline distance from the unmoved root. Metric `attachment` records the
measured stop station (the contact-follow distance reference; without growth the
fitted base), `root_offset` records `joints[0]-A` in metres, where A is the unmoved root. Per-group `pivot` records F, K,
`gap_exit` E, `gap_ceiling` H, the successful `joint_index`, solved
`depth`, signed `margin` at the moved head, `capped` and the fallback `reason`
(empty on a normal solve; missing chord distance is null).
`weight_ramp + link_blend` must
be strictly less than the first split (or 1 for a single link), and internal
blend zones must not overlap. Each link must have core vertices (weight > 0.9);
metrics report `core_verts_per_link` and `bind_bend_deg` at every internal joint.
An attachment ring obeys the same bounds, with a `1e-6` tolerance in normalized
axial distance at the attachment plane for float roundtrips. After placement,
the measured tube radius bounds distance to the measured slice-centroid polyline
over the full part, rather than to the coarser bone polyline. The full connected
surface inside this tube is recovered, including the contact side omitted by
protrusion candidates. Original-axis bounds preserve the attachment stop, and
negative slices additionally retain their tracked centroid radius bounds.
The centroid line extends to both declared axial endpoints, so end rings do not
lose radial clearance through clamped endpoint distance.
Only the connected component supported by the detected tip remains. All retained surface
vertices outside the physical attachment ring initially have total chain weight 1;
the optional inside contact ramp below can attenuate the seam.
`link_blend` divides that total between neighbouring links without reducing it.
`contact_ramp` remains required and validated but no longer attenuates a retained
tube surface. Connectivity and hard tube membership separate adjacent surfaces;
no radial fade is applied inside the tube. All captured vertices remain part of
the transfer region even at zero extension
weight. Only a bounded component smaller than `segment_min_vertices` or beyond
`leak_t_limit` uses front-only fallback; metrics retain `leak` and `leak_reason`.
Declared `reweight_from` base joints (`[]` to disable transfer) move their entire
weight to the chain's declared parent on every captured vertex, including fallback.
Outside the captured part, optional contact following spreads the motion across
adjacent body surfaces without changing mesh topology. A contact face shares a retained
tube vertex (total chain weight >= 0.9) outside `attachment_ring_max` with a
non-tube vertex. Its eligible non-tube vertices form the d=0 boundary.
An eligible non-tube copy coincident with an outside full tube vertex also
seeds at d=0, even when no face spans the copies. This uses a fixed 0.00001 m
position tolerance, independent of pack parameters and segmentation normals.
A multi-source shortest edge-path search extends up to `contact_follow_distance`
metres; propagation uses source edges, without face diagonals. The chain weight is
`contact_follow_weight * smoothstep(1 - d / contact_follow_distance)`; zero
weight disables following. Link shares come from the nearest full-weight tube
vertex, so internal link blends remain aligned. Ring-zone points and points
above the original-axis growth stop are hard exclusions and cannot bridge paths.
All followers also require nearest-tube-vertex distance <= the declared distance.
Points with original weight > 0.5 on `reweight_from` qualify only within this
contact edge-path zone; distant source-joint surfaces keep chain weight zero.
Original bones are preserved in descending weight order in the remaining slots
of the four-influence budget, normalized to the exact remainder `1 - w`.
Overlapping groups preserve their combined extension total; the largest
extension shares occupy at most three slots when an original remainder exists,
or four when the combined extension weight is one. Retained extension shares
are proportionally normalized to that total.
Follow vertices never undergo the captured-part source-to-parent transfer.
`contact_inside_distance` is required, nonnegative and measured in metres. Zero
disables the inside ramp and preserves the existing weights exactly. After
following is calculated, contact-face tube vertices with total weight >= 0.9
and attachment distance greater than `attachment_ring_max` seed a shortest
edge-path ramp into the full tube. Coincident copies within `weld_distance`
share distance and boundary value, so UV seams do not interrupt propagation.
Seeds stay outside the attachment ring. Propagation includes all full tube
vertices (total >= 0.9), including those inside the ring distance; partial ring
vertices (total < 0.9) are never scaled. Each seed takes the maximum follower
value of its contact faces' outside vertices; a seam
with only ineligible outside vertices takes zero. Nearest-seed distance `d`
and boundary value `b` give the multiplier
`b + (1 - b) * smoothstep(d / contact_inside_distance)` up to the declared
distance. Equal shortest paths prefer the lowest seed index. Per-link shares,
followers, captured membership, placement, pivot and attachment stay unchanged.
The remainder follows the existing original-group normalization and
source-to-parent transfer. Ramped vertices use the same four-influence packing
as followers, preserving the chain total and link shares while fitting the
original remainder into the available slots. A link without a core vertex
fails normally; the declared distance is never shortened automatically. With no
contact faces the inside ramp leaves the tube plan untouched; the final copy
unification rule below still applies. `contact_inside_ramped` counts original tube
vertices whose weights were scaled, including coincident copies;
`contact_inside_weight_min` reports their minimum exported total chain weight
(or 1 when none were scaled). `contact_faces_outside_ring`,
`contact_tissue_vertices_weighted`, `contact_follow_weight_max` and
`contact_follow_weight_mean` report the boundary and actual exported weights.
After source-to-parent transfer, follower handling and the final four-influence
pass, coincident copies always share exported weights. Otherwise a weight split
across a crease tears the mesh open under motion. Within the same fixed
0.00001 m tolerance, connected groups with differing exported weight dictionaries
receive their average, reduced to the four largest weights (ties prefer the
lower exported joint index), then normalized and written to every copy.
Already-agreeing groups are untouched. This can turn an open seam into local
stretch under motion; counts and posed metrics use the unified exported values.
This final rule also applies when contact following or the inside ramp is disabled.
Final averaging can restore body/source weights from a non-tube copy onto its
captured tube copy, or make that tube copy partial outside the attachment ring.
The source-transfer and full-tube rules above hold before this final averaging;
final defect counters can therefore be nonzero on deliberately unified copies.
Each `appendage_chain` reports `coincident_groups_unified`: the global number
of positional groups changed in this export, repeated for each chain group.
Groups with zero chain weight also count; it is not a per-link or per-copy count.
The opt-in real smoke compares max and p99 stretch over the same complete
contact neighbourhood at 70 degrees, checks topology and tube weights, and
reports `far_chain_weight_max` (must be zero) and `above_stop_weighted`.
Metrics `base_extension_t` (negative original-axis fraction), `base_stop_reason`,
`stem_vertices_captured` (original vertices, including seams), and
`base_slice_table` describe growth. Each row reports `t`, welded `count`,
`p95_radius` in metres, `tube_radius`, `tube_centre`, `accepted`, and, for an
accepted slice, `accepted_count` and its tracked `centre`. A rejected row is
included for diagnosis. `captured_outside_base_tube` must be zero;
`captured_beyond_radius` diagnoses the original straight segmentation beyond
`cut`; a curved measured tube can leave that cylinder. The actual tube bound
is checked by `captured_beyond_tube_radius`, which must be zero.
`partial_weight_vertices` counts tube chain weights in (0.1,0.9), while
`partial_outside_attachment_ring` also counts tube vertices only and is expected
to be zero before final coincident-copy unification.
Intentionally inside-ramped vertices are excluded from this defect counter
and from `uncaptured_in_part`; `partial_weight_vertices` still includes them.
`tube_radius` and
`captured_tube_distance_max` report metres of nearest-centroid-polyline distance;
`tube_centerline` records those measured slice centres in world-space metres.
`captured_beyond_tube_radius` must be zero. `weighted_outside_part` (excluding
declared contact followers) is expected to be zero before final copy unification.
`uncaptured_in_part` checks retained connected surface vertices outside the
attachment ring; a point merely inside the old straight cylinder is not assumed
to belong to the part.
Fingerprint version 12 rebuilds from prerig for coincident contact seeds and
shared exported copy weights. `link_blend` replaces the old
2-link `blend_start`/`blend_width` parameters; remove those from declarations.
The existing required declaration
fields `leak_radius_limit` and `reweight_factor` remain validated but no longer
control radius rejection or transfer: bounded segmentation and entire source-weight
transfer supersede those rules. All segmentation and refinement parameters are required. `chain_split` contains N-1 increasing
fractions. `chain_split` is required even for a single link (`[]`). Test pose measurements are reset before export.

`appendage_chain` declaration example values:

| Parameter | Example declaration value |
|---|---|
| `anchor_bone` | `"Hips"` |
| `anchor_offset` | `[0, 0, -0.09]` |
| `search_z_min` | `-0.26` |
| `search_z_max` | `0.06` |
| `reference_lateral_min` | `0.09` |
| `reference_lateral_max` | `0.13` |
| `slice_size` | `0.01` |
| `candidate_lateral_max` | `0.1` |
| `part_half_width` | `0.06` |
| `protrusion_threshold` | `0.035` |
| `axis_initial` | `[0, -0.5, -1]` |
| `axis_iterations` | `50` |
| `root_depth` | `0.03` |
| `root_wall_margin` | `0.01` |
| `chain_split` | `[0.33, 0.66]` (three links) |
| `cut` | `0.15` |
| `weld_distance` | `0.0005` |
| `weld_normal_min` | `0.5` (normal dot product, in [-1,1]) |
| `window_length_factor` | `0.6` |
| `window_margin` | `0.08` |
| `leak_t_limit` | `1.6` |
| `leak_radius_limit` | `0.09` (superseded by bounded segmentation) |
| `segment_radius_factor` | `1.35` |
| `segment_radius_percentile` | `0.95` (strictly between 0 and 1) |
| `segment_radius_margin` | `1.2` (positive) |
| `segment_radius_growth_max` | `1.5` (positive, relative to preceding radius) |
| `segment_passes` | `3` (positive integer; refinement passes after pass 0) |
| `segment_min_vertices` | `3` (positive integer, welded vertices) |
| `base_slice_size` | `0.01` (positive, metres) |
| `base_radius_margin` | `1.8` (at least 1, relative to measured part cross-section) |
| `base_growth_max` | `1.8` (greater than 1, connected count or radial growth ratio) |
| `base_extension_max` | `0.35` (positive fraction of original detected length) |
| `base_history_slices` | `5` (positive integer, running median window) |
| `attachment_ring_max` | `0.01` (positive, metres; limits the attachment transition) |
| `contact_follow_distance` | `0.025` (positive, metres, shortest source edge path) |
| `contact_inside_distance` | `0.02` (nonnegative, metres, shortest tube edge path; `0` disables) |
| `contact_follow_weight` | `0.6` (in [0,1); `0` disables) |
| `contact_ramp` | `0.01` (validated, superseded by tube membership) |
| `ring_radius_percentile` | `0.9` |
| `ring_radius_scale` | `1.15` |
| `near_slice_margin` | `0.05` |
| `far_slice_fraction` | `0.85` |
| `attachment_inset` | `0.02` |
| `weight_ramp` | `0.25` |
| `fallback_half_width` | `0.075` |
| `fallback_z_margin` | `0.04` |
| `fallback_front_fraction` | `0.3` |
| `fallback_front_ramp` | `0.02` |
| `fallback_side_ramp` | `0.025` |
| `fallback_top_margin` | `0.02` |
| `fallback_top_ramp` | `0.03` |
| `centerline_slab` | `0.08` (total slab width as axial-length fraction) |
| `link_blend` | `0.06` (half-width in centreline fraction) |
| `reweight_factor` | `2.0` (superseded by full transfer) |
| `reweight_from` | `[]` |
| `weight_min` | `0.003` |
| `test_rotation_deg` | `[-35, 0, 0]` |
| `test_rotation_decay` | `0.4` |
| `test_scale` | `[1, 1, 1]` |

### State-Flags

Der zentrale Flag-Lifecycle-Executor (`app/core/flag_lifecycle.py`) rendert für
gesetzte Flags die `prompt_when_set`-Zeile in den Situationskontext des Charakters
(Platzhalter `{name}`, `{clear_tool}`) und beendet Flags automatisch per
`ttl_minutes` bzw. `reset_on_location_change` — der Auto-Clear ruft das
`cleared_by`-Verb auf, damit exakt dieselben Seiteneffekte laufen wie beim
LLM-Tool-Call. Ein `ttl_minutes`-Feld im `config_schema` des Pakets
(`skills.<paket>.ttl_minutes`) überschreibt den Manifest-Default zur Laufzeit.

## Skill-Klasse

```python
from typing import Any, Dict
from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext


class MeinSkill(PluginSkill):
    SKILL_ID = "mein_paket"

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description kommen aus templates/llm/skills/mein_paket.md
        self.api_url = ctx.get_config("skills.mein_paket.url", "http://localhost:9000")
        self._defaults = {"max_results": 5}   # per-Character konfigurierbar

    def execute(self, raw_input: str) -> str:
        data = self._parse_base_input(raw_input)
        query = data.get("input", raw_input).strip()
        cfg = self._get_effective_config(data.get("agent_name", ""))
        try:
            resp = self.ctx.http.get(f"{self.api_url}/api", params={"q": query}, timeout=10)
            resp.raise_for_status()
            return resp.json().get("result", "")
        except Exception as e:
            self.ctx.logger.error("request failed: %s", e)
            return f"Error: {e}"
```

Parametrisierte Verben: definiert der Manifest-Eintrag `params`, bekommt der
Konstruktor sie als Kwargs (`def __init__(self, config, ctx, active: bool)`) — eine
Klasse, mehrere Verben (Muster: `plugins/decency_exempt`, `plugins/sleep`,
`plugins/party`, `plugins/wet`).

### Per-Character-Config (`get_config_fields`)

`_defaults` legt die per-Character speicherbaren Schlüssel fest; die Felder
selbst rendert der Skills-Tab (Characters → Skills) **generisch** aus
`get_config_fields()`. Ohne Überschreibung leitet `BaseSkill` Typ und Label aus
den `_defaults`-Werten ab; wer Label, Hilfetext oder einen der beiden
Nicht-Skalar-Typen will, überschreibt die Methode.

| `type` | Eingabe im Skills-Tab | Wert |
|---|---|---|
| `bool` | Checkbox | `true`/`false` |
| `int` / `float` | Zahlenfeld | Zahl |
| `str` | Textfeld | String |
| `locations` | Liste aller Locations mit Checkboxen | Liste von Location-IDs |
| `choice` | Dropdown, gefüllt vom Server | String (leer = Standard) |

Optional bei jedem Feld: `"label"` (Überschrift) und `"description"`
(Hilfetext unter der Eingabe). Beide sind **englisch** und laufen im Frontend
durch `t()`; die Übersetzung gehört nach `shared/languages/<lang>.json`.

Ein `choice`-Feld nennt seine Optionen nicht selbst, sondern **eine Quelle**
(Beispiel — kein mitgelieferter Skill deklariert derzeit ein `choice`-Feld; das
letzte, `animate_service` des Video-Skills, ist mit dem Bild-Routing entfallen.
Die Maschinerie prüft `scripts/smoke_skill_choice_fields.py` mit einem
Probe-Skill):

```python
def get_config_fields(self):
    return {
        "preview_backend": {
            "type": "choice",
            "options_source": "image_backends",
            "default": "",
            "label": "Preview backend",
            "description": "Image backend for the preview. Empty = the world default.",
        },
    }
```

`GET /characters/{name}/skills/available` liefert die Optionen aller
vorkommenden Quellen einmal pro Aufruf mit, als
`option_sources: {"<quelle>": [{"value", "label"}, …]}`. Bekannte Quellen
(`character_ops.skill_option_source` — die EINZIGE Stelle, die Namen auf
Listen abbildet):

| `options_source` | Optionen |
|---|---|
| `image_backends` | aktivierte und gerade verfügbare Backends mit `MEDIA_TYPE == "image"`, günstigstes zuerst |
| `video_backends` | dieselbe Regel für `MEDIA_TYPE == "video"` |

Regeln, die für jedes `choice`-Feld gelten und die das Frontend generisch
umsetzt: die **leere** Option bedeutet „Welt-Standard"; ein gespeicherter
Wert, den die Quelle nicht mehr anbietet (entferntes oder offline gegangenes
Backend), bleibt wählbar und wird als `(unavailable)` markiert — der Server
setzt dafür `value_unavailable: true` am Feld. Die Quellen lesen nur
In-Memory-Zustand: der Skills-Tab lädt sie bei jedem Öffnen, ein Probe-Aufruf
gegen ein totes Backend würde die Seite blockieren.

Optionale Überschreibungen aus `BaseSkill`, die der Core generisch abfragt:
`visible_for(character_name)`, `defer_for_attachment(raw_input)`,
`thought_context_block(character_name)`, `handle_intent(intent_type, payload)`,
`tool_intent_payload(raw_input)`, `get_usage_instructions(format_name, character_name)`.
Details in `docs/skill-core-api.md` → „Skill-Hooks".

## PluginContext API

| Attribut/Methode | Beschreibung |
|---|---|
| `ctx.logger` | Logger mit Prefix `plugin.<paket>` |
| `ctx.http` | das `requests`-Modul für externe API-Aufrufe |
| `ctx.plugin_id` | Paket-ID (Ordnername) |
| `ctx.get_config(path, default)` | **Bevorzugt:** Welt-Config per Dot-Pfad (`skills.<paket>.<feld>`) |
| `ctx.get_env / get_env_int / get_env_bool` | Nur Altbestand (Env-Bridge, siehe `docs/config-defaults.md`) |

Der Context ist bewusst schmal. Alles Fachliche holt sich ein Paket direkt aus
`app.core` / `app.models` — die erlaubte Auswahl steht in `docs/skill-core-api.md`.

## Aktivierung

**Global (pro Welt).** Das Lade-Gate eines Pakets für seine Verben OHNE
`always_load`, in dieser Reihenfolge:

1. `skills.<paket-id>.enabled` in der Welt-Config (das Paket liefert das Feld über
   sein `config_schema`; Admin-Settings → Skills),
2. die Env-Bridge `<env_prefix>ENABLED` (Default-Präfix `SKILL_<ID>_`) — Altbestand,
3. `enabled_default` aus dem Manifest, sonst `false`.

Verben mit `always_load` ignorieren das Gate komplett; ein Paket darf beides mischen
(instagram: die Reaktions-Verben immer, das Posting-Verb per Gate).

**Per Character.** Skills-Tab im Game-Admin, gespeichert als
`<storage>/characters/<name>/skills/<SKILL_ID>.json` mit `{"enabled": true}`. Die
Datei wird pro Turn frisch gelesen — kein Server-Restart nötig. Die `_defaults` der
Klasse definieren, welche weiteren Felder pro Charakter überschreibbar sind
(`_get_effective_config`).

## Marketplace-Installation

Der Content-Marketplace kennt den Pack-Typ `skill_package`
(`app/core/skill_package_io.py`). Ein Paket-ZIP (`plugin.yaml` an der Wurzel bzw.
genau ein Paketordner) wird nach `plugins/installed/<id>/` entpackt, danach
`discover_packages(force=True)` + `reload_skills()`.

Anders als Content-Packs enthält ein Skill-Paket **ausführbaren Code**. Deshalb:
Admin-Rolle (der ganze Router hängt an `require_admin`) **und** eine explizite
In-App-Trust-Bestätigung — der Request muss `confirm_code=true` im Body tragen, sonst
antwortet die Route mit **428**. Absolute Pfade und `..` im Archiv werden abgelehnt.
Deinstallation = Ordner löschen + Reload (R7).

`plugins/installed/` ist komplett gitignored, damit Repo-Inhalt und installierter
Inhalt nie kollidieren. NSFW- und andere private Pakete werden ausschließlich so
verteilt — nie in diesem SFW-Repo.

Veröffentlichen: ein fertiges Paket-ZIP geht mit
`./.venv/bin/python scripts/marketplace_publish.py [--instance <dir>] --world worlds/<welt> --catalog "<Katalog>"
--type skill_package --zip <paket>.zip --name "<Name>" [--thumb <bild>]` in den Katalog
(Katalog-URL und Token sind Instanz-Config; `--instance` ist per Default `<repo>/instance`) — als
Release-Asset des Katalog-Repos (`packs-skill_package`), dieselbe Ablage wie der Publish-Button
(`app/core/marketplace_store.py`). Private Pakete gehören in einen privaten Forgejo-Katalog.

## Pakete im Repo

| Paket | Skill-IDs | Beschreibung |
|---|---|---|
| `act` | `act` | Konkrete Handlung in der Szene, vom Storyteller-LLM erzählt (Verb über die Core-Act-Engine) |
| `cat` | — | Spezies Katze — Body-Slots, minimale Kleidungs-Topologie, eigene Silhouette (`conflicts: [human]`) |
| `consume_item` | `consume_item` | Gegenstand aus dem eigenen Inventar konsumieren (Effekte, Conditions) |
| `decency_exempt` | `allow_exposed`, `require_decency` | Kleiderordnungs-Ausnahme — AllowExposed/RequireDecency, bewusst persistenter Zustand |
| `human` | — | Spezies Mensch — Body-Slots, Kleidungs-Slot-Topologie, UI-Silhouette |
| `instagram` | `instagram`, `instagram_comment`, `instagram_reply` | Posting-Verb, Reaktions-Verben, Social-Reaktionen, Pending-Posts-Block im Thought-Prompt |
| `interact` | `interact` | Paar-Interaktion — zwei anwesende Charaktere spielen einen Paar-Clip an einem Anker (`on_load` registriert `pair_verb_name`) |
| `knowledge` | `knowledge_extract`, `knowledge_search` | Wissens-Extraktion aus Dateien (LLM) und Suche über die extrahierten Memories |
| `markdown_writer` | `markdown_writer` | Charaktere schreiben Markdown-Dateien (Tagebuch, Notizen) in ihr eigenes Verzeichnis |
| `movement` | `setlocation`, `go_to_character`, `cancel_travel` | Strukturierte Bewegung — benannte Orte, getaktete Reisen, Ziel-Auflösung über Personen |
| `n8n` | `n8n` | Ruft n8n-Workflows per Webhook und gibt die JSON-Antwort an das LLM zurück |
| `notify_user` | `notify_user` | SendNotification — der Charakter schickt dem aktiven Avatar proaktiv eine Systemnachricht |
| `party` | `invite_to_party`, `join_party`, `leave_party` | Gemeinsames Reisen — Leader bewegt, Follower werden mitgezogen |
| `retrospect` | `retrospect` | Reflexion — verdichtet Erlebtes zu Beliefs/Lessons/Goals in den Soul-Dateien |
| `romantic_interests` | — | Freitext-Feld für romantische/sexuelle Interessen (Beziehungs-Core) |
| `rp` | — | Rollenspiel-Paket — RP-Regeln und die RP-Status-Stats |
| `searx` | `searx` | Websuche über eine selbst gehostete SearX-Instanz |
| `send_message` | `send_message` | Textnachricht an einen NICHT anwesenden Charakter (optional mit Bildanhang aus demselben Turn) |
| `set_pose` | `set_pose` | Setzt die aktuelle Pose (Katalog-Key + Anzeige-Detail) |
| `sleep` | `sleep`, `wakeup` | Schlaf-Flag setzen und den Charakter währenddessen von der Karte nehmen |
| `take_photo` | `image_generation` | Der Charakter macht ein Foto / erzeugt ein Bild (Verb über den Core-Bild-Service) |
| `talk_to` | `talk_to` | Dialog von Angesicht zu Angesicht, in Hörweite |
| `undress` | `undress`, `get_dressed` | Aus-/Anziehen für Freitext-Garderoben |
| `wet` | `enter_water`, `dry_off` | Nässe-Zustand — Schwimm-Ausnahme solange nass, Auto-Trocknung per TTL |

Drei weitere Ordner unter `plugins/` sind **Symlinks in ein privates Repo** und
gehören nicht zu diesem SFW-Repo; ohne dieses Repo existieren sie schlicht nicht.

## Best Practices

- **Abhängigkeits-Richtung:** Pakete dürfen Core-Engines importieren und rufen
  (`app.models`/`app.core` — Compliance, Stats, Pathfinder); das Core referenziert
  niemals ein Paket (R1). Externe Services (HTTP, Env, Config) über `self.ctx`.
- **Nur öffentliche Core-Funktionen rufen** — kein `_privater_name` aus einem
  Core-Modul. Was ein Paket braucht, gehört als benannte Funktion nach
  `docs/skill-core-api.md`.
- **Lebenszyklus vollständig deklarieren** — wer ein Flag setzt, deklariert Löser,
  Prompt-Sichtbarkeit und Zerfall (R3).
- **`_defaults` definieren** — für Per-Character-Config und `get_config_fields()`.
- **Profil-Schreiber sperren** — jedes Read-Modify-Write auf einem Profil läuft unter
  `keyed_lock("character_profile", name)`, in der dokumentierten Lock-Reihenfolge
  (`docs/skill-core-api.md` → „Sperren").
- **Lösch-Test** — Paketordner entfernen ⇒ Feature weg, Server startet ohne Reste,
  nichts anderes bricht (R7). Das ist die Definition von „fertig".

Exported meshes use at most four deform influences per vertex across the entire
mesh. Keep the four largest weights, breaking ties by skin joint index, then
renormalize. Counts and posed edge-stretch metrics describe that final
representation, matching the browser's `JOINTS_0`/`WEIGHTS_0` consumption.

### Extension motion layers (P3)

Package body-slot `rigs` declarations remain the base physics values.
Declared `length` defaults to 1 in [0.5,3]; declared `girth` defaults to 1 in
[0.5,2]. Both layer package → world → character, multiply state pose factors,
and clamp effective values to [0.25,4]. `scale_axis` is declaration-only,
`centroid` (default) or `bone`; it is copied to runtime payload groups and cannot
be overridden as motion. A leaf using `bone` scales length along bind-frame +Y
and girth perpendicular to it. Other leaves use their weighted centroid;
links with a successor keep the axis toward that joint. Core declares
`extension_motion.groups` as a **world** setting: arbitrary package group IDs map
to partial overrides of `length`, `girth`, `freq_hz`, `zeta`, `gravity`, `spill`, `flatten`, `stretch`, `spread`, `flatten_floor`, `translate`, `gain`,
`max_deg`, `sag_max_deg`, `spill_max_deg`, `head_sag`, `axis_gain`, `squash`, `rest_max_deg`, `straighten_deg` and `freetext_clothing_gain`. Missing values inherit the package; no group IDs are named in core.
Game-Admin → Setup → Extension motion lists loaded declarations from the admin-only
`GET /admin/world-settings/extension-motion` endpoint and saves through the existing
world-settings endpoint. Reset removes the override so future package defaults flow through.

Effective order: package → world override → slot attribute-profile multipliers →
absolute character overrides → bounce/weight → clothing gain → state bone pose. The character
3D panel's Extension bones box shows Bounce/Weight sliders and Advanced numeric physics and Reset removes that
character's group override. It sends `{extension_motion: {group_id: {field: value}}}`
to admin-only `POST /characters/{name}/model3d/extension-motion`; profile storage
is `model3d_opts.extension_motion`, validated and saved under
`keyed_lock("character_profile", name)`. Raw fields and ranges match world overrides; Bounce/Weight are character-only.
The existing mesh-option route is independent.

After character overrides, every distinct worn item whose occupied slots or `outfit_piece.covers` hit
the body slot's `covered_by` contributes its `motion_damping` (0..1, default 1)
to the gain product. Mirrored occupied slots count once; hidden layers still count.
A partial cover contributes `1 - (1 - motion_damping)/2`; full coverage takes
precedence for the same item. Without any resolved outfit pieces, non-empty `outfit_description` or `outfit_worn`
contributes the group's `freetext_clothing_gain` (0..1, default 1). Empty or whitespace-only
text contributes 1; worn pieces take precedence. `apply_clothing=False` bypasses both factors.
The shared character template's `motion_gravity_scale` (0..3, default 1) is transported separately as group `gravity_scale=m`:
`a_g=gravity*(m*g-R_anchor*g_rest)`. Thus upright m=1 gives zero, m=2 adds sag,
and m=.5 lifts. Static equilibrium `e=a_g/omega²` (after removing inward axial force) is bounded
by `sag_max_deg` (default: declared `max_deg`); flatten supplies the direct length target. The spring has no gravity
term and swings around `T'=T+e`; its dynamic limit is `max_deg`, independent of sag.
The dynamic angle stays linear below half the limit, then smoothly saturates with
tanh; gain scales the saturated displacement, preserving static sag even at zero.
`axis_gain: [lateral, vertical, longitudinal]` defaults to `[1,1,1]`; each
entry must be a finite number in [0,1] (booleans are rejected). It is supported
only in package physics, world overrides and absolute character overrides, never
in `attribute_profiles` multipliers or state `bone_pose`. Both editors expose
all three gains. Static sag, flatten, spill and rest pose are unaffected.
At each step decompose only `d=p-T'`: longitudinal along `u=unit(T'-head)`,
vertical along projected bind-pose body up rotated with the anchor, and lateral
as the remainder. For a vertical lever use projected bind body front instead;
if bind geometry cannot define front, bind world +Z is the deterministic fallback.
Filter the three components before the existing soft dynamic angle and gain.
Only the filtered longitudinal component changes dynamic length; transverse
motion rotates the static lever without stretching it. Final squash limits
and volume compensation still apply.

These settings change `motion.rev`, never the extension rig fingerprint or mesh.


### State bone pose and neutral mesh inputs (P4)

The Setup motion editor, character overrides and state pose editor share preview hints:
`live` covers `rest_deg`, `rest_max_deg`, state `length` and `girth` (visible immediately); `motion` covers
`freq_hz` (`freq` in state poses), `zeta`, `gain`, `axis_gain`, `max_deg` and `bounce` (play a clip);
`tilt` covers `weight`, `gravity`, `head_sag`, `spill_max_deg`, `sag_max_deg`, `flatten`, `stretch`, `spread`, `flatten_floor`, `spill`, `translate` and `squash` (use Tilt,
since the upright rest shape already carries gravity). Character `motion_gravity_scale`
is visible upright when different from 1; otherwise use Tilt. Group enabled/flip and
mesh-operation parameters are `rebuild`: they take effect after Rebuild extension bones.

States in `prompt_filters` may carry `bone_pose`, a JSON mapping from loaded
rig group IDs to sparse values. Game-Admin → States lists the declared groups
from the same extension-motion endpoint. For example:

```json
{"bone_pose":{"example_group":{"rest_deg":24,"gravity":0.5,"freq":0.8,"flatten":2,"spill":0}}}
```

`rest_deg` is an absolute signed angle in degrees in `[-180,180]`, independent
of package defaults. Runtime clamps it to ± the effective `rest_max_deg`
(package → world → attribute profile → character override).
Front is derived generically from the bind pose: take the horizontal component
of (mean chain-root head minus mean declared-parent joint head). If that vector
is meaningfully zero, use the horizontal component of (mean target centroid
minus mean chain-root head). Up is bind-pose world/model up. Only for groups
with exactly one root, inspect the root parent's direct Bone children, excluding
the root and every Bone declared in any extension group of the payload. Choose
the pair with the widest horizontal separation. Use it only when its separation
is greater than 1e-4 bind world units and at least 0.25 times the largest
horizontal distance from the parent head to any candidate head. Set front to
normalize(up cross normalize(horizontal(head_a - head_b))), choosing its sign
to have a positive dot product with the original front. If the absolute dot
product is below 1e-6, or no pair qualifies, retain the original front. The root
may sit off the midline, so this pair supplies front independently of its lateral
offset. Paired and multi-root groups retain the original front. All group front
consumers use this corrected direction. For groups with exactly one root, define
the body lateral axis X as
normalize(front cross up), signed to match the existing lever cross projected
front for a sagittal lever. The root lever L points to the child head, or to
its weighted centroid when there is no child. Project L into the sagittal
plane: L_s = L - dot(L, X) X. Let C rotate unit(L) onto unit(L_s), or be
identity when L_s is effectively zero. Store X and C in the root bone-local
frame using the inverse bind world rotation. Each frame uses
restQ = R(X_local, rest) * slerp(identity, C_local, f), where f is the root's
existing blended smoothstep straightening fraction (zero when straighten_deg
is zero). Centering acts first: rest zero preserves the natural hanging lean;
straightening fades that lean proportionally, while disabled straightening
preserves its lateral component through the raise. Paired and multi-root
groups retain their existing per-root axis: project front perpendicular to
the lever u, then normalize(u cross projected_front); use up for a lever
parallel to front. Store that axis in the root anchor frame.
The rest angle rotates the chain at its ROOT link. Children inherit that
rotation; optional `straighten_deg` removes their relative bind bends as
described below. With its default 0, the chain rotates rigidly. Compute T' and static sag around
this rotated rest. max_deg and soft saturation limit ONLY dynamic deviation
from T'; rest is limited only by the effective rest_max_deg. Paired groups
rotate each chain root about its own derived axis. Negative angles move in the
opposite direction. Changes blend over 1.5 real seconds with smoothstep.
`gravity`, `freq`, `zeta`, `gain`, `flatten` and `spill` are finite, nonnegative
multipliers; `freq` multiplies `freq_hz`, not its square. Values may exceed 1.
Gain/flatten/spill results clamp to [0,1] after all active states. Missing keys
leave values unchanged; explicit zero is retained. Multiple active states use
the maximum present rest angle and the product of each multiplier. Group IDs
from absent packages remain serializable and are ignored by motion resolution.

The enabled/tag/evaluated-expression rule is identical to image modifiers.
Tag and expression transitions, including tag expiry, change `motion.rev`;
the 3D clients smoothly blend the rest angle and scalar fields over 1.5 real
seconds. Frequency zero disables the spring and its static equilibrium offset;
particle propagation remains finite. States never change the mesh fingerprint,
`model_sig` or `model_rev`. State values apply after clothing gain.

World saves, moves between shared and world storage, and states ZIP
export/import preserve `bone_pose`. Marketplace `states` installation and
plugin `on_load` code using `content_io.import_states_from_zip` use the same
validated import path; there is no separate state field whitelist for plugins.

All T-pose views and animal mesh-input renders use neutral outfit signatures
and `apply_state_modifiers=False`. Generation, uploads, finished-job retrieval,
Improvements and model selection reject retired `<sig>-s<fp>` forks. Cache GC
removes these files and their tiers, textures, raw and prerig derivatives.
A character whose only mesh is such a fork has no usable model until a neutral
model is available. Ordinary pose references use `<sig>-p<fp>` state identity;
expressions retain their existing state fingerprint. Their image modifiers,
as well as chat/profile/gallery image modifiers, continue to apply.


### Extension motion calibration: spill, static pull and character sliders

`spill_max_deg` is finite in [0,180], defaulting server-side to the group's
`sag_max_deg` when omitted; every resolved payload carries a number. Lying paired
spill is `spill*spill_max_deg*f_in` degrees, independent of the force sag limit.
For sag 5, spill maximum 30, spill .5 and f_in=1, the outward target is 15 degrees.
`head_sag` is finite in [0,1], default 1: **vertical static pull when not upright**.
After force sag limits, let d be the static force displacement and U the anchor's
bind-pose body up in the current world frame. Replace only that displacement by
`d + (head_sag-1)*(d·U)*U`. Flatten and spill are applied subsequently;
front/back and lateral force components, rest pose and dynamics remain unchanged.
Final length rendering preserves this post-limit static target even with squash [1,1].

Per-character `model3d_opts.extension_motion[group]` stores `bounce` and `weight`
next to raw overrides. Both are finite in [.5,1.5], default 1. Resolution order:
package → world → attribute profile → raw character overrides → bounce/weight →
clothing → state. The provisional mapping is a **calibration point**:
bounce b multiplies gain (clamp 1) and max_deg by b, and freq_hz and zeta by
`b^-0.5`; weight w multiplies gravity, sag_max_deg, spill_max_deg, flatten and stretch (both clamp 1)
and translate (clamp 1) by w. Angle limits remain capped at 180 degrees.
For raw gain .6, max 20, frequency 4, zeta .5, gravity 2, sag 5, spill maximum 30,
flatten .5 and translate .6, b=1.25/w=.8 yield .75, 25, 3.577708764,
.4472135955, 1.6, 4, 24, .4 and .48 respectively before clothing/state.
The client consumes these effective numbers without applying the sliders again.

The character Extension bones editor shows Bounce and Weight sliders with
range .5..1.5, step .05 and value labels. Raw fields are under collapsed Advanced;
Save/Revert/Reset retain draft semantics. Bounce uses the motion preview hint;
Weight, spill_max_deg, head_sag, stretch, spread and flatten_floor use Tilt. World overrides expose the raw
fields but do not accept character sliders. Motion changes leave mesh fingerprints
unchanged. Editor defaults precede raw character overrides and sliders.

### Bind-relative calibration and state extent

Setup and character Advanced expose `stretch`, `spread` and `flatten_floor` with Tilt
hints. Attribute profiles may multiply both fields. Weight additionally maps
`stretch -> min(1,stretch*w)` (and `flatten -> min(1,flatten*w)`).
The admin Tilt follows its sliders at at most 120 degrees per real second,
including simultaneous forward/sideways movement.

For anchor turns faster than 360 degrees/s, every spring substep bounds both
the dynamic deviation increment and its magnitude. With static lever length r
and the link's immutable bind share `share_j`,
`B=r*sin(min(pi/2,max_deg*share_j*pi/180))`: increment <= `B*min(1,120*h)`,
magnitude <= B. On a cap hit velocity follows the target; non-finite spring
results reset to the current substep target. The existing soft angular limit
still bounds rendered deviation around the static target. A one-frame 90-degree
jump stays within the whole-chain budget `max_deg*1.05`, with each link limited
by its allocated `max_deg*share_j`; normal motion retains exact propagation.
Gaps, reset and LOD transitions clear anchor history with particle history.

State `bone_pose[group]` additionally accepts optional `length` and `girth`,
each finite in [.5,2], default multiplier 1. Active states multiply these fields
(e.g. length 1.5*.5=.75, girth .8*1.5=1.2), preserving sparse storage and
ZIP import/export. Effective products blend with smoothstep over 1.5 real
seconds, including interrupted transitions and far LOD, like `rest_deg`.
They scale the immutable lever and both perpendicular directions respectively
on top of the static/dynamic deformation; they do not change volume compensation.
State editor hints are `live`. Resolved payloads always include numeric
`stretch`, `spread`, `flatten_floor`, `length` and `girth`; all five affect only motion
revision, leaving mesh fingerprints unchanged.

### Independent rig templates and rest-angle straightening

A slot's `rigs[].templates` optionally selects templates independently of package
`apply_to`: a non-empty name list, `"*"`, or `{feature: humanoid}` uses the same
selector semantics. When present, it replaces the slot/package applicability
for this rig only. `rigs[].applies_to` remains the condition map and still filters
profile fields and stored slot attributes (case-insensitive AND conditions).
Without `rigs[].templates`, existing package and slot applicability remains.
This never activates the owning slot's prompt fragments, attribute editor,
coverage, silhouette or clothing topology on additional templates. Motion
attribute profiles and item coverage are taken only from active slots.
`rigs[].apply_to` is rejected to keep template selectors and conditions unambiguous.

```yaml
rigs:
  - # Add these keys to an existing declaration with id/op/chains/params.
    templates: [example-template]
    applies_to: {gender: [female]}
    straighten_deg: 60
    freetext_clothing_gain: 0.25
```

`straighten_deg` is finite in [0,180], default 0 (off). For each non-root
chain link, reduce the bind relative bend by `smoothstep(clamp(abs(rest_effective)
/ straighten_deg,0,1))`, using the same 1.5-second rest transition. At zero rest,
bends remain unchanged. At or above the threshold every link points along its
parent. With two 20-degree joints, rest 90/threshold 60 leaves 0 degrees; rest
30 leaves 10 degrees per joint; threshold 0 leaves 20 degrees. Negative rest
uses the same absolute fraction. Changing the threshold (including enabling,
disabling and interrupted transitions) blends the derived straightening amount
over 1.5 seconds, so a threshold passing through zero cannot cause a snap. Rest rotation is still root-only; bind front
and pureWorld scale isolation remain unchanged. Paired one-link groups have
no non-root links and are unaffected. Straightening is geometric, independent
of imported bone axes, and uses the next head or terminal weighted centroid.

Both `straighten_deg` and `freetext_clothing_gain` are package physics defaults,
world `extension_motion.groups` overrides and character Advanced overrides
in `model3d_opts.extension_motion`. Both are included in effective motion payloads
and `motion.rev`, excluded from mesh fingerprints and state `bone_pose`. Preview
hints are `live` for straightening and `motion` for free-text clothing gain.
Non-empty free text without resolved item pieces supplies clothing factor k
from `freetext_clothing_gain`; blank text supplies k=1. Item pieces override
this fallback. Temporary NPCs use the same normalize → extension → LOD pipeline,
rebuild route and Improvements batch; the 3D panel shows Extension bones whenever
resolved groups exist, independently of inventory/outfit-system features.

### Rig controls

A rig may declare `controls`, a non-empty list of unique names from
`extension_rig.MOTION_FIELDS` plus `bounce` and `weight`. Omitting it allows
all controls. Invalid names, duplicates and empty lists reject the rig.
This declaration does not affect the mesh fingerprint.

The character toolbar, motion editors and States editor show only declared
controls. Explicit declarations show character motion fields directly;
otherwise they remain under Advanced. State `bone_pose` fields map `freq`
to `freq_hz`, `rest_deg` to `rest_max_deg`, and other names to themselves.
World and character overrides and state saves reject excluded fields for
known groups. Unknown group ids retain their existing validation behavior.
At runtime, excluded stored overrides and state fields are ignored, so a
changed declaration takes effect without rewriting stored data.
