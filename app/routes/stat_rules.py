"""Admin adapters for template stat rules and world stat settings."""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core import stat_rules
from app.core.auth_dependency import require_admin

router = APIRouter(prefix='/admin/stat-rules', tags=['stat-rules'],
                   dependencies=[Depends(require_admin)])


async def _body(request):
    try:
        return await request.json()
    except ValueError as exc:
        raise HTTPException(400, detail=['Invalid JSON body']) from exc


@router.get('')
def get_rules():
    return stat_rules.build_admin_payload()


@router.put('/stat/{key}')
async def put_stat(key: str, request: Request):
    body = await _body(request)
    errors = stat_rules.validate_rule(body)
    if errors:
        raise HTTPException(400, detail=errors)
    return {'ok': stat_rules.save_stat_override(key, body)}


@router.delete('/stat/{key}')
def delete_stat(key: str):
    return {'ok': stat_rules.delete_stat_override(key)}


@router.put('/setting/{name}')
async def put_setting(name: str, request: Request):
    body = await _body(request)
    if not isinstance(body, dict) or set(body) != {'value'}:
        raise HTTPException(400, detail=['Body must contain value'])
    errors = stat_rules.validate_setting(name, body['value'])
    if errors:
        raise HTTPException(400, detail=errors)
    return {'ok': stat_rules.save_setting(name, body['value'])}


@router.delete('/setting/{name}')
def delete_setting(name: str):
    try:
        return {'ok': stat_rules.delete_setting(name)}
    except ValueError as exc:
        raise HTTPException(400, detail=[str(exc)]) from exc


world_router = APIRouter(prefix='/world', tags=['world'])


@world_router.get('/stat-keys')
def get_stat_keys():
    from app.core.stat_hints import get_all_stat_keys
    return {'keys': get_all_stat_keys()}
