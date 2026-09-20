"""
Tool format system - configurable tool-calling format for different LLMs.

Every format defines:
- instruction: how the LLM should format tool calls (for the system prompt)
- example: template for examples (with {tool_name} and {input} placeholders)
- pattern: regex that detects tool calls in the LLM answer
- stream_pattern: regex for early detection while streaming
- direct_pattern: regex for direct tool calls in user messages
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("tool_formats")


# ============================================================================
# Format definitions
# ============================================================================

TOOL_FORMATS: Dict[str, Dict[str, Any]] = {
    "tag": {
        "name": "XML Tag",
        "description": "XML-like tag format. Very reliable, LLMs know tags well.",
        "instruction": (
            "To use a tool, write EXACTLY this format:\n"
            "<tool name=\"ToolName\">your detailed input here</tool>\n"
            "RULES:\n"
            "- The tool name must be EXACTLY one of the available tool names\n"
            "- Write your input between the opening and closing tags\n"
            "- Do NOT add any text after the closing </tool> tag\n"
            "- WRONG: I will use ToolName to create...\n"
            "- RIGHT: <tool name=\"ToolName\">your detailed input here</tool>\n"
            "- If a tool needs no input, write {} between the tags: <tool name=\"ToolName\">{}</tool>"
        ),
        "example": '<tool name="{tool_name}">{input}</tool>',
        "pattern": r'<tool\s+name="(\w+)">([\s\S]*?)</tool>',
        "stream_pattern": r'<tool\s+name="(\w+)">([\s\S]*?)</tool>',
        "direct_pattern": r'^<tool\s+name="(\w+)">([\s\S]*?)</tool>$',
    },
    "natural_en": {
        "name": "English Natural",
        "description": "English natural-language format. Good for English-trained models.",
        "instruction": (
            "To use a tool, write EXACTLY this format:\n"
            "Use ToolName for: your detailed input here\n"
            "RULES:\n"
            "- Write EXACTLY 'Use' then the tool name then 'for:' WITH COLON\n"
            "- Then the details. Do NOT use brackets [] in real tool calls.\n"
            "- Example: Use ToolName for: your detailed input here"
        ),
        "example": "Use {tool_name} for: {input}",
        "pattern": r"(?:I\s+)?[Uu]se\s+(\w+)\s+for:\s*(.*?)(?:\n|$)",
        "stream_pattern": r"(?:I\s+)?[Uu]se\s+(\w+)\s+for:\s*(.*?)(?:\n|$)",
        "direct_pattern": r"^(?:I\s+)?[Uu]se\s+(\w+)\s+for:\s*(.*?)$",
    },
    "natural_de": {
        "name": "German Natural",
        "description": "German natural-language format. The former default format.",
        "instruction": (
            "Um ein Tool zu nutzen, schreibe EXAKT dieses Format:\n"
            "Ich nutze ToolName für: deine detaillierte Eingabe hier\n"
            "REGELN:\n"
            "- Schreibe GENAU 'Ich nutze' gefolgt vom Tool-Namen (ein Wort)\n"
            "- Dann 'für:' MIT DOPPELPUNKT\n"
            "- Dann die Details/Beschreibung\n"
            "- FALSCH: Ich nutze die Skills des ToolName für Dich\n"
            "- RICHTIG: Ich nutze ToolName für: deine detaillierte Eingabe hier"
        ),
        "example": "Ich nutze {tool_name} für: {input}",
        "pattern": r"(?:Ich\s+)?[Nn]utze\s+(\w+)\s+f(?:ü|ue)r:\s*(.*?)(?:\n|$)",
        "stream_pattern": r"(?:Ich\s+)?[Nn]utze\s+(\w+)\s+f(?:ü|ue)r:\s*(.*?)(?:\n|$)",
        "direct_pattern": r"^(?:Ich\s+)?[Nn]utze\s+(\w+)\s+f(?:ü|ue)r:\s*(.*?)$",
    },
}


# ============================================================================
# Model-to-format library
# Mapping: model name (or substring) -> recommended format
# The longest matching substring wins - more specific entries first
# ============================================================================

MODEL_FORMAT_LIBRARY: Dict[str, str] = {
    # --- Large models (>30B) - tag format recommended ---
    "gpt-4": "tag",
    "gpt-3.5": "tag",
    "claude": "tag",
    "qwen3": "tag",
    "qwen2.5-coder": "tag",
    "deepseek": "tag",
    "codestral": "tag",
    "command-r": "tag",
    "gemma2": "tag",

    # --- Mid-size models (7B-13B) ---
    "mistral": "natural_en",
    "llama3": "natural_en",
    "llama2": "natural_en",
    "phi3": "natural_en",
    "phi4": "tag",
    "gemma": "natural_en",
    "solar": "natural_en",
    "yi": "natural_en",
    "internlm": "natural_en",
    "glm": "tag",

    # --- Small / uncensored models ---
    "wizardlm": "natural_en",
    "wizard-vicuna": "natural_en",
    "dolphin": "natural_en",
    "openhermes": "natural_en",
    "nous-hermes": "natural_en",
    "neural-chat": "natural_en",
    "orca": "natural_en",
    "stablelm": "natural_en",
    "tinyllama": "natural_en",

    # --- Fallback ---
    "_default": "tag",
}


# ============================================================================
# Helpers
# ============================================================================

def get_format(format_name: str) -> Dict[str, Any]:
    """Returns a tool format; falls back to 'tag' when unknown."""
    return TOOL_FORMATS.get(format_name, TOOL_FORMATS["tag"])


def get_format_for_model(model_name: str) -> str:
    """Determines the recommended format for a model from the library.

    Searches MODEL_FORMAT_LIBRARY for substring matches in the model name.
    """
    if not model_name:
        return MODEL_FORMAT_LIBRARY.get("_default", "tag")

    model_lower = model_name.lower()

    # Exact match first
    if model_lower in MODEL_FORMAT_LIBRARY:
        return MODEL_FORMAT_LIBRARY[model_lower]

    # Substring match (longest match wins)
    best_match = ""
    best_format = MODEL_FORMAT_LIBRARY.get("_default", "tag")

    for pattern, fmt in MODEL_FORMAT_LIBRARY.items():
        if pattern.startswith("_"):
            continue
        if pattern.lower() in model_lower and len(pattern) > len(best_match):
            best_match = pattern
            best_format = fmt

    return best_format


def format_example(format_name: str, tool_name: str, example_input: str) -> str:
    """Builds an example for the system prompt."""
    fmt = get_format(format_name)
    return fmt["example"].format(tool_name=tool_name, input=example_input)


# No tool names here: the AVAILABLE TOOLS block above the instruction already
# lists exactly the tools this character has, and a hard-wired name list
# contradicts it as soon as a tool is renamed or unavailable (A3.2b — the old
# text still advertised "ImageGenerator", a name that has not existed since the
# rename to TakePhoto).
_DEFAULT_TOOL_INSTRUCTION = (
    "WHEN TO USE TOOLS:\n"
    "- Only the tools listed under AVAILABLE TOOLS above exist. Never call a tool that is "
    "not on that list and never invent a tool name.\n"
    "- Whenever the user asks for something one of those tools does — up-to-date information "
    "about current events, news or real-world facts; an image or a picture; looking something "
    "up; going somewhere or changing location — you MUST call that tool. Do NOT answer from "
    "memory, do NOT make up information.\n"
    "HOW: Write your in-character response, then add the tool call at the end. "
    "The system will execute the tool automatically.\n"
    "TOOL INPUT RULES: When a tool expects JSON input, field values must be plain text — "
    "NEVER put JSON objects or tool tags inside field values."
)

# Extra clause for roleplay characters only (chatbots may/should use tools freely)
_ROLEPLAY_TOOL_NOUSE_CLAUSE = (
    "WHEN NOT TO USE TOOLS:\n"
    "- The user is just chatting, asking about your feelings, or discussing fiction/roleplay."
)


def _image_tool_names() -> frozenset:
    """Tool names of skills that produce an image (PROGRESS_TYPE 'image').

    The appearance / photographer hints only make sense for those. Declared by
    the skill, never named in the core (F7/R1).
    """
    try:
        from app.core.dependencies import get_skill_manager
        return frozenset(
            s.name for s in get_skill_manager().skills
            if getattr(s, "PROGRESS_TYPE", "") == "image")
    except Exception:
        return frozenset()


def _get_tool_instruction_for_model(model_name: str) -> str:
    """Loads the tool_instruction for a model from model_capabilities.json.

    Falls back to _DEFAULT_TOOL_INSTRUCTION when not configured.
    """
    if not model_name:
        return _DEFAULT_TOOL_INSTRUCTION
    try:
        from app.core.model_capabilities import get_model_capabilities
        caps = get_model_capabilities(model_name)
        custom = caps.get("tool_instruction", "")
        if custom:
            return custom
    except Exception:
        pass
    return _DEFAULT_TOOL_INSTRUCTION


def build_tool_instruction(format_name: str, tools: List[Any],
                           appearance: str = "", usage_instructions: str = "",
                           model_name: str = "",
                           photographer_mode: bool = False,
                           user_appearance: str = "",
                           is_roleplay: bool = True) -> str:
    """Builds the complete tool-instruction block for the system prompt.

    Args:
        format_name: name of the tool format (tag, natural_en, natural_de)
        tools: list of available tools (with .name and .description)
        appearance: agent appearance for the appearance hint
        usage_instructions: skill-specific usage instructions
        model_name: model name for model-specific tool instructions
        photographer_mode: True when the agent is the photographer (not in the picture)
        user_appearance: user appearance (for photographer mode)
        is_roleplay: True for RP characters (adds the "WHEN NOT TO USE TOOLS"
            clause that keeps chatting/feelings/fiction out of tool calls).
            Chatbots = False.
    """
    fmt = get_format(format_name)

    parts = ["\n\n=== AVAILABLE TOOLS ==="]
    for tool in tools:
        parts.append(f"- {tool.name}: {tool.description}")

    parts.append("\n=== HOW TO USE TOOLS ===")
    parts.append(fmt["instruction"])

    # Output discipline — derived from real bad outputs (suitability data):
    # models drift into meta/reasoning prose ("Based on...", "We need to
    # analyse...") or invent their own formats ([brackets], "INTENT:"/"TOOLS:"
    # headers, **markdown** tool names) — the parser then executes nothing.
    # STRICT OUTPUT targets ONLY the tool-call format. Important: do NOT ban
    # square brackets / markdown wholesale — the rp_first tool LLM gets this
    # block as its system prompt AND is expected to emit markers (**I feel ...**)
    # and [INTENT:/NEW_ASSIGNMENT:] lines afterwards. What is forbidden is a
    # TOOL call in a foreign shape, not brackets as such.
    parts.append(
        "\nSTRICT OUTPUT:\n"
        "- Do NOT explain, analyse or think out loud. No preamble, no commentary, "
        "no phrases like \"Based on...\", \"We need to analyse...\", \"Let me...\".\n"
        "- A TOOL CALL is ONLY the exact tag syntax shown above. Never write a tool "
        "call any other way: not in [square brackets], not as a \"TOOLS:\" list or an "
        "\"[INTENT: execute_tool ...]\" line, not in **markdown** or bold, "
        "not buried inside a sentence."
    )

    # Positive example in the exact target format — pulls weak models into the
    # format and shows multiple calls. Tool name = the first tool that really
    # is available (no invented name); the input is the textual placeholder
    # that _is_placeholder_input filters, should a model copy the example.
    # Deliberately NO square brackets: a bracketed example teaches the model
    # to bracket its inputs, and a parameterless verb then comes back as "[]".
    if tools:
        _ex = format_example(format_name, tools[0].name, "your detailed input here")
        parts.append(
            "\nEXAMPLE of a correct tool call (use this exact shape):\n"
            f"{_ex}\n"
            "If two actions happen, write two such lines, one per line."
        )

    # Appearance hint for image-producing tools. Which tool produces an image
    # is declared by the skill (PROGRESS_TYPE "image"), never named here
    # (F7/R1) — the former `if "ImageGenerator" in tool_names` had been dead
    # since the rename to TakePhoto and silently dropped both hints.
    tool_names = [t.name for t in tools]
    if any(n in _image_tool_names() for n in tool_names):
        if photographer_mode:
            # Photographer mode: the agent takes the picture and is not in it
            photographer_hint = (
                "\nYou are a PHOTOGRAPHER. When generating images, describe ONLY the subjects "
                "you are photographing. Do NOT include yourself or your own appearance in the "
                "image description. When the user says 'Foto von mir' or 'photo of me', "
                "they mean themselves — describe THEM, not yourself."
            )
            if user_appearance:
                photographer_hint += f"\nThe user's appearance: {user_appearance}"
            parts.append(photographer_hint)
        elif appearance:
            # Normal mode: agent appearance for self-portraits
            parts.append(
                f"\nWhen generating images of yourself, always include your appearance: {appearance}"
            )

    # Skill-specific examples (one line per skill)
    if usage_instructions:
        for line in usage_instructions.split('\n'):
            if line.strip():
                parts.append(f"- {line.strip()}")

    # Model-specific tool instruction (from model_capabilities.json)
    instruction = _get_tool_instruction_for_model(model_name)
    parts.append(f"\n{instruction}")

    # RP only: chatting/feelings/fiction trigger no tools
    if is_roleplay:
        parts.append(_ROLEPLAY_TOOL_NOUSE_CLAUSE)

    return "\n".join(parts)




def _is_placeholder_input(tool_input: str) -> bool:
    """Detects whether a tool input is a hallucinated placeholder.

    Small LLMs often copy the examples from the system prompt as real tool
    calls; this filters the obvious placeholder inputs out.

    An EMPTY container is not a placeholder: a parameterless verb (Undress,
    IgnoreDressCode, ...) is legitimately called as ``{}`` or ``[]`` — the
    model has nothing to put between the tags. Dropping ``[]`` here used to
    swallow every such call silently (the verb showed up in the LLM log and
    was never executed).
    """
    stripped = tool_input.strip()
    if not stripped:
        return False
    if stripped in ("[]", "{}"):
        return False
    # "[search query or question]", "[detailed image description]", "[mood/feeling]"
    if stripped.startswith("[") and stripped.endswith("]"):
        return True
    # "your detailed input here", "deine detaillierte Eingabe hier", "your input"
    if stripped.lower() in ("your detailed input here", "deine detaillierte eingabe hier", "your input"):
        return True
    return False


def find_tool_calls(format_name: str, text: str,
                    known_tools: Optional[Dict] = None) -> List[Tuple[str, str]]:
    """Finds all tool calls in a text.

    Checks ALL known formats (not only the configured one) because LLMs
    often use a different format than instructed.

    Args:
        format_name: name of the configured tool format (checked first)
        text: the text to search
        known_tools: optional dict of known tools for fallback matching

    Returns:
        list of (tool_name, tool_input) tuples
    """
    raw_matches = []

    # 1. Configured format first
    fmt = get_format(format_name)
    matches = re.findall(fmt["pattern"], text, re.IGNORECASE)
    if matches:
        raw_matches = [(name, inp.strip()) for name, inp in matches]
    else:
        # 2. Try every other format
        for other_name, other_fmt in TOOL_FORMATS.items():
            if other_name == format_name:
                continue
            matches = re.findall(other_fmt["pattern"], text, re.IGNORECASE)
            if matches:
                logger.debug("Tool detected via '%s' format (configured: '%s')", other_name, format_name)
                raw_matches = [(name, inp.strip()) for name, inp in matches]
                break

        # 3. Fallback: flexible matching on known tool names
        if not raw_matches and known_tools:
            tool_names_pattern = "|".join(re.escape(name) for name in known_tools.keys())
            # Universal fallback: tool name followed by für:/for: and text.
            # The colon is MANDATORY (prevents matches on running prose)
            fallback = rf"(?:[Nn]utze|[Uu]se)\s+({tool_names_pattern})\s+(?:f(?:ü|ue)r|for):\s*(.*?)(?:\n|$)"
            matches = re.findall(fallback, text, re.IGNORECASE)
            if matches:
                # Several fallback matches = mass hallucination → drop all
                if len(matches) > 1:
                    logger.debug("Fallback: %d matches found - hallucination, all dropped", len(matches))
                    return []
                logger.debug("Fallback pattern detected a tool: %s", matches)
                raw_matches = [(name, inp.strip()) for name, inp in matches]

    # Open end tag: LLMs often drop the closing </tool> on the LAST
    # <tool name="X"> (especially on a JSON-heavy final tag). The closed
    # pattern above loses it entirely, so recover the last unclosed tag
    # up to the end of the text.
    _last_open = None
    for _m in re.finditer(r'<tool\s+name="(\w+)">', text, re.IGNORECASE):
        _last_open = _m
    if _last_open and "</tool>" not in text[_last_open.end():]:
        _nm = _last_open.group(1)
        _inp = text[_last_open.end():].strip()
        # Running to EOF swallows whatever follows the call — typically the
        # fallback-marker lines (**I feel ...**) the Tool-LLM appends. For a
        # JSON input keep only the first balanced object; otherwise strip
        # trailing marker-only lines. Without this, downstream json.loads
        # fails and e.g. Instagram posts the raw JSON blob as its caption.
        if _inp.startswith("{"):
            try:
                _, _json_end = json.JSONDecoder().raw_decode(_inp)
                _inp = _inp[:_json_end].strip()
            except ValueError:
                _inp = re.sub(r'(?:\s*\n\s*\*\*[^*\n]+\*\*)+\s*$', '', _inp).strip()
        else:
            _inp = re.sub(r'(?:\s*\n\s*\*\*[^*\n]+\*\*)+\s*$', '', _inp).strip()
        if _inp and not any(n == _nm and i.strip() == _inp for n, i in raw_matches):
            raw_matches.append((_nm, _inp))
            logger.debug("Recovered unclosed end tag: %s", _nm)

    if not raw_matches:
        return []

    # Resolve nested tag tool calls: when an LLM forgets the closing </tool>,
    # the next <tool name="..."> lands inside the previous call's input.
    # Split them apart here.
    _nested_tag = re.compile(r'<tool\s+name="(\w+)">([\s\S]*)', re.IGNORECASE)
    split_matches = []
    for name, inp in raw_matches:
        nested = _nested_tag.search(inp)
        if nested:
            clean_inp = inp[:nested.start()].strip()
            split_matches.append((name, clean_inp))
            nested_name = nested.group(1)
            nested_inp = re.sub(r'</tool>\s*$', '', nested.group(2)).strip()
            split_matches.append((nested_name, nested_inp))
            logger.debug("Nested tool call split: %s + %s", name, nested_name)
        else:
            split_matches.append((name, inp))
    raw_matches = split_matches

    # Detect mass hallucination: when a tool name occurs several times AND
    # the inputs are identical, the calls are hallucinated. Different inputs
    # = legitimate multi-use (e.g. describing several rooms).
    from collections import defaultdict
    tool_inputs_by_name = defaultdict(list)
    for name, inp in raw_matches:
        tool_inputs_by_name[name].append(inp)
    hallucinated_tools = set()
    for name, inputs in tool_inputs_by_name.items():
        if len(inputs) > 1:
            unique_inputs = set(inputs)
            if len(unique_inputs) == 1:
                # All inputs identical → hallucination
                hallucinated_tools.add(name)
                logger.debug("Hallucination detected (identical inputs): %s (%dx)", name, len(inputs))
            else:
                logger.debug("Multi-call with different inputs accepted: %s (%dx)", name, len(inputs))

    # Filter placeholders, duplicates and hallucinated tools
    filtered = []
    for name, inp in raw_matches:
        # "ToolName" is the placeholder from the instruction
        if name.lower() == "toolname":
            logger.debug("Placeholder tool 'ToolName' skipped")
            continue
        # Placeholder inputs such as "[search query or question]". Logged as
        # a warning: a dropped call is otherwise invisible ("tool call in the
        # log, never executed").
        if _is_placeholder_input(inp):
            logger.warning("Tool call %s dropped — placeholder input: %.60s", name, inp)
            continue
        # Tools with identical multi-calls are hallucinated → drop all
        if name in hallucinated_tools:
            continue
        filtered.append((name, inp))

    return filtered


def find_stream_tool_call(format_name: str, text: str,
                          known_tools: Optional[Dict] = None) -> Optional[re.Match]:
    """Checks whether a tool call is detected in the streaming text.

    Checks ALL known formats, not only the configured one.

    Returns:
        re.Match object when found, else None
    """
    # 1. Configured format first
    fmt = get_format(format_name)
    match = re.search(fmt["stream_pattern"], text, re.IGNORECASE)
    if match:
        return match

    # 2. Try every other format
    for other_name, other_fmt in TOOL_FORMATS.items():
        if other_name == format_name:
            continue
        match = re.search(other_fmt["stream_pattern"], text, re.IGNORECASE)
        if match:
            return match

    # 3. Universal fallback on known tool names
    # IMPORTANT: the pattern must match the find_tool_calls() fallback!
    # Colon mandatory, no extra words between Use/Nutze and the tool name
    if known_tools:
        tool_names_pattern = "|".join(re.escape(name) for name in known_tools.keys())
        fallback = rf"(?:[Nn]utze|[Uu]se)\s+({tool_names_pattern})\s+(?:f(?:ü|ue)r|for):\s*(.*?)(?:\n|$)"
        match = re.search(fallback, text, re.IGNORECASE)
        if match:
            return match

    return None
