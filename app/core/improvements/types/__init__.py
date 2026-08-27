"""Importing this package registers every built-in improvement type."""
from app.core.improvements import registry

from .fill_missing import FillMissing
from .model_replace import ModelReplace

registry.register(ModelReplace())
registry.register(FillMissing())

__all__ = ["FillMissing", "ModelReplace"]
