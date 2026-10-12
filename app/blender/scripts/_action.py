"""F-curves of Blender 5 slotted actions (layers -> strips -> channelbags). bpy only.

Blender 5.0 removed ``Action.fcurves``: an action's curves live in one
channelbag per slot. Every script reaches them through ``curves(owner)``.
"""
from bpy_extras import anim_utils


def curves(owner):
    """The F-curve collection of the action assigned to ``owner``, on the slot
    ``owner`` is bound to — created (slot and channelbag) for a fresh action.
    Supports ``find(path, index=)``, ``new(data_path=, index=)`` and iteration."""
    ad = owner.animation_data
    if ad is None or ad.action is None:
        raise ValueError(f"{owner.name} carries no action")
    slot = ad.action_slot
    if slot is None:
        slot = ad.action.slots.new(id_type="OBJECT", name=owner.name)
        ad.action_slot = slot
    return anim_utils.action_ensure_channelbag_for_slot(ad.action, slot).fcurves
