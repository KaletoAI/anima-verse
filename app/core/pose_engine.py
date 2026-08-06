"""Pose helpers (step 5, May 2026, plan-outfit-system-rethink.md §6).

Since the pose catalog (Aug 2026, plan-pose-katalog.md) the write path no
longer runs through this module: ``set_pose_intent`` resolves the free text to
a catalog key (``app.core.pose_catalog``) and asks ``pose_variants`` for the
variant of that key directly — no LLM normalization, no per-pose embedding.

What is left here is the visual-analysis path only:
    compute_embedding(text) -> list[float] | None
    enqueue_visual_analysis(variant_id, image_path) -> None
"""
from typing import List, Optional

from app.core.log import get_logger

logger = get_logger("pose_engine")


def compute_embedding(text: str) -> Optional[List[float]]:
    """Compute an embedding for the text.

    Delegates to ``app.core.embedding.embed`` — depending on
    ``config.embedding.backend`` that picks either the built-in ONNX model
    (fastembed, CPU) or a routed external ``/v1/embeddings`` provider.

    Returns ``None`` when no model is available or the call fails → the match
    module falls back to string equality of the normalized pose (no crash, no
    queue block).
    """
    from app.core.embedding import embed
    return embed(text)


def enqueue_visual_analysis(variant_id: int, image_path: str) -> None:
    """Trigger the asynchronous visual-LLM analysis for a freshly generated
    pose variant. Updates canonical_pose + embedding on success.

    Runs in a low-priority daemon thread. Swallows every error — no crash on
    provider outages, no block of the GPU queue.
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
            logger.debug("Visual analysis skipped: %s does not exist", image_path)
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
            logger.debug("Visual analysis LLM call failed (variant %s): %s",
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
                "Visual analysis [variant %s]: canonical=%r",
                variant_id, canonical,
            )
    except Exception as e:
        logger.debug("Visual analysis worker error (variant %s): %s",
                     variant_id, e)
