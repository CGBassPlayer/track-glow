import time
from collections.abc import Callable

from track_glow.models import Flag, RaceState, Series
from track_glow.sources import RaceSource

LAPS_IN_RACE = 80

SCRIPT: tuple[tuple[float, Flag, int, int], ...] = (
    (6, Flag.COLD_TRACK, 0, 0),
    (6, Flag.HOT_TRACK, 0, 0),
    (23, Flag.GREEN, 1, 24),
    (10, Flag.YELLOW, 24, 28),
    (32, Flag.GREEN, 28, 60),
    (8, Flag.RED, 60, 60),
    (19, Flag.GREEN, 60, 79),
    (6, Flag.WHITE, 79, 80),
    (12, Flag.CHECKERED, 80, 80),
)
TOTAL = sum(seg[0] for seg in SCRIPT)


class ReplaySource(RaceSource):
    def __init__(
        self, series: Series = Series.CUP, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._series = series
        self._clock = clock
        self._t0 = clock()

    def fetch(self) -> RaceState:
        t = (self._clock() - self._t0) % TOTAL
        for dur, flag, a, b in SCRIPT:
            if t < dur:
                return self._state(flag, a + int((b - a) * t / dur))
            t -= dur
        return self._state(Flag.CHECKERED, LAPS_IN_RACE)

    def _state(self, flag: Flag, lap: int) -> RaceState:
        return RaceState(
            flag=flag,
            raw_flag=int(flag),
            series=self._series,
            race_id=1,
            lap=lap,
            laps_in_race=LAPS_IN_RACE,
            laps_to_go=LAPS_IN_RACE - lap,
            track_name="Demo Speedway",
            run_name="Demo 80",
        )
