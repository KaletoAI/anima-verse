"""Contract every improvement type implements.  The engine never names a type."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Candidate:
    key: str      # stable + unique per type, e.g. "character:Mira"
    label: str    # display


@dataclass(frozen=True)
class ParamField:
    key: str
    label: str
    kind: str     # "mesh_backend" | "image_backend" | "subject_kind" | "enum" | "text"
    options: Optional[List[Dict[str, str]]] = None   # [{"value","label"}] for enum/subject_kind
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "options": self.options or [], "required": self.required}


class ImprovementType:
    id: str = ""
    label: str = ""
    params_schema: List[ParamField] = []

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return normalised params or raise ValueError(message)."""
        out: Dict[str, Any] = {}
        for f in self.params_schema:
            v = params.get(f.key, "")
            v = str(v).strip() if v is not None else ""
            if f.required and not v:
                raise ValueError(f"missing parameter '{f.key}'")
            if f.options and v and v not in {o["value"] for o in f.options}:
                raise ValueError(f"invalid value for '{f.key}'")
            out[f.key] = v
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        """Every subject NOT yet is_done, stable order (label, key)."""
        raise NotImplementedError

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        """The type's own finished-test, used INSIDE ``find_candidates`` — the
        engine never calls it; a subject that drops off the candidate list is
        closed as done."""
        raise NotImplementedError

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        """Synchronous; returns only after the asset is persisted.  May raise
        BackendBusyError (step stays pending) or any other Exception (attempt)."""
        raise NotImplementedError


class CandidateBusy(Exception):
    """The subject is being generated elsewhere right now — treat like busy."""
