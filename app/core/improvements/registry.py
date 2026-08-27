"""The name→type map the engine looks improvement types up in."""
from typing import Dict, List, Optional

from app.core.improvements.base import ImprovementType

_types: Dict[str, ImprovementType] = {}


def register(t: ImprovementType) -> None:
    if not t.id:
        raise ValueError("improvement type needs an id")
    _types[t.id] = t          # last registration wins (repo > plugin on collision is the loader's job)


def get(type_id: str) -> Optional[ImprovementType]:
    return _types.get(type_id)


def list_types() -> List[ImprovementType]:
    return sorted(_types.values(), key=lambda t: t.label.lower())


def clear() -> None:          # tests only
    _types.clear()
