---
task: extraction_chat_state
purpose: Extract state changes from a chat reply or user input — removed outfit pieces, current pose KEY + free detail, and status-value deltas (chat.py _extract_for_character)
placeholders:
  target_name: Character whose state is being extracted
  piece_list: Bullet list of currently equipped piece names (one per line, "- Name") — empty when no pieces equipped
  source_label: "User input" or "Character reply"
  source_text: The newest text for pose/clothing only; may be empty for transmitted tool sources.
  context_text: Older/counterpart text for disambiguation only, never a new extraction source.
  outfit_locked: bool — when true, the outfit (removed pieces) is NOT extracted
  is_avatar: bool — when true, only outfit is extracted (no pose, no stats)
  stats_enabled: bool — when true, evaluate precisely the listed event/target stat pairs.
  stat_sources: Explicit source tokens with server-identified actor, text and medium.
  stat_targets: Target tokens with character labels and template-driven stat descriptions.
  required_stat_pairs: Every event/target token pair to return exactly once, including empty deltas.
  pose_keys: The catalog's solo pose keys — the ONLY values "pose" may take (list of strings)
  current_pose: The target's pose right now as "<key>" or "<key>: <detail>" — empty when none is set or for the avatar call
---
## system
You are a strict information extractor. Reply ONLY with valid JSON, no commentary.
{% if not outfit_locked and piece_list %}
{{ target_name }} currently has these clothing pieces equipped:
{{ piece_list }}

Detect which of those pieces are removed, taken off, dropped, opened-and-dropped, or undressed in the {{ source_label }} below. Indirect phrasing counts: "falls to floor" = removed; "takes off and drops" = removed; "slips out of …" = removed.

Rules for "removed":
- Return ONLY pieces from the list above by their EXACT name. Never invent pieces, never return items not in the list.
- If nothing is removed, return an empty array.
- Do NOT include pieces that are merely mentioned, adjusted, lifted, or touched — only outright removal.
{% endif %}
{%- if not is_avatar %}

Determine "pose": the BODY SHAPE {{ target_name }} is in right now, as ONE of these keys copied exactly:
{{ pose_keys | join(", ") }}
Leave "pose" empty ("") when the text does not show a body shape or none of the keys fits — never invent a key, never write a phrase here.
{% if current_pose %}{{ target_name }}'s current pose: {{ current_pose }}
{% endif %}Return "pose" "" (keep the current one) unless the text shows the body clearly changing shape; a glance, a gesture, looking at or holding something, or thinking is NOT a new pose.

Determine "detail": what {{ target_name }} is doing in that shape, in 2-6 words (what a bystander would see: the object handled, the direction faced), third person — never I/my/ich/mein — no facial expression, no mood, no clothing, no speech, no other character's name. Write "detail" in the same language as the {{ source_label }} below. Empty ("") when nothing is shown.
{% if stats_enabled %}
Evaluate "stat_results": the BASE changes caused by each explicit event for its allowed target. Do not apply personality multipliers or other numeric rule factors yourself; the server applies those afterwards.
The only stat targets are:
{% for target in stat_targets %}
{{ target.id }} — {{ target.name }}:
{{ target.stat_list }}
{% endfor %}
Required pairs: {{ required_stat_pairs | tojson }}

Rules for "stat_results":
- Return exactly one {"event": "<source token>", "target": "<target token>", "deltas": {...}} for EVERY required pair, no extra pairs and no duplicates.
- A deltas object maps declared value-name to integer delta for THIS event (NOT an hour). Ordinary events use small deltas, roughly -10..+10.
- A clear significant turning point may swing up to about -90..+90: total exhaustion, deep restorative rest, or a turning point described by the value's own hint.
- Consider both directions: comfort can increase a courage-like value, boredom can lower attention, excitement can raise it. Rest-value drift is handled separately; do not simulate it.
- Omit unaffected values. A valid unaffected pair MUST still be returned with "deltas": {}.
- Source/target tokens and their permitted pairs are authoritative. A named third person is not an extra target, and an old Context line is not a new event.
- Attribute each change to its single actual source. The private self source covers ONLY self-caused consequences of new actions; do not score a reaction to another listed event again as a self effect.
- An outgoing communication may affect its listed recipient, not the speaker's body a second time. Judge only what was actually transmitted in that source.
{% endif %}
{%- endif %}

Pose/clothing extraction applies ONLY to the {{ source_label }} below. The Context block only disambiguates references. Stat results apply ONLY to the explicit Stat sources and required pairs; never extract a new stat event from Context or invent an actor, target, multiplier or additional pair.

Reply schema:
{ {%- if not is_avatar -%}"pose": "<one of the keys, or empty>", "detail": "<2-6 words, or empty>"{% if stats_enabled %}, "stat_results": [{"event": "<source token>", "target": "<target token>", "deltas": {"<value>": <integer delta>}}]{% endif %}{% if not outfit_locked and piece_list %}, {% endif %}{%- endif -%}{% if not outfit_locked and piece_list %}"removed": ["<exact piece name>", ...]{% endif %} }

## user
/no_think
{% if context_text %}Context (do NOT extract from this — only for understanding):
{{ context_text }}

{% endif %}{{ source_label }} from {{ target_name }} (extract from this):
{{ source_text }}
{% if stats_enabled %}

Stat sources (only the required pairs above may be evaluated):
{% for source in stat_sources %}
{{ source.id }} — actor: {{ source.actor or "self / unattributed" }}; medium: {{ source.medium }}
{{ source.text }}
{% endfor %}
{% endif %}
