"""The CUT of a template top, without its drape: the pattern pieces (``islands.json``) in seconds (cut-first, 2026-11-21).

A top's pattern-piece UVs are assigned to the cut panels BEFORE the cloth run (``garment_template_build.run``:
``build_bodice`` -> ``clear_of_body`` -> ``pattern_uv_of``); the drape only moves vertices. So the islands depend on
the cut alone, and the "texture from cut" (``garment_cut_texture``) need not wait for a drape: the same builder runs
with ``cut_only`` (it stops after the pattern UVs — no collider drape, no pose shapes, no bake, no export) on the CPU,
in a Blender slot, never a hub job and never the piece's hub-job claim (``piece_jobs``): it may run beside a drape
and beside the cut-texture flow of another piece.

The CUT SIGNATURE (``cut_sig``) is exactly what the cut reads (derived from ``garment_template_build.run`` up to
``pattern_uv_of`` and from ``garment_template.build_args`` / ``panel_spec``):

- the parameters as the drape key has them (``garment_template.keyed_params``: without ``TEXTURE_ONLY`` /
  ``MATERIAL_ONLY`` and the fields of other kinds) minus ``DRAPE_ONLY`` — ``fabric`` reaches the builder only as the
  cloth settings (``fabric``, ``drape_quality``), read after the cut. Every other field shapes ``panel_spec`` (the
  pattern), ``slit`` or ``uv_mode``;
- the base model sha256 (the body the panels are wrapped round and laid out of; ``measure_body`` reads it too);
- the lower-layer tokens of the drape key (``garment_template.under_tokens``: the drapes / fits under the piece are
  the colliders ``clear_of_body`` lays the panels out of, the jacket allowance shapes ``panel_spec``, the chest
  shaping shapes the body) plus which lower template drapes are READY (only those are handed over as colliders);
  while one is still to be draped there is no sig (``WAITING_LOWER``: the Build drapes it first, ``sig_of``);
- ``TEMPLATE_VERSION`` and the flattening's key (``uv_pattern_key``): a fitted piece's is ``UV_PATTERN_SHA`` (md5 of
  ``app/blender/scripts/uv_pattern.py``: any change of the flattening re-cuts it, seconds); a top's is
  ``TOP_UV_PATTERN_SHA``, the md5 of the ``uv_pattern.py`` that last changed a top's islands — the step 3a additions
  (the fitted kinds' parts, rows, ring strips, direct solves) leave a top's islands byte-identical, and keying the top
  on the whole file re-draped every top once for nothing (decision D7 b).

NOT in it: the views / item picture (the drape key's texture part), ``fabric``, ``opacity``, ``texture``,
``sleeve_print``, ``fly``, the drape's frames / quality / poses / shape groups.

Files under ``templates/cut/`` (beside the cut-texture records, whose 12-hex csig names never end in these suffixes):
``{item}_{cutsig}.islands.json`` (the builder's bytes), ``.cut.json`` (the record: state, metrics, wall seconds) and
``.pattern.png`` (the debug pattern sheet, ``garment_cut_texture.render_pattern_sheet``); a jacket's / dress's / covered
top's cut also ``.marks.json`` (step 3c, B11: the placket lines in atlas pixels, ``marks_file``; never part of the islands' bytes).

A drape records the sig of the cut it was laid out of (``cut_sig``); one whose recorded sig differs from the
current one (a new flattening, a lower layer that became ready) is stale for ``garment_template.drape_state``
and the next Build drapes it again — the drape key (``tsig``) stays, so no other drape moves.

A drape of the same cut writes the same islands bytes (``scripts/smoke_template_cut_first.py`` proves it on a real
body), so the cut atlas — keyed by the islands sha (``garment_cut_texture.csig``) — fits every drape of that cut and
no other. A drape whose own-mesh colliders had to be shrunk or dropped (``drape_with_fallback``) was laid out of other
colliders: its islands differ, and ``garment_template.cut_info`` says so.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("garment_template_cut")

#: The parameters the builder reads only for the cloth run (after the cut): never in ``cut_sig``.
DRAPE_ONLY = ("fabric",)
UV_PATTERN_FILE = Path(__file__).resolve().parents[1] / "blender" / "scripts" / "uv_pattern.py"
#: md5[:12] of the flattening code (part of ``cut_sig``; the core never imports the Blender scripts).
UV_PATTERN_SHA = hashlib.md5(UV_PATTERN_FILE.read_bytes()).hexdigest()[:12]
#: md5[:12] of the ``uv_pattern.py`` that last changed a top's islands (c926b67f0) — a top's cut key. Bump it to the
#: new file's md5 (and ``scripts/smoke_uv_pattern.py`` [21]'s base commit to the new one) only when a change alters a
#: top's islands: [21] fails then, as it compares a top's payload with that commit's flattening.
TOP_UV_PATTERN_SHA = "9f1a4a8ce3b8"
FITTED_PATTERN_FILE = UV_PATTERN_FILE.parent / "fitted_pattern.py"
#: md5[:12] of the fitted kinds' part rules (step 3a; in ``cut_sig`` of a fitted piece only).
FITTED_PATTERN_SHA = hashlib.md5(FITTED_PATTERN_FILE.read_bytes()).hexdigest()[:12]
#: A cut that does not end in this many seconds is left (measured ~10 s; the slot wait comes on top).
CUT_TIMEOUT_S = 180
#: After a run that judged nothing (timeout, Blender missing or interrupted) the cut is not started again for so
#: long — the dialog polls, and a poll must not start Blender over and over.
RETRY_AFTER_S = 300.0

#: The words of the cut's states (English; the React dialog puts them through ``t()``).
CUTTING = "Cutting the pattern (CPU, 0 hub jobs)"
NOT_CUT = "The pattern is not cut yet — it is cut when the dialog opens or the parameters are saved (CPU, 0 hub jobs)"
CUT_FAILED = "Cutting the pattern failed: {error}"
CUT_LEFT = "Cutting the pattern stopped ({outcome}) — it is cut again when the dialog is opened"
NO_PATTERN = "This kind is not cut into pattern pieces — it keeps its projection texture"
#: A lower template layer is not draped yet: the next Build drapes it first and lays this piece out of it, so a cut
#: made now would differ from the drape the Build makes.
WAITING_LOWER = "Waiting for the layers under it to be draped — the next Build drapes them, then the pattern is cut"
#: B11 (phase E): a cut made before the builder wrote the placket line (its record has no "marks" key) of a piece that
#: wants a placket is cut ONCE more under the same sig — CPU, seconds; its islands must come out byte-identical.
MARKS_MISSING = "Writing the placket line into the cut (CPU, 0 hub jobs)"
MARKS_ISLANDS_CHANGED = "islands changed while writing marks"

_lock = threading.Lock()
#: (character, item, cut sig) -> "running"
_running: Dict[Tuple[str, str, str], str] = {}
#: (character, item, cut sig) -> (monotonic time, outcome) of a run that judged nothing
_left: Dict[Tuple[str, str, str], Tuple[float, str]] = {}


def cut_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """The parameters the cut is keyed by (module docstring)."""
    from app.core import garment_template as gt
    return {k: v for k, v in gt.keyed_params(params).items() if k not in DRAPE_ONLY}


def uv_pattern_key(params: Dict[str, Any]) -> str:
    """The flattening's part of the cut key (module docstring): ``UV_PATTERN_SHA`` for a fitted kind and a panel piece
    (step 3b, ``garment_template.panel_piece``: a skirt, a strapless top), ``TOP_UV_PATTERN_SHA`` for a top with a
    bodice."""
    from app.core import garment_template as gt
    live = params.get("kind") in gt.FITTED_KINDS or gt.panel_piece(params)
    return UV_PATTERN_SHA if live else TOP_UV_PATTERN_SHA


def cut_sig(params: Dict[str, Any], *, base_sha: str, lower: List[str]) -> str:
    """The cut signature (module docstring): md5[:12]; ``lower`` = the drape key's lower-layer tokens."""
    from app.core import garment_template as gt
    payload = {"params": cut_params(params), "version": gt.TEMPLATE_VERSION,
               "uv_pattern": uv_pattern_key(params),
               "base": base_sha, "lower": sorted(lower)}
    if params.get("kind") in gt.FITTED_KINDS:
        # step 3a: a fitted piece's cut also follows its own version and the part rules (``fitted_pattern.py``)
        payload["fitted"] = gt.FITTED_VERSION
        payload["fitted_pattern"] = FITTED_PATTERN_SHA
    if gt.panel_piece(params):
        # step 3b (B16): a panel piece's cut follows the panel version (``garment_template.PANEL_VERSION``)
        payload["panels"] = gt.PANEL_VERSION
    if gt.neck_piece(params):
        # phases E + F: a covered top's neck ring (the B8 neckband, the stand-collar strip, the placket line)
        payload["neck"] = gt.NECK_VERSION
    return hashlib.md5(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


def sig_of(character_name: str, item_id: str, params: Dict[str, Any], *, base_sha: str, lower: List[str],
           item: Optional[Dict[str, Any]] = None, wait: bool = True) -> Tuple[Optional[str], str, List[str]]:
    """``(cut sig | None, reason, under tokens)`` of a piece within the worn set ``lower`` — the ONE rule for the cut
    (``cut_key``) and for the cut a drape was laid out of (``garment_template._build_drape``, its record's
    ``cut_sig``; ``garment_template.drape_state`` compares the two).

    - not a ``PATTERN_KINDS`` kind -> ``NO_PATTERN`` — never a Blender run (step 3b: a strapless top is cut by
      ``wrap``);
    - ``wait`` and a lower template layer in state "missing" (the next Build drapes it first and lays this piece out
      of it) -> ``WAITING_LOWER``: a cut made now would differ from the drape the Build makes;
    - else the sig of ``under_tokens`` plus one ``collider:<item>`` token per lower template layer that is READY —
      the colliders a cut / a drape is really handed (a failed or blocked layer is none). A layer that becomes ready
      later (a Retry, the same drape key) so changes the cut, and the drape laid out without it is stale.
    ``wait=False`` (the drape's record) gives the sig of what the drape WAS laid out of even when a layer was left
    due. ``item`` None reads the item (live E2E 2026-11-21, Kai: ``drape_state`` / the Build's plan pass none, and
    without it the chest shaping's token was missing — the sig differed from the drape's recorded ``cut_sig``, so
    every Build re-draped the shirt as "cut anew")."""
    from app.core import garment_template as gt
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id)
    if params["kind"] not in gt.PATTERN_KINDS:
        return None, NO_PATTERN, []
    states = gt.collider_states(character_name, item_id, params["kind"], lower, base_sha=base_sha)
    if wait and any(sub["state"] == "missing" for _o, _it, sub in states):
        return None, WAITING_LOWER, []
    under = gt.under_tokens(character_name, item_id, params, base_sha=base_sha, lower=lower, item=item,
                            states=states)
    tokens = under + [f"collider:{other}" for other, _it, sub in states if sub["state"] == "ready"]
    return cut_sig(params, base_sha=base_sha, lower=tokens), "", under


def cut_dir(character_name: str) -> Path:
    from app.core import garment_template as gt
    return gt.templates_dir(character_name) / "cut"


def _file(character_name: str, item_id: str, sig: str, suffix: str) -> Path:
    return cut_dir(character_name) / f"{item_id}_{sig}{suffix}"


def islands_file(character_name: str, item_id: str, sig: str) -> Path:
    return _file(character_name, item_id, sig, ".islands.json")


def marks_file(character_name: str, item_id: str, sig: str) -> Path:
    """Step 3c (B11): the placket lines of a jacket's / dress's cut (``marks.json`` of the builder; not part of the
    islands' bytes or sha)."""
    return _file(character_name, item_id, sig, ".marks.json")


def record_file(character_name: str, item_id: str, sig: str) -> Path:
    return _file(character_name, item_id, sig, ".cut.json")


def sheet_file(character_name: str, item_id: str, sig: str) -> Path:
    return _file(character_name, item_id, sig, ".pattern.png")


def cut_key(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None,
            item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the piece's cut is made of now: ``{sig, reason, params, base, base_sha, lower, under, item}`` — ``sig``
    None with the plain ``reason`` when it cannot be cut (no parameters, not a pattern kind or a strapless top, no
    plain body, a lower layer still to be draped — ``sig_of``). ``lower``
    is the worn set under the rule of the drape key (``garment_template.lower_layers``; [] while not worn)."""
    from app.core import base_body, figure
    from app.core import garment_template as gt
    from app.models.character import get_character_profile
    from app.models.inventory import get_item
    item = item if item is not None else get_item(item_id)
    params = gt.params_of(item)
    out: Dict[str, Any] = {"sig": None, "reason": "", "params": params, "base": None, "base_sha": "", "lower": [],
                           "under": [], "item": item}
    if params is None:
        out["reason"] = gt.NEEDS_PARAMS
        return out
    if params["kind"] not in gt.PATTERN_KINDS:
        out["reason"] = NO_PATTERN
        return out
    profile = profile if profile is not None else (get_character_profile(character_name) or {})
    base = base_body.current_base(character_name, profile=profile)
    if not base:
        out["reason"] = gt.NO_BASE
        return out
    sets = figure.worn_sets(character_name, profile=profile)
    worn = item_id in set(sets.pieces.values())
    lower = gt.lower_layers(sets.own, item_id) if worn else []
    sig, reason, under = sig_of(character_name, item_id, params, base_sha=base[1], lower=lower, item=item)
    out.update(sig=sig, reason=reason, base=base, base_sha=base[1], lower=lower, under=under)
    return out


def read_record(character_name: str, item_id: str, sig: str) -> Dict[str, Any]:
    try:
        data = json.loads(record_file(character_name, item_id, sig).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def state(character_name: str, item_id: str, *, key: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The piece's cut now: ``{state, reason, cut_sig, islands_path, islands_sha, cut_at, wall_s, record}`` —
    ``state`` "ready" (its islands on disk), "cutting" (a run in this process), "missing", "failed" (a run that
    judged the input: its error) or "blocked" (``cut_key``'s reason). ``islands_path`` only when ready."""
    key = key if key is not None else cut_key(character_name, item_id)
    sig = key["sig"]
    out: Dict[str, Any] = {"state": "blocked", "reason": key["reason"], "cut_sig": sig, "islands_path": None,
                           "islands_sha": "", "cut_at": "", "wall_s": None, "record": {}}
    if sig is None:
        return out
    record = read_record(character_name, item_id, sig)
    path = islands_file(character_name, item_id, sig)
    if record.get("state") == "ready" and path.is_file() and (record.get("islands") or {}).get("sha256") \
            and not marks_due(key.get("params"), record, marks_file(character_name, item_id, sig)):
        out.update(state="ready", reason="", islands_path=path, islands_sha=str(record["islands"]["sha256"]),
                   cut_at=str(record.get("created_at") or ""), wall_s=record.get("wall_s"), record=record)
        return out
    with _lock:
        running = _running.get((character_name, item_id, sig)) == "running"
        left = _left.get((character_name, item_id, sig))
    if running:
        out.update(state="cutting", reason=CUTTING)
    elif record.get("state") == "failed":
        out.update(state="failed", reason=CUT_FAILED.format(error=record.get("error") or "?"), record=record)
    elif left is not None:
        out.update(state="missing", reason=CUT_LEFT.format(outcome=left[1]))
    elif record.get("state") == "ready":
        out.update(state="missing", reason=MARKS_MISSING)
    else:
        out.update(state="missing", reason=NOT_CUT)
    return out


def marks_due(params: Optional[Dict[str, Any]], record: Dict[str, Any], marks: Path) -> bool:
    """B11: a ready cut whose placket line is still to be written — the piece wants a placket, the line is not on disk,
    and the cut was made before the builder wrote lines (no "marks" key in its record; ``run`` records whether it
    wrote one, so a cut that had none to write is never cut again)."""
    return bool(params) and str(params.get("placket") or "none") != "none" and "marks" not in record \
        and not marks.is_file()


def run_blender(body_glb: Path, params: Dict[str, Any], *, item_id: str, out_dir: Path,
                colliders: Optional[List[Tuple[Path, Any]]] = None, own: Optional[List[Tuple[Path, Any]]] = None,
                over_sleeves: bool = False, timeout_s: int = CUT_TIMEOUT_S) -> Dict[str, Any]:
    """ONE cut-only run of ``garment_template_build`` with the inputs a drape's first attempt gets
    (``garment_template._run_drape_once`` / ``drape_with_fallback`` "full": the template drapes under it, then the
    own-mesh fits at offset 0). ``{ok, outcome, error, data, islands (Path | None), log_tail, wall_s, slot_wait_s,
    measure_s}`` — ``wall_s`` the whole call less the slot wait."""
    from app.blender import runner
    from app.core import garment_template as gt
    started = time.time()
    meas = gt.measure_body(Path(body_glb).read_bytes())
    spec = gt.panel_spec(params, meas, over_sleeves=over_sleeves)
    measure_s = round(time.time() - started, 2)
    cols = list(colliders or []) + list(own or [])
    offsets = [0.0] * len(cols) if own else None
    args = gt.build_args(params, spec, item_id=item_id, lower_shapes=[payload for _p, payload in cols],
                         lower_offsets=offsets)
    args["cut_only"] = True
    inputs = {"body": Path(body_glb)}
    for i, (path, _payload) in enumerate(cols):
        inputs[f"lower_{i}"] = Path(path)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    res = runner.run(gt.SCRIPT, inputs=inputs, params=args, out_dir=Path(out_dir), timeout_s=timeout_s)
    islands = (res.get("outputs") or {}).get("islands")
    marks = (res.get("outputs") or {}).get("marks")
    wait = float(res.get("slot_wait_s") or 0.0)
    return {"ok": bool(res.get("ok")) and bool(islands) and Path(islands).is_file(),
            "outcome": res.get("outcome"), "error": str(res.get("error") or ("" if islands else "no islands written")),
            "data": dict(res.get("data") or {}), "islands": Path(islands) if islands else None,
            "marks": Path(marks) if marks and Path(marks).is_file() else None,
            "log_tail": res.get("log_tail") or "", "wall_s": round(time.time() - started - wait, 2),
            "slot_wait_s": round(wait, 2), "measure_s": measure_s}


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def run(character_name: str, item_id: str) -> Dict[str, Any]:
    """Cut the piece now (synchronous; ``schedule`` runs it in a thread): the colliders a drape would get (the ready
    template drapes under it, the own-mesh fits under it, the chest-shaped body), one ``run_blender``, then the
    islands, the pattern sheet and the record under ``templates/cut/``. A ready cut is kept. Returns ``state``."""
    from app.blender import outcome as oc
    from app.core import bust_shaping
    from app.core import garment_template as gt
    from app.core.timeutils import utc_now_iso
    from app.models.character import get_character_dir
    key = cut_key(character_name, item_id)
    sig = key["sig"]
    if sig is None:
        return state(character_name, item_id, key=key)
    current = state(character_name, item_id, key=key)
    if current["state"] == "ready":
        return current
    # B11: a ready cut without its placket line is cut again under the same sig — its islands must not move
    before = read_record(character_name, item_id, sig)
    old_raw = islands_file(character_name, item_id, sig).read_bytes() \
        if current["reason"] == MARKS_MISSING and before.get("state") == "ready" else None
    params, item, lower, base = key["params"], key["item"], key["lower"], key["base"]
    colliders: List[Tuple[Path, Any]] = []
    ready = []
    for _other, it, sub in gt.collider_states(character_name, item_id, params["kind"], lower,
                                              base_sha=key["base_sha"]):
        if sub["state"] == "ready" and sub.get("path"):
            colliders.append((Path(sub["path"]), (sub.get("record") or {}).get("pose_shapes")))
            ready.append(it)
    own = [(fit, None) for _o, fit in gt.own_colliders(character_name, item_id, params["kind"], lower,
                                                        base_sha=key["base_sha"]) if fit is not None]
    body = get_character_dir(character_name) / "model3d" / f"{base[0]}.glb"
    scratch = Path(tempfile.mkdtemp(prefix="av-cut-"))
    try:
        shaped, shaping, _note = bust_shaping.prepare(body, item_id, item, lower, scratch / "shaping")
        res = run_blender(shaped, params, item_id=item_id, out_dir=scratch / "run", colliders=colliders, own=own,
                          over_sleeves=gt.over_sleeved_layer(params["kind"], ready))
        record: Dict[str, Any] = {"item_id": item_id, "cut_sig": sig, "params": params,
                                  "version": gt.TEMPLATE_VERSION, "uv_pattern": uv_pattern_key(params),
                                  "base_signature": base[0], "base_model_sha256": key["base_sha"], "lower": lower,
                                  "under": key["under"], "colliders": [Path(c[0]).name for c in colliders + own],
                                  **({"shaping": shaping} if shaping else {}),
                                  "metrics": res["data"], "wall_s": res["wall_s"], "slot_wait_s": res["slot_wait_s"],
                                  "created_at": utc_now_iso()}
        if res["ok"] and old_raw is not None and res["islands"].read_bytes() != old_raw:
            record.update(state="failed", error=MARKS_ISLANDS_CHANGED, outcome="rejected", log_tail="",
                          islands_kept={"sha256": hashlib.sha256(old_raw).hexdigest()})
            _write_atomic(record_file(character_name, item_id, sig), json.dumps(record, indent=1).encode("utf-8"))
            logger.warning("Cut %s %s: %s", character_name, item_id, MARKS_ISLANDS_CHANGED)
        elif res["ok"]:
            raw = res["islands"].read_bytes()
            _write_atomic(islands_file(character_name, item_id, sig), raw)
            record["marks"] = bool(res.get("marks"))
            if res.get("marks"):
                _write_atomic(marks_file(character_name, item_id, sig), res["marks"].read_bytes())
            try:
                from app.core import garment_cut_texture as gct
                _write_atomic(sheet_file(character_name, item_id, sig),
                              gct._png(gct.render_pattern_sheet(json.loads(raw))))
            except Exception as e:  # noqa: BLE001 — the sheet is rendered again on demand
                logger.warning("Cut %s %s: pattern sheet not rendered: %s", character_name, item_id, e)
            record.update(state="ready", islands={"file": islands_file(character_name, item_id, sig).name,
                                                   "sha256": hashlib.sha256(raw).hexdigest(),
                                                   "px_per_cm": json.loads(raw).get("px_per_cm")})
            _write_atomic(record_file(character_name, item_id, sig), json.dumps(record, indent=1).encode("utf-8"))
            logger.info("Cut %s %s (%s): %s s", character_name, item_id, sig, res["wall_s"])
        elif oc.is_retryable(res["outcome"]):
            with _lock:
                _left[(character_name, item_id, sig)] = (time.monotonic(), str(res["outcome"]))
            logger.warning("Cut %s %s left (%s): %s", character_name, item_id, res["outcome"], res["error"])
        else:
            record.update(state="failed", error=res["error"], outcome=res["outcome"], log_tail=res["log_tail"])
            _write_atomic(record_file(character_name, item_id, sig), json.dumps(record, indent=1).encode("utf-8"))
            logger.warning("Cut %s %s failed: %s", character_name, item_id, res["error"])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return state(character_name, item_id)


def schedule(character_name: str, item_id: str, *, runner=None) -> Dict[str, Any]:
    """Start the cut in a thread when it is missing (the dialog opened, the parameters saved): never twice for one
    key, never again for a failed key (new parameters make a new key), not within ``RETRY_AFTER_S`` after a run that
    judged nothing. CPU only — no hub job, no ``piece_jobs`` claim. Returns the piece's ``state`` after the call
    ("cutting" when it started)."""
    key = cut_key(character_name, item_id)
    sig = key["sig"]
    now = state(character_name, item_id, key=key)
    if sig is None or now["state"] in ("ready", "cutting", "failed"):
        return now
    k = (character_name, item_id, sig)
    with _lock:
        if _running.get(k) == "running":
            return {**now, "state": "cutting", "reason": CUTTING}
        left = _left.get(k)
        if left is not None and time.monotonic() - left[0] < RETRY_AFTER_S:
            return now
        _left.pop(k, None)
        _running[k] = "running"
    fn = runner or run

    def work() -> None:
        try:
            fn(character_name, item_id)
        except Exception as e:  # noqa: BLE001 — the dialog shows the missing cut; the log says why
            logger.warning("Cut %s %s: %s", character_name, item_id, e)
            with _lock:
                _left[k] = (time.monotonic(), type(e).__name__)
        finally:
            with _lock:
                _running.pop(k, None)

    threading.Thread(target=work, name=f"template-cut-{item_id}", daemon=True).start()
    return {**now, "state": "cutting", "reason": CUTTING}


#: How often ``ensure`` looks whether a cut started elsewhere (the dialog's ``schedule``) has ended.
ENSURE_POLL_S = 1.0


def ensure(character_name: str, item_id: str, *, timeout_s: float = CUT_TIMEOUT_S * 3,
           poll_s: float = ENSURE_POLL_S, runner=None, retry_failed: bool = False) -> Dict[str, Any]:
    """The Build's way to the cut (cut-texture Build step, 2026-11-21): the piece's cut NOW, synchronously — a ready
    cut is returned as it is; a cut that runs in another thread (the dialog's ``schedule``) is waited for, never
    started twice; a missing cut is run here under the same ``_running`` mark ``schedule`` honours (a dialog poll
    meanwhile reads "cutting"). Unlike ``schedule`` a Build ignores ``RETRY_AFTER_S`` (a Build is a deliberate run).
    A cut that failed for its key is returned as it is — an automatic Build never re-runs it — unless
    ``retry_failed`` (a MANUAL Build): then it is run ONCE more here (a run another thread had started meanwhile is
    waited for instead, and its result stands). Returns the piece's ``state`` afterwards ("ready" / "failed" /
    "missing" / "blocked"); "missing" with the waiting reason when ``timeout_s`` ran out."""
    import time as _time
    deadline = _time.monotonic() + timeout_s
    fn = runner or run
    retry = bool(retry_failed)
    while True:
        key = cut_key(character_name, item_id)
        sig = key["sig"]
        now = state(character_name, item_id, key=key)
        if sig is None or now["state"] == "ready" or (now["state"] == "failed" and not retry):
            return now
        k = (character_name, item_id, sig)
        with _lock:
            mine = _running.get(k) != "running"
            if mine:
                _left.pop(k, None)
                _running[k] = "running"
        retry = False           # one re-run at most: ours below, or the one running elsewhere
        if mine:
            try:
                fn(character_name, item_id)
            except Exception as e:  # noqa: BLE001 — the state says what is left; the log says why
                logger.warning("Cut %s %s (Build): %s", character_name, item_id, e)
                with _lock:
                    _left[k] = (_time.monotonic(), type(e).__name__)
            finally:
                with _lock:
                    _running.pop(k, None)
            return state(character_name, item_id)
        if _time.monotonic() >= deadline:
            return {**now, "state": "missing", "reason": CUTTING}
        _time.sleep(poll_s)
