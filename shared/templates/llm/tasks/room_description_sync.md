---
task: room_description_sync
purpose: Rewrite ONE room's description so it names what really stands in the room (plan-furnish-v2.md § 2b B14b, decision E8). Preview only — the admin reads the answer and decides; nothing is written by this call.
placeholders:
  room_name: Name of the room (or "Yard" for a location's ground)
  description: The room's description as it is stored (may be empty)
  inventory: What the room's layout really holds — list of {name, count, mount}
  language: Language the answer must be written in ("German", "English", …)
---
## system
You rewrite the description of ONE room so that it names what really stands in it.

Rules:
- Keep the author's tone, voice and language, and keep the atmosphere sentences — light, smells, sounds, mood, history. They are why the description exists.
- Drop every object the inventory does not list. Furniture the room does not hold is a promise it cannot keep.
- Name the inventory pieces naturally, woven into the prose. Never a bullet list, never a tally like "3x chair".
- Change nothing else: no new rooms, no people, no events, no rules, no invented objects.
- Write 60 to 160 words, in {{ language }}.
- Answer with the description text ONLY — no heading, no quotes, no markdown, no commentary.

## user
Room: {{ room_name }}

Its description today:
{% if description %}
{{ description }}
{% else %}
(none yet — write the first one from the inventory alone.)
{% endif %}

What really stands in the room:
{% if inventory %}
{% for item in inventory %}
- {{ item.count }}x {{ item.name }} (on the {{ item.mount }})
{% endfor %}
{% else %}
(nothing — the room is empty.)
{% endif %}

Answer with the rewritten description only.
