"""Per-piece fit settings of a clothing piece (Ruling A47).

A clothing piece carries, per character, how its sleeves are placed and how much width the automatic size retry
may add — ``garment_fit.fit_clothing``'s ``settings``:

- ``sleeves_left`` / ``sleeves_right``: ``garment_fit.SLEEVE_CHOICES`` — "auto" (the fit decides per side,
  ``garment_fit.auto_sleeve``), "generated" (as generated, re-centred on the arm), "wider" (+20 % about the arm
  axis) or "fitted" (laid onto the arm).
- ``allowance``: ``garment_fit.ALLOWANCE_CHOICES`` — "auto" (the width allowance of ``garment_fit.scale_retry``) or
  a fixed percent of the torso's half width, applied as room over the whole piece after the clearance pass
  (``garment_fit.room_offset``, A174; negative = tighter, never closer than the clearance).
- ``depth`` (Ruling A68): ``garment_fit.DEPTH_CHOICES`` — room in front of and behind the trunk added after the
  push-out, a percent of the torso's half depth (default 0, Auto never adds depth; A174: room over the whole piece,
  ``garment_fit.room_offset``, negative = tighter).
- ``trunk`` (Ruling A83): ``garment_fit.TRUNK_CHOICES`` — "auto" (the fit decides, ``garment_fit.auto_trunk``),
  "generated" (as generated) or "fitted" (laid onto the body, ``garment_fit.place_trunk``; before the depth
  allowance).
- ``shaft`` (Ruling A122): ``garment_shaft.SHAFT_CHOICES`` — a piece on the feet AND the legs (a boot past the
  knee): "split" (the default; a shoe part and a leg part that overlaps it) or "cut" (the shoe part
  only, everything above the shoe top dropped). Ignored for every other piece.
- ``shaft_overlap`` (A177): cm the leg part reaches down into the shoe part with ``split``
  (``garment_shaft.OVERLAP_CM_MIN``..``OVERLAP_CM_MAX``, default ``OVERLAP_CM_DEFAULT`` 10). Ignored elsewhere.
The mesh shape (Ruling A48d) is no setting: the item's mode decides it (``garment_shell.shape_of``: mode ``shell``
→ the shell from the body, else as generated). The fit records the shape it made (``inputs.mesh_shape``); a fit whose
made shape is not the current one is due (``changed``).
- ``shell_offset`` (A166): ``garment_shell.SHELL_OFFSET_CHOICES`` — mm the shell stands off the skin (default 4);
  only a shell-mode piece's fit becomes due for it.

Stored on the character profile (``SETTINGS_KEY``: ``{item_id: {key: value}}``, only the values that differ from
the defaults). Not part of the fingerprint: a change keeps every image and the mesh and only makes the fit due — the
fit records the settings it was made with (``inputs.fit_settings``) and a fit made with others is ``stale``
(``garments._fit_state`` / ``garments.body_fit_state``); the next run refits on the CPU, no hub job.
"""
from typing import Any, Dict, Optional

#: Profile key of the per-piece fit settings: ``{item_id: {sleeves_left, sleeves_right, allowance, depth, trunk,
#: shaft}}``.
SETTINGS_KEY = "garment_fit_settings"
SIDES = ("left", "right")


def defaults() -> Dict[str, Any]:
    from app.core.garment_shell import SHELL_OFFSET_DEFAULT
    return {"sleeves_left": "auto", "sleeves_right": "auto", "allowance": "auto", "depth": 0, "trunk": "auto",
            "shaft": "split", "shaft_overlap": 10, "shell_offset": SHELL_OFFSET_DEFAULT}


def normalise(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The full settings (every key, unknown or missing values "auto") of a stored or recorded settings dict."""
    from app.core import garment_fit
    out = defaults()
    raw = raw if isinstance(raw, dict) else {}
    for side in SIDES:
        value = raw.get(f"sleeves_{side}")
        if isinstance(value, str) and value in garment_fit.SLEEVE_CHOICES:
            out[f"sleeves_{side}"] = value
    out["allowance"] = garment_fit.allowance_choice(raw)
    out["depth"] = garment_fit.depth_choice(raw)
    out["trunk"] = garment_fit.trunk_choice(raw)
    from app.core import garment_shaft
    out["shaft"] = garment_shaft.shaft_choice(raw)
    out["shaft_overlap"] = garment_shaft.overlap_cm(raw)
    from app.core import garment_shell
    out["shell_offset"] = garment_shell.shell_offset_choice(raw)
    return out


def fit_settings(profile: Optional[Dict[str, Any]], item_id: str) -> Dict[str, Any]:
    """The current fit settings of ``item_id`` on the character ``profile`` (``normalise``)."""
    stored = profile.get(SETTINGS_KEY) if isinstance(profile, dict) else None
    return normalise(stored.get(item_id) if isinstance(stored, dict) else None)


def recorded(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The settings a fit record was made with (``inputs.fit_settings``; a record without them: the defaults)."""
    return normalise(((record or {}).get("inputs") or {}).get("fit_settings"))


def made_shape(record: Optional[Dict[str, Any]]) -> str:
    """The mesh shape a fit ``record`` made (``inputs.mesh_shape``; a fit before Ruling A48d: as generated)."""
    from app.core import garment_shell
    value = ((record or {}).get("inputs") or {}).get("mesh_shape")
    return garment_shell.SHELL if value == garment_shell.SHELL else garment_shell.AS_GENERATED


def current_shape(settings: Dict[str, Any], item_id: str) -> str:
    """The mesh shape a fit of ``item_id`` makes now — its mode decides (``garment_shell.shape_of``); ``settings``
    play no part since A168 (kept for the callers that hold them)."""
    from app.core import garment_shell
    from app.models.inventory import get_item
    return garment_shell.shape_of(get_item(item_id))


def changed(record: Optional[Dict[str, Any]], profile: Optional[Dict[str, Any]], item_id: str) -> bool:
    """Whether the fit ``record`` was made with other fit settings than the current ones — or made another mesh
    shape than the item's mode makes now (``current_shape``). The shell offset (A166) counts for a shell only."""
    from app.core import garment_shell
    current = fit_settings(profile, item_id)
    made = recorded(record)
    now = dict(current)
    if current_shape(current, item_id) != garment_shell.SHELL:
        # A166: the shell offset shapes a shell only — a generated mesh's fit is not due for it.
        made.pop("shell_offset", None)
        now.pop("shell_offset", None)
    return made != now or made_shape(record) != current_shape(current, item_id)


def validate(changes: Dict[str, Any]) -> Dict[str, Any]:
    """The checked changes (a subset of the settings keys) -> ``{key: value}``; ValueError naming what is wrong."""
    from app.core import garment_fit
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Nothing to change")
    out: Dict[str, Any] = {}
    for key, value in changes.items():
        if key in ("sleeves_left", "sleeves_right"):
            if not isinstance(value, str) or value not in garment_fit.SLEEVE_CHOICES:
                raise ValueError(f"{key} must be one of {', '.join(garment_fit.SLEEVE_CHOICES)}")
            out[key] = value
        elif key == "allowance":
            if value == "auto":
                out[key] = "auto"
            elif (isinstance(value, bool) or not isinstance(value, (int, float))
                  or value not in garment_fit.ALLOWANCE_CHOICES):
                raise ValueError("allowance must be auto or one of "
                                 + ", ".join(str(c) for c in garment_fit.ALLOWANCE_CHOICES if c != "auto"))
            else:
                out[key] = int(value)
        elif key == "depth":
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or value not in garment_fit.DEPTH_CHOICES):
                raise ValueError("depth must be one of " + ", ".join(str(c) for c in garment_fit.DEPTH_CHOICES))
            out[key] = int(value)
        elif key == "shaft":
            from app.core import garment_shaft
            if not isinstance(value, str) or value not in garment_shaft.SHAFT_CHOICES:
                raise ValueError(f"shaft must be one of {', '.join(garment_shaft.SHAFT_CHOICES)}")
            out[key] = value
        elif key == "shaft_overlap":
            from app.core import garment_shaft
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value
                    or not garment_shaft.OVERLAP_CM_MIN <= value <= garment_shaft.OVERLAP_CM_MAX):
                raise ValueError(f"shaft_overlap must be a whole number of cm from {garment_shaft.OVERLAP_CM_MIN} "
                                 f"to {garment_shaft.OVERLAP_CM_MAX}")
            out[key] = int(value)
        elif key == "shell_offset":
            from app.core import garment_shell
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or value not in garment_shell.SHELL_OFFSET_CHOICES):
                raise ValueError("shell_offset must be one of "
                                 + ", ".join(str(c) for c in garment_shell.SHELL_OFFSET_CHOICES) + " (mm)")
            out[key] = int(value)
        elif key == "trunk":
            if not isinstance(value, str) or value not in garment_fit.TRUNK_CHOICES:
                raise ValueError(f"trunk must be one of {', '.join(garment_fit.TRUNK_CHOICES)}")
            out[key] = value
        else:
            raise ValueError(f"Unknown fit setting {str(key)[:40]!r}")
    return out


def set_fit_settings(character_name: str, item_id: str, changes: Dict[str, Any]) -> bool:
    """Store ``changes`` (``validate``) for ``item_id`` — one read-modify-write under the profile lock; values back
    at their default are dropped. Returns ``save_character_profile``'s bool (True without a change). Runs nothing: the
    fit becomes due (module docstring). ValueError for invalid changes or an
    item that is no clothing piece of the character."""
    from app.core import garment_set, garments
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    checked = validate(changes)
    _item, kind = garments._item(character_name, item_id)
    if kind != garment_set.CLOTHING:
        raise ValueError("Fit settings are for clothing pieces")
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        stored = dict(profile.get(SETTINGS_KEY)) if isinstance(profile.get(SETTINGS_KEY), dict) else {}
        current = fit_settings(profile, item_id)
        merged = {**current, **checked}
        if merged == current:
            return True
        base = defaults()
        compact = {k: v for k, v in merged.items() if v != base[k]}
        if compact:
            stored[item_id] = compact
        else:
            stored.pop(item_id, None)
        if stored:
            profile[SETTINGS_KEY] = stored
        else:
            profile.pop(SETTINGS_KEY, None)
        saved = bool(save_character_profile(character_name, profile))
    if saved:
        forget_fit_failures(character_name, item_id)
    return saved


def forget_fit_failures(character_name: str, item_id: str) -> None:
    """Drop the recorded fit refusals of ``item_id`` (base model and every outfit body; persisted and in memory):
    they were judged with other fit settings, and an automatic trigger would otherwise skip the refit."""
    from app.core import garment_store as gs
    for (iid, fsig), files in gs.stored_groups(character_name).items():
        if iid != item_id:
            continue
        if gs.read_record(gs.garment_path(character_name, item_id, fsig, "failed")).get("step") == "fit":
            gs.clear_failure(character_name, item_id, fsig)
        for body in {gs.body_of(p) for p in files} - {""}:
            gs.clear_failure_on_body(character_name, item_id, fsig, body)
    gs.forget_failed_step(character_name, item_id, "fit")
