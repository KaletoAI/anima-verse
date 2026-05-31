"""API-Routes fuer das Rules-System (Blockade + Zwangs-Regeln)."""
import io
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query
from fastapi.responses import StreamingResponse

from app.models.rules import load_rules, add_rule, update_rule, delete_rule, get_rule

router = APIRouter(prefix="/rules", tags=["rules"])


# --- Rules CRUD ---
# (Status-Modifier wurden in /admin/prompt-filters konsolidiert — Zustaende-Tab
#  im Game Admin nutzt jetzt direkt die prompt_filters-Tabelle.)


def _normalize_target(value: Any) -> str:
    """Akzeptiert ``shared`` / ``world`` (alles andere → world)."""
    v = (str(value or "")).strip().lower()
    return "shared" if v == "shared" else "world"


@router.get("")
def list_rules_route() -> Dict[str, Any]:
    """Listet alle Regeln (Shared baseline + Welt-Overlay, mit ``_origin``)."""
    return {"rules": load_rules()}


@router.get("/{rule_id}")
def get_rule_route(rule_id: str) -> Dict[str, Any]:
    """Gibt eine einzelne Regel zurueck."""
    rule = get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Regel nicht gefunden")
    return {"rule": rule}


@router.post("")
async def create_rule_route(request: Request) -> Dict[str, Any]:
    """Erstellt eine neue Regel.

    Body: ``{"rule": {...}, "target": "world"|"shared"}`` — ``target`` defaults
    to ``world``. ``shared`` schreibt in ``shared/rules/rules.json``.
    """
    data = await request.json()
    rule = data.get("rule", {})
    target = _normalize_target(data.get("target", "world"))
    if not rule.get("name") or not rule.get("type"):
        raise HTTPException(status_code=400, detail="name und type sind Pflichtfelder")
    created = add_rule(rule, target_dir=target)
    return {"ok": True, "rule": created, "target": target}


@router.put("/{rule_id}")
async def update_rule_route(rule_id: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert eine Regel.

    Body: ``{"rule": {...}, "target": "world"|"shared"}``. ``world`` legt
    automatisch einen Override an, falls die Rule bisher nur in der Shared-
    Baseline existiert.
    """
    data = await request.json()
    updates = data.get("rule", {})
    target = _normalize_target(data.get("target", "world"))
    updated = update_rule(rule_id, updates, target_dir=target)
    if not updated:
        raise HTTPException(status_code=404, detail="Regel nicht gefunden")
    return {"ok": True, "rule": updated, "target": target}


@router.delete("/{rule_id}")
def delete_rule_route(rule_id: str, target: str = "") -> Dict[str, Any]:
    """Loescht eine Regel.

    Query-Parameter ``target``:
      - leer (default): Auto — Welt-Override zuerst, sonst Shared-Eintrag.
      - ``world``: nur den Welt-Eintrag entfernen (Shared bleibt sichtbar).
      - ``shared``: den Shared-Eintrag entfernen (gilt fuer alle Welten).
    """
    target_norm = (target or "").strip().lower()
    if target_norm not in ("", "world", "shared"):
        raise HTTPException(status_code=400, detail="target muss world|shared|leer sein")
    if delete_rule(rule_id, target_dir=target_norm):
        return {"ok": True, "target": target_norm or "auto"}
    raise HTTPException(status_code=404, detail="Regel nicht gefunden")


# ── Rule Import / Export ──

@router.get("/{rule_id}/export")
def export_rule_route(rule_id: str) -> StreamingResponse:
    """Streams a single-rule ZIP."""
    from app.core.content_io import export_rule_to_zip
    try:
        zip_bytes = export_rule_to_zip(rule_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{rule_id}.zip"'},
    )


@router.post("/import")
async def import_rule_route(
    file: UploadFile = File(...),
    overwrite: bool = Query(False),
    target: str = Query("auto"),
) -> Dict[str, Any]:
    """Import a single-rule ZIP."""
    from app.core.content_io import import_rule_from_zip
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()
    try:
        return import_rule_from_zip(content, target=target, overwrite=overwrite)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
