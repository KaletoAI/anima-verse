=== Agreed shared trip ===
Intent {{ intent_id }}: {{ destination_label }}.
Participants: {{ participants | join(', ') }}. Leader: {{ owner }}.
Phase: {{ phase }}{% if reason %} — {{ reason }}{% endif %}.
{% if phase == 'waiting_consent' %}
{% if character_name == owner %}The companion has not consented yet. Do not independently call SetLocation or retarget the plan. Their real JoinParty answer will resume this exact destination.
{% else %}This is a proposal, not an order. Decide explicitly: JoinParty with leader={{ owner }}, invite_id={{ invite_id }} accepts, JoinParty with leader={{ owner }}, invite_id={{ invite_id }}, answer=no declines. Keep the exact invitation identity; prose alone is not consent.
{% endif %}
{% elif phase == 'travelling' or phase == 'starting' %}
The authoritative journey already owns this destination. Do not start it again. Actual arrival of every participant, not a promise or progress count, completes the intent.
{% elif phase == 'ready' or phase == 'blocked' %}
Consent is recorded, but the group has not departed. The server resumes the same trip once its displayed gate is satisfied. Do not replace it with a second move or an ordinary plan.
{% endif %}
You may withdraw by leaving the party, or explicitly cancel this intent. Withdrawal ends this trip; cancelling a trip does not silently dissolve its party.
