"""Rebuild extension bones for every stored model of one character.

The key is ``character:<name>:<token>``; the token (``wanted_token``) is the
fingerprint over what ``is_done`` compares every target's stored extension
state against — the extension fingerprint a rebuild would record now
(``model3d.extension_state_current``: the groups the model carries and its
effective overrides) per target model. A standing entry therefore offers the
character again when a declaration or a model's extension setting changes
AFTER its step was done, never while those inputs stay. The key is never
read back (``is_done`` and ``apply`` go by the ``character`` param), so a
step of the older shape ``character:<name>`` runs as before."""
import hashlib
import json
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, ImprovementType, ParamField


def wanted_token(name: str) -> str:
    """12 hex over ``(model stem, wanted extension fingerprint)`` of every
    rebuild target — the fingerprint ``model3d._extension_state_current``
    compares the stored one with."""
    from app.core import model3d
    from app.core.extension_rig import (effective_extension_overrides, extension_rig_fingerprint,
                                       rig_groups_for)
    from app.models.character import get_character_profile
    profile = get_character_profile(name) or {}
    wanted = []
    for path in model3d.extension_rebuild_targets(name)[0]:
        meta = model3d._read_sidecar(path)
        declarations = model3d._extension_groups_for(meta, rig_groups_for(
            name, profile=profile, mesh_variant=model3d.stored_mesh_variant(name, meta)))
        wanted.append([path.stem, extension_rig_fingerprint(
            declarations, effective_extension_overrides(profile, path.stem, meta, declarations))])
    return hashlib.sha256(json.dumps(wanted, sort_keys=True).encode("utf-8")).hexdigest()[:12]


class ExtensionRigRebuild(ImprovementType):
    id = "extension_rig_rebuild"
    label = "Rebuild extension bones"
    params_schema = [ParamField("character", "Character", "text")]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from app.models.character import get_character_profile
        out = super().validate(params)
        if not get_character_profile(out["character"]):
            raise ValueError("Character not found")
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        from app.core.model3d import extension_rebuild_targets
        name = params["character"]
        if not extension_rebuild_targets(name)[0]:
            return []
        if self.is_done(Candidate(f"character:{name}", name), params):
            return []
        return [Candidate(f"character:{name}:{wanted_token(name)}", name)]

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        """Done when every model the rebuild TARGETS
        (``model3d.extension_rebuild_targets`` — on the base-body pipeline
        the current base and the current outfit models, never a stale outfit
        or an older base) carries a current extension state with the groups
        it carries itself (``model3d.extension_state_current``), and a
        humanoid outfit/whole-body model a current distance tier (a base body
        has none)."""
        import json
        from app.core.model3d import extension_rebuild_targets, extension_state_current
        name = params["character"]

        def read_meta(path):
            try:
                value = json.loads(path.with_suffix(".json").read_text())
                return value if isinstance(value, dict) else {}
            except (OSError, ValueError):
                return {}

        for path in extension_rebuild_targets(name)[0]:
            meta = read_meta(path)
            if not extension_state_current(name, path, meta):
                return False
            state = meta.get("extension_rig") or {}
            tier_state = (state.get("per_tier") or {}).get("low") or {}
            if tier_state.get("status") == "failed":
                return False
            # Terminal detection outcomes require no derived tier; a base body
            # has no distance tier at all.
            if (state.get("status") in ("not_found", "none_applicable") or meta.get("rig") != "mixamo"
                    or meta.get("base")):
                continue
            low = path.parent / "low" / path.name
            if not low.exists():
                return False
            low_state = read_meta(low).get("extension_rig") or {}
            if (not low_state.get("attempted") or low_state.get("fingerprint") != state.get("fingerprint")
                    or low_state.get("status") not in ("applied", "not_found", "none_applicable")):
                return False
        return True

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core.model3d import rebuild_character_extension_rigs
        result = rebuild_character_extension_rigs(params["character"])
        if isinstance(result, dict) and result.get("ok") is False:
            raise RuntimeError(result.get("reason") or result.get("error") or "Extension rig rebuild failed")
