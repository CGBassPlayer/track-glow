from track_glow.models import Flag, Series
from track_glow.sources import RaceSource
from track_glow.sources.replay import ReplaySource


def fake_clock(*elapsed: float):
    times = iter([100.0, *(100.0 + e for e in elapsed)])
    return lambda: next(times)


def test_is_race_source():
    assert isinstance(ReplaySource(clock=fake_clock()), RaceSource)


def test_starts_cold_track():
    state = ReplaySource(clock=fake_clock(0)).fetch()
    assert state.flag is Flag.COLD_TRACK
    assert state.raw_flag == 9
    assert state.lap == 0


def test_green_lap_progresses():
    src = ReplaySource(clock=fake_clock(12, 18))
    first, second = src.fetch(), src.fetch()
    assert (first.flag, first.lap) == (Flag.GREEN, 1)
    assert (second.flag, second.lap) == (Flag.GREEN, 7)


def test_loops_after_122s():
    state = ReplaySource(clock=fake_clock(122)).fetch()
    assert state.flag is Flag.COLD_TRACK


def test_checkered_last_segment():
    state = ReplaySource(clock=fake_clock(110)).fetch()
    assert (state.flag, state.lap, state.laps_to_go) == (Flag.CHECKERED, 80, 0)


def test_static_fields():
    state = ReplaySource(clock=fake_clock(40)).fetch()
    assert state.flag is Flag.YELLOW
    assert state.race_id == 1
    assert state.laps_in_race == 80
    assert state.laps_to_go == 80 - state.lap
    assert state.track_name == "Demo Speedway"
    assert state.run_name == "Demo 80"
    assert state.series is Series.CUP


def test_replay_uses_given_series():
    state = ReplaySource(Series.TRUCK, clock=fake_clock(0)).fetch()
    assert state.series is Series.TRUCK


def test_green_runs_one_lap_per_second():
    src = ReplaySource(clock=fake_clock(20, 21, 50, 51))
    laps = [src.fetch().lap for _ in range(4)]
    assert laps[1] - laps[0] == 1 and laps[3] - laps[2] == 1
