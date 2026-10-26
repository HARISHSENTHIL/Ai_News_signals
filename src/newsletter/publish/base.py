"""The contract every destination implements.

The two destinations want the card in different forms, which is why `Card`
carries both: Instagram hands Meta a URL and Meta fetches it, while LinkedIn
takes the JPEG bytes in the request. Passing one object keeps the protocol
honest instead of growing a parameter per platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Card:
    path: Path
    """The rendered JPEG on disk. Present because publish.yml checks the repo out."""

    url: str = ""
    """Public URL of the same file. Only destinations that fetch it need this."""

    alt: str = ""
    """Alt text for screen readers. Destinations that support it should send it."""


@dataclass
class PublishResult:
    platform: str
    post_id: str
    url: str = ""


class Publisher(Protocol):
    name: str

    def preflight(self) -> str:
        """Raise if this destination cannot publish right now. Returns a status line."""
        ...

    def publish(self, card: Card, caption: str) -> PublishResult:
        ...
