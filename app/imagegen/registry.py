"""Registry of available image backend types."""
from app.imagegen.backends.a1111 import A1111Backend
from app.imagegen.backends.civitai import CivitAIBackend
from app.imagegen.backends.localai import LocalAIBackend
from app.imagegen.backends.openai_chat import OpenAIChatImageBackend
from app.imagegen.backends.openai_diffusion import OpenAIDiffusionBackend
from app.imagegen.backends.together import TogetherBackend

# Registry of available backend types
BACKEND_REGISTRY = {
    "a1111": A1111Backend,
    "openai_chat": OpenAIChatImageBackend,
    "civitai": CivitAIBackend,
    "together": TogetherBackend,
    "localai": LocalAIBackend,
    "openai_diffusion": OpenAIDiffusionBackend,
}
