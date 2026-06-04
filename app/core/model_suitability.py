"""Model Suitability Test — prueft ein konkretes Modell auf Tool-/Helper-Eignung.

Eine synthetische Check-Batterie, abgeleitet aus den realen Tool-/Helper-LLM-
Aufrufen des Projekts (JSON-Objekt/-Array/verschachtelt, Enum-Klassifikation,
projekteigenes Tool-Call-Format, Anti-Halluzination, Einzeiler-Normalisierung,
Laengen-/Sprach-Treue). Jeder Check ist self-contained (kein Spielstand noetig)
und wird deterministisch validiert.

Ergebnisse werden in storage/model_capabilities.json unter dem exakten Modell-
Namen abgelegt (Felder ``tested_*`` + ``tested_suitability``) und auf der
"Model Capabilities"-Admin-Seite angezeigt.
"""
import json
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.core.log import get_logger
from app.core.timeutils import utc_now

logger = get_logger("model_suitability")

# Validator-Rueckgabe: (ok, hallucinated, detail)
Verdict = Tuple[bool, bool, str]


# ---------------------------------------------------------------------------
# Parser-Helfer
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Entfernt umschliessende ```...```-Codefences."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _json_obj(text: str) -> Optional[dict]:
    m = re.search(r"\{[\s\S]*\}", _strip_fences(text))
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except Exception:
        return None


def _json_arr(text: str) -> Optional[list]:
    m = re.search(r"\[[\s\S]*\]", _strip_fences(text))
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, list) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Validatoren — je Check eine Funktion (text) -> Verdict
# ---------------------------------------------------------------------------

def _v_json_object(text: str) -> Verdict:
    obj = _json_obj(text)
    if obj is None:
        return False, False, "no valid JSON object"
    missing = [k for k in ("spell_id", "confidence", "chat_substitute") if k not in obj]
    if missing:
        return False, False, f"missing keys: {missing}"
    conf = obj.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0 <= conf <= 100):
        return False, False, f"confidence out of range: {conf!r}"
    sid = obj.get("spell_id")
    if sid not in ("fireball", "heal", ""):
        return False, True, f"hallucinated spell_id: {sid!r}"
    if sid != "fireball":
        return False, False, f"wrong spell_id: {sid!r} (expected 'fireball')"
    return True, False, "valid object, correct match"


def _v_json_floats(text: str) -> Verdict:
    obj = _json_obj(text)
    if obj is None:
        return False, False, "no valid JSON object"
    for k, lo, hi in (("sentiment_a", -1, 1), ("sentiment_b", -1, 1),
                      ("romantic_delta", -0.2, 0.2)):
        v = obj.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return False, False, f"{k} not a number: {v!r}"
        if not (lo <= v <= hi):
            return False, False, f"{k} out of range [{lo},{hi}]: {v}"
    return True, False, "valid floats in range"


def _v_json_array(text: str) -> Verdict:
    arr = _json_arr(text)
    if arr is None:
        return False, False, "no valid JSON array"
    if len(arr) < 2:
        return False, False, f"expected >=2 items, got {len(arr)}"
    for i, it in enumerate(arr):
        if not isinstance(it, dict):
            return False, False, f"item {i} not an object"
        if "content" not in it or not isinstance(it.get("content"), str):
            return False, False, f"item {i} missing string 'content'"
        if it.get("category") not in ("personal", "relationship", "location"):
            return False, False, f"item {i} bad category: {it.get('category')!r}"
        sev = it.get("severity")
        if not isinstance(sev, int) or isinstance(sev, bool) or not (1 <= sev <= 5):
            return False, False, f"item {i} severity out of range: {sev!r}"
    return True, False, "valid array of objects"


def _v_json_nested(text: str) -> Verdict:
    obj = _json_obj(text)
    if obj is None:
        return False, False, "no valid JSON object"
    pieces = obj.get("pieces")
    if not isinstance(pieces, list) or len(pieces) < 2:
        return False, False, "missing 'pieces' list with >=2 entries"
    for i, p in enumerate(pieces):
        if not isinstance(p, dict):
            return False, False, f"piece {i} not an object"
        if not isinstance(p.get("slots"), list) or not p["slots"]:
            return False, False, f"piece {i} missing non-empty 'slots' list"
        if not isinstance(p.get("name"), str) or not p["name"].strip():
            return False, False, f"piece {i} missing 'name'"
    return True, False, "valid nested structure"


_ENUM_OPTIONS = ("sleeping", "eating", "walking", "fighting")


def _v_enum(text: str) -> Verdict:
    first = (_strip_fences(text).splitlines() or [""])[0].strip().lower().strip('.\"\'')
    if first not in _ENUM_OPTIONS:
        return False, False, f"not one of the options: {first!r}"
    if first != "sleeping":
        return False, False, f"wrong class: {first!r} (expected 'sleeping')"
    return True, False, "exact option, correct"


def _v_json_only(text: str) -> Verdict:
    s = (text or "").strip()
    if "```" in s:
        return False, False, "used markdown code fences"
    if not s.startswith("{"):
        return False, False, "prose/text before JSON"
    obj = _json_obj(text)
    if obj is None:
        return False, False, "not valid JSON"
    tail = s[s.rfind("}") + 1:].strip()
    if tail:
        return False, False, f"trailing text after JSON: {tail[:40]!r}"
    return True, False, "pure JSON, no prose"


def _v_abstain(text: str) -> Verdict:
    obj = _json_obj(text)
    if obj is None:
        return False, False, "no valid JSON object"
    if "pet_name" not in obj:
        return False, False, "missing 'pet_name' key"
    v = obj.get("pet_name")
    if v in ("", None):
        return True, False, "correctly abstained (empty)"
    return False, True, f"hallucinated pet name: {v!r}"


def _v_oneline(text: str) -> Verdict:
    lines = [l for l in _strip_fences(text).splitlines() if l.strip()]
    if len(lines) != 1:
        return False, False, f"expected single line, got {len(lines)}"
    ln = lines[0].strip()
    if ln != ln.lower():
        return False, False, "not lowercase"
    if any(c in ln for c in '"\'.!?,;:'):
        return False, False, "contains punctuation/quotes"
    wc = len(ln.split())
    if not (2 <= wc <= 7):
        return False, False, f"word count {wc} not in 2..7"
    return True, False, "clean single-line phrase"


def _v_length_summary(text: str) -> Verdict:
    s = _strip_fences(text).strip()
    if not s:
        return False, False, "empty"
    if "```" in s or re.search(r"(?m)^\s*[-*#]", s):
        return False, False, "contains markdown bullets/heading"
    sentences = len(re.findall(r"[.!?]+", s))
    if sentences > 2:
        return False, False, f"more than 2 sentences ({sentences})"
    return True, False, "plain text within length"


def _v_language_de(text: str) -> Verdict:
    s = (text or "").lower()
    de = ("der", "die", "das", "und", "ist", "ein", "eine", "nacht", "brücke",
          "bruecke", "während", "waehrend", "regen", "alte", "stürz", "stuerz",
          "zusammen", "gestern", "schwer")
    de_hits = sum(1 for w in de if w in s)
    if de_hits < 2:
        return False, False, "output does not look German"
    en = ("the", "bridge", "collapsed", "during", "heavy", "rain", "last", "night")
    en_hits = sum(1 for w in en if re.search(r"\b" + w + r"\b", s))
    if en_hits >= 4:
        return False, False, "too much English leakage"
    return True, False, "responded in German"


def _v_image_prompt(text: str) -> Verdict:
    s = (text or "").strip()
    if not s:
        return False, False, "empty"
    low = s.lower()
    preambles = ("here is", "here's", "sure", "certainly", "prompt:",
                 "image prompt", "okay", "of course", "i'll", "i will")
    if any(low.startswith(p) for p in preambles):
        return False, False, "has conversational preamble"
    if "```" in s or s[0] in "\"'":
        return False, False, "wrapped in fences/quotes"
    if not (3 <= len(s) <= 400):
        return False, False, f"length {len(s)} out of range 3..400"
    return True, False, "clean prompt, no preamble"


def _v_max_chars(text: str) -> Verdict:
    s = (text or "").strip()
    if not s:
        return False, False, "empty"
    if len(s) > 120:
        return False, False, f"{len(s)} chars > 120 limit"
    return True, False, f"{len(s)} chars, within limit"


def _v_extract_abstain(text: str) -> Verdict:
    obj = _json_obj(text)
    if obj is None:
        return False, False, "no valid JSON object"
    mems = obj.get("memories")
    if not isinstance(mems, list):
        return False, False, "missing 'memories' list"
    if len(mems) == 0:
        return True, False, "correctly returned empty list"
    return False, True, f"invented {len(mems)} memories from smalltalk"


# ---------------------------------------------------------------------------
# Check-Definitionen
# ---------------------------------------------------------------------------

_JSON_SYS = ("You are a strict JSON API. Output ONLY raw JSON. "
             "No markdown, no code fences, no explanation before or after.")

CHECKS: List[Dict[str, Any]] = [
    {
        "id": "json_object", "label": "JSON object (spell detect)", "category": "tool",
        "system": _JSON_SYS,
        "user": ("Spell catalog (id -> trigger word):\n- fireball -> \"ignis\"\n"
                 "- heal -> \"sana\"\n\nA character shouts: \"Ignis!\"\n\n"
                 "Return a JSON object: {\"spell_id\": matching catalog id or \"\" if none, "
                 "\"confidence\": integer 0-100, \"chat_substitute\": short third-person description}."),
        "validate": _v_json_object,
    },
    {
        "id": "json_floats", "label": "JSON floats in range (relationship)", "category": "tool",
        "system": _JSON_SYS,
        "user": ("Dialogue:\nAnna: \"I never want to see you again!\"\n"
                 "Ben: \"Please, I'm so sorry.\"\n\n"
                 "Return JSON: {\"sentiment_a\": float in [-1,1], \"sentiment_b\": float in [-1,1], "
                 "\"romantic_delta\": float in [-0.2,0.2]}."),
        "validate": _v_json_floats,
    },
    {
        "id": "json_array", "label": "JSON array of objects (secrets)", "category": "tool",
        "system": _JSON_SYS,
        "user": ("Invent exactly 2 secrets for a fantasy character. Output ONLY a JSON array of "
                 "2 objects, each: {\"content\": string, \"category\": one of "
                 "[\"personal\",\"relationship\",\"location\"], \"severity\": integer 1-5}."),
        "validate": _v_json_array,
    },
    {
        "id": "json_nested", "label": "Nested JSON (outfit pieces)", "category": "tool",
        "system": _JSON_SYS,
        "user": ("Design an outfit. Output ONLY JSON: {\"pieces\": [{\"slots\": [string], "
                 "\"name\": string}, ...]} with at least 2 pieces."),
        "validate": _v_json_nested,
    },
    {
        "id": "enum_classify", "label": "Enum classification (activity)", "category": "tool",
        "system": "Respond with EXACTLY one item from the provided list and nothing else.",
        "user": ("Options: sleeping, eating, walking, fighting.\n"
                 "Text: \"He lies on the bed with closed eyes, breathing slowly and steadily.\"\n"
                 "Which option fits best?"),
        "validate": _v_enum,
    },
    # tool_call_format wird im Runner gesondert behandelt (mehrere Formate)
    {
        "id": "tool_call_format", "label": "Project tool-call format", "category": "tool",
        "kind": "tool_format",
    },
    {
        "id": "json_only", "label": "JSON only, no prose/fences", "category": "tool",
        "system": ("Output ONLY raw JSON. Absolutely no markdown code fences and no text "
                   "before or after the JSON object."),
        "user": "Return this exact structure with values filled: {\"ok\": true, \"count\": 3}.",
        "validate": _v_json_only,
    },
    {
        "id": "abstain", "label": "Anti-hallucination (abstain)", "category": "tool",
        "system": _JSON_SYS,
        "user": ("Bio: \"Mara is a 29-year-old cartographer who loves mountains and black coffee.\"\n"
                 "Return JSON: {\"pet_name\": the name of Mara's pet, or \"\" if the bio does not "
                 "mention a pet}."),
        "validate": _v_abstain,
    },
    {
        "id": "extract_abstain", "label": "Extraction abstain (empty array)", "category": "tool",
        "system": _JSON_SYS,
        "user": ("Dialogue:\nA: \"Nice weather today.\"\nB: \"Yes, quite sunny.\"\n\n"
                 "Extract noteworthy facts or commitments. Return JSON: {\"memories\": [ ... ]}. "
                 "If there is nothing noteworthy, return {\"memories\": []}."),
        "validate": _v_extract_abstain,
    },
    {
        "id": "oneline", "label": "Single-line normalization (pose)", "category": "helper",
        "system": ("Respond with ONLY a short lowercase phrase of 2 to 6 words. No punctuation, "
                   "no quotes, no explanation, a single line."),
        "user": ("Normalize this pose to a short canonical phrase: \"She is sitting down at the "
                 "wooden table and reading a thick old book.\""),
        "validate": _v_oneline,
    },
    {
        "id": "length_summary", "label": "Length-bounded summary", "category": "helper",
        "system": "Write plain text only. No markdown, no bullet points, no headings.",
        "user": ("Summarize in at most 2 sentences:\n- The festival opened at noon.\n"
                 "- A storm interrupted it briefly.\n- It resumed in the evening.\n"
                 "- Fireworks closed the night.\n- Many visitors returned home happy."),
        "validate": _v_length_summary,
    },
    {
        "id": "language_de", "label": "Language adherence (German)", "category": "helper",
        "system": "Respond ONLY in German. Do not include any English.",
        "user": "Translate to German: \"The old bridge collapsed during the heavy rain last night.\"",
        "validate": _v_language_de,
    },
    {
        "id": "image_prompt", "label": "Image prompt rewrite (no preamble)", "category": "helper",
        "system": ("Output ONLY the image prompt. English. No preamble, no quotes, no markdown, "
                   "no explanation."),
        "user": ("Rewrite as a concise comma-separated image prompt: a knight standing on a cliff "
                 "at sunset, dramatic lighting."),
        "validate": _v_image_prompt,
    },
    {
        "id": "max_chars", "label": "Max-length instruction", "category": "helper",
        "system": "Write a single atmospheric sentence of at most 120 characters. Output only the sentence.",
        "user": "Setting: a foggy harbor at dawn.",
        "validate": _v_max_chars,
    },
]


def list_checks() -> List[Dict[str, str]]:
    """Metadaten aller Checks (id/label/category) — fuer UI-Vorschau."""
    return [{"id": c["id"], "label": c["label"], "category": c["category"]} for c in CHECKS]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _run_tool_format(ask) -> Verdict:
    """Probiert die projekteigenen Tool-Call-Formate; ermittelt das erste, das
    sauber matcht (-> tested_best_format). Gibt Verdict + best-format via detail."""
    from app.core.tool_formats import TOOL_FORMATS
    tools = "ImageGenerator, MoveTo"
    for fmt_key in ("tag", "natural_en", "natural_de"):
        fmt = TOOL_FORMATS.get(fmt_key)
        if not fmt:
            continue
        system = (f"Available tools: {tools}\n\n{fmt['instruction']}")
        user = "Use the ImageGenerator tool to depict a sunset over the ocean."
        try:
            out = ask(system, user)
        except Exception as e:
            return False, False, f"call error: {str(e)[:80]}"
        m = re.search(fmt["pattern"], out)
        if m and m.group(1) == "ImageGenerator":
            return True, False, f"best_format={fmt_key}"
    return False, False, "no tool-call format matched"


def iter_suitability_results(model_full: str) -> Iterator[Dict[str, Any]]:
    """Fuehrt die Check-Batterie gegen ein Modell aus und yieldet Events:

    - {"type":"start", "model","total"}
    - {"type":"check", "index","id","label","category","ok","hallucinated","detail"}
    - {"type":"done", "summary": {...}}      (persistiert das Ergebnis)
    - {"type":"error", "message"}            (Abbruch, nichts gespeichert)
    """
    from app.core.llm_router import create_llm_instance

    inst = create_llm_instance("suitability_test", model_full)
    if inst is None:
        yield {"type": "error", "message": f"No provider found for model '{model_full}'"}
        return
    if not inst.available:
        yield {"type": "error",
               "message": f"Provider '{inst.provider_name}' is not available"}
        return
    try:
        client = inst.create_llm(temperature=0.0, max_tokens=800)
    except Exception as e:
        yield {"type": "error", "message": f"client init failed: {e}"}
        return

    def ask(system: str, user: str) -> str:
        resp = client.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return (getattr(resp, "content", "") or "").strip()

    yield {"type": "start", "model": model_full, "total": len(CHECKS)}

    results: List[Dict[str, Any]] = []
    best_format = ""
    for idx, chk in enumerate(CHECKS):
        try:
            if chk.get("kind") == "tool_format":
                ok, hall, detail = _run_tool_format(ask)
                if ok and detail.startswith("best_format="):
                    best_format = detail.split("=", 1)[1]
            else:
                out = ask(chk["system"], chk["user"])
                ok, hall, detail = chk["validate"](out)
        except Exception as e:
            ok, hall, detail = False, False, f"call error: {str(e)[:120]}"
            logger.warning("suitability check %s failed: %s", chk["id"], e)
        rec = {"id": chk["id"], "label": chk["label"], "category": chk["category"],
               "ok": bool(ok), "hallucinated": bool(hall), "detail": detail}
        results.append(rec)
        yield {"type": "check", "index": idx, **rec}

    summary = _summarize(model_full, results, best_format)
    _persist(model_full, summary, results, best_format)
    yield {"type": "done", "summary": summary}


def _summarize(model_full: str, results: List[Dict[str, Any]],
               best_format: str) -> Dict[str, Any]:
    tool = [r for r in results if r["category"] == "tool"]
    helper = [r for r in results if r["category"] == "helper"]
    tp = sum(1 for r in tool if r["ok"])
    hp = sum(1 for r in helper if r["ok"])
    passed = sum(1 for r in results if r["ok"])
    halluc = sum(1 for r in results if r["hallucinated"])
    return {
        "model": model_full,
        "date": utc_now().date().isoformat(),
        "score": f"{passed}/{len(results)}",
        "tool": f"{tp}/{len(tool)}",
        "helper": f"{hp}/{len(helper)}",
        "hallucinations": halluc,
        "best_format": best_format,
        "checks": results,
    }


def _persist(model_full: str, summary: Dict[str, Any],
             results: List[Dict[str, Any]], best_format: str) -> None:
    """Schreibt das Ergebnis in model_capabilities.json unter dem exakten Modell-
    Namen — bestehende Felder (tool_calling, vision, notes_de, ...) bleiben."""
    from app.core.model_capabilities import (get_all_capabilities,
                                             save_model_capability)
    name = model_full.split("::", 1)[1] if "::" in model_full else model_full
    key = name.lower()
    caps_all = get_all_capabilities()
    save_key = key
    existing: Dict[str, Any] = {}
    for pat, c in caps_all.items():
        if pat.lower() == key:
            existing = dict(c)
            save_key = pat
            break
    existing["tested_date"] = summary["date"]
    existing["tested_score"] = summary["score"]
    existing["tested_tool_score"] = summary["tool"]
    existing["tested_helper_score"] = summary["helper"]
    existing["tested_hallucinations"] = summary["hallucinations"]
    if best_format:
        existing["tested_best_format"] = best_format
    existing["tested_suitability"] = {
        "model": model_full,
        "tool": summary["tool"],
        "helper": summary["helper"],
        "checks": results,
    }
    try:
        save_model_capability(save_key, existing)
        logger.info("Suitability test saved for %s: %s", model_full, summary["score"])
    except Exception as e:
        logger.error("Failed to persist suitability for %s: %s", model_full, e)
