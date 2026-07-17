"""Assist endpoints for the Game-Admin side panels (Translate / Prompt Help).

Small helper-LLM utilities, pure request/response — nothing is persisted:

- ``POST /admin/assist/translate``    → free-text translation via the
  ``translation`` task ("Translation — Small Helper Model" routing).
- ``POST /admin/assist/prompt-help``  → image-prompt improvement (always
  answered in English) via the ``image_prompt`` task ("Image Prompt
  Enhancer — Small Helper Model" routing).

Both endpoints are sync ``def`` on purpose: ``llm_call`` blocks on the
provider queue, FastAPI runs them in its threadpool.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth_dependency import require_admin
from app.core.log import get_logger

logger = get_logger("assist")

router = APIRouter(prefix="/admin/assist", tags=["assist"],
                   dependencies=[Depends(require_admin)])


def _language_label(code: str) -> str:
    """Resolve a language code ("de") to its English name ("German") for the
    LLM prompt. Unknown values pass through unchanged so free-text language
    names keep working."""
    from app.core.i18n import list_languages
    for entry in list_languages():
        if entry.get("value") == code:
            return str(entry.get("label") or code)
    return code


class TranslateRequest(BaseModel):
    text: str
    source_lang: str = ""   # language code, empty = auto-detect
    target_lang: str = "en"


@router.post("/translate")
def translate(req: TranslateRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")

    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task

    source = (req.source_lang or "").strip()
    system_prompt, user_prompt = render_task(
        "translate_text",
        text=text,
        source_lang=_language_label(source) if source else "",
        target_lang=_language_label((req.target_lang or "en").strip()))
    try:
        resp = llm_call(task="translation", system_prompt=system_prompt,
                        user_prompt=user_prompt, label="admin-translate")
    except RuntimeError as e:
        logger.warning("translate failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    return {"text": (resp.content or "").strip()}


class PromptHelpRequest(BaseModel):
    prompt: str
    request: str = ""   # optional natural-language improvement request


@router.post("/prompt-help")
def prompt_help(req: PromptHelpRequest):
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task

    system_prompt, user_prompt = render_task(
        "prompt_helper",
        original_prompt=prompt,
        improvement_request=(req.request or "").strip())
    try:
        resp = llm_call(task="image_prompt", system_prompt=system_prompt,
                        user_prompt=user_prompt, label="admin-prompt-help")
    except RuntimeError as e:
        logger.warning("prompt-help failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    improved = (resp.content or "").strip()
    if not improved:
        raise HTTPException(status_code=502, detail="LLM returned an empty prompt")
    return {"prompt": improved}
