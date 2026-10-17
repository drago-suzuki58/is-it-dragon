from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Box:
    top: float
    left: float
    bottom: float
    right: float


@dataclass(frozen=True)
class Verdict:
    profile: str
    result: Literal["yes", "no", "unsure"]
    p: float
    details: dict[str, str]
    box: Box | None = None


class Normalizer(Protocol):
    def __call__(self, raw: bytes) -> bytes: ...  # -> JPEG


class Transport(Protocol):
    async def __call__(self, body: dict) -> dict: ...  # -> response body


class Cache(Protocol):
    def get(self, key: str) -> dict | None: ...
    def set(self, key: str, value: dict) -> None: ...
