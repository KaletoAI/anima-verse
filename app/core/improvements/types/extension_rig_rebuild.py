"""Rebuild extension bones for every stored model of one character."""
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, ImprovementType, ParamField


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
        from app.core.model3d import get_model3d_dir
        from app.core.model_refs import is_state_fork
        name = params["character"]
        if not any(not is_state_fork(path.stem) for path in get_model3d_dir(name).glob("*.glb")):
            return []
        candidate = Candidate(f"character:{name}", name)
        return [] if self.is_done(candidate, params) else [candidate]

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        import json
        from app.core.extension_rig import (extension_rig_fingerprint, rig_groups_for,
                                           model_extension_overrides)
        from app.core.model3d import get_model3d_dir
        from app.models.character import get_character_profile
        name = params["character"]
        profile = get_character_profile(name) or {}
        def read_meta(path):
            try:
                value = json.loads(path.with_suffix(".json").read_text())
                return value if isinstance(value, dict) else {}
            except (OSError, ValueError):
                return {}

        from app.core.model_refs import is_state_fork
        for path in get_model3d_dir(name).glob("*.glb"):
            if is_state_fork(path.stem):
                continue
            meta = read_meta(path)
            declarations = rig_groups_for(name, profile=profile, mesh_variant=meta.get("mesh_variant") or "")
            fingerprint = extension_rig_fingerprint(
                declarations, model_extension_overrides(profile, path.stem))
            state = meta.get("extension_rig") or {}
            if not state.get("attempted") or state.get("fingerprint") != fingerprint or state.get("status") not in (
                    "applied", "not_found", "none_applicable"):
                return False
            tier_state = (state.get("per_tier") or {}).get("low") or {}
            if tier_state.get("status") == "failed":
                return False
            # Terminal detection outcomes require no derived tier.
            if state.get("status") in ("not_found", "none_applicable") or meta.get("rig") != "mixamo":
                continue
            low = path.parent / "low" / path.name
            if not low.exists():
                return False
            low_state = read_meta(low).get("extension_rig") or {}
            if (not low_state.get("attempted") or low_state.get("fingerprint") != fingerprint
                    or low_state.get("status") not in ("applied", "not_found", "none_applicable")):
                return False
        return True

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core.model3d import rebuild_character_extension_rigs
        result = rebuild_character_extension_rigs(params["character"])
        if isinstance(result, dict) and result.get("ok") is False:
            raise RuntimeError(result.get("reason") or result.get("error") or "Extension rig rebuild failed")
