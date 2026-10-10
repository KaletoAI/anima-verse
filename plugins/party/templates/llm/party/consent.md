{{ inviter }} invites you to travel together{% if destination_label %} to {{ destination_label }}{% endif %}.
{% if participants %}The explicitly included group is: {{ participants | join(', ') }}.{% endif %}
Decide in character whether to accept this exact proposal. Consent is your choice.
To accept, call JoinParty with leader={{ inviter }}, invite_id={{ invite_id }}. To decline, call JoinParty with leader={{ inviter }}, invite_id={{ invite_id }}, answer=no. Keep this exact invitation identity; a later proposal is a different decision.
An invitation is not a completed trip, and agreeing in prose alone does not move anyone.
