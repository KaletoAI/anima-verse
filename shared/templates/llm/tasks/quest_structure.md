---
task: quest_structure
purpose: Turn a prose quest draft and world context into a structured quest template JSON block (quest_authoring.generate)
placeholders:
  draft: The prose quest draft from quest_draft
  context: Rendered world context (giver, nearby locations, present characters, items, prop library)
  catalog: The registered quest type catalog lines
  role_kinds: Comma-separated allowed role kinds
  giver: Name of the quest giver character, or empty
  avatar: Name of the target avatar, or empty
  mode: Authoring mode ("admin" or "auto")
---
## system
You convert a prose quest draft into a strictly valid quest template JSON object and proposed world bindings.

### Template schema (ONLY these top-level keys are allowed — do not invent fields)
- `title` (string, required): quest title shown to the player
- `summary` (string): short player-facing summary
- `gm_notes` (string): internal author notes (never shown to players, no placeholders needed)
- `giver_role` (string): empty `""` or the `key` of a declared `character` role
- `roles` (list): `[{"key": "<snake_case>", "kind": "<one of {{ role_kinds }}>", "description": "<short description>"}]`
- `steps` (list, at least 1 step):
  `[{"id": "<unique_id>", "text": "<player-facing step text>", "condition": <expr>, "hint": "<optional hint>", "on_done": [<effect>, ...], "role_notes": [{"role": "<character role key>", "text": "<note <= 500 chars>"}]}]`
  `hint`, `on_done`, and `role_notes` are optional. Every step MUST have a non-empty `condition`.
- `start_condition` (object): `<expr>` or `{}` for immediate start
- `prerequisites` (object): `{}` or `{"condition": <expr>, "locked_text": "<text>"}`
- `setup_effects` (list): `[<effect>, ...]`
- `rewards` (list): `[<effect>, ...]` (every reward effect is always permanent — never set `"permanent": false`)
- `time_limit_s` (int >= 0): game seconds (`0` = no limit)

### Expressions (`<expr>`)
- `{}` (empty = true; allowed for `start_condition` and `prerequisites.condition`, NOT for a step `condition`)
- `{"type": "<type_id>", "params": {...}}` (a leaf using ONLY types from the catalog)
- `{"all": [<expr>, ...]}`
- `{"any": [<expr>, ...]}`
- `{"not": <expr>}`

### Effects (`<effect>`)
- `{"key": "<a-z, 0-9, _ starting with a-z, <= 40 chars>", "type": "<effect_type_id>", "params": {...}, "permanent": false}`
- Effect keys share ONE namespace with all role keys and all other effect keys (no duplicates).
- ONLY use types listed in the catalog with their exact parameter names and types.
- Types marked `step only` may ONLY appear directly in a step `condition`, NEVER in `start_condition`, `prerequisites`, or under `not`.

### Placeholders
- Player-facing texts (`title`, `summary`, `steps[].text`, `steps[].hint`, `steps[].role_notes[].text`, `prerequisites.locked_text`, and effect/criterion text params) may reference declared roles using `{role_key}`. Never reference an undeclared role; escape literal braces as {% raw %}`{{` or `}}`{% endraw %}.

### Bindings
- Map role keys to world entities using ONLY ids and names from the world context:
  - `character`: `{"name": "<character name>"}`
  - `location`: `{"location_id": "<location id>"}`
  - `room`: `{"location_id": "<location id>", "room_id": "<room id>"}`
  - `item`: `{"item_id": "<item id>"}`

{% if mode == "auto" %}
### Auto-mode rules (strict)
- `giver_role` MUST be set to the giver's character role key (and bound to `{{ giver }}`).
- `start_condition` MUST be `{}` (empty).
- Do NOT use `create_prop` anywhere in `setup_effects`, `steps[].on_done`, or `rewards`.
- Every declared role MUST have a valid binding in `bindings`.
- Step 0's condition MUST NOT already be true for `{{ avatar }}` right now.
{% endif %}

## user
Mode: {{ mode }}
{% if giver %}Giver: {{ giver }}
{% endif %}{% if avatar %}Avatar: {{ avatar }}
{% endif %}
Quest draft:
{{ draft }}

World context:
{{ context }}

Quest type catalog:
{{ catalog }}

Answer with exactly one ```json:quest block containing {"template": {...}, "bindings": {...}} and nothing else.
