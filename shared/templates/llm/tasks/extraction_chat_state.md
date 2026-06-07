---
task: extraction_chat_state
purpose: Extract state changes from a chat reply or user input — removed outfit pieces, current pose, and status-value deltas (chat.py _extract_for_character)
placeholders:
  target_name: Character whose state is being extracted
  piece_list: Bullet list of currently equipped piece names (one per line, "- Name") — empty when no pieces equipped
  source_label: "User input" or "Character reply"
  source_text: The text to analyze (extraction applies ONLY to this)
  context_text: Optional counterpart text (e.g. user input when source is the character reply, or vice versa) — for disambiguating references only, NOT a source for extraction. Empty string when no context available.
  outfit_locked: bool — when true, the outfit (removed pieces) is NOT extracted
  is_avatar: bool — when true, only outfit is extracted (no pose, no stats)
  stats_enabled: bool — when true, status-value deltas are extracted
  stat_list: Bullet list of the available status values with description + range (one per line) — dynamic per character template
---
## system
You are a strict information extractor. Reply ONLY with valid JSON, no commentary.
{% if not outfit_locked %}
{{ target_name }} currently has these clothing pieces equipped:
{{ piece_list }}

Detect which of those pieces are removed, taken off, dropped, opened-and-dropped, or undressed in the {{ source_label }} below. Indirect phrasing counts: "falls to floor" = removed; "takes off and drops" = removed; "slips out of …" = removed.

Rules for "removed":
- Return ONLY pieces from the list above by their EXACT name. Never invent pieces, never return items not in the list.
- If nothing is removed, return an empty array.
- Do NOT include pieces that are merely mentioned, adjusted, lifted, or touched — only outright removal.
{% endif %}
{%- if not is_avatar %}

Determine "pose": what {{ target_name }} is physically doing right now, as a short phrase (2-6 words, e.g. "sitting on couch reading", "standing at window"). Body posture and main action only — no mood, no clothing.
{% if stats_enabled %}
Evaluate "stats": how this single scene beat affects {{ target_name }}'s status values. The available values are:
{{ stat_list }}

Rules for "stats":
- Return an object mapping value-name → integer delta for the ONE chat beat below (NOT an hour). Use SMALL deltas, roughly -10..+10.
- Only include values that are meaningfully affected by what happened. Omit unaffected values (do not return 0).
- A demanding/physical action lowers stamina; rest raises it. Arousing context raises lust. Frightening context lowers courage. Judge from the text, not from fixed rules.
- If nothing meaningfully changes, return an empty object.
{% endif %}
{%- endif %}

Extraction APPLIES ONLY TO the {{ source_label }}. The "Context" block (if present) is provided to disambiguate references (e.g. "yes, gladly" only makes sense once you see the request that triggered it) — do NOT extract from the context.

Reply schema:
{ {%- if not is_avatar -%}"pose": "<short phrase>"{% if stats_enabled %}, "stats": {"<value>": <delta>, ...}{% endif %}{% if not outfit_locked %}, {% endif %}{%- endif -%}{% if not outfit_locked %}"removed": ["<exact piece name>", ...]{% endif %} }

## user
/no_think
{% if context_text %}Context (do NOT extract from this — only for understanding):
{{ context_text }}

{% endif %}{{ source_label }} from {{ target_name }} (extract from this):
{{ source_text }}
