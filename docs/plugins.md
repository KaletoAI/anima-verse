# Skill-Pakete (Plugin-System)

Skills werden als **selbst-enthaltene Pakete** unter `plugins/` entwickelt und geladen —
ohne Änderungen am Hauptcode. Ein Paket bringt alles mit, was sein Skill braucht: die
Verb-Klassen, LLM-Templates, Admin-Config-Schema, Character-Template-Fragmente und
State-Flag-Deklarationen. Regeln und Architektur:
`development_instructions/plan-skill-plugin-architecture.md` (R1–R7).

Der Migrationsstand ist am Dateisystem ablesbar: Was unter `plugins/` liegt, ist
regelkonform paketiert; was noch in `app/skills/*.py` liegt, ist unmigrierter Altbestand.

Die **aufrufbaren Core-Schnittstellen** (Flags, Stats, Compliance, Beziehung, Welt,
LLM, …) sind in `docs/skill-core-api.md` dokumentiert — jede Migration pflegt die
dort genutzten Einträge nach.

## Architektur

```
plugins/                          # Paket-Verzeichnis (Projektroot)
  mein_paket/
    plugin.yaml                   # Manifest (Paketformat v1)
    skill.py                      # Verb-Klasse(n) (erben von PluginSkill)
    templates/
      llm/skills/<skill_id>.md    # Tool-Name + Beschreibung (LLM-Meta)
      llm/sections/...            # optionale Prompt-Sections
      character/<fragment>.json   # Character-Template-Fragmente

app/plugins/                      # Paket-Infrastruktur
  loader.py                       # Discovery, Manifest-Parsing, Laden
  registry.py                     # Aggregierte Beiträge aller Pakete
  context.py                      # PluginContext (Service-API)
  base.py                         # PluginSkill (Basisklasse)
```

**Ladevorgang:**

1. `SkillManager.load_skills()` ruft `load_all_plugins()` auf.
2. `discover_packages()` scannt `plugins/` nach Ordnern mit `plugin.yaml`, parst die
   Manifeste und registriert alle Beiträge in `app/plugins/registry.py`.
3. Beiträge werden verdrahtet: Template-Suchpfad (`prompt_templates`), Character-
   Template-Cache, Admin-Config-Schema (`config_schema.get_schema()`), Default-Skills
   für neue Charaktere, State-Flag-Lebenszyklen.
4. Pro Verb wird die Skill-Klasse importiert und mit `PluginContext` (+ `params`)
   instanziiert; Tool-Name/Beschreibung kommen aus `templates/llm/skills/<skill_id>.md`.
5. Der Skill hängt wie ein Built-in im SkillManager (Per-Character-Config,
   Tool-Formate, `reload_skills()` funktionieren identisch).

## plugin.yaml — Manifest-Referenz (Paketformat v1)

```yaml
name: intimacy
version: "1.0.0"
description: Kurzbeschreibung des Pakets

# Verben — Kurzform (skill_id/module top-level) oder Listenform:
skills:
  - skill_id: start_intimate
    module: skill.py            # Default: skill.py
    class: IntimateSkill        # Default: erste PluginSkill-Subklasse im Modul
    params: {active: true}      # Konstruktor-Kwargs (parametrisierte Verben)
    always_load: true           # immer laden, Aktivierung per Character
    pair_with: end_intimate     # UI-Hinweis: gekoppelter Toggle
    default_enabled: false      # bei neuen Charakteren default-aktiv

templates:
  llm: templates/llm            # wird in den Prompt-Template-Suchpfad aufgenommen
  character:                    # Character-Template-Fragmente (siehe unten)
    - templates/character/lust.json

config_schema:                  # Admin-Settings-Subsections unter "Skills"
  intimacy:
    label: Intimacy
    fields:
      ttl_minutes: {type: int, label: "Auto-end after (min)", default: 120, min: 0}

state_flags:                    # Flag-Lebenszyklen (Flag-Lifecycle-Executor)
  - flag: is_intimate
    cleared_by: end_intimate    # skill_id des lösenden Verbs (Auto-Clear ruft es auf)
    prompt_when_set: "You are in an intimate moment — end it with {clear_tool} when it is over."
    ttl_minutes: 120            # 0 = kein Zeit-Zerfall
    reset_on_location_change: true
```

| Feld | Pflicht | Beschreibung |
|---|---|---|
| `name` | ja | Eindeutiger Paketname |
| `skills` / `skill_id` | nein* | Listenform oder Single-Skill-Kurzform. *Ein Paket ohne Verben („Content-Pack") ist erlaubt, solange es mindestens einen Beitrag liefert (Templates/Fragmente/Config/Flags). Beiträge gelten, sobald das Paket im Dateisystem liegt — das enabled-Gate betrifft nur Verben |
| `skills[].class` | nein | Explizite Klasse (nötig bei mehreren Klassen pro Modul) |
| `skills[].params` | nein | Konstruktor-Kwargs — EINE Klasse kann mehrere Verben bedienen |
| `skills[].always_load` | nein | Immer laden, Aktivierung per Character (auch top-level erlaubt) |
| `skills[].pair_with` | nein | Skill-ID des Partner-Verbs (UI rendert einen gekoppelten Schalter) |
| `skills[].default_enabled` | nein | Neue Charaktere bekommen den Skill aktiviert |
| `templates.llm` | nein | Ordner relativ zum Paket; gleiche Struktur wie `shared/templates/llm/` |
| `templates.character` | nein | Liste von Fragment-JSONs (siehe unten) |
| `config_schema` | nein | Subsections für `/admin/settings → Skills` |
| `state_flags` | nein | Flag-Deklarationen mit Lebenszyklus |
| `env_prefix` | nein | Nur Altbestand (Env-Bridge); neue Pakete nutzen `ctx.get_config` |

### LLM-Templates

`templates/llm/` wird dem Template-Suchpfad hinzugefügt (Haupt-Tree
`shared/templates/llm/` hat Vorrang). `skills/<skill_id>.md` liefert Tool-Name +
Beschreibung im bekannten Format (Frontmatter `name:`, Body = Description) und wird
vom Loader automatisch auf die Skill-Instanz angewandt — die Klasse muss
`name`/`description` nicht selbst setzen.

### Character-Template-Fragmente

Ein Fragment ist ein Extension-Template (gleiche Merge-Semantik wie `base:`-Merges)
plus `apply_to`-Selektor:

```json
{
  "apply_to": ["human-roleplay-nsfw"],
  "sections": [
    {"id": "traits", "fields": [
      {"key": "lust", "label": "Desire", "type": "number",
       "store": "status_effects", "default": 30, "hint": "0-100 ..."}
    ]}
  ]
}
```

`apply_to`: `"*"` (alle Templates) · Liste von Template-Namen · `{"feature": "<flag>"}`
(alle Templates mit diesem Feature). Wird das Paket entfernt, verschwinden seine
Felder aus den Templates — paketeigene Stats gehören damit dem Paket (R2).

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
Klasse, mehrere Verben (Muster wie `_Verb` im skill_manager).

## PluginContext API

| Attribut/Methode | Beschreibung |
|---|---|
| `ctx.logger` | Logger mit Prefix `plugin.{paket}` |
| `ctx.http` | `requests` für externe API-Aufrufe |
| `ctx.plugin_id` | Paket-ID (Ordnername) |
| `ctx.get_config(path, default)` | **Bevorzugt:** Welt-Config per Dot-Pfad (`skills.<paket>.<feld>`) |
| `ctx.get_env / get_env_int / get_env_bool` | Nur Altbestand (Env-Bridge) |

## Aktivierung

- **Global:** `skills.<paket>.enabled` in der Welt-Config (Admin-Settings; das Paket
  liefert das Feld über sein `config_schema`). Pakete mit `always_load`-Verben werden
  immer geladen.
- **Per Character:** Skills-Tab im Game-Admin bzw.
  `.../agents/{agent}/skills/{skill_id}.json` (`enabled`). `_defaults` der Klasse
  definieren die per-Character-Felder.

## Vorhandene Pakete

| Paket | Skill-IDs | Beschreibung |
|---|---|---|
| `plugins/searx/` | `searx` | Web-Suche über selbst gehostete SearX-Instanz |
| `plugins/n8n/` | `n8n` | n8n-Workflows per Webhook, Workflows + API-Key pro Character |
| `plugins/knowledge/` | `knowledge_extract`, `knowledge_search` | Wissens-Extraktion + Suche |

## Best Practices

- **Abhängigkeits-Richtung:** Pakete dürfen Core-Engines importieren und rufen
  (`app.models`/`app.core` — Compliance, Stats, Pathfinder); das Core referenziert
  niemals ein Paket (R1). Externe Services (HTTP, Env, Config) über `self.ctx`.
- **Lebenszyklus vollständig deklarieren** — wer ein Flag setzt, deklariert Löser,
  Prompt-Sichtbarkeit und Zerfall (R3).
- **`_defaults` definieren** — für Per-Character-Config und `get_config_fields()`.
- **Lösch-Test** — Paketordner entfernen ⇒ Server startet ohne Reste (R7).
