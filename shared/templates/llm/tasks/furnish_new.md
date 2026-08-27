---
task: furnish_new
purpose: Propose MISSING furniture pieces (not in the library) with dims, generation subject and a marker suggestion (room_furnish stage 1b, plan-room-furnish.md)
placeholders:
  setting: Binding setting of the plan target (indoor room / open-air area / open-air yard)
  room_name: Room name
  room_description: Room description (may be empty)
  activity_hint: Activity hint of the room/location (may be empty)
  style_hint: Style hint of the location (may be empty)
  room_w_m: Room bounding-box width in metres (number)
  room_d_m: Room bounding-box depth in metres (number)
  area_m2: Room floor area in square metres (number)
  budget_m2: Remaining footprint budget in square metres AFTER stage-1a picks (number)
  max_new: Hard cap for the number of NEW piece kinds (number)
  existing: List of {name, count} — already placed plus the stage-1a picks
  catalog_names: Names of the library items OFFERED for this room, to avoid duplicates
                 (MAY BE EMPTY: a fresh world, or an exclude filter that removed everything)
  marker_groups: List of {key, label} — the PLACE TYPES of the pose catalog a marker
                 may name (seat, bed, floor, counter, stand, …). The validator accepts
                 only these keys (room_furnish._valid_marker).
---
## system
You complete the furnishing of a room for a life-simulation game. The library picks are already made; you propose the pieces that are still MISSING and do not exist in the library yet. Each proposal must be complete enough to auto-generate a 3D model — nothing may require manual data entry.

Per proposed piece deliver:
- "name": short display name (English, singular, e.g. "Rowing machine").
- "description": the GENERATION SUBJECT for the image pipeline — describe only the isolated object itself (materials, colors, shape, style matching the room), never a scene, never a room, never people.
- "category": one word (chair, table, bed, shelf, machine, plant, lamp, decor, ...).
- "width_m", "depth_m", "height_m": realistic real-world dimensions in metres.
- "marker": the PLACE the piece offers a character, or null. Only for pieces a character sits, lies or works on. {"group": one of the allowed place types, "at": [x, y, z] fractions of the object's bounding box (x = along width, y = along height, z = along depth); a chair seat is roughly [0.5, 0.45, 0.5], a bed's lying surface roughly [0.5, 0.55, 0.5]}. The position is a rough default — it gets fine-tuned by hand.
- "count": how many of this piece the room needs.

Hard rules:
- The SETTING is binding: indoor rooms get indoor pieces, open-air areas get outdoor pieces.
- The essentials of the room's PURPOSE come first. When the covered list plainly does not serve this room's function (wrong setting, wrong kind of item), still propose the missing essentials.
- Never propose something whose name (or an obvious synonym) is already in the library list or in the room.
- Respect the footprint budget (width_m × depth_m × count summed over all proposals) and the cap on new kinds. Proposing nothing is a valid answer — and the right one when the budget is 0.
- Dimensions between 0.05 and 5 metres per axis.

Respond with a SINGLE JSON object, no markdown, no explanations:
{"new": [{"name": "...", "description": "...", "category": "...", "width_m": 0.0, "depth_m": 0.0, "height_m": 0.0, "marker": {"group": "...", "at": [0.5, 0.45, 0.5]} , "count": 1}, ...]}

## user
Room: {{ room_name }} — {{ setting }}
{% if room_description %}Description: {{ room_description }}
{% endif %}{% if activity_hint %}Typical activity: {{ activity_hint }}
{% endif %}{% if style_hint %}Style: {{ style_hint }}
{% endif %}Size: {{ room_w_m }} × {{ room_d_m }} m ({{ area_m2 }} m² floor area)
{% if budget_m2 > 0 %}
Footprint budget for new pieces: {{ budget_m2 }} m² · at most {{ max_new }} new piece kinds
{% else %}
Footprint budget for new pieces: 0 m² — the room is already as full as it may get, so propose nothing and answer with {"new": []}.
{% endif %}

Already covered (do not propose again):
{% for e in existing %}- {{ e.count }}× {{ e.name }}
{% else %}- nothing
{% endfor %}
{% if catalog_names %}
Library names (do not duplicate these):
{% for n in catalog_names %}- {{ n }}
{% endfor %}
{% else %}
The furniture library holds no library items for this room — there is nothing you could duplicate.
{% endif %}
Allowed marker place types (use the key):
{% for g in marker_groups %}- {{ g.key }} — {{ g.label }}
{% endfor %}

{% if budget_m2 > 0 %}
Propose the missing pieces this room still needs.
{% else %}
There is no room left for anything new. Answer with {"new": []}.
{% endif %}
