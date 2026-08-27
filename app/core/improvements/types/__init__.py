"""Importing this package registers every built-in improvement type."""
from app.core.improvements import registry

from .fill_missing import FillMissing
from .image_rerender import ImageRerender
from .model_replace import ModelReplace

registry.register(ModelReplace())
registry.register(FillMissing())
registry.register(ImageRerender())

__all__ = ["FillMissing", "ImageRerender", "ModelReplace"]
