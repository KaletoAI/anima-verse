"""Registry of available image/video backend types."""
from app.imagegen.backends.a1111 import A1111Backend
from app.imagegen.backends.civitai import CivitAIBackend
from app.imagegen.backends.localai import LocalAIBackend
from app.imagegen.backends.localai_video import LocalAIVideoBackend
from app.imagegen.backends.openai_chat import OpenAIChatImageBackend
from app.imagegen.backends.openai_diffusion import OpenAIDiffusionBackend
from app.imagegen.backends.openai_video import OpenAIVideoBackend
from app.imagegen.backends.together import TogetherBackend
from app.imagegen.backends.together_video import TogetherVideoBackend

# Registry of available backend types. MEDIA_TYPE on each class ("image" or
# "video") keeps image and video matching apart in the BackendPool.
BACKEND_REGISTRY = {
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
}
