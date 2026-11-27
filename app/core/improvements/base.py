"""Contract every improvement type implements.  The engine never names a type."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Candidate:
    # Stable + unique per type, e.g. "character:Mira:<token>". A scan inserts NEW keys, and reopens a key only
    # when its step is ``fulfilled`` (a scan saw the subject satisfied in between): a step that ran (``done``)
    # or was given up (``skipped``) is never offered again under the same key. So every type puts the token
    # that makes its work due (a version, a signature, the identity of the input it works from) into the key:
    # a subject due again for a NEW reason is a new key, a new step.
    key: str
    label: str    # display
    # Estimated hub jobs the step will submit on its FIRST attempts (a chain
    # may spend one more per refused attempt — the note says so where it
    # applies). None = unknown: listed as such, never silently as 0.
    hub_jobs: Optional[int] = 0
    note: str = ""    # one line: what the estimate counts, or a dry-run summary


@dataclass(frozen=True)
class Listing:
    """What a scan sees: the candidates, and the subjects it could NOT judge this time.

    ``withheld`` holds subject key prefixes (a step key is under one when it equals it or starts with it plus
    ":") — a subject whose state is in flux right now (its run in progress elsewhere, its base model being
    built, its running jobs unreadable). Such a subject is neither due nor satisfied: the scan leaves an
    unlisted step under it as it is — a pending one stays pending, a done one done (never ``fulfilled``, so it
    is not re-offered when the subject shows up again under the same key). A listed key under a withheld
    prefix is handled as any listed key. A permanent exclusion (a persisted failure, a setting, a scope) is
    not withheld: the subject drops off the list and its step closes as fulfilled."""
    candidates: List[Candidate]
    withheld: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ParamField:
    key: str
    label: str
    kind: str     # "mesh_backend" | "image_backend" | "subject_kind" | "enum" | "text"
    options: Optional[List[Dict[str, str]]] = None   # [{"value","label"}] for enum/subject_kind
    required: bool = True

    default: str = ""
    show_if: Optional[Dict[str, List[str]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "options": self.options or [], "required": self.required,
                "own_options": self.options is not None, "default": self.default,
                "show_if": self.show_if or {}}


class ImprovementType:
    id: str = ""
    label: str = ""
    #: One English line under the type picker: what the type works on, when that is not obvious from the
    #: label (the tab translates it).
    description: str = ""
    params_schema: List[ParamField] = []
    # Whether a step of this type generates media (images, meshes, bakes).
    # With the world's media switch off the engine submits only steps of
    # types that say False here — the CPU-only work keeps running.
    needs_media: bool = True

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return normalised params or raise ValueError(message)."""
        out: Dict[str, Any] = {}
        for f in self.params_schema:
            if f.show_if and not all(out.get(key, "") in values
                                     for key, values in f.show_if.items()):
                out[f.key] = ""
                continue
            v = params.get(f.key, f.default)
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

    def list_candidates(self, params: Dict[str, Any]) -> Listing:
        """What the scan diffs onto the steps (``Listing``). A type that leaves a subject out for a transient
        reason overrides this and reports it as withheld; ``find_candidates`` then returns
        ``list_candidates(params).candidates``."""
        return Listing(self.find_candidates(params))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        """The type's own finished-test, used INSIDE ``find_candidates`` — the
        engine never calls it; a subject that drops off the candidate list is
        closed as fulfilled."""
        raise NotImplementedError

    def invalid_reason(self, key: str, params: Dict[str, Any]) -> str:
        """Why a stored step of this type is WRONG under today's rules ("" = valid). Wrong means the step
        must never run — its subject now belongs to another producer, or the key no longer names work this
        type can do — not merely "satisfied" (that is the scan's ``fulfilled``). The engine asks it before
        a step is submitted and in every validity pass (``engine.remove_invalid``) and drops a wrong step
        instead of running it. It must be cheap (no hub, no image read) and RAISE when it cannot judge:
        an unreadable roster must not read as "wrong"."""
        return ""

    def release_invalid(self, keys: List[str], params: Dict[str, Any], *,
                        explicit: bool, dry_run: bool) -> Dict[str, Any]:
        """Delete the files that belong ONLY to these wrong steps (``invalid_reason`` said so) — never a
        file anything else still reaches, and only inside the world's storage. ``explicit`` = a person
        asked (the "Remove invalid" click); ``dry_run`` only counts. Returns ``{"files": n, "bytes": n,
        "kept": [{"key", "why"}]}`` — ``kept`` names what stayed because something else reaches it."""
        return {"files": 0, "bytes": 0, "kept": []}

    #: The candidate-key heads whose second part is a character name (``character:<name>[:…]``).
    CHARACTER_KEY_HEADS = ("character", "base", "clothing", "outfit", "gallery")

    def subject_character(self, key: str) -> str:
        """The character a candidate works on, "" when it is no single character's (a location, a prop, an
        item shared by its wearers). The engine holds the steps of a character whose automatic generation is
        paused (Ruling A42); a type whose keys do not start ``<head>:<name>`` overrides this."""
        head, _sep, rest = str(key or "").partition(":")
        return rest.split(":", 1)[0] if head in self.CHARACTER_KEY_HEADS and rest else ""

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> Optional[str]:
        """Synchronous; returns only after the asset is persisted.  May raise
        BackendBusyError (step stays pending) or any other Exception (attempt).
        A non-empty string returned is the step's result note: it replaces
        the candidate's note once the step is done (a cleanup reports what it
        freed); None keeps the note as scanned."""
        raise NotImplementedError


class CandidateBusy(Exception):
    """The subject is being generated elsewhere right now — treat like busy."""


class CandidateRefused(Exception):
    """The subject's own gates refused it, or its chain recorded a failure
    automatic triggers honour — terminal.  The engine skips the step after
    this ONE attempt and marks it refused; only an explicit action (the
    Wardrobe, the 3D tab) may spend the subject again."""
