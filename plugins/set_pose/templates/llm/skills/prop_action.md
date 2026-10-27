---
name: PropAction
action_hint: Walk to and use an enabled exact furniture action, or explicitly stop the character's own action
---
Execute the current room's semantic prop action through the authoritative server. Request JSON: {"operation":"request","action_id":"<offered action_id>","revision":"<offered definition_revision>","target":{"location_id":"...","room_id":"...","placement_id":"...","variant_uid":"..."},"partner":"<enabled exact partner or empty>","request_id":"<optional unique retry nonce>"}. Copy all IDs and target fields from the enabled offer. Do not invent coordinates, animations, IDs or consent. Description/effects explain why the action is useful and when its real effects happen. Blocked offers cannot execute; missing_entry_transition needs an authored real playable walking-to-pose transition, not a different pose or asset fallback.

An accepted request begins walking or asks the exact partner for consent. It is NOT instant seating, sleep or completed rewards. A pair starts only after the partner's explicit InteractWith {"execution_id":"<incoming own execution>","answer":"yes"|"no"} response. Use {"operation":"cancel","execution_id":"<own execution_id>"} to stop or withdraw. Free body poses remain SetActivity; it cannot allocate a prop. Actor identity is bound by the caller and cannot be selected in the payload.
