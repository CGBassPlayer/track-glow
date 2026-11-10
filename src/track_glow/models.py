from dataclasses import dataclass
from enum import IntEnum
from typing import Literal


class Flag(IntEnum):
    GREEN = 1
    YELLOW = 2
    RED = 3
    WHITE = 4
    CHECKERED = 5
    HOT_TRACK = 8
    COLD_TRACK = 9

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def label(self) -> str:
        return _FLAG_LABELS[self]

    @property
    def color(self) -> str:
        return _FLAG_COLORS[self]


_FLAG_LABELS = {
    Flag.GREEN: "GREEN",
    Flag.YELLOW: "YELLOW",
    Flag.RED: "RED",
    Flag.WHITE: "WHITE · LAST LAP",
    Flag.CHECKERED: "CHECKERED",
    Flag.HOT_TRACK: "HOT TRACK",
    Flag.COLD_TRACK: "COLD TRACK",
}

_FLAG_COLORS = {
    Flag.GREEN: "#2e7d32",
    Flag.YELLOW: "#f9a825",
    Flag.RED: "#c62828",
    Flag.WHITE: "#f5f5f5",
    Flag.CHECKERED: "#212121",
    Flag.HOT_TRACK: "#ef6c00",
    Flag.COLD_TRACK: "#1565c0",
}


class Series(IntEnum):
    CUP = 1
    XFINITY = 2
    TRUCK = 3

    @property
    def label(self) -> str:
        return {Series.CUP: "Cup", Series.XFINITY: "Xfinity", Series.TRUCK: "Truck"}[self]


@dataclass(frozen=True)
class RaceState:
    flag: Flag | None
    raw_flag: int | None
    series: Series
    race_id: int
    lap: int | None = None
    laps_in_race: int | None = None
    laps_to_go: int | None = None
    track_name: str = ""
    run_name: str = ""


@dataclass(frozen=True)
class FeedStatus:
    health: Literal["connecting", "ok", "retrying", "offline"] = "connecting"
    message: str = ""
    failures: int = 0
    last_ok: float | None = None
