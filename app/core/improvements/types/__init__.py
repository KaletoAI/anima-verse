"""Importing this package registers every built-in improvement type."""
from app.core.improvements import registry

from .extension_rig_rebuild import ExtensionRigRebuild
from .face_retexture import FaceRetexture
from .fallback_rerender import FallbackRerender
from .fill_missing import FillMissing
from .image_rerender import ImageRerender
from .mesh_from_tpose import MeshFromTpose
from .model_replace import ModelReplace
from .rig_weight_repair import RigWeightRepair
from .surface_bake import SurfaceBake

registry.register(FaceRetexture())
registry.register(ExtensionRigRebuild())
registry.register(RigWeightRepair())
registry.register(ModelReplace())
registry.register(FillMissing())
registry.register(ImageRerender())
registry.register(SurfaceBake())
registry.register(MeshFromTpose())
registry.register(FallbackRerender())

__all__ = ["FaceRetexture", "ExtensionRigRebuild", "FallbackRerender", "FillMissing", "ImageRerender", "MeshFromTpose", "ModelReplace",
           "RigWeightRepair", "SurfaceBake"]
