"""Token and cost estimate of an LLM call (World Dev chat and free mode).

The provider's model list carries a price per 1M input / output tokens
(`pricing`); tokens are the rough 4-characters estimate of
`llm_logger.estimate_tokens` unless the caller has the provider's own count.
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional, Tuple

ZERO_PRICING: Dict[str, float] = {"input": 0.0, "output": 0.0}


async def resolve_pricing(model: str, provider: str = "") -> Dict[str, float]:
    """The price entry of `model` from its provider's model list, or zeros.
    A list_models cache miss may do synchronous HTTP, so it runs in the
    thread pool, never on the event loop."""
    pricing = dict(ZERO_PRICING)
    try:
        from app.core.provider_manager import get_provider_manager
        pm = get_provider_manager()
        prov = pm.get_provider(provider) if provider else pm.find_provider_for_model(model)
        if prov:
            for entry in await asyncio.to_thread(prov.list_models):
                if entry.get("name") == model:
                    found = entry.get("pricing") or {}
                    pricing = {"input": float(found.get("input") or 0.0),
                               "output": float(found.get("output") or 0.0)}
                    break
    except Exception:  # noqa: BLE001 — pricing is display only
        pass
    return pricing


def estimate_cost(input_text: str, output_text: str,
                  pricing: Optional[Dict[str, float]] = None,
                  tokens_in: Optional[int] = None,
                  tokens_out: Optional[int] = None) -> Tuple[int, int, float]:
    """(tokens_in, tokens_out, cost). A token count the caller passes (the
    provider's usage report) wins over the estimate from the text."""
    from app.utils.llm_logger import estimate_tokens
    p = pricing or ZERO_PRICING
    t_in = int(tokens_in) if tokens_in is not None else estimate_tokens(input_text or "")
    t_out = int(tokens_out) if tokens_out is not None else estimate_tokens(output_text or "")
    cost = (t_in * float(p.get("input") or 0.0) / 1_000_000
            + t_out * float(p.get("output") or 0.0) / 1_000_000)
    return t_in, t_out, cost
