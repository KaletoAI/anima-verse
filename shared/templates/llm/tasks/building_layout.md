---
task: building_layout
purpose: Design a complete floor plan and hull appearance in one call
---
## system
This is a ONE-SHOT building design request. Ignore the schema's ask-the-user / chat flow.
Answer with ONLY one fenced ```json:layout block, with a one-paragraph summary.
Use the following schema as the single authority for coordinates, room sizes, openings,
stairs, boundary openings, room_type, storey_height_m and hull fields:

{{ layout_schema }}

Additional design guidance:
- Rooms tile each storey without gaps: the server derives the building contour from them.
- Every upper storey sits inside the one below it.
- Put windows on outer walls of living rooms, bedrooms, kitchens and shops.
- Add one entrance door on storey 0 leading outside, plus a boundary opening on the nearest plot edge.
- Stairs connect all storeys. Include a hall/corridor when more than three rooms share a storey.
- Give every room a room_type from the supplied catalog.
- Shops, cafés, bakeries and taverns get hull.overrides.shopfront: true.
- Few windows for the building's size means hull.overrides.blind_windows: true.
- Choose storey_height_m between 2.6 and 4.5 metres.
- Choose a listed hull style. A forced style must win. Do not provide a seed.
Optional hull.overrides: roof_form (gable, hip, shed, flat),
pitch_deg (5–60), max_rise_m (1.5–12), ornament_density (0–1), tint (#rrggbb),
storeys_total (0–40), blind_windows and shopfront (booleans), frame_color,
door_color (painted doors only), shop_color and awning_color (each #rrggbb).

## user
Building description: {{ text }}
Forced style (empty means choose): {{ forced_style }}
Room types:
{% for room in room_types %}- {{ room.id }}: {{ room.label }}
{% endfor %}
Hull styles:
{% for style in hull_styles %}- {{ style.id }}: {{ style.name }} — {{ style.description }}
{% endfor %}
{% if previous | default('') %}
Previous normalized proposal:
{{ previous }}
{% endif %}
{% if revision | default('') %}
Revision: {{ revision }}
{% endif %}
