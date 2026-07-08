"""TakePhoto verb — the LLM tool surface of the core image service.

The character takes a photo / creates an image; all heavy lifting
(backend pool, instance selection, prompt pipeline, gallery) lives in
the core ImageService (app/imagegen/service.py, R5 — many consumers).
This package only contributes the tool the LLM can call.

SKILL_ID stays "image_generation": per-character config files and the
F8 capability key (📷 scene photo) keep working unchanged; only the
tool NAME was renamed to TakePhoto (approved rename table §8.2).
"""
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec


class TakePhotoSkill(PluginSkill):
    """Character takes a photo — thin wrapper over the image service."""

    SKILL_ID = "image_generation"
    DEFERRED = True  # image is generated after the chat reply
    PROGRESS_TYPE = "image"  # count-based intent/assignment progress

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description/action_hint come from templates/llm/skills/image_generation.md
        # Per-character settings use the service's instance-based config —
        # no generic _defaults fields here.
        self._defaults = {}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "TakePhoto is disabled."
        from app.imagegen.service import get_image_service
        svc = get_image_service()
        if not svc.enabled:
            return ("Image generation is not available. No instance "
                    "configured or reachable.")
        return svc.generate_from_input(raw_input)

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        if "usage_instructions" in self.config:
            return self.config["usage_instructions"]
        from app.core.tool_formats import format_example
        return format_example(format_name or "tag", self.name,
                              "young woman with blonde hair at the beach, sunset")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=f"{self.description}. Input should be a detailed "
                        f"description of the desired image.",
            func=self.execute)
