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
| `piece_slots` | nein | Kleidungs-Slot-Topologie der Spezies (String oder `{id, label}`); ohne Deklaration gilt der Core-Default (`inventory.VALID_PIECE_SLOTS`) inkl. Core-Reihenfolge/-Labels |

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
| `intents` | `[INTENT: <typ>]`-Marker, die dieses Verb ausführt (F6) — die Klasse implementiert `handle_intent()`; Default = Payload-Durchreichung an `execute()` |
| `intent_payload_keys` | INTENT-Params mit dem vergleichbaren Inhalt (Redundanz-Skip: Marker vs. bereits ausgeführtes Tool im selben Turn) |
| `user_notification` | Tool-Ergebnis wird User-Notification — generisch gelesen via `skill_manager.tool_names_with_flag` |
| `remote_comm` | Verb erreicht NICHT anwesende Charaktere (World-Setup-Checkliste „Kommunikation") |
| `progress_type` | Generischer Fortschritts-Typ (`image`, `search`, `talkto`, …) für zählbasierte Intents/Assignments |

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
| `attributes` | `{name: {type: …, options: …}}`. `interest_aliases` (`{kanonischer_wert: [phrase, …]}`) ist das Attraction-Matching: Phrasen im romantic_interests-Text der GEGENSEITE matchen gegen den Slot-Wert dieses Charakters — der Core hat keine Alias-Tabellen |
| `prompt` | `always` / `covered` / `exposed` (s.o.) |
| `face` | Fragment gehört auch in Portrait-/Ausdrucks-Prompts (`prompt_fragments(face_only=True)`) |
| `back` | Die Anatomie ist auch von HINTEN zu sehen. Rückansicht-Renders — die T-Pose-Back-Referenz der Bild→3D-Kette — behalten nur `exposed`-Fragmente solcher Slots und deren LoRAs; alles andere beschreibt die Vorderseite und zöge die Figur zur Kamera herum. `always`/`covered` sind nicht betroffen: sie beschreiben die ganze Person, nicht eine Seite. Default `false` |

Werte pro Charakter liegen im Profil (`body_slots: {<slot>: {<attr>: <wert>}}`).
Fragmente mit fehlenden Attribut-Werten entfallen komplett (kein halb gerendertes
`{size}`). Die Fragmente gehen auch mit Referenzbild mit (F3).

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

Ein `choice`-Feld nennt seine Optionen nicht selbst, sondern **eine Quelle**:

```python
def get_config_fields(self):
    return {
        "animate_service": {
            "type": "choice",
            "options_source": "video_backends",
            "default": "",
            "label": "Video service",
            "description": "Video backend that animates the still. Empty = the cheapest available one.",
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
