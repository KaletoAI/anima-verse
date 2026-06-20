---
task: intro_memory
purpose: Suggest one short intro memory for a character freshly moved into a new world (fresh-start import).
placeholders:
  character_name: The character's name
  character_personality: The character's personality text (may be empty)
  world_name: Name of the world they are moving into
  world_setup: Per-world briefing (genre, tone, premise) — may be empty
  user_hint: Optional steer from the user — may be empty
---
## system
You write a single short autobiographical memory for a character who has just
moved into a new world. Write in third person, present perspective, 1–3 sentences.
State only that they are newly arrived and a plausible intention or hope — grounded
in their personality and the world. Do NOT invent specific other characters, past
events, place names, or backstory from another world. Output ONLY the memory text,
no quotes, no preamble.

## user
Character: {{ character_name }}
{% if character_personality %}Personality: {{ character_personality }}{% endif %}
World: {{ world_name }}
{% if world_setup %}World briefing: {{ world_setup }}{% endif %}
{% if user_hint %}Steer: {{ user_hint }}{% endif %}

Write the one-sentence-to-three-sentence intro memory now.
