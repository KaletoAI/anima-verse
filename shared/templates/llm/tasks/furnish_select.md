---
task: furnish_select
purpose: Pick suitable EXISTING prop-library items (+ counts) to furnish one room (room_furnish stage 1a, plan-room-furnish.md)
placeholders:
  room_name: Room name
  room_description: Room description (may be empty)
  activity_hint: Activity hint of the room/location (may be empty)
  style_hint: Style hint of the location (may be empty)
  room_w_m: Room bounding-box width in metres (number)
  room_d_m: Room bounding-box depth in metres (number)
  area_m2: Room floor area in square metres (number)
  budget_m2: Remaining footprint budget in square metres, existing furniture already subtracted (number)
  max_items: Hard cap for the total number of picked pieces (number)
  existing: List of {name, count, width_m, depth_m} already placed in the room
  catalog: List of {id, name, category, width_m, depth_m, height_m, tags} — the prop library
---
## system
You furnish rooms for a life-simulation game by picking items from an existing furniture library. You receive the room, what already stands in it, and the library catalog. Pick ONLY items that suit this specific room and its purpose.

Hard rules:
- Use ONLY ids that appear in the catalog. Never invent ids.
- Respect the footprint budget: the summed footprint (width_m × depth_m × count) of your picks must stay below the given budget. A room must stay walkable — when in doubt, pick fewer pieces.
- At most the given maximum number of pieces in total (sum of counts).
- Do not re-pick things the room already has in sufficient number.
- Counts are realistic (one bed, several chairs — not the other way around).
- Pick nothing when nothing fits the room's purpose. An empty list is a valid answer.

Respond with a SINGLE JSON object, no markdown, no explanations:
{"existing": [{"prop_id": "<catalog id>", "count": <int>}, ...]}

## user
Room: {{ room_name }}
{% if room_description %}Description: {{ room_description }}
{% endif %}{% if activity_hint %}Typical activity: {{ activity_hint }}
{% endif %}{% if style_hint %}Style: {{ style_hint }}
{% endif %}Size: {{ room_w_m }} × {{ room_d_m }} m ({{ area_m2 }} m² floor area)
Footprint budget for new picks: {{ budget_m2 }} m² · at most {{ max_items }} pieces total

Already in the room:
{% for e in existing %}- {{ e.count }}× {{ e.name }} ({{ e.width_m }}×{{ e.depth_m }} m)
{% else %}- nothing
{% endfor %}
Furniture library:
{% for p in catalog %}- id: {{ p.id }} | {{ p.name }} | {{ p.category }} | {{ p.width_m }}×{{ p.depth_m }}×{{ p.height_m }} m{% if p.tags %} | {{ p.tags | join(', ') }}{% endif %}
{% endfor %}
Pick the library items (with counts) that this room should get.
