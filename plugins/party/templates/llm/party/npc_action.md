You may propose ONE shared trip when your standing task, goals or arrival reason calls for going somewhere with a present companion. Do not move rooms in this turn, and do not also produce say or pair.
A proposal is not consent: the companion will answer through their normal chat/tool response. Neither character moves until that answer.
When proposing to go to another place or room with someone, you MUST use this structured action rather than a say-only narrative invitation or a room-change field. A spoken promise by itself has no movement continuation.
Set optional action to {"type":"travel_together","target":"<present name>","destination":{"location_id":"<listed id>","room_id":"<listed room id>"},"scope":"pair","line":"<short spoken invitation>"}.
Use scope="party" ONLY if you explicitly intend to include all existing followers. Pair scope never removes or absorbs extra companions.
{% if shared_activities %}For a shared undertaking with an activity at the destination, also include "after_arrival":{"type":"pair","pose_key":"<exact key>"} in action. Available keys: {{ shared_activities | join(', ') }}. This requires exactly two participants. The invitation's line must name BOTH the destination and the activity. Arrival alone does not finish the undertaking; the normal paired-action invitation follows, and it can still be refused.{% endif %}
Use only a present partner: {% for partner in present %}{{ partner.name }}{% if not loop.last %}, {% endif %}{% endfor %}.
Destinations known to {{ npc_name }}:
{% for destination in destinations %}- {{ destination.name }} (location_id={{ destination.location_id }}): {% for room in destination.rooms %}{{ room.name }} (room_id={{ room.room_id }}){% if not loop.last %}, {% endif %}{% endfor %}
{% endfor %}
If no shared trip is appropriate, omit action. Never execute arbitrary tools in action or infer acceptance from text.
