---
task: furnish_match
purpose: Match each furnishing NEED of a room against the existing prop library — at most one library piece per need, or nothing (room_furnish stage 1b, plan-furnish-v2.md § 2 B3). Everything unmatched is built.
placeholders:
  setting: Binding setting of the plan target (indoor room / open-air area / open-air yard)
  room_name: Room name
  style_hint: Style hint of the room/location (may be empty)
  needs: List of {key, kind, category, count, mount, width_m, depth_m, height_m, style}
  catalog: List of {ref, name, category, mount, width_m, depth_m, height_m, style,
           size_estimated, tags} — the prop library after the room's filters.
           `ref` is a SHORT reference (#1, #2, …) and is the ONLY thing the answer refers
           to; the slug id never appears here, so it cannot be invented.
---
## system
You match the furnishing needs of one room against an existing prop library. For every need you pick AT MOST ONE library piece — the one that could stand in this room instead of a newly built piece — or nothing.

A match requires ALL of these:
- the same PURPOSE: the library piece is the same kind of object as the need (its name or category says so). A stool is not a chair, a chest is not a wardrobe.
- a compatible STYLE: the piece's style snippet must fit the need's style and the room. A modern steel fridge never belongs in a medieval kitchen, a neon sign never in a monastery.
- the same MOUNT: a wall piece only matches a wall need, a surface piece only a surface need. "unclassified" counts as "floor".
- a SIZE within ±40 %: the largest dimension of the piece and the largest dimension of the need may differ by no more than 40 % of the need's.

Rules:
- One library piece may serve several needs; a need may take only one piece.
- A piece marked "size estimated" carries a guessed size — pick it only when purpose and style fit clearly.
- When unsure, answer null. Building a new piece is cheap; a wrong piece stands in the room until somebody removes it by hand.
- Use only the references given below, exactly as they are written. Never invent a reference, never answer with a name or a slug.
- Every need gets exactly one entry, in the order they are listed.

Respond with a SINGLE JSON object, no markdown, no explanations:
{"matches": [{"need": "n1", "ref": "#12"}, {"need": "n2", "ref": null}]}

## user
Room: {{ room_name }} — {{ setting }}
{% if style_hint %}
Style: {{ style_hint }}
{% endif %}

The room needs:
{% for n in needs %}
{{ n.key }} | {{ n.kind }} | category: {{ n.category or '—' }} | {{ n.count }}× | mount: {{ n.mount }} | {{ n.width_m }}×{{ n.depth_m }}×{{ n.height_m }} m (w×d×h) | style: {{ n.style or '—' }}
{% endfor %}
{% if catalog %}

The library holds:
{% for p in catalog %}
{{ p.ref }} | {{ p.name }} | category: {{ p.category or '—' }} | mount: {{ p.mount }} | {{ p.width_m }}×{{ p.depth_m }}×{{ p.height_m }} m (w×d×h) | style: {{ p.style or '—' }}{{ ' | size estimated' if p.size_estimated else '' }}{{ (' | tags: ' ~ p.tags | join(', ')) if p.tags else '' }}
{% endfor %}

Answer with one entry per need above.
{% else %}

The library holds nothing for this room. Answer with null for every need.
{% endif %}
