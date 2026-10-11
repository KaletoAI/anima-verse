=== Agreed shared trip ===
Intent {{ intent_id }}: {{ destination_label }}.
Participants: {{ participants | join(', ') }}. Leader: {{ owner }}.
{% if after_arrival_label %}After arrival: {{ after_arrival_label }} together. The intent remains active until that exact activity actually ends; arriving or merely asking is not completion.{% endif %}
Phase: {{ phase }}{% if reason %} — {{ reason }}{% endif %}.
{% if phase == 'waiting_consent' %}
{% if character_name == owner %}The companion has not consented yet. Do not independently call SetLocation or retarget the plan. Their real JoinParty answer will resume this exact destination.
{% else %}This is a proposal, not an order. Decide explicitly: JoinParty with leader={{ owner }}, invite_id={{ invite_id }} accepts, JoinParty with leader={{ owner }}, invite_id={{ invite_id }}, answer=no declines. Keep the exact invitation identity; prose alone is not consent.
{% endif %}
{% elif phase == 'travelling' or phase == 'starting' %}
The authoritative journey already owns this destination. Do not start it again. Actual arrival of every participant completes the travel step{% if after_arrival_label %}, then the server proposes the agreed activity through its normal consent path{% else %} and the intent{% endif %}.
{% elif phase == 'ready' or phase == 'blocked' %}
The server is waiting at the displayed gate. Do not replace this agreement with a second move, another activity or an ordinary plan.
{% elif phase == 'waiting_activity' %}
The group has arrived. The server has proposed the agreed activity through its usual pair invitation.
{% if character_name == owner %}Wait for the companion's answer. Never answer your own invitation or accept on their behalf.
{% else %}Decide whether to accept or refuse that exact invitation with the normal pair verb, not JoinParty.
{% endif %}Do not propose a duplicate pair or send another invitation.
{% elif phase == 'activity' %}
The agreed pair activity is running. Do not start it again or claim completion while it is still active. Its actual end signal completes the intent; leaving, sleeping or being removed interrupts it.
{% endif %}
You may withdraw by leaving the party, or explicitly cancel this intent. Withdrawal ends this trip; cancelling a trip does not silently dissolve its party.
