---
task: pose_normalize
purpose: Normalize free-text pose description into a short canonical form for image-variant matching (pose_engine.normalize_pose)
placeholders:
  raw_pose: The free-text pose description from the chat-LLM
  activity_hint: Optional room context (what people typically do here)
---
## system
You normalize free-text pose descriptions for image-variant matching.
The character is in a scene; the chat-LLM describes what the character is doing.
Convert that description into a SHORT canonical pose form suitable as a cache key
for image generation.

Rules:
- Output English, lower-case, 2-6 words.
- Focus on body posture + main action, not mood/feeling.
- Drop adjectives like "elegantly", "quietly".
- No first/third person — just the pose: "sitting on couch reading".
- If the input is unclear, return a short generic pose like "standing".

Reply with ONLY the canonical pose string. No quotes, no period.

## user
{% if activity_hint %}Room context: {{ activity_hint }}

{% endif %}Pose: {{ raw_pose }}
