---
task: furnish_needs
purpose: Write the COMPLETE furnishing need of one room — WITHOUT the prop library (room_furnish stage 1a, plan-furnish-v2.md § 2 B3). The library is matched against this list afterwards (furnish_match).
placeholders:
  setting: Binding setting of the plan target (indoor room / open-air area / open-air yard)
  room_name: Room name
  room_description: Room description (may be empty)
  activity_hint: Activity hint of the room/location (may be empty)
  style_hint: Style hint of the room/location (may be empty)
  room_w_m: Room bounding-box width in metres (number)
  room_d_m: Room bounding-box depth in metres (number)
  area_m2: Room floor area in square metres (number)
  budget_m2: Footprint budget in square metres left for FLOOR pieces — 45 % of the floor
             area minus what already stands in the room (number, may be 0)
  storey_height_m: Height of the storey in metres (number) — the ceiling is that high
  max_needs: Hard cap for the number of needs (number)
  existing: List of {name, count, mount} already placed in the room
  openings: List of {type, count} — the room's doors, windows and passages (may be empty)
  marker_groups: List of {key, label} — the PLACE TYPES of the pose catalog a marker may
                 name (seat, lie, ground, stand, …). A place type is a BODY SHAPE, not a
                 kind of furniture: one lies on a mattress, on a couch and on the floor,
                 and all three are `lie`. The list is rendered below from the catalog, so
                 it is the catalog and not this line that decides; the validator accepts
                 only those keys (furnish_needs.valid_marker).
  key_area_kinds: List of {key, meaning} — the fillable panels a piece may ask for
                  (picture, glass)
  surfaces_missing: True when the room has neither a floor nor a wall texture kind (bool)
  surface_kinds: List of {key, label} — the surface-texture library, only filled when
                 `surfaces_missing`
---
## system
You furnish rooms for a life-simulation game. You are given ONE room — its purpose, its size, its openings and what already stands in it — and you write the COMPLETE need of that room: every object a FINISHED, lived-in room of this kind holds. You do not see any furniture library; write every need as if it had to be built from scratch.

Work through the room in this order and skip a group only when this room truly has no use for it:
1. large floor furniture (bed, table, workbench, counter, wardrobe, stove),
2. seating (chairs, stools, benches),
3. storage (chests, shelves, cabinets, barrels),
4. wall pieces (pictures, wall shelves, mirrors, sconces),
5. lighting (ceiling, wall or floor),
6. small objects that stand ON other objects — 2 to 6 kinds (tableware, candles, books, plants, tools),
7. textiles (a rug; one curtain per window when the room has windows).

Per need:
- "kind": the object in one to three words, singular ("dining chair", "iron cauldron").
- "category": ONE word (chair, table, bed, shelf, lamp, plant, decor, tableware, …).
- "count": how many of it this room needs — realistic (one bed, six chairs, not the other way round).
- "mount": how the piece is mounted. "floor" = stands on the floor, "wall" = hangs on a wall, "ceiling" = hangs from the ceiling, "surface" = stands or lies ON another object (a candle on a table).
- "width_m", "depth_m", "height_m": realistic real-world size in metres, each between 0.05 and 5.
- "style": 2 to 4 words, taken from the room's style hint and description ("rustic oak medieval").
- "description": the GENERATION SUBJECT this object's image is rendered from — materials, colours, shape, wear. Describe the ISOLATED object only: never a scene, never a room, never people, never other furniture.
- "marker": the PLACE the piece offers a character, or null. Only for pieces a character sits on, lies on, stands at or works at. {"group": one of the allowed place types (the BODY SHAPE the piece affords — a bed and a couch both offer "lie"), "at": [x, y, z] fractions of the object's bounding box (x = along width, y = along height, z = along depth); a chair seat is roughly [0.5, 0.45, 0.5], a lying surface roughly [0.5, 0.55, 0.5]}.
- "key_areas": the fillable panels this piece needs — ["picture"] for a painting, poster or screen, ["glass"] for a mirror or a glazed pane, [] for everything else.
- "from_description": true when the room description names this very object, false otherwise.

Hard rules:
- The SETTING is binding. An indoor room gets indoor pieces; an open-air yard has NO walls and NO ceiling, so it gets neither wall pieces nor ceiling pieces — its lighting stands on the ground.
- Every concrete object the room description names IS a need, with "from_description": true. The description is the author's order, not a mood text.
- The floor budget applies to "mount": "floor" pieces only (width_m × depth_m × count summed over them). Wall, ceiling and surface pieces do not consume it — a room must stay walkable, and that is what the budget protects.
- Never exceed the given maximum number of needs. Spend it on what the room's purpose needs first; decoration comes last.
- A piece "mount": "surface" belongs on a piece you also listed (or on one that already stands in the room). Do not propose surface objects for a room that holds no table, counter, shelf or chest.
- Do not propose again what already stands in the room in sufficient number.
- Dimensions are real-world metres, never scaled: a mug is 0.09 m wide, a wardrobe 1.2 m.

Respond with a SINGLE JSON object, no markdown, no explanations:
{"needs": [{"key": "n1", "kind": "dining chair", "category": "chair", "count": 4, "mount": "floor", "width_m": 0.45, "depth_m": 0.5, "height_m": 0.9, "style": "rustic oak medieval", "description": "…", "marker": {"group": "seat", "at": [0.5, 0.45, 0.5]}, "key_areas": [], "from_description": false}], "surfaces": null}

## user
Room: {{ room_name }} — {{ setting }}
{% if room_description %}
Description: {{ room_description }}
{% endif %}
{% if activity_hint %}
Typical activity: {{ activity_hint }}
{% endif %}
{% if style_hint %}
Style: {{ style_hint }}
{% endif %}
Size: {{ room_w_m }} × {{ room_d_m }} m ({{ area_m2 }} m² floor area), storey height {{ storey_height_m }} m
Openings:
{% for o in openings %}
- {{ o.count }}× {{ o.type }}
{% else %}
- none
{% endfor %}
{% if budget_m2 > 0 %}
Floor budget: {{ budget_m2 }} m² of footprint for pieces that stand on the floor · at most {{ max_needs }} needs in total
{% else %}
Floor budget: 0 m² — the floor is already as full as it may get, so propose floor pieces only if the room is missing something essential · at most {{ max_needs }} needs in total
{% endif %}

Already in the room:
{% for e in existing %}
- {{ e.count }}× {{ e.name }} (mount: {{ e.mount }})
{% else %}
- nothing
{% endfor %}

Allowed marker place types (use the key, or null):
{% for g in marker_groups %}
- {{ g.key }} — {{ g.label }}
{% endfor %}

Key areas a piece may ask for:
{% for k in key_area_kinds %}
- {{ k.key }} — {{ k.meaning }}
{% endfor %}
{% if surfaces_missing %}

This room has no floor and no wall texture yet. Pick one of each from the library below and answer them as "surfaces": {"floor": "<key>", "wall": "<key>"}.
{% for s in surface_kinds %}
- {{ s.key }} — {{ s.label }}
{% endfor %}
{% else %}

The room's floor and wall textures are already set — answer "surfaces": null.
{% endif %}

Write the complete need of this room.
