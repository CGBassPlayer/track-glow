from abc import ABC, abstractmethod
from typing import Literal

from track_glow.models import RaceState, Series


class FeedError(Exception):
    pass


class RaceSource(ABC):
    @abstractmethod
    def fetch(self) -> RaceState | None:
        """Return the live state, or None if nothing is live. Raise FeedError if unusable."""

    def close(self) -> None:
        return None


def build_source(kind: Literal["live", "replay"], series: Series | None) -> RaceSource:
    from track_glow.sources.nascar import NascarFeedSource
    from track_glow.sources.replay import ReplaySource

    if kind == "replay":
        return ReplaySource(series or Series.CUP)
    return NascarFeedSource()
