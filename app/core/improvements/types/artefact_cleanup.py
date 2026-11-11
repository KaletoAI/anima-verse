"""``artefact_cleanup`` — orphaned derived files of the characters, removed
at idle time through the ONE collector (spec
docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.6).

The type makes no judgement of its own: the candidate rule IS the dry run of
``artefact_graph.collect`` and the step IS ``collect`` — reachability, the
protections (worn combination, live stages, hub ops, locks, the current base,
the equipped garments' current fsig, the grace window) and the painted-body
rule (a texture lives while a live outfit would paint it now, commit
72e260fb) all stay there. It never passes ``keys``.

Subjects: every character (``subjects.characters()``, pipeline or not) with
any of ``artefact_graph.ROOT_DIRS``; a character is a candidate when its dry
run lists orphans that are not all protected and was not ``aborted``. Plus,
with no character chosen, one world candidate for the shoe sources
(``footwear_source.collect``). ``grace`` ``on`` (default) = the sweep's
semantics (``explicit=False``: a node with a file younger than
``artefact_graph.GRACE_S`` is skipped — a run may be writing it); ``off`` =
the admin's explicit delete (``explicit=True``).

Both collectors run under ``artefact_graph.HOOK_BUDGET_S`` (read at call
time); a collect over it is abandoned without a delete — ``aborted``: no
candidate in a scan, ``CandidateBusy`` in a step. What the collector skips
(running, locked) is no failure: the step is done, its result note says so,
and the next scan lists what is still orphaned. ``needs_media`` is False —
CPU only, the entry keeps running with the media switch off.
"""
from pathlib import Path
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, CandidateBusy, ImprovementType, ParamField
from app.core.improvements.types import subjects

WORLD_KEY = "footwear_sources"
CHARACTER_PREFIX = "character:"
GRACE_ON, GRACE_OFF = "on", "off"


def _mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB"


def _budget() -> float:
    from app.core import artefact_graph
    return artefact_graph.HOOK_BUDGET_S


def _dry_run(name: str, explicit: bool) -> Dict[str, Any]:
    """The collector's dry run of ``name`` (nothing deleted)."""
    from app.core import artefact_graph
    return artefact_graph.collect(name, dry_run=True, explicit=explicit, reason="improvements preview",
                                  budget_s=_budget())


def _deletable(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The orphans a collect would delete now: not ``protected``."""
    return [e for e in report.get("orphans") or [] if not e.get("protected")]


def _character_candidate(name: str, report: Dict[str, Any]) -> Candidate:
    from app.core.artefact_graph import CATEGORIES
    gone = _deletable(report)
    files = sum(int(e.get("files") or 0) for e in gone)
    size = sum(int(e.get("bytes") or 0) for e in gone)
    parts = []
    for category in CATEGORIES:
        group = [e for e in gone if e.get("category") == category]
        if group:
            parts.append(f"{category} {len(group)} ({_mb(sum(int(e.get('bytes') or 0) for e in group))})")
    n = len(gone)
    return Candidate(f"{CHARACTER_PREFIX}{name}",
                     f"{name} · {n} node{'' if n == 1 else 's'} · {files} file(s) · {_mb(size)}",
                     hub_jobs=0, note=" · ".join(parts))


def _tree_size(path: Path) -> int:
    try:
        if path.is_dir() and not path.is_symlink():
            return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        return path.stat().st_size
    except OSError:
        return 0


def _world_candidate() -> List[Candidate]:
    """The shoe sources' dry run as one candidate (sizes read here: the dry
    run reports none), or nothing when it would remove nothing."""
    from app.core import footwear_source
    removed = footwear_source.collect(dry_run=True).get("removed") or []
    if not removed:
        return []
    size = sum(_tree_size(Path(p)) for p in removed)
    return [Candidate(WORLD_KEY, f"Shoe sources · {len(removed)} folder(s) · {_mb(size)}", hub_jobs=0,
                      note=f"world footwear sources {len(removed)} ({_mb(size)})")]


def _has_roots(name: str) -> bool:
    from app.core.artefact_graph import ROOT_DIRS
    from app.models.character import get_character_dir
    try:
        root = get_character_dir(name)
    except Exception:  # noqa: BLE001 — a vanished character has nothing to clean
        return False
    return any((root / d).is_dir() for d in ROOT_DIRS)


class ArtefactCleanup(ImprovementType):
    id = "artefact_cleanup"
    label = "Clean up orphaned derived files"
    needs_media = False

    @property
    def params_schema(self) -> List[ParamField]:
        return [
            ParamField("character", "Character", "enum",
                       [{"value": "", "label": "All characters"}] +
                       [{"value": n, "label": n} for n in subjects.characters()], required=False),
            ParamField("grace", "Grace window", "enum",
                       [{"value": GRACE_ON, "label": "On — skip files younger than 10 minutes"},
                        {"value": GRACE_OFF, "label": "Off — delete like an explicit cleanup"}],
                       required=False, default=GRACE_ON),
        ]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        if out.get("character") and out["character"] not in subjects.characters():
            raise ValueError("Character not found")
        out["grace"] = out.get("grace") or GRACE_ON
        return out

    def _names(self, params: Dict[str, Any]) -> List[str]:
        wanted = params.get("character") or ""
        return [n for n in subjects.characters() if (not wanted or n == wanted) and _has_roots(n)]

    @staticmethod
    def _explicit(params: Dict[str, Any]) -> bool:
        return (params.get("grace") or GRACE_ON) == GRACE_OFF

    # --- candidates ------------------------------------------------------------

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        explicit = self._explicit(params)
        out: List[Candidate] = []
        for name in self._names(params):
            report = _dry_run(name, explicit)
            if report.get("aborted") or not _deletable(report):
                continue
            out.append(_character_candidate(name, report))
        if not params.get("character"):
            out += _world_candidate()
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        if candidate.key == WORLD_KEY:
            return not _world_candidate()
        name = candidate.key.removeprefix(CHARACTER_PREFIX)
        if name not in self._names(params):
            return True
        report = _dry_run(name, self._explicit(params))
        return bool(report.get("aborted")) or not _deletable(report)

    # --- apply -----------------------------------------------------------------

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> str:
        """One collect; returns the step's result note (deleted files, freed
        bytes, skipped nodes)."""
        if candidate.key == WORLD_KEY:
            from app.core import footwear_source
            report = footwear_source.collect()
        else:
            from app.core import artefact_graph
            name = candidate.key.removeprefix(CHARACTER_PREFIX)
            report = artefact_graph.collect(name, dry_run=False, explicit=self._explicit(params),
                                            reason="improvements cleanup", budget_s=_budget())
            if report.get("aborted"):
                raise CandidateBusy(f"{name}: {report['aborted']}")
        return (f"deleted {int(report.get('deleted_files') or 0)} file(s), "
                f"freed {_mb(int(report.get('freed_bytes') or 0))}, "
                f"{len(report.get('skipped') or [])} skipped")
