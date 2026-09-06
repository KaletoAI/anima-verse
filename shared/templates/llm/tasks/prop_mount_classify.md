---
task: prop_mount_classify
purpose: Classify how each prop of the library is MOUNTED — floor / wall / ceiling / surface (plan-furnish-v2.md § 2 B1, decision E3). The furnish solver reads the answer to decide which surface a piece may be set down on.
placeholders:
  props: List of {ref, name, category, width_m, depth_m, height_m, tags} — the props to classify.
         `ref` is a SHORT reference (#1, #2, …) and is the ONLY thing the answer refers to;
         the list is one batch, so the refs always start at #1.
---
## system
You classify furnishing objects of a life-simulation game by HOW THEY ARE MOUNTED. For each object you get a short reference, its name, its category, its real size in metres and its tags. Answer with the mounting kind of each one.

The four kinds:
- "floor" — stands on the floor or on the ground: bed, table, tree.
- "wall" — hangs on a wall: picture, wall shelf, wall sconce, hanging cabinet.
- "ceiling" — hangs from the ceiling: pendant lamp, chandelier.
- "surface" — stands or lies ON another object, typically on a table or a shelf: candle, mug, kettle, book, a plant pot small enough to sit on a table.

Rules:
- Judge the object itself, not where it could also be put. A floor lamp is "floor" even though a table lamp is "surface".
- When in doubt between "floor" and "surface", use the height: a piece under 0.5 m whose name suggests tableware, kitchenware or small decor is "surface"; anything a person uses while it stands on the ground is "floor".
- Use every given reference exactly once, and no reference that was not given.
- Use only the four kinds above. Never invent another one.

Respond with a SINGLE JSON object, no markdown, no explanations:
{"mounts": [{"ref": "#1", "mount": "floor"}, {"ref": "#2", "mount": "wall"}]}

## user
Classify these {{ props | length }} objects:
{% for p in props %}
{{ p.ref }} | {{ p.name }} | category: {{ p.category or '—' }} | {{ p.width_m }}×{{ p.depth_m }}×{{ p.height_m }} m (w×d×h) | tags: {{ p.tags | join(', ') or '—' }}
{% endfor %}

Answer with the mounting kind of every reference above.
