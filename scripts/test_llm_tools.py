#!/usr/bin/env python3
"""
LLM Tool-Calling & Vision Test Script
========================================
Laedt alle verfuegbaren Modelle von einem LLM-Provider und testet jedes
Modell auf:
  1. Tool-Calling-Faehigkeit in 3 Formaten (tag, natural_en, natural_de)
  2. Vision-Faehigkeit (Farberkennung auf Test-PNG)

Ergebnisse werden als Tabelle ausgegeben und optional in
storage/model_capabilities.json gespeichert.

LEGACY: Dieses Skript liest die Provider aus PROVIDER_N_*-Zeilen einer
./.env-Datei — es ist aelter als das Welt-Config-Modell. Die App selbst
konfiguriert Provider ausschliesslich in worlds/<welt>/config.json; mit
--api-base laeuft der Check ganz ohne .env.

Usage:
  python scripts/test_llm_tools.py local-llm              # Tools + Vision testen
  python scripts/test_llm_tools.py local-llm-2                  # Alle Modelle auf local-llm-2
  python scripts/test_llm_tools.py local-llm --model "qwen3*"  # Nur bestimmtes Modell
  python scripts/test_llm_tools.py local-llm --save        # In model_capabilities.json speichern
  python scripts/test_llm_tools.py local-llm --format tag  # Nur Tag-Format testen
  python scripts/test_llm_tools.py local-llm --no-vision   # Vision-Test ueberspringen
  python scripts/test_llm_tools.py local-llm --no-tools    # Nur Vision testen
  python scripts/test_llm_tools.py local-llm -v            # Mit Antwort-Texten
  python scripts/test_llm_tools.py --list                   # Alle Provider aus .env auflisten
  python scripts/test_llm_tools.py --api-base http://...    # Direkte URL (ohne .env)
"""
import argparse
import base64
import fnmatch
import json
import re
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    print("httpx nicht installiert. Bitte: pip install httpx")
    sys.exit(1)


# ============================================================================
# Konfiguration
# ============================================================================

ENV_FILE = Path("./.env")
CAPABILITIES_FILE = Path("./storage/model_capabilities.json")

# Tool-Formate (aus app/core/tool_formats.py)
TOOL_FORMATS = {
    "tag": {
        "instruction": (
            "To use a tool, write EXACTLY this format:\n"
            '<tool name="ToolName">your detailed input here</tool>\n'
            "RULES:\n"
            "- The tool name must be EXACTLY one of the available tool names\n"
            "- Write your input between the opening and closing tags\n"
            "- Do NOT add any text after the closing </tool> tag"
        ),
        "example": '<tool name="{tool_name}">{input}</tool>',
        "pattern": r'<tool\s+name="(\w+)">([\s\S]*?)</tool>',
    },
    "natural_en": {
        "instruction": (
            "To use a tool, write EXACTLY this format:\n"
            "Use ToolName for: your detailed input here\n"
            "RULES:\n"
            "- Write EXACTLY 'Use' then the tool name then 'for:' WITH COLON\n"
            "- Then the details. Do NOT use brackets [] in real tool calls."
        ),
        "example": "Use {tool_name} for: {input}",
        "pattern": r"(?:I\s+)?[Uu]se\s+(\w+)\s+for:\s*(.*?)(?:\n|$)",
    },
    "natural_de": {
        "instruction": (
            "Um ein Tool zu nutzen, schreibe EXAKT dieses Format:\n"
            "Ich nutze ToolName für: deine detaillierte Eingabe hier\n"
            "REGELN:\n"
            "- Schreibe GENAU 'Ich nutze' gefolgt vom Tool-Namen (ein Wort)\n"
            "- Dann 'für:' MIT DOPPELPUNKT\n"
            "- Dann die Details/Beschreibung"
        ),
        "example": "Ich nutze {tool_name} für: {input}",
        "pattern": r"(?:Ich\s+)?[Nn]utze\s+(\w+)\s+f(?:ü|ue)r:\s*(.*?)(?:\n|$)",
    },
}

# Test-Tools die dem LLM angeboten werden
TEST_TOOLS = [
    {"name": "WebSearch", "description": "Searches the internet for current information"},
    {"name": "ImageGenerator", "description": "Generates images based on text descriptions"},
]

# Test-Prompts: User-Nachrichten die einen Tool-Call ausloesen SOLLEN
TEST_PROMPTS = [
    {
        "name": "web_search",
        "user_msg": "What is the current weather in Berlin?",
        "expected_tool": "WebSearch",
        "description": "Soll WebSearch ausloesen (aktuelle Info angefragt)",
    },
    {
        "name": "image_gen",
        "user_msg": "Generate a picture of a sunset over the ocean.",
        "expected_tool": "ImageGenerator",
        "description": "Soll ImageGenerator ausloesen (Bild angefragt)",
    },
]


# ============================================================================
# Provider-Aufloesung aus .env
# ============================================================================

def load_env_providers() -> Dict[str, Dict[str, str]]:
    """Liest alle PROVIDER_N_* Bloecke aus der .env Datei.

    Returns:
        Dict[provider_name, {"api_base": ..., "api_key": ..., "type": ..., "timeout": ...}]
    """
    if not ENV_FILE.exists():
        return {}

    env_vars: Dict[str, str] = {}
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip()

    providers: Dict[str, Dict[str, str]] = {}
    for i in range(1, 20):
        name = env_vars.get(f"PROVIDER_{i}_NAME")
        if not name:
            break
        providers[name] = {
            "api_base": env_vars.get(f"PROVIDER_{i}_API_BASE", ""),
            "api_key": env_vars.get(f"PROVIDER_{i}_API_KEY", ""),
            "type": env_vars.get(f"PROVIDER_{i}_TYPE", "openai"),
            "timeout": env_vars.get(f"PROVIDER_{i}_TIMEOUT", "120"),
        }

    return providers


def resolve_provider(provider_name: str) -> Tuple[str, str]:
    """Loest einen Provider-Namen in (api_base, api_key) auf.

    Returns:
        (api_base, api_key) Tuple
    Raises:
        SystemExit wenn Provider nicht gefunden
    """
    providers = load_env_providers()

    if not providers:
        print(f"FEHLER: Keine Provider in {ENV_FILE} gefunden.")
        sys.exit(1)

    # Case-insensitive Match
    for name, config in providers.items():
        if name.lower() == provider_name.lower():
            api_base = config["api_base"]
            if not api_base:
                print(f"FEHLER: Provider '{name}' hat keine API_BASE konfiguriert.")
                sys.exit(1)
            if config["type"] not in ("openai", "ollama"):
                print(f"FEHLER: Provider '{name}' ist Typ '{config['type']}' — nur openai/ollama werden unterstuetzt.")
                sys.exit(1)
            return api_base, config.get("api_key", "")

    # Nicht gefunden — verfuegbare Provider anzeigen
    print(f"FEHLER: Provider '{provider_name}' nicht gefunden.")
    print(f"\nVerfuegbare Provider:")
    for name, config in providers.items():
        ptype = config["type"]
        base = config["api_base"]
        print(f"  {name:<20} ({ptype}) {base}")
    sys.exit(1)


def list_providers():
    """Listet alle Provider aus .env auf."""
    providers = load_env_providers()
    if not providers:
        print(f"Keine Provider in {ENV_FILE} gefunden.")
        return

    print(f"LLM Provider (aus {ENV_FILE}):\n")
    for name, config in providers.items():
        ptype = config["type"]
        base = config["api_base"]
        supported = "openai/ollama" if ptype in ("openai", "ollama") else ptype
        marker = " ✓" if ptype in ("openai", "ollama") else " (nicht testbar)"
        print(f"  {name:<20} {supported:<12} {base}{marker}")


# ============================================================================
# API Funktionen
# ============================================================================

def list_models(api_base: str, api_key: str = "", timeout: float = 30) -> List[Dict[str, Any]]:
    """Listet alle verfuegbaren Modelle vom Server."""
    url = f"{api_base}/models"
    headers = {}
    if api_key and api_key != "not-needed":
        headers["Authorization"] = f"Bearer {api_key}"
    resp = httpx.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


def chat_completion(
    api_base: str,
    model: str,
    messages: List[Dict[str, str]],
    api_key: str = "",
    temperature: float = 0.1,
    max_tokens: int = 500,
    timeout: float = 120,
) -> str:
    """Sendet eine Chat-Completion-Anfrage und gibt den Antworttext zurueck."""
    url = f"{api_base}/chat/completions"
    headers = {}
    if api_key and api_key != "not-needed":
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "")


# ============================================================================
# Tool-Call Erkennung
# ============================================================================

def find_tool_call(text: str, fmt_name: str) -> Optional[Tuple[str, str]]:
    """Sucht einen Tool-Call im gegebenen Format. Gibt (tool_name, input) oder None zurueck."""
    pattern = TOOL_FORMATS[fmt_name]["pattern"]
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return (match.group(1), match.group(2).strip())
    return None


def find_any_tool_call(text: str) -> Optional[Tuple[str, str, str]]:
    """Sucht Tool-Call in ALLEN Formaten. Gibt (tool_name, input, format_name) oder None zurueck."""
    for fmt_name in TOOL_FORMATS:
        result = find_tool_call(text, fmt_name)
        if result:
            return (result[0], result[1], fmt_name)
    return None


def is_placeholder(tool_input: str) -> bool:
    """Erkennt Platzhalter-Inputs (halluzinierte Beispiele)."""
    stripped = tool_input.strip()
    if not stripped:
        return True
    if stripped.startswith("[") and stripped.endswith("]"):
        return True
    if stripped.lower() in ("your detailed input here", "deine detaillierte eingabe hier", "your input"):
        return True
    return False


def detect_hallucination(response: str, prompt: Dict[str, str]) -> bool:
    """Erkennt ob das Modell VOR dem Tool-Call Fakten halluziniert hat.

    Prueft den Text vor dem ersten Tool-Call auf Anzeichen dass das Modell
    die Frage selbst beantwortet hat statt nur den Tool aufzurufen.

    Returns:
        True wenn Halluzination erkannt (Fakten-Antwort vor Tool-Call)
    """
    # Tool-Call Position finden (alle Formate pruefen)
    tool_pos = len(response)
    for fmt in TOOL_FORMATS.values():
        match = re.search(fmt["pattern"], response, re.IGNORECASE)
        if match and match.start() < tool_pos:
            tool_pos = match.start()

    # Text vor dem Tool-Call
    pre_text = response[:tool_pos].strip()
    if not pre_text:
        return False  # Kein Text vor dem Tool-Call — sauber

    # Kurze Ueberleitung ist OK ("Sure!", "Let me search that for you.")
    # Nur pruefen wenn substantieller Text vorhanden
    if len(pre_text) < 60:
        return False

    # Prompt-spezifische Halluzinations-Marker
    hallucination_patterns = {
        "web_search": [
            r'\d+\s*°[CF]',           # Temperatur (18°C, 72°F)
            r'\d+\s*degrees',          # "18 degrees"
            r'\d+\s*Grad',             # "18 Grad"
            r'sunny|cloudy|rainy|rain|snow|fog|clear sky|overcast',
            r'sonnig|wolkig|regnerisch|Regen|Schnee|Nebel',
            r'humidity|Luftfeucht',
            r'wind\s*speed|Windgeschwindigkeit',
            r'forecast|Vorhersage|Wetterbericht',
        ],
        "image_gen": [
            r'here\s+is\s+(the|your)\s+image',
            r'I\s+(have\s+)?(created|generated|made)',
            r'hier\s+ist\s+(das|dein|Ihr)\s+Bild',
            r'habe.*generiert|habe.*erstellt',
        ],
    }

    patterns = hallucination_patterns.get(prompt["name"], [])
    for pattern in patterns:
        if re.search(pattern, pre_text, re.IGNORECASE):
            return True

    return False


# ============================================================================
# System-Prompt Builder
# ============================================================================

def build_system_prompt(fmt_name: str) -> str:
    """Baut den System-Prompt mit Tool-Instruktionen."""
    fmt = TOOL_FORMATS[fmt_name]
    tools_section = "\n".join(f"- {t['name']}: {t['description']}" for t in TEST_TOOLS)

    example_search = fmt["example"].format(tool_name="WebSearch", input="current weather in Berlin")
    example_image = fmt["example"].format(tool_name="ImageGenerator", input="a sunset over the ocean")

    return (
        "You are a helpful assistant with access to tools.\n\n"
        "=== AVAILABLE TOOLS ===\n"
        f"{tools_section}\n\n"
        "=== HOW TO USE TOOLS ===\n"
        f"{fmt['instruction']}\n\n"
        "EXAMPLES:\n"
        f"  {example_search}\n"
        f"  {example_image}\n\n"
        "WHEN TO USE TOOLS:\n"
        "- The user asks about current events, weather, news → use WebSearch\n"
        "- The user asks for an image or picture → use ImageGenerator\n"
        "- For normal conversation, just respond without tools.\n\n"
        "Write your response, then add the tool call at the end if needed."
    )


# ============================================================================
# Vision Test
# ============================================================================

def _create_solid_png(r: int, g: int, b: int, size: int = 16) -> str:
    """Erzeugt ein einfarbiges PNG als base64 Data-URI."""
    width = height = size
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    raw = b''
    for _ in range(height):
        raw += b'\x00' + bytes([r, g, b]) * width
    compressed = zlib.compress(raw)

    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack('>I', len(data)) + c + crc

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', ihdr_data)
    png += chunk(b'IDAT', compressed)
    png += chunk(b'IEND', b'')
    return base64.b64encode(png).decode()


# Zwei Test-Farben: pruefen ob das Modell beide korrekt erkennt
VISION_TESTS = [
    {
        "name": "red",
        "rgb": (255, 0, 0),
        "expected": ["red", "rot"],
    },
    {
        "name": "blue",
        "rgb": (0, 0, 255),
        "expected": ["blue", "blau"],
    },
]


class VisionResult:
    def __init__(self, model: str, color_name: str):
        self.model = model
        self.color_name = color_name
        self.success = False
        self.error: Optional[str] = None
        self.response_text: str = ""
        self.duration: float = 0.0


def test_vision(
    api_base: str,
    api_key: str,
    model: str,
    timeout: float,
    verbose: bool = False,
) -> Tuple[Optional[bool], Dict[str, str]]:
    """Testet Vision-Faehigkeit eines Modells.

    Returns:
        (vision_ok, responses) Tuple:
          vision_ok: True/False/None
          responses: Dict mit Farb-Name → Antworttext (fuer Qualitaetsbewertung)
    """
    results: List[VisionResult] = []
    responses: Dict[str, str] = {}

    for vt in VISION_TESTS:
        vr = VisionResult(model, vt["name"])
        label = f"  [vision] {vt['name']}"
        print(f"{label:.<50}", end=" ", flush=True)

        png_b64 = _create_solid_png(*vt["rgb"])
        data_uri = f"data:image/png;base64,{png_b64}"

        messages = [
            {"role": "system", "content": "You are a vision assistant. Answer briefly."},
            {"role": "user", "content": [
                {"type": "text", "text": "What color is this image? Answer with just the color name."},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]},
        ]

        start = time.time()
        try:
            url = f"{api_base}/chat/completions"
            headers = {}
            if api_key and api_key != "not-needed":
                headers["Authorization"] = f"Bearer {api_key}"
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 50,
                "stream": False,
            }
            resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            response = choices[0]["message"]["content"] if choices else ""

            vr.duration = time.time() - start
            vr.response_text = response
            responses[vt["name"]] = response.strip()

            response_lower = response.lower()
            if any(kw in response_lower for kw in vt["expected"]):
                vr.success = True
                print(f"OK — \"{response.strip()[:60]}\" [{vr.duration:.1f}s]")
            else:
                print(f"FAIL — \"{response.strip()[:60]}\" [{vr.duration:.1f}s]")

        except httpx.HTTPStatusError as e:
            vr.duration = time.time() - start
            vr.error = f"HTTP {e.response.status_code}"
            print(f"NO VISION (HTTP {e.response.status_code}) [{vr.duration:.1f}s]")
        except httpx.TimeoutException:
            vr.duration = time.time() - start
            vr.error = "TIMEOUT"
            print(f"TIMEOUT [{vr.duration:.1f}s]")
        except Exception as e:
            vr.duration = time.time() - start
            vr.error = str(e)[:80]
            print(f"ERROR ({vr.error}) [{vr.duration:.1f}s]")

        if verbose and vr.response_text:
            print(f"    Response: {vr.response_text.strip()[:200]}")

        results.append(vr)

        # Erster Test schon HTTP-Fehler → kein Vision, zweiten Test sparen
        if vr.error and vr.error.startswith("HTTP"):
            break

    # Auswertung
    http_errors = [r for r in results if r.error and r.error.startswith("HTTP")]
    if http_errors:
        return False, responses

    successes = sum(1 for r in results if r.success)
    if successes > 0:
        return True, responses
    return False, responses


# ============================================================================
# Test Runner
# ============================================================================

class TestResult:
    def __init__(self, model: str, format_name: str, prompt_name: str):
        self.model = model
        self.format_name = format_name
        self.prompt_name = prompt_name
        self.success = False
        self.correct_tool = False
        self.detected_tool: Optional[str] = None
        self.detected_format: Optional[str] = None
        self.is_placeholder = False
        self.hallucinated = False
        self.error: Optional[str] = None
        self.response_text: str = ""
        self.duration: float = 0.0


def test_model_format(
    api_base: str,
    api_key: str,
    model: str,
    fmt_name: str,
    prompt: Dict[str, str],
    timeout: float,
) -> TestResult:
    """Testet ein Modell mit einem Format und einem Prompt."""
    result = TestResult(model, fmt_name, prompt["name"])

    system_prompt = build_system_prompt(fmt_name)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt["user_msg"]},
    ]

    start = time.time()
    try:
        response = chat_completion(api_base, model, messages, api_key=api_key, timeout=timeout)
        result.duration = time.time() - start
        result.response_text = response

        # Tool-Call suchen — zuerst im angeforderten Format, dann alle
        tc = find_tool_call(response, fmt_name)
        if tc:
            result.detected_format = fmt_name
            result.detected_tool = tc[0]
            result.is_placeholder = is_placeholder(tc[1])
        else:
            tc_any = find_any_tool_call(response)
            if tc_any:
                result.detected_format = tc_any[2]
                result.detected_tool = tc_any[0]
                result.is_placeholder = is_placeholder(tc_any[1])

        if result.detected_tool and not result.is_placeholder:
            result.success = True
            result.correct_tool = (result.detected_tool == prompt["expected_tool"])
            result.hallucinated = detect_hallucination(response, prompt)

    except httpx.TimeoutException:
        result.duration = time.time() - start
        result.error = "TIMEOUT"
    except httpx.HTTPStatusError as e:
        result.duration = time.time() - start
        result.error = f"HTTP {e.response.status_code}"
    except Exception as e:
        result.duration = time.time() - start
        result.error = str(e)[:80]

    return result


def test_model(
    api_base: str,
    api_key: str,
    model: str,
    timeout: float,
    verbose: bool = False,
    run_tools: bool = True,
    run_vision: bool = True,
) -> Dict[str, Any]:
    """Testet ein Modell mit allen Formaten und Prompts + Vision."""
    print(f"\n{'='*70}")
    print(f"  Modell: {model}")
    print(f"{'='*70}")

    results: List[TestResult] = []

    # --- Tool-Tests ---
    if run_tools:
        for fmt_name in TOOL_FORMATS:
            for prompt in TEST_PROMPTS:
                label = f"  [{fmt_name}] {prompt['name']}"
                print(f"{label:.<50}", end=" ", flush=True)

                r = test_model_format(api_base, api_key, model, fmt_name, prompt, timeout)
                results.append(r)

                if r.error:
                    print(f"ERROR ({r.error}) [{r.duration:.1f}s]")
                elif r.success and r.correct_tool and not r.hallucinated:
                    fmt_info = f" (via {r.detected_format})" if r.detected_format != fmt_name else ""
                    print(f"OK {r.detected_tool}{fmt_info} [{r.duration:.1f}s]")
                elif r.success and r.correct_tool and r.hallucinated:
                    fmt_info = f" (via {r.detected_format})" if r.detected_format != fmt_name else ""
                    print(f"OK (WARN) {r.detected_tool}{fmt_info} — halluziniert vor Tool-Call [{r.duration:.1f}s]")
                elif r.success and not r.correct_tool:
                    print(f"WRONG TOOL: {r.detected_tool} (erwartet: {prompt['expected_tool']}) [{r.duration:.1f}s]")
                elif r.is_placeholder:
                    print(f"PLACEHOLDER (halluziniert) [{r.duration:.1f}s]")
                else:
                    print(f"FAIL (kein Tool-Call erkannt) [{r.duration:.1f}s]")

                if verbose and r.response_text:
                    snippet = r.response_text[:300].replace("\n", "\n    ")
                    print(f"    Response: {snippet}")
                    if len(r.response_text) > 300:
                        print(f"    ... ({len(r.response_text)} chars total)")

    # --- Vision-Test ---
    vision_result = None
    vision_responses: Dict[str, str] = {}
    if run_vision:
        vision_result, vision_responses = test_vision(api_base, api_key, model, timeout, verbose)

    # Zusammenfassung pro Modell
    summary = analyze_results(model, results, vision_result, vision_responses)
    return summary


def analyze_results(model: str, results: List[TestResult],
                    vision_result: Optional[bool] = None,
                    vision_responses: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Analysiert die Test-Ergebnisse eines Modells."""
    total = len(results)
    clean = sum(1 for r in results if r.success and r.correct_tool and not r.hallucinated)
    warned = sum(1 for r in results if r.success and r.correct_tool and r.hallucinated)
    successes = clean + warned
    wrong_tool = sum(1 for r in results if r.success and not r.correct_tool)
    placeholders = sum(1 for r in results if r.is_placeholder)
    errors = sum(1 for r in results if r.error)
    fails = total - successes - wrong_tool - placeholders - errors

    # Bestes Format ermitteln
    format_scores: Dict[str, int] = {}
    for fmt_name in TOOL_FORMATS:
        fmt_results = [r for r in results if r.format_name == fmt_name]
        score = sum(1 for r in fmt_results if r.success and r.correct_tool)
        format_scores[fmt_name] = score

    best_format = max(format_scores, key=format_scores.get) if any(format_scores.values()) else None
    best_score = format_scores.get(best_format, 0) if best_format else 0

    # Bevorzugtes Ausgabeformat (welches Format das LLM tatsaechlich benutzt)
    preferred_formats = [r.detected_format for r in results if r.success and r.detected_format]
    from collections import Counter
    preferred = Counter(preferred_formats).most_common(1)
    preferred_format = preferred[0][0] if preferred else None

    tool_calling = successes > 0
    avg_duration = sum(r.duration for r in results) / total if total > 0 else 0

    summary = {
        "model": model,
        "tool_calling": tool_calling,
        "vision": vision_result,
        "vision_responses": vision_responses or {},
        "score": f"{clean}/{total}",
        "score_with_warn": f"{successes}/{total}",
        "clean": clean,
        "warned": warned,
        "successes": successes,
        "wrong_tool": wrong_tool,
        "placeholders": placeholders,
        "fails": fails,
        "errors": errors,
        "best_format": best_format,
        "best_format_score": best_score,
        "preferred_format": preferred_format,
        "avg_duration": avg_duration,
        "format_scores": format_scores,
    }

    # Zusammenfassung ausgeben
    parts = []
    if total > 0:
        status = "OK — TOOL-CALLING" if tool_calling else "FAIL — KEIN TOOL-CALLING"
        warn_info = f", {warned} mit Halluzination" if warned else ""
        parts.append(f"Tools: {status} ({clean}/{total} sauber{warn_info})")
    if vision_result is not None:
        v_status = "OK — VISION" if vision_result else "FAIL — KEIN VISION"
        parts.append(f"Vision: {v_status}")
    print(f"\n  Ergebnis: {' | '.join(parts)}")
    if best_format and best_score > 0:
        print(f"  Bestes Format: {best_format} ({best_score}/{len(TEST_PROMPTS)})")
    if preferred_format:
        print(f"  LLM bevorzugt: {preferred_format}")
    if total > 0:
        print(f"  Durchschnittliche Antwortzeit: {avg_duration:.1f}s")

    return summary


# ============================================================================
# Ergebnis-Tabelle & Export
# ============================================================================

def print_summary_table(provider_name: str, summaries: List[Dict[str, Any]]):
    """Gibt eine Zusammenfassungstabelle aus."""
    if not summaries:
        return

    print(f"\n{'='*90}")
    print(f"  ZUSAMMENFASSUNG — {provider_name}")
    print(f"{'='*90}")

    # Header
    has_vision = any(s.get("vision") is not None for s in summaries)
    has_tools = any(s.get("clean", 0) + s.get("fails", 0) > 0 for s in summaries)

    hdr = f"  {'Modell':<40}"
    sep = f"  {'-'*40}"
    if has_tools:
        hdr += f" {'Tools':>5} {'Score':>7} {'Warn':>5} {'Best Format':>14}"
        sep += f" {'-'*5} {'-'*7} {'-'*5} {'-'*14}"
    if has_vision:
        hdr += f" {'Vision':>7}"
        sep += f" {'-'*7}"
    hdr += f" {'Avg Time':>9}"
    sep += f" {'-'*9}"
    print(f"\n{hdr}")
    print(sep)

    for s in sorted(summaries, key=lambda x: (x.get("clean", 0), -x.get("warned", 0)), reverse=True):
        line = f"  {s['model']:<40}"
        if has_tools:
            status = "  OK" if s["tool_calling"] else "FAIL"
            best_fmt = s["best_format"] or "-"
            warn_str = str(s["warned"]) if s.get("warned") else "-"
            line += f" {status:>5} {s['score']:>7} {warn_str:>5} {best_fmt:>14}"
        if has_vision:
            v = s.get("vision")
            v_str = "  OK" if v is True else "FAIL" if v is False else "   -"
            line += f" {v_str:>7}"
        line += f" {s['avg_duration']:>7.1f}s"
        print(line)

    # Legende
    if has_tools:
        print(f"\n  Getestete Formate: {', '.join(TOOL_FORMATS.keys())}")
        print(f"  Test-Prompts: {len(TEST_PROMPTS)} pro Format = {len(TEST_PROMPTS) * len(TOOL_FORMATS)} Tests pro Modell")
    if has_vision:
        print(f"  Vision-Test: Farberkennung auf 2 Test-PNGs (rot, blau)")


def save_to_capabilities(summaries: List[Dict[str, Any]]):
    """Speichert Ergebnisse in model_capabilities.json."""
    if not CAPABILITIES_FILE.exists():
        data = {"_comment": "Model Capabilities.", "models": {}}
    else:
        with open(CAPABILITIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

    models = data.setdefault("models", {})
    updated = 0

    for s in summaries:
        model_key = s["model"]
        entry = models.get(model_key, {})

        old_tc = entry.get("tool_calling")
        new_tc = s["tool_calling"]

        entry["tool_calling"] = new_tc
        if s["best_format"] and s["tool_calling"]:
            entry["tested_best_format"] = s["best_format"]
        if s.get("clean", 0) + s.get("fails", 0) > 0:
            entry["tested_score"] = s["score"]
        if s.get("warned"):
            entry["tested_hallucinations"] = s["warned"]
        elif "tested_hallucinations" in entry:
            del entry["tested_hallucinations"]

        # Vision
        if s.get("vision") is not None:
            old_vision = entry.get("vision")
            entry["vision"] = s["vision"]
            if s["vision_responses"]:
                entry["tested_vision_responses"] = s["vision_responses"]
            if old_vision != s["vision"]:
                v_action = "NEU" if old_vision is None else f"{old_vision} -> {s['vision']}"
                print(f"  {model_key}: vision {v_action}")

        entry["tested_date"] = time.strftime("%Y-%m-%d")

        if old_tc != new_tc:
            updated += 1
            action = "NEU" if old_tc is None else f"{old_tc} -> {new_tc}"
            print(f"  {model_key}: tool_calling {action}")

        models[model_key] = entry

    with open(CAPABILITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n  {len(summaries)} Modelle in {CAPABILITIES_FILE} gespeichert ({updated} geaendert)")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Testet alle LLMs eines Providers auf Tool-Calling-Faehigkeit"
    )
    parser.add_argument(
        "provider", nargs="?", default=None,
        help="Name des LLM-Providers aus dem Legacy-.env-Block (z.B. local-llm, local-llm-2)"
    )
    parser.add_argument(
        "--api-base", default=None,
        help="Direkte API-URL (statt Provider-Name aus dem .env-Block)"
    )
    parser.add_argument(
        "--api-key", default="",
        help="API-Key (nur bei --api-base noetig)"
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_providers",
        help="Alle Provider aus .env auflisten"
    )
    parser.add_argument(
        "--model", default=None,
        help="Nur bestimmtes Modell testen (glob-Pattern, z.B. 'qwen3*')"
    )
    parser.add_argument(
        "--timeout", type=float, default=300,
        help="Timeout pro Request in Sekunden (default: 120)"
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Ergebnisse in model_capabilities.json speichern"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Antwort-Texte anzeigen"
    )
    parser.add_argument(
        "--format", choices=list(TOOL_FORMATS.keys()), default=None,
        help="Nur ein bestimmtes Format testen"
    )
    parser.add_argument(
        "--no-vision", action="store_true",
        help="Vision-Test ueberspringen"
    )
    parser.add_argument(
        "--no-tools", action="store_true",
        help="Tool-Tests ueberspringen (nur Vision)"
    )
    args = parser.parse_args()

    # --list: Provider auflisten und beenden
    if args.list_providers:
        list_providers()
        sys.exit(0)

    # Provider oder --api-base erforderlich
    if not args.provider and not args.api_base:
        parser.print_usage()
        print(f"\nBitte Provider-Name oder --api-base angeben.")
        print(f"Verfuegbare Provider anzeigen: python {sys.argv[0]} --list")
        sys.exit(1)

    # API-URL aufloesen
    if args.api_base:
        api_base = args.api_base
        api_key = args.api_key
        provider_label = args.api_base
    else:
        api_base, api_key = resolve_provider(args.provider)
        provider_label = args.provider

    # Wenn nur ein Format getestet werden soll — Modul-Global einschraenken
    if args.format:
        _filtered = {args.format: TOOL_FORMATS[args.format]}
        TOOL_FORMATS.clear()
        TOOL_FORMATS.update(_filtered)

    run_tools = not args.no_tools
    run_vision = not args.no_vision

    test_label = []
    if run_tools:
        test_label.append("Tools")
    if run_vision:
        test_label.append("Vision")

    print(f"LLM Test: {' + '.join(test_label)}")
    print(f"Provider: {provider_label}")
    print(f"API: {api_base}")
    print(f"Timeout: {args.timeout}s")

    # Modelle laden
    print(f"\nLade Modelle...")
    try:
        models_raw = list_models(api_base, api_key)
    except Exception as e:
        print(f"FEHLER: Kann keine Modelle laden: {e}")
        sys.exit(1)

    model_ids = sorted(m["id"] for m in models_raw if "id" in m)
    print(f"  {len(model_ids)} Modelle gefunden")

    # Filter
    if args.model:
        model_ids = [m for m in model_ids if fnmatch.fnmatch(m.lower(), args.model.lower())]
        print(f"  {len(model_ids)} nach Filter '{args.model}'")

    if not model_ids:
        print("Keine Modelle zum Testen gefunden.")
        sys.exit(0)

    print(f"\nModelle zum Testen:")
    for m in model_ids:
        print(f"  - {m}")

    # Tests durchfuehren
    summaries: List[Dict[str, Any]] = []
    for model_id in model_ids:
        try:
            summary = test_model(api_base, api_key, model_id, args.timeout, args.verbose,
                                run_tools=run_tools, run_vision=run_vision)
            summaries.append(summary)
        except KeyboardInterrupt:
            print("\n\nAbgebrochen (Ctrl+C)")
            break
        except Exception as e:
            print(f"\n  FEHLER bei {model_id}: {e}")
            summaries.append({
                "model": model_id,
                "tool_calling": False, "vision": None,
                "vision_responses": {},
                "score": "0/0",
                "clean": 0, "warned": 0,
                "successes": 0, "wrong_tool": 0, "placeholders": 0,
                "fails": 0, "errors": 1,
                "best_format": None, "best_format_score": 0,
                "preferred_format": None, "avg_duration": 0,
                "format_scores": {},
            })

    # Zusammenfassung
    print_summary_table(provider_label, summaries)

    # Optional speichern
    if args.save and summaries:
        print(f"\nSpeichere in {CAPABILITIES_FILE}...")
        save_to_capabilities(summaries)

    # JSON-Export
    print(f"\n--- JSON-Export ---")
    export = []
    for s in summaries:
        entry = {
            "model": s["model"],
            "tool_calling": s["tool_calling"],
            "vision": s.get("vision"),
            "score": s["score"],
            "hallucinations": s.get("warned", 0),
            "best_format": s["best_format"],
            "preferred_format": s["preferred_format"],
            "avg_duration_s": round(s["avg_duration"], 1),
        }
        if s.get("vision_responses"):
            entry["vision_responses"] = s["vision_responses"]
        export.append(entry)
    print(json.dumps(export, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
