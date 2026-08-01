"""Pose-Pipeline (Schritt 5, May 2026, plan-outfit-system-rethink.md §6).

Verbindet:
  1. free-text pose_intent (vom Chat-LLM gesetzt)
  2. pose_normalize (Tool-LLM → kanonische Kurzform)
  3. compute_embedding (via app.core.embedding: intern fastembed/ONNX
     oder extern gerouteter /v1/embeddings-Provider) → Vektor zum Match
  4. character_pose_variants (DB-Match oder neuer Variant)

Wenn kein Embedding-Modell verfuegbar ist: Match-Modul faellt auf reine
String-Equality der normalisierten Pose zurueck.

API:
    resolve_pose_variant(char, raw_pose) -> variant_dict | None
    compute_embedding(text) -> list[float] | None
    normalize_pose(raw_pose, activity_hint="") -> str
"""
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("pose_engine")

# Completion budget for the pose_normalize call. The template demands 2-6
# English words, i.e. roughly 8-12 tokens; 24 leaves about double that for
# tokenizer variance and punctuation while cutting a rambling answer off early
# instead of paying for a whole paragraph.
_MAX_ANSWER_TOKENS = 24

# Garbage gate for the LLM answer. The value is stored as canonical_pose and
# goes verbatim into the image prompt, so an answer that is obviously not a
# pose must not be stored at all — the raw fallback is the better value.
# 80 chars = the storage cap the DB value has always had; 12 words = double the
# template's ceiling of 6, so a wordy but genuine pose ("sitting on a couch
# reading a book by the window", 10 words) still passes while a prose sentence
# ("Sure! Here is the canonical pose you asked for: …", 13 words) does not.
_MAX_ANSWER_CHARS = 80
_MAX_ANSWER_WORDS = 12


def _is_pose_shaped(text: str) -> bool:
    """True if the cleaned LLM answer can plausibly be a pose at all.

    Deliberately NOT a content judgement — only a length/word-count filter
    against obviously broken output (prose, explanations, refusals).
    """
    return len(text) <= _MAX_ANSWER_CHARS and len(text.split()) <= _MAX_ANSWER_WORDS


def normalize_pose(raw_pose: str, activity_hint: str = "") -> str:
    """Call the pose_normalize LLM and return the canonical short form.

    On error / routing conflict: falls back to the raw_pose (lowercased,
    truncated) — never a hard failure.
    """
    raw = (raw_pose or "").strip()
    if not raw:
        return ""
    # Very short inputs are already "normal" — BUT only if they carry no
    # location/scene preposition. "standing at mountain" / "standing in lobby"
    # carry the PLACE along; without normalization they embed differently and
    # identical body poses are never merged. Such cases therefore go through
    # the normalizer (which strips the place → exact match → merge).
    _low = raw.lower()
    _has_location = any(
        f" {p} " in f" {_low} "
        for p in ("at", "in", "on", "near", "by", "inside", "outside",
                  "next to", "in front of", "behind", "beside", "around")
    )
    if not _has_location and len(raw.split()) <= 4 and len(raw) <= 40:
        return _low

    try:
        from app.core.prompt_templates import render_task
        from app.core.llm_router import llm_call
        sys_prompt, user_prompt = render_task(
            "pose_normalize",
            raw_pose=raw,
            activity_hint=(activity_hint or "").strip(),
        )
        response = llm_call(
            task="pose_normalize",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            max_tokens=_MAX_ANSWER_TOKENS,
        )
        # FIRST line, THEN quotes/whitespace. The other way round a multi-line
        # answer keeps a stray closing quote ('"standing at window"\nBecause…'
        # would become 'standing at window"') and that lands verbatim in the
        # image prompt.
        lines = (response.content or "").splitlines()
        first = lines[0].strip() if lines else ""
        if first.startswith("```"):
            # Fenced answer — the pose is not on the first line. Discard the
            # whole answer instead of guessing which line carries it.
            first = ""
        # One strip pass over quotes AND trailing punctuation: stripping the
        # quote alone leaves '"standing at window".' as 'standing at window".'
        # — the same stray quote, just behind a period.
        norm = first.strip(" .,\"'").lower()
        if norm and _is_pose_shaped(norm):
            return norm
    except Exception as e:
        logger.debug("normalize_pose LLM call failed: %s", e)

    # Fallback: truncate the raw text to 80 characters
    return raw.lower()[:80]


def compute_embedding(text: str) -> Optional[List[float]]:
    """Berechnet ein Embedding fuer den Text.

    Delegiert an ``app.core.embedding.embed`` — das waehlt je nach
    ``config.embedding.backend`` zwischen dem eingebauten ONNX-Modell
    (fastembed, CPU) und einem gerouteten externen ``/v1/embeddings``-Provider.

    Returns ``None`` wenn kein Modell verfuegbar ist oder der Aufruf
    fehlschlaegt → das Match-Modul faellt auf String-Equality der normalisierten
    Pose zurueck (kein Crash, kein Queue-Block).
    """
    from app.core.embedding import embed
    return embed(text)


def resolve_pose_variant(character_name: str,
                          raw_pose: str,
                          activity_hint: str = "") -> Optional[Dict[str, Any]]:
    """End-to-End: rohen pose_intent → Variant-Dict (mit id).

    Steps:
      1. normalize_pose → kanonische Kurzform (LLM oder Fallback)
      2. compute_embedding → Vektor (oder None)
      3. get_or_create_variant → existierender oder neuer Variant

    Returns das Variant-Dict (inkl. id, canonical_pose, ...) oder None
    bei leerem Input. Bei DB-Fehlern: ebenfalls None.
    """
    raw = (raw_pose or "").strip()
    if not (character_name and raw):
        return None
    normalized = normalize_pose(raw, activity_hint=activity_hint)
    if not normalized:
        return None
    embedding = compute_embedding(normalized)
    from app.core.pose_variants import get_or_create_variant
    return get_or_create_variant(character_name, normalized, embedding=embedding)


def enqueue_visual_analysis(variant_id: int, image_path: str) -> None:
    """Triggert asynchrone Visual-LLM-Analyse fuer einen frisch erzeugten
    Pose-Variant. Aktualisiert canonical_pose + embedding falls erfolgreich.

    Laeuft in einem Daemon-Thread mit niedriger Priority. Schluckt alle
    Fehler — kein Crash bei Provider-Aussetzern, kein Block der GPU-Queue.
    """
    if not variant_id or not image_path:
        return
    import threading
    t = threading.Thread(
        target=_run_visual_analysis,
        args=(int(variant_id), str(image_path)),
        daemon=True,
        name=f"pose-visual-{variant_id}",
    )
    t.start()


def _run_visual_analysis(variant_id: int, image_path: str) -> None:
    """Worker function for enqueue_visual_analysis."""
    try:
        from pathlib import Path
        p = Path(image_path)
        if not p.exists():
            logger.debug("Visual-Analyse skip: %s existiert nicht", image_path)
            return
        # image_recognition task: "Describe what the person is doing in this image"
        try:
            # NOT FUNCTIONAL: this call cannot work as written. `llm_call` takes
            # no image input at all (task, system_prompt, user_prompt,
            # agent_name, priority, label, max_tokens), so `image_paths` has no
            # receiver — and the imported name `call` does not exist either.
            # Vision in this repo runs through app/imagegen/service.py
            # (_get_vision_llm_config). Making this work is a rewiring onto that
            # path, not a line fix, and is tracked as its own scope (LLM routing
            # review, section A4) — deliberately left untouched here.
            from app.core.llm_router import call as llm_call
            response = llm_call(
                task="image_recognition",
                system_prompt=(
                    "You analyze character poses for image-variant matching. "
                    "Describe ONLY what the person in the image is doing — "
                    "body posture and main action. 2-6 words, English, lowercase. "
                    "No mood, no clothing, no scene description. "
                    "Examples: 'sitting on couch reading', 'standing at window', "
                    "'walking up stairs', 'lying on bed'."
                ),
                user_prompt="Describe the pose of the person in this image.",
                image_paths=[str(p)],
            )
        except Exception as e:
            logger.debug("Visual-Analyse LLM-Call fehlgeschlagen (variant %s): %s",
                         variant_id, e)
            return
        canonical = (response or "").strip().strip('"').strip("'")
        if not canonical:
            return
        # Single-line, lowercase, cap length
        canonical = canonical.splitlines()[0].strip().lower()[:80]
        if not canonical:
            return
        # Compute an embedding for the new description (None means the match
        # falls back to string equality).
        new_embedding = compute_embedding(canonical)
        from app.core.pose_variants import update_variant_canonical
        if update_variant_canonical(variant_id, canonical, embedding=new_embedding):
            logger.info(
                "Visual-Analyse [variant %s]: canonical=%r",
                variant_id, canonical,
            )
    except Exception as e:
        logger.debug("Visual-Analyse Worker-Fehler (variant %s): %s",
                     variant_id, e)
