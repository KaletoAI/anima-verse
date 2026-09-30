"""Importing this package registers every built-in improvement type."""
from app.core.improvements import registry

from .fallback_rerender import FallbackRerender
from .fill_missing import FillMissing
from .image_rerender import ImageRerender
from .mesh_from_tpose import MeshFromTpose
from .model_replace import ModelReplace
from .surface_bake import SurfaceBake

registry.register(ModelReplace())
registry.register(FillMissing())
registry.register(ImageRerender())
registry.register(SurfaceBake())
registry.register(MeshFromTpose())
registry.register(FallbackRerender())

__all__ = ["FallbackRerender", "FillMissing", "ImageRerender", "MeshFromTpose", "ModelReplace",
           "SurfaceBake"]
