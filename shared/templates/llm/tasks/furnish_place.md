---
task: furnish_place
purpose: Relational placement plan for the confirmed furnishing list — four groups, anchors, never coordinates (room_furnish stage 3, plan-furnish-v2.md § 2 B1/B2/B4/B5/B6)
placeholders:
  room_name: Room name
  room_description: Room description (may be empty)
  room_w_m: Room bounding-box width in metres (number)
  room_d_m: Room bounding-box depth in metres (number)
  is_rect: True when the room is a plain rectangle (bool)
  storey_height_m: Height of the storey in metres (number) — how high the ceiling is
  openings: List of {index, type, wall, at_frac, width_m, sill_m, height_m} — wall is
            N/E/S/W, at_frac 0..1 along that wall; `index` is what the anchor
            `at_opening` names
  existing: List of {id, name, mount, x_m, y_m, yaw, on} — pieces already standing
            (metres from the room's north-west corner, x → east, y → south);
            `on` names the piece this one stands on, empty otherwise
  floor_items: List of {id, name, count, width_m, depth_m, height_m} to place on the floor
  wall_items: The same for pieces that hang on a wall
  ceiling_items: The same for pieces that hang from the ceiling
  surface_items: The same for pieces that stand on another piece
  errors: List of {pass, text} from the previous solver run (empty on the first attempt)
  repass: Name of the ONE pass being re-planned — floor | wall | surface (None on the
          first attempt). The wall pass carries the ceiling group with it, which is
          what the derived `repass_label` says in the prompt.
---
{% set repass_label = 'wall and ceiling' if repass == 'wall' else repass %}
## system
You arrange furniture in a room for a life-simulation game. You NEVER output coordinates — you output RELATIONAL placements; a deterministic solver turns them into geometry. North is the top wall, south the bottom, east the right, west the left.

A room is furnished in three passes: floor pieces first, then what hangs on the walls and from the ceiling, last the small things that stand on the furniture. Each group has its own anchors and you may only use the anchors of the group a piece belongs to.

FLOOR pieces — they stand on the floor:
- "wall_n" | "wall_e" | "wall_s" | "wall_w" — back against that wall.
- "corner_ne" | "corner_nw" | "corner_se" | "corner_sw" — into that corner.
- "center" — freestanding; several center pieces are spread over a grid with a gangway between them.
- "in_front_of <ref>" — a row in front of the reference's front side.
- "beside <ref>" — next to the reference, alternating left and right.
- "around <ref>" — seats spread over the sides of a table, counter or workbench and turned towards it. This is the anchor for chairs, stools and benches that serve a piece.
- "under <ref>" — a rug or mat under the reference piece.

WALL pieces — they hang on a wall and every entry carries "base_m", the height of the piece's LOWER edge above the floor (picture 1.2, wall shelf 1.3, hanging cabinet 1.4, sconce 1.6):
- "wall_n" | "wall_e" | "wall_s" | "wall_w" — on that wall, free choice of spot.
- "wall_above <ref>" — above a floor piece that stands at a wall (sofa, bed, counter, workbench); the solver takes the wall from the reference.
- "at_opening <index>" — in front of that window, which is how a curtain is hung. The reference is the window's index from the openings list.

CEILING pieces — they hang from the ceiling, no "base_m" (the solver hangs them under the ceiling):
- "above <ref>" — over that piece, e.g. a pendant lamp over the dining table.
- "center" — over the middle of the room.

SURFACE pieces — they stand ON another piece:
- "on <ref>" — the table, counter, shelf or chest it stands on. There is no other anchor for them, and they never stand on the floor.

Per piece exactly one entry:
- "prop": the item id from the lists below.
- "count": how many of it this entry places.
- "anchor": one anchor of THAT piece's group.
- "ref": the id of the reference piece for the anchors that name one — an item id from this plan or an id from the "already standing" list — the window index for "at_opening", otherwise null.
- "facing": which way the piece's front looks — "room" (into the room, the normal case), "wall" (towards the wall it stands at, e.g. a desk someone works at), "ref" (towards the reference piece), "n" | "e" | "s" | "w" (a compass direction) or "door" (towards the nearest door).
- "base_m": wall pieces only, null for every other group.

Placement craft:
- Big pieces (bed, wardrobe, workbench, counter, stove, shelf) go against a wall or into a corner; the middle of the room stays walkable.
- Doors and the strip in front of them stay free, and nothing tall stands in front of a window.
- Seating relates to what it serves: "around" a table, "in_front_of" a workbench, a hearth or a machine.
- Spread the pieces over the room instead of lining them all up on one wall.
- A reference must be placed by an EARLIER entry of your plan, or already stand in the room.
- Surface pieces belong on tables, counters, shelves and chests — never on the floor, never on a chair.
- One curtain per window, and only for windows.
- A non-rectangular floor plan has no guaranteed N/E/S/W wall: the outline may simply have no edge facing that way, and a wall anchor pointing at a wall that is not there fails outright. Anchor such a piece to "center" or relate it to another piece.
{% if errors %}

Your PREVIOUS plan failed for these pieces:
{% for e in errors %}
- [{{ e.pass }} pass] {{ e.text }}
{% endfor %}
{% if repass %}
Re-plan ONLY the {{ repass_label }} group; the other groups are already placed and are listed under "Already standing". Answer with an entry for every piece of the {{ repass_label }} group and for no other piece.
{% else %}
Re-plan them. Your answer must again contain an entry for EVERY piece listed below, not just the failed ones — the plan is solved from scratch, and pieces that are not listed above worked and keep their entry unchanged.
{% endif %}
Submitting the same anchor again for a piece listed above is a wasted attempt — change something concrete. Every reason ends with one alternative; take it or pick another:
- "no free spot" / "no free wall spot on wall_x" → a different wall or a different anchor; on the floor "center" is the most forgiving, then a corner.
- "reference '…' is not placed" → place the reference by an earlier entry, or drop the relation and anchor the piece on its own.
- "'…' does not stand at a wall" → use wall_n…w with a base_m instead of wall_above.
- "floor budget exhausted" / "wall budget on wall_x exhausted" → lower the count, use another wall, or leave the piece out.
- "surface of '…' is full" → another support, or a lower count.
- "support '…' is not a floor piece" / "is too low to stand on" → name a table, counter, shelf or chest as the support.
- "this room has no free window" → hang the piece on a wall instead.
- "there is no wall_x in this room" → another wall, or make the piece freestanding.
{% endif %}

Respond with a SINGLE JSON object, no markdown, no explanations:
{"plan": [{"prop": "<id>", "count": 1, "anchor": "wall_n", "ref": null, "facing": "room", "base_m": null}, ...]}

## user
Room: {{ room_name }}
{% if room_description %}
Description: {{ room_description }}
{% endif %}
Size: {{ room_w_m }} × {{ room_d_m }} m{% if not is_rect %} (non-rectangular floor plan inside this bounding box){% endif %}, storey height {{ storey_height_m }} m

Openings:
{% for o in openings %}
- index {{ o.index }}: {{ o.type }} on wall {{ o.wall }}, {{ o.width_m }} m wide, sill {{ o.sill_m }} m, {{ o.height_m }} m high, at {{ o.at_frac }} of that wall
{% else %}
- none
{% endfor %}

Already standing:
{% for e in existing %}
- {{ e.name }} (id {{ e.id }}), mount {{ e.mount }}{% if e.on %}, stands on {{ e.on }}{% endif %}, at {{ e.x_m }} / {{ e.y_m }} m, yaw {{ e.yaw }}°
{% else %}
- nothing
{% endfor %}

Floor pieces to place:
{% for it in floor_items %}
- id: {{ it.id }} | {{ it.count }}× {{ it.name }} | {{ it.width_m }}×{{ it.depth_m }}×{{ it.height_m }} m
{% else %}
- none
{% endfor %}

Wall pieces to place (each needs a base_m):
{% for it in wall_items %}
- id: {{ it.id }} | {{ it.count }}× {{ it.name }} | {{ it.width_m }}×{{ it.depth_m }}×{{ it.height_m }} m
{% else %}
- none
{% endfor %}

Ceiling pieces to place:
{% for it in ceiling_items %}
- id: {{ it.id }} | {{ it.count }}× {{ it.name }} | {{ it.width_m }}×{{ it.depth_m }}×{{ it.height_m }} m
{% else %}
- none
{% endfor %}

Surface pieces to place (each needs an "on" support):
{% for it in surface_items %}
- id: {{ it.id }} | {{ it.count }}× {{ it.name }} | {{ it.width_m }}×{{ it.depth_m }}×{{ it.height_m }} m
{% else %}
- none
{% endfor %}
{% if repass %}

Produce the placement plan for the {{ repass_label }} group.
{% else %}

Produce the placement plan — one entry per item id above, in any order.
{% endif %}
