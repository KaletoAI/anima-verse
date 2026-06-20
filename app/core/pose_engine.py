"""Pose-Pipeline (Schritt 5, May 2026, plan-outfit-system-rethink.md §6).

Verbindet:
  1. free-text pose_intent (vom Chat-LLM gesetzt)
  2. pose_normalize (Tool-LLM → kanonische Kurzform)
  3. pose_embedding (LLM-Routing-Stub, Vektor zum Match)
  4. character_pose_variants (DB-Match oder neuer Variant)

Wenn weder Embedding-Provider konfiguriert noch verfuegbar: Match-Modul
faellt auf reine String-Equality der normalisierten Pose zurueck.

API:
    resolve_pose_variant(char, raw_pose) -> variant_dict | None
    compute_embedding(text) -> list[float] | None
    normalize_pose(raw_pose, activity_hint="") -> str
"""
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("pose_engine")


def normalize_pose(raw_pose: str, activity_hint: str = "") -> str:
    """Ruft pose_normalize-LLM auf und liefert die kanonische Kurzform.

    Bei Fehler / Routing-Konflikt: faellt zurueck auf den raw_pose (lowercase,
    geschnitten) — keine harte Fehlersituation.
    """
    raw = (raw_pose or "").strip()
    if not raw:
        return ""
    # Sehr kurze Inputs sind schon "normal" — ABER nur, wenn keine Orts-/
    # Szenen-Praeposition drinsteckt. "standing at mountain" / "standing in
    # lobby" tragen den ORT mit; ohne Normalisierung embedden sie verschieden
    # und gleiche Koerperposen werden nie zusammengeführt. Solche Faelle laufen
    # daher durch den Normalizer (der den Ort strippt → exakter Match → merge).
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
        from app.core.llm_router import call as llm_call
        sys_prompt, user_prompt = render_task(
            "pose_normalize",
            raw_pose=raw,
            activity_hint=(activity_hint or "").strip(),
        )
        response = llm_call(
            task="pose_normalize",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
        )
        norm = (response or "").strip().strip('"').strip("'")
        if norm:
            # Single-line, lowercase, max 80 chars (DB-Anti-Halluzination)
            norm = norm.splitlines()[0].strip().lower()
            return norm[:80]
    except Exception as e:
        logger.debug("normalize_pose LLM-Call fehlgeschlagen: %s", e)

    # Fallback: rohen Text auf 80 Zeichen kuerzen
    return raw.lower()[:80]


def compute_embedding(text: str) -> Optional[List[float]]:
    """Berechnet ein Embedding fuer den Text via dem Task ``pose_embedding``.

    Nutzt den fuer ``pose_embedding`` gerouteten Provider (OpenAI-kompatibler
    ``/v1/embeddings``-Endpoint — z.B. vLLM oder llama-server mit ``BAAI/bge-m3``).
    Direkter HTTP-Call (Embeddings sind ein anderer Endpoint als die Chat-Queue),
    sync — laeuft nur in Worker-Threads (Chat-Extraktor / Visual-Analyse).

    Returns ``None`` wenn kein Embedding-Modell zugewiesen ist oder der Call
    fehlschlaegt → das Match-Modul faellt auf String-Equality der normalisierten
    Pose zurueck (kein Crash, kein Queue-Block). Optionales Input-Praefix ueber
    Setting ``pose.embedding_input_prefix`` (leer fuer bge-m3, ``"query: "`` fuer
    e5-Modelle).
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        from app.core.llm_router import resolve_llm
        inst = resolve_llm("pose_embedding")
        if inst is None:
            return None  # kein Embedding-Modell geroutet → String-Fallback
        prov = inst._provider
        if prov is None:
            from app.core.provider_manager import get_provider_manager
            prov = get_provider_manager().get_provider(inst.provider_name)
        if not prov or not (prov.api_base or "").strip():
            return None
        api_base = prov.api_base.rstrip("/")
        api_key = (prov.api_key or "not-needed").strip()
        from app.models.world import get_world_setting
        prefix = get_world_setting("pose.embedding_input_prefix", "") or ""
        import httpx
        resp = httpx.post(
            f"{api_base}/embeddings",
            json={"model": inst.model, "input": prefix + text},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=float(prov.timeout or 30),
        )
        resp.raise_for_status()
        payload = resp.json()
        vec = (payload.get("data") or [{}])[0].get("embedding")
        if not vec:
            return None
        return [float(x) for x in vec]
    except Exception as e:
        logger.debug("compute_embedding fehlgeschlagen (%s): %s",
                     type(e).__name__, e)
        return None


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
    """Worker-Function fuer enqueue_visual_analysis."""
    try:
        from pathlib import Path
        p = Path(image_path)
        if not p.exists():
            logger.debug("Visual-Analyse skip: %s existiert nicht", image_path)
            return
        # image_recognition-Task: "Describe what the person is doing in this image"
        try:
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
        # Embedding fuer neue Beschreibung berechnen (Stub gibt None — Match
        # faellt dann auf String zurueck).
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
