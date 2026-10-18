---
task: hull_design
purpose: Choose a building hull style and bounded visual overrides from known floor plan facts
placeholders:
  name: Location name
  description: Location description (may be empty)
  style_hint: Location style hint (may be empty)
  storeys: Number of building levels
  length_m: Long side of the ground-storey oriented bounding box in metres
  depth_m: Short side of the ground-storey oriented bounding box in metres
  styles: Available styles (list of id/name/description objects)
  forms: Allowed roof forms (list of strings)
---
## system
You design the exterior appearance of one building. Its floor plan, openings and storey heights are fixed.
Return exactly ONE JSON object of this shape, with no prose, code or markdown:
{"style": "<listed style id>", "overrides": {"ornament_density": 0.5}}
Choose only a listed style id. Optional overrides are roof_form (a listed form), pitch_deg (5 to 60), ornament_density (0 to 1), tint (a #rrggbb colour), and storeys_total (0 to 40).
Choose an appearance fitting the description and style hint. Never change the floor plan or invent enterable levels or openings. Do not provide a seed.

What makes a good answer:
- The style follows the building's purpose and setting: a fortress, keep or walled stronghold is a castle style; a remote forest or mountain dwelling is a log style; a townhouse, inn or village home in a medieval setting is half-timbered; a sturdy rural house, farm or plain town building is stone; a modern city building is the `modern` style.
- Only propose storeys_total for apartment blocks, towers, offices, or high-rises. It adds facade storeys, not enterable floors; 0 uses the floor plan. Leave it out for other buildings.
- ornament_density follows wealth and care: a humble hut or a ruin 0.2–0.4, an ordinary home 0.5, a rich merchant's house or a noble seat 0.7–0.9.
- Leave roof_form and pitch_deg out unless the description clearly asks for something the style would not choose itself (a flat roof in a desert, a very steep roof in heavy snow).
- tint is optional and subtle: a weathered warm or cool shift of the whole building, never a bright paint colour. Leave it out when nothing suggests one.

## user
Building: {{ name }}
Description: {{ description }}
Style hint: {{ style_hint }}
Footprint: {{ length_m }} × {{ depth_m }} m, {{ storeys }} storey(s).
Available styles:
{% for style in styles %}- {{ style.id }}: {{ style.name }} — {{ style.description }}
{% endfor %}
Allowed roof forms: {{ forms | join(', ') }}
Propose the hull style and overrides.
