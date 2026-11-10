from abc import ABC, abstractmethod

from track_glow.models import RaceState


class FeedError(Exception):
    pass


class RaceSource(ABC):
    @abstractmethod
    def fetch(self) -> RaceState | None:
        """Return the live state, or None if nothing is live. Raise FeedError if unusable."""

    def close(self) -> None:
        return None
