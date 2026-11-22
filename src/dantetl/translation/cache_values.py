from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheInventory:
    total: int
    games: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class CacheView:
    inventory: CacheInventory | None = None
    busy: bool = False
    error: str = ""
