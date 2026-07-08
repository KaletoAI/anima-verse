"""Base Skill Class für alle Skills"""
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict

from app.core.log import get_logger
from app.core.tool_formats import format_example

logger = get_logger("skill_base")

from app.models.character import get_character_skill_config, save_character_skill_config


@dataclass
class ToolSpec:
    """Einfacher Tool-Descriptor (Ersatz fuer LangChain Tool)."""
    name: str
    description: str
    func: Callable


class BaseSkill(ABC):
    """
    Basis-Klasse für alle Skills.

    Jeder Skill definiert:
    - SKILL_ID: Identifier für per-Agent Config-Dateien (z.B. "image_generation")
    - name / description: Fest definiert in der Subklasse
    - _defaults: Dict mit Default-Werten aus .env

    Per-Agent Overrides werden zur Laufzeit aus
    storage/users/{user}/agents/{agent}/skills/{SKILL_ID}.json geladen.
    """

    SKILL_ID = ""  # subclass must define
    ALWAYS_LOAD = False  # True = skill always loaded, activation per character
    DEFERRED = False  # True = tool intent detected but executed after the chat reply
    CONTENT_TOOL = False  # True = result must flow into the RP (retry in rp_first mode)
    # Declarative tool metadata (F7) — read generically by the core, never
    # by skill name. Packages set them via plugin.yaml, built-ins as class
    # attributes / from their skills/<id>.md frontmatter:
    SINGLETON = False           # state-setting tool: only the LAST call per stream sticks
    SUPPRESS_IN_PERSON = False  # hidden while the conversation partners share a room
    CASCADE_BRAKE = False       # reply_only_to gate for messaging cascades
    SEARCH_INTENT = False       # search-forcing hint targets this tool
    # Declarative intents (F6): [INTENT: <type>] markers the skill executes.
    # The intent engine collects these from loaded skills — no intent type
    # is hardcoded in the core. INTENT_PAYLOAD_KEYS lists the INTENT params
    # (checked in order) that carry the comparable content for the
    # redundancy skip (INTENT marker vs tool already executed this turn).
    INTENT_TYPES: tuple = ()
    INTENT_PAYLOAD_KEYS: tuple = ()

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get('enabled', True)
        self.name = self.__class__.__name__
        self.description = ""
        # Short "Character does X" line for the constrained-mode tool prompt
        # (frontmatter `action_hint:` in the skill meta template).
        self.action_hint = ""
        self._defaults: Dict[str, Any] = {}

    @abstractmethod
    def execute(self, *args, **kwargs) -> str:
        pass

    def _parse_base_input(self, raw_input: str) -> Dict[str, Any]:
        """Extracts the standardized context from the tool input (JSON with character_name)."""
        data: Dict[str, Any] = {"input": raw_input, "agent_name": "", "user_id": ""}

        if isinstance(raw_input, str) and raw_input.strip().startswith("{"):
            try:
                parsed = json.loads(raw_input)
                if isinstance(parsed, dict):
                    data.update(parsed)
            except Exception:
                # Salvage: LLM tool inputs sometimes carry trailing garbage
                # after the JSON object (e.g. fallback-marker lines). Parse
                # the first balanced object instead of dropping all fields.
                try:
                    parsed, _ = json.JSONDecoder().raw_decode(raw_input.strip())
                    if isinstance(parsed, dict):
                        data.update(parsed)
                except Exception:
                    pass

        return data

    def _get_effective_config(self, character_name: str) -> Dict[str, Any]:
        """Merged .env-Defaults mit per-Agent Overrides. Typen werden automatisch anhand der Defaults gecastet."""
        result = dict(self._defaults)

        if not character_name or not self.SKILL_ID:
            return result

        agent_config = get_character_skill_config(character_name, self.SKILL_ID)
        if agent_config:
            for key, default_val in result.items():
                if key in agent_config:
                    val = agent_config[key]
                    # bool VOR int pruefen (bool ist Subklasse von int)
                    if isinstance(default_val, bool):
                        result[key] = bool(val)
                    elif isinstance(default_val, float):
                        result[key] = float(val)
                    elif isinstance(default_val, int):
                        result[key] = int(val)
                    elif isinstance(default_val, list):
                        result[key] = val if isinstance(val, list) else []
                    else:
                        result[key] = str(val).strip()
        else:
            # Erstelle per-Agent Config mit Defaults beim ersten Aufruf
            save_character_skill_config(character_name, self.SKILL_ID, dict(self._defaults))
            logger.info(f"[{self.name}] Per-Agent Config erstellt für {character_name}: {self.SKILL_ID}.json")

        return result

    def get_config_fields(self) -> Dict[str, Dict[str, Any]]:
        """Gibt die konfigurierbaren Felder mit Typ-Info und Defaults zurueck.

        Returns:
            Dict[field_name, {"type": "str"|"bool"|"int"|"float", "default": value, "label": str}]
        """
        fields = {}
        for key, default_val in self._defaults.items():
            if key == "enabled":
                continue  # enabled wird separat per Checkbox gesteuert
            if isinstance(default_val, bool):
                field_type = "bool"
            elif isinstance(default_val, float):
                field_type = "float"
            elif isinstance(default_val, int):
                field_type = "int"
            else:
                field_type = "str"
            fields[key] = {
                "type": field_type,
                "default": default_val,
                "label": key.replace("_", " ").title(),
            }
        return fields

    def get_usage_instructions(self, format_name: str = "", character_name: str = "") -> str:
        if 'usage_instructions' in self.config:
            return self.config['usage_instructions']
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "[input]")

    def handle_intent(self, intent_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one of the skill's declared intents (dispatched from the
        intent engine's TaskQueue handler).

        Default: pass the payload through to execute() as JSON — skills
        with special payload shaping override this.
        """
        raw_input = json.dumps({k: v for k, v in payload.items()
                                if k != "intent_type"}, ensure_ascii=False)
        result = self.execute(raw_input)
        success = bool(result) and "Fehler" not in str(result) \
            and "Error" not in str(result)
        return {"success": success, "result": str(result)[:500]}

    def tool_intent_payload(self, raw_input: str) -> str:
        """Comparable content blob from a tool invocation of this skill —
        used by the intent engine's redundancy skip. Default: the values of
        INTENT_PAYLOAD_KEYS (plus 'input') from a JSON input, else the raw
        text. Empty string disables matching for this call."""
        if not raw_input:
            return ""
        s = raw_input.strip()
        if s.startswith("{"):
            try:
                d = json.loads(s)
                if isinstance(d, dict):
                    for key in tuple(self.INTENT_PAYLOAD_KEYS) + ("input",):
                        val = d.get(key)
                        if val:
                            return str(val)
                    return ""
            except Exception:
                pass
        return s

    def memorize_result(self, result: str, character_name: str) -> bool:
        """Speichert das Execute-Ergebnis als Memory (optional).

        Default: Nichts speichern. Skills ueberschreiben dies bei Bedarf,
        damit Scheduler-Ergebnisse als Erinnerung erhalten bleiben.

        Returns:
            True wenn eine Memory gespeichert wurde, False sonst.
        """
        return False

    def as_tool(self, character_name: str = "") -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            func=self.execute)

    @classmethod
    def from_env(cls, env_prefix: str) -> 'BaseSkill':
        """Erstellt einen Skill aus Umgebungsvariablen."""
        config = {}
        for key, value in os.environ.items():
            if key.startswith(env_prefix):
                config_key = key[len(env_prefix):].lower()
                if value.lower() in ('true', 'false'):
                    value = value.lower() == 'true'
                config[config_key] = value
        return cls(config)
