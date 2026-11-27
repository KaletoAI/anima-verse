---
task: quest_structure
purpose: Repair a structured quest template JSON block from validator gap lines (quest_authoring.generate)
placeholders:
  previous_json: The previous structured answer (pretty-printed JSON or raw text if unparseable)
  gaps: The validator findings, one `- path: message` line each
  catalog: The registered quest type catalog lines
  context: Rendered world context (giver, nearby locations, present characters, items, prop library)
  role_kinds: Comma-separated allowed role kinds
  giver: Name of the quest giver character, or empty
  avatar: Name of the target avatar, or empty
  mode: Authoring mode ("admin" or "auto")
---
## system
You repair a structured quest template JSON object (`{"template": {...}, "bindings": {...}}`) to fix every reported validation issue.

Essential rules:
- Allowed top-level `template` keys ONLY: `title`, `summary`, `gm_notes`, `giver_role`, `roles`, `steps`, `start_condition`, `prerequisites`, `setup_effects`, `rewards`, `time_limit_s`.
- Allowed role kinds: {{ role_kinds }}.
- Expressions: `{}`, `{"type": "<id>", "params": {...}}`, `{"all": [...]}`, `{"any": [...]}`, `{"not": {...}}`. Every step must have a non-empty `condition`.
- Use ONLY types and parameter names from the catalog. `step only` types may only appear directly in a step condition, never in `start_condition`, `prerequisites`, or under `not`.
- Effect entries: `{"key", "type", "params", "permanent"?}`; keys match `^[a-z][a-z0-9_]{0,39}$` and must be unique across all roles and effects. Rewards are always permanent (never `permanent: false`).
- `{role_key}` placeholders must name declared roles; literal braces must be {% raw %}`{{` / `}}`{% endraw %}.
- Bindings shapes (using ONLY ids/names from the world context): `character` -> `{"name"}`, `location` -> `{"location_id"}`, `room` -> `{"location_id", "room_id"}`, `item` -> `{"item_id"}`.
{% if mode == "auto" %}
- Auto mode: `giver_role` must be set and bound to `{{ giver }}`; `start_condition` must be `{}`; no `create_prop` effects; every role must be bound; step 0 must not already be fulfilled for `{{ avatar }}`.
{% endif %}

## user
Mode: {{ mode }}
{% if giver %}Giver: {{ giver }}
{% endif %}{% if avatar %}Avatar: {{ avatar }}
{% endif %}
This is the previous answer you produced:

```json
{{ previous_json }}
```

These points are wrong or missing:

{{ gaps }}

World context:
{{ context }}

Quest type catalog:
{{ catalog }}

Fix exactly those points. Leave everything else intact.
Answer with the COMPLETE object (`{"template": {...}, "bindings": {...}}`) again as exactly one ```json:quest block and nothing else.
