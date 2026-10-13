"""Registry of available media backend types (image / video / mesh / animation)."""
from app.imagegen.backends.local_quadruped_rig import LocalQuadrupedRigBackend
from app.imagegen.backends.local_upscale import LocalUpscaleBackend
from app.imagegen.backends.openai_upscale import OpenAIUpscaleBackend
from app.imagegen.backends.a1111 import A1111Backend
from app.imagegen.backends.civitai import CivitAIBackend
from app.imagegen.backends.civitai_video import CivitAIVideoBackend
from app.imagegen.backends.localai import LocalAIBackend
from app.imagegen.backends.localai_video import LocalAIVideoBackend
from app.imagegen.backends.openai_chat import OpenAIChatImageBackend
from app.imagegen.backends.openai_diffusion import OpenAIDiffusionBackend
from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
from app.imagegen.backends.openai_mesh_animation import OpenAIMeshAnimationBackend
from app.imagegen.backends.openai_video import OpenAIVideoBackend
from app.imagegen.backends.together import TogetherBackend
from app.imagegen.backends.together_video import TogetherVideoBackend

# Registry of available backend types. MEDIA_TYPE on each class ("image",
# "video", "mesh" or "animation") keeps the media kinds apart in the BackendPool.
BACKEND_REGISTRY = {
    "local_upscale": LocalUpscaleBackend,
    "openai_upscale": OpenAIUpscaleBackend,
    "a1111": A1111Backend,
    "openai_chat": OpenAIChatImageBackend,
    "civitai": CivitAIBackend,
    "together": TogetherBackend,
    "localai": LocalAIBackend,
    "openai_diffusion": OpenAIDiffusionBackend,
    # Video (MEDIA_TYPE == "video")
    "localai_video": LocalAIVideoBackend,
    "together_video": TogetherVideoBackend,
    "openai_video": OpenAIVideoBackend,
    "civitai_video": CivitAIVideoBackend,
    # 3D mesh (MEDIA_TYPE == "mesh")
    "openai_mesh": OpenAIMeshBackend,
    "local_quadruped_rig": LocalQuadrupedRigBackend,
    # Mesh animation (MEDIA_TYPE == "animation")
    "openai_mesh_animation": OpenAIMeshAnimationBackend,
}
