"""Model gallery — the shared file mechanics behind every 3D model store.

Locations/rooms (``location_model3d.py``) and props (``props.py``) keep their
models in the same shape, and used to implement it twice: SEVERAL timestamped
files per subject, a JSON sidecar next to each file, one ``selection.json``
naming the active file, and a ``__none__`` sentinel for "the admin chose no
model". This module owns that mechanism once; a store only says WHERE its
directory is and WHICH stem its files carry.

    <dir>/<stem>_<ts>.<ext>      the model files
    <dir>/<stem>_<ts>.json       one sidecar per file (created_at, source,
                                 tier, backend, face_num, texture_size, the
                                 admin's orientation/offset dials, …)
    <dir>/selection.json         {"<stem>": {"<tier>": "<filename>"}}

**Resolution tiers** (plan-3d-lod-und-betreten.md, 2026-08-03): a subject may
hold ONE file per tier — ``full`` (the modelled quality, the default for
everything that exists) and ``low`` (the overview/distance mesh). The tier
names are DATA: a selection may carry any tier string, ``TIERS`` only fixes
the order the fallback walks. A missing tier key means that tier does not
exist and the consumer takes the best available one; ``__none__`` on the
DEFAULT tier is the master switch that renders nothing at all.

Without a selection entry the NEWEST file of the stem is the default tier —
a store whose files were dropped in by hand still serves.
"""
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.core.model3d import MODEL_EXTS

# Named resolution tiers, in FALLBACK ORDER: a consumer that asks for a tier
# the subject does not have walks this list. `full` is the default — every
# model that existed before the tiers did is one.
TIERS = ("full", "low")
DEFAULT_TIER = "full"

SEL_FILE = "selection.json"
# Selection sentinel: the admin explicitly chose NO model for this stem —
# nothing is rendered instead of falling back to the newest file (a 404 on
# the meta route is the normal no-model state).
SEL_NONE = "__none__"


def normalize_tier(tier: Any) -> str:
    """A requested tier as a plain lowercase token ('' when unusable) — route
    input, never trusted. Unknown names are NOT rejected here: the gallery
    answers them with its best available tier."""
    t = str(tier or "").strip().lower()
    return t if re.fullmatch(r"[a-z0-9_-]{1,16}", t or "") else ""


def variant_urls(base_url: str, tiers: Sequence[str]) -> Dict[str, str]:
    """``{tier: "<base_url>?tier=<tier>"}`` — the ONE shape a resolution-tier
    URL has in every payload (scene models § B1, terrain scatter § A9).

    There is exactly one way to name a tier so there is exactly one way to
    resolve it: every consumer picks with the single ``pickVariant`` rule of
    ``@anima/scene-render``. Only tiers the subject actually HAS belong in
    here — an invented one is a 404 that looks like a configured model.

    A base URL that already carries a query (a prop's ``?variant=<i>``, E2.3)
    gets the tier appended to it instead of a second ``?``."""
    sep = "&" if "?" in base_url else "?"
    return {str(t): f"{base_url}{sep}tier={t}" for t in tiers if t}


def read_sidecar(model_path: Path) -> Dict[str, Any]:
    """The JSON sidecar next to a model file ({} when absent/unreadable)."""
    sp = model_path.with_suffix(".json")
    if sp.exists():
        try:
            meta = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                return meta
        except (OSError, ValueError):
            pass
    return {}


def write_sidecar(model_path: Path, meta: Dict[str, Any]) -> None:
    model_path.with_suffix(".json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


class ModelGallery:
    """One stem's gallery inside one directory.

    The directory is NOT created on construction — a read must never conjure
    a ghost directory; the write paths (``new_path``, ``select``) create it.

    An instance memoizes the directory listing and the selection file: a scene
    composition asks the same gallery a dozen questions in a row, and one
    prop placement should not cost a dozen reads. Instances are therefore
    SHORT-LIVED by contract — every store builds one per call.
    """

    def __init__(self, directory: Path, stem: str,
                 exts: Sequence[str] = MODEL_EXTS) -> None:
        self.dir = Path(directory)
        self.stem = stem
        self.exts = tuple(e.lstrip(".").lower() for e in exts)
        self._files: Optional[List[Path]] = None
        self._sel: Optional[Dict[str, Dict[str, str]]] = None

    # ── files ───────────────────────────────────────────────────────────

    def _name_re(self) -> re.Pattern:
        """``<stem>.<ext>`` (single-file legacy name) or ``<stem>_<ts>.<ext>``."""
        return re.compile(rf"^{re.escape(self.stem)}(_\d+)?\.({'|'.join(self.exts)})$")

    def matches(self, filename: str) -> bool:
        """The name belongs to THIS stem — also the route-level guard against
        path escapes and cross-stem deletes."""
        return bool(self._name_re().match(filename or ""))

    def _created_key(self, p: Path) -> float:
        """Sort key: sidecar created_at, falling back to file mtime."""
        ts = read_sidecar(p).get("created_at") or ""
        if ts:
            from app.core.timeutils import parse_iso
            try:
                return parse_iso(ts).timestamp()
            except (TypeError, ValueError):
                pass
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    def files(self) -> List[Path]:
        """All stored model files of the stem, newest first."""
        if self._files is None:
            if not self.dir.is_dir():
                self._files = []
            else:
                pat = self._name_re()
                found = [p for p in self.dir.iterdir()
                         if p.is_file() and pat.match(p.name)]
                self._files = sorted(found, key=self._created_key, reverse=True)
        return list(self._files)

    def file(self, filename: str) -> Optional[Path]:
        """ONE stored file by name — None when foreign or missing."""
        if not self.matches(filename):
            return None
        p = self.dir / filename
        return p if p.exists() else None

    def new_path(self, suffix: str = ".glb") -> Path:
        """Fresh timestamped target file; bumps the timestamp on a collision."""
        self._files = None
        self.dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        while True:
            p = self.dir / f"{self.stem}_{ts}{suffix}"
            if not p.exists():
                return p
            ts += 1

    # ── selection ───────────────────────────────────────────────────────

    def _read_all(self) -> Dict[str, Dict[str, str]]:
        """The whole selection file, stems whose value is not a tier object
        dropped (the pre-tier ``{stem: "<file>"}`` format was migrated once —
        see plan-3d-lod-und-betreten.md; nothing reads it any more)."""
        if self._sel is not None:
            return self._sel
        out: Dict[str, Dict[str, str]] = {}
        sp = self.dir / SEL_FILE
        raw: Any = {}
        if sp.exists():
            try:
                raw = json.loads(sp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
        if isinstance(raw, dict):
            for stem, value in raw.items():
                if isinstance(value, dict):
                    out[str(stem)] = {str(t): str(f) for t, f in value.items()
                                      if isinstance(f, str)}
        self._sel = out
        return out

    def _write_all(self, sel: Dict[str, Dict[str, str]]) -> None:
        self._sel = None
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / SEL_FILE).write_text(
            json.dumps(sel, indent=2, ensure_ascii=False), encoding="utf-8")

    def selection(self) -> Dict[str, str]:
        """``{tier: filename}`` of THIS stem (values may be ``__none__``)."""
        return dict(self._read_all().get(self.stem) or {})

    def tier_order(self, first: str = "") -> List[str]:
        """Fallback order: the requested tier, then the named tiers, then any
        further tier the selection carries."""
        order: List[str] = []
        for t in [first, *TIERS, *self.selection().keys()]:
            if t and t not in order:
                order.append(t)
        return order

    def none_selected(self) -> bool:
        """The admin explicitly chose NO model for this subject (sentinel on
        the default tier) — distinct from "no files stored"."""
        return self.selection().get(DEFAULT_TIER) == SEL_NONE

    def tier_declined(self, tier: str) -> bool:
        """The admin explicitly deselected THIS tier (sentinel) — the
        auto-LOD demand must not refill it (user finding 2026-08-20)."""
        t = normalize_tier(tier) or DEFAULT_TIER
        return self.selection().get(t) == SEL_NONE

    def select(self, filename: str, tier: str = DEFAULT_TIER) -> bool:
        """Make ``filename`` the active file of ``tier``. An EMPTY filename
        deselects: it persists the ``__none__`` sentinel — on the default
        tier that means "render nothing", on any other tier "this tier is
        DECLINED" (resolution falls through to the full model and the
        auto-LOD demand leaves it alone).
        False when a non-empty file does not belong to the stem or is
        missing."""
        tier = normalize_tier(tier) or DEFAULT_TIER
        sel = self._read_all()
        entry = dict(sel.get(self.stem) or {})
        if not filename:
            # EVERY tier persists the sentinel (user finding 2026-08-20):
            # dropping the entry made a deselected ``low`` indistinguishable
            # from a never-built one, so the auto-LOD demand rebuilt and
            # re-selected it on the next payload — the deselection never
            # stuck. With the sentinel the tier is DECLINED: resolution falls
            # through to the full model and the demand stays quiet.
            entry[tier] = SEL_NONE
        else:
            if not self.file(filename):
                return False
            entry[tier] = filename
        sel[self.stem] = entry
        self._write_all(sel)
        return True

    def find(self, tier: str = "", *, fallback: bool = True) -> Optional[Path]:
        """The active model file of ``tier``, or None.

        Active = the selection entry when it points at an existing file, else
        (default tier only) the newest stored file that no OTHER tier claims —
        so a store filled by hand keeps working. With ``fallback`` an unknown
        or empty tier gets the best available one (``TIERS`` order); the
        ``__none__`` sentinel on the default tier suppresses every tier, it is
        the admin's "no model" switch for the whole subject.
        """
        sel = self.selection()
        if sel.get(DEFAULT_TIER) == SEL_NONE:
            return None
        want = normalize_tier(tier) or DEFAULT_TIER
        order = self.tier_order(want) if fallback else [want]
        claimed = {name for t, name in sel.items()
                   if t != DEFAULT_TIER and name and name != SEL_NONE}
        for t in order:
            name = sel.get(t, "")
            if name and name != SEL_NONE:
                p = self.file(name)
                if p:
                    return p
            elif t == DEFAULT_TIER and not name:
                for p in self.files():
                    if p.name not in claimed:
                        return p
        return None

    def tiers(self) -> Dict[str, Path]:
        """``{tier: file}`` for every tier that resolves ON ITS OWN (no
        fallback) — what ``/model/meta`` publishes and what the scene payload
        turns into ``variants``. Empty when the subject has no model."""
        out: Dict[str, Path] = {}
        for t in self.tier_order():
            p = self.find(t, fallback=False)
            if p:
                out[t] = p
        return out

    def signature(self, tier: str = "") -> str:
        """Change key over the selection of ALL tiers (or one tier): file name
        + created_at per tier. A newly generated LOW variant moves it too —
        with the old single-file signature the clients never noticed."""
        parts = []
        for t, p in sorted(self.tiers().items()):
            if tier and t != tier:
                continue
            parts.append(f"{t}:{p.name}:{read_sidecar(p).get('created_at', '')}")
        return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]

    def tier_of(self, path: Path) -> str:
        """The tier a stored file was made for (sidecar; default ``full``)."""
        return normalize_tier(read_sidecar(path).get("tier")) or DEFAULT_TIER

    def selected_for(self, filename: str) -> List[str]:
        """Tiers whose active file is ``filename`` (admin gallery list)."""
        return sorted(t for t, name in self.selection().items()
                      if name == filename)

    def forget(self) -> None:
        """Drop this stem's WHOLE selection entry — for a stem that ceases to
        exist (a deleted prop model variant). ``select('')`` cannot do it: on
        the default tier it writes the ``__none__`` sentinel, which is a
        statement about a subject that is still there."""
        sel = self._read_all()
        if sel.pop(self.stem, None) is not None:
            self._write_all(sel)

    def delete(self, filename: str = "") -> bool:
        """Remove ONE stored file (+ its sidecar) or ALL files of the stem.
        A selection pointing at a removed file moves to the newest remaining
        one (default tier) or is dropped (any other tier) — never dangling."""
        removed = False
        if filename:
            p = self.file(filename)
            if not p:
                return False
            targets = [p]
        else:
            targets = self.files()
        self._files = None
        for p in targets:
            sidecar = p.with_suffix(".json")
            p.unlink()
            if sidecar.exists():
                sidecar.unlink()
            removed = True
        sel = self._read_all()
        entry = dict(sel.get(self.stem) or {})
        changed = False
        for t, name in list(entry.items()):
            if not name or name == SEL_NONE or (self.dir / name).exists():
                continue
            remaining = self.files()
            if t == DEFAULT_TIER and remaining:
                entry[t] = remaining[0].name
            else:
                entry.pop(t, None)
            changed = True
        if changed:
            sel[self.stem] = entry
            self._write_all(sel)
        return removed
