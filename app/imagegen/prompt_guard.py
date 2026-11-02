"""Reject LLM refusal prose before it becomes an image prompt."""
import re


_REFUSAL_OPENER = re.compile(
    r"^(?:(?:i(?:\s+am|'m)\s+sorry|i\s+apologize|sorry|unfortunately)[\s,.:!—-]*(?:but\s+)?)?"
    r"(?:i\s+(?:cannot|can't|can\s+not|won't|will\s+not|must\s+decline)\b|"
    r"i(?:\s+am|'m)\s+(?:not\s+able|unable)\b|"
    r"(?:as\s+an?\s+(?:ai|language\s+model))\b|"
    r"(?:this|that|the)\s+(?:request|content)\s+(?:is\s+not\s+allowed|violates)\b)",
    re.IGNORECASE)


def is_prompt_refusal(answer: str, input_text: str = "", *,
                      min_length_ratio: float = 0.5) -> bool:
    """Check usual refusal openers and content lost relative to the input.

    Distillation callers must lower the ratio and cap the input sample: a
    concise summary of a long transcript is valid. Prompt rewrites can use
    the usual half-length guard (see pose_check).
    """
    text = (answer or "").strip().strip('"').replace("’", "'")
    return (not text or bool(_REFUSAL_OPENER.match(text))
            or len(text) < len(input_text.strip()) * min_length_ratio)
