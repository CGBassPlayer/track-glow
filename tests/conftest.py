from dataclasses import replace

import pytest

from track_glow.engine import EngineState
from track_glow.models import FeedStatus, Flag, RaceState, Series

GREEN_CUP = RaceState(
    flag=Flag.GREEN,
    raw_flag=1,
    series=Series.CUP,
    race_id=5600,
    lap=112,
    laps_in_race=267,
    laps_to_go=155,
    track_name="Phoenix Raceway",
    run_name="NASCAR Cup Series Championship",
)


class FakeEngine:
    def __init__(self, state: EngineState | None = None):
        self.state = state or EngineState(follow=Series.CUP)
        self.started = False
        self.stopped = False

    def snapshot(self) -> EngineState:
        return self.state

    def set_override(self, flag: Flag | None) -> None:
        self.state = replace(self.state, override=flag)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def fake_engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def green_engine() -> FakeEngine:
    return FakeEngine(EngineState(race=GREEN_CUP, feed=FeedStatus("ok"), follow=Series.CUP))


class FakeLights:
    def __init__(self, statuses=None, frame: bytes = b""):
        from track_glow.outputs.wled import ControllerStatus

        self.statuses = statuses or [ControllerStatus("10.0.0.5", 2, "ok")]
        self._frame = frame
        self.started = False
        self.stopped = False

    def status(self):
        return list(self.statuses)

    def frame(self) -> bytes:
        return self._frame

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
