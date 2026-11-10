import threading
import time

from track_glow.engine import Engine
from track_glow.models import Flag, RaceState, Series
from track_glow.sources import FeedError, RaceSource


def race(flag=Flag.GREEN, series=Series.CUP) -> RaceState:
    return RaceState(flag=flag, raw_flag=int(flag), series=series, race_id=1, lap=10)


class ScriptedSource(RaceSource):
    def __init__(self, *steps):
        self.steps = list(steps)
        self.closed = False

    def fetch(self):
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, BaseException):
            raise step
        return step

    def close(self):
        self.closed = True


def engine(*steps, follow=Series.CUP) -> Engine:
    return Engine(ScriptedSource(*steps), follow=follow, source_kind="live")


def test_first_good_poll_is_ok():
    e = engine(race())
    assert e.poll_once() == 3.0
    s = e.snapshot()
    assert s.feed.health == "ok" and s.flag is Flag.GREEN and s.feed.last_ok is not None


def test_starts_connecting():
    assert engine(race()).snapshot().feed.health == "connecting"


def test_backoff_doubles_and_caps():
    e = engine(FeedError("down"))
    assert [e.poll_once() for _ in range(5)] == [6.0, 12.0, 24.0, 30.0, 30.0]


def test_offline_after_three_failures():
    e = engine(race(), FeedError("down"))
    e.poll_once()
    healths = []
    for _ in range(3):
        e.poll_once()
        healths.append(e.snapshot().feed.health)
    assert healths == ["retrying", "retrying", "offline"]
    assert e.snapshot().race is None
    assert e.snapshot().feed.message == "down"


def test_race_kept_while_retrying():
    e = engine(race(), FeedError("down"))
    e.poll_once()
    e.poll_once()
    assert e.snapshot().flag is Flag.GREEN


def test_recovers_after_offline():
    e = engine(FeedError("a"), FeedError("b"), FeedError("c"), race(Flag.YELLOW))
    for _ in range(3):
        e.poll_once()
    assert e.snapshot().feed.health == "offline"
    assert e.poll_once() == 3.0
    s = e.snapshot()
    assert s.feed.health == "ok" and s.feed.failures == 0 and s.flag is Flag.YELLOW


def test_no_race_is_ok_with_no_flag():
    e = engine(None)
    e.poll_once()
    s = e.snapshot()
    assert s.feed.health == "ok" and s.race is None and s.flag is None


def test_other_series_waits():
    e = engine(race(series=Series.XFINITY))
    e.poll_once()
    s = e.snapshot()
    assert s.race is None and s.waiting_for_series is Series.CUP
    assert "Xfinity" in s.feed.message


def test_follow_any_accepts_all_series():
    e = engine(race(series=Series.TRUCK), follow=None)
    e.poll_once()
    assert e.snapshot().race.series is Series.TRUCK
    assert e.snapshot().waiting_for_series is None


def test_override_beats_feed():
    e = engine(race())
    e.poll_once()
    e.set_override(Flag.RED)
    assert e.snapshot().flag is Flag.RED
    e.set_override(None)
    assert e.snapshot().flag is Flag.GREEN


def test_override_works_with_no_race():
    e = engine(None)
    e.set_override(Flag.YELLOW)
    assert e.snapshot().flag is Flag.YELLOW


def test_unexpected_exception_counts_as_failure():
    e = engine(ValueError("boom"))
    assert e.poll_once() == 6.0
    assert e.snapshot().feed.health == "retrying"


class SlowSource(RaceSource):
    def fetch(self):
        time.sleep(0.2)
        return race()


def test_thread_start_polls_and_stop_is_prompt():
    src = SlowSource()
    e = Engine(src, follow=Series.CUP, source_kind="live")
    e.start()
    deadline = time.monotonic() + 2
    while e.snapshot().feed.health != "ok" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert e.snapshot().feed.health == "ok"
    t0 = time.monotonic()
    e.stop()
    assert time.monotonic() - t0 < 2
    assert not e.running


def test_stop_closes_source():
    src = ScriptedSource(race())
    e = Engine(src, follow=Series.CUP, source_kind="live")
    e.start()
    e.stop()
    assert src.closed


def test_status_text_variants():
    from track_glow.engine import EngineState, status_text
    from track_glow.models import FeedStatus

    full = RaceState(Flag.GREEN, 1, Series.CUP, 1, lap=112, laps_in_race=267)
    assert status_text(EngineState(race=full, feed=FeedStatus("ok"))) == "GREEN · Cup · Lap 112/267"
    no_lap = RaceState(Flag.HOT_TRACK, 8, Series.TRUCK, 1)
    assert status_text(EngineState(race=no_lap, feed=FeedStatus("ok"))) == "HOT TRACK · Truck"
    lap_only = RaceState(Flag.YELLOW, 2, Series.CUP, 1, lap=5)
    assert status_text(EngineState(race=lap_only, feed=FeedStatus("ok"))) == "YELLOW · Cup · Lap 5"
    assert status_text(EngineState(feed=FeedStatus("offline"))) == "Feed offline"
    assert status_text(EngineState(waiting_for_series=Series.XFINITY)) == "Waiting for Xfinity"
    assert status_text(EngineState(feed=FeedStatus("ok"))) == "No race"
    assert status_text(EngineState(override=Flag.RED)) == "RED · manual override"


class BlockingSource(RaceSource):
    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Event()
        self.closed = False

    def fetch(self):
        self.entered.set()
        self.release.wait(15)
        return race()

    def close(self):
        self.closed = True


def test_stop_does_not_block_on_hung_request():
    src = BlockingSource()
    e = Engine(src, follow=Series.CUP, source_kind="live")
    e.start()
    assert src.entered.wait(2)
    t0 = time.monotonic()
    e.stop()
    assert time.monotonic() - t0 < 2
    assert e.running
    assert not src.closed
    src.release.set()
    deadline = time.monotonic() + 2
    while e.running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not e.running and src.closed


def test_start_while_running_does_not_spawn_second_thread():
    src = BlockingSource()
    e = Engine(src, follow=Series.CUP, source_kind="live")
    e.start()
    assert src.entered.wait(2)
    e.start()
    names = [t.name for t in threading.enumerate()].count("track-glow-engine")
    src.release.set()
    e.stop()
    assert names == 1


def test_stop_without_start_closes_source():
    src = ScriptedSource(race())
    Engine(src, follow=Series.CUP, source_kind="live").stop()
    assert src.closed


def test_status_text_live_race_with_unknown_flag():
    from track_glow.engine import EngineState, status_text
    from track_glow.models import FeedStatus

    unknown = RaceState(None, 7, Series.CUP, 1, lap=112, laps_in_race=267)
    text = status_text(EngineState(race=unknown, feed=FeedStatus("ok")))
    assert text == "Flag unknown (7) · Cup · Lap 112/267"


def test_configure_resets_race_and_keeps_override_and_mode():
    e = engine(race())
    e.poll_once()
    e.set_override(Flag.RED)
    e.set_mode("blackout")
    e.configure(ScriptedSource(race()), follow=None, kind="replay")
    s = e.snapshot()
    assert s.race is None and s.waiting_for_series is None
    assert s.feed.health == "connecting" and s.feed.failures == 0
    assert s.override is Flag.RED and s.mode == "blackout"
    assert s.follow is None and s.source_kind == "replay"


def test_configure_resets_waiting_and_failures():
    e = engine(race(series=Series.XFINITY))
    e.poll_once()
    e.configure(ScriptedSource(FeedError("down")), follow=Series.CUP, kind="live")
    e.poll_once()
    e.configure(ScriptedSource(race()), follow=Series.TRUCK, kind="live")
    s = e.snapshot()
    assert s.waiting_for_series is None and s.feed.failures == 0
    assert s.follow is Series.TRUCK


def test_configure_closes_old_source_and_polls_new():
    old = ScriptedSource(race())
    e = Engine(old, follow=Series.CUP, source_kind="live")
    e.configure(ScriptedSource(race(Flag.YELLOW)), follow=Series.CUP, kind="live")
    assert old.closed
    e.poll_once()
    assert e.snapshot().flag is Flag.YELLOW


def test_stale_fetch_after_configure_is_dropped():
    old = BlockingSource()
    e = Engine(old, follow=Series.CUP, source_kind="live")
    result = []
    t = threading.Thread(target=lambda: result.append(e.poll_once()))
    t.start()
    assert old.entered.wait(2)
    e.configure(ScriptedSource(race()), follow=Series.CUP, kind="live")
    old.release.set()
    t.join(2)
    assert result == [0]
    s = e.snapshot()
    assert s.race is None and s.feed.failures == 0 and s.feed.health == "connecting"


class BlockingFailSource(BlockingSource):
    def fetch(self):
        self.entered.set()
        self.release.wait(15)
        raise FeedError("old down")


def test_stale_failure_after_configure_is_not_counted():
    old = BlockingFailSource()
    e = Engine(old, follow=Series.CUP, source_kind="live")
    result = []
    t = threading.Thread(target=lambda: result.append(e.poll_once()))
    t.start()
    assert old.entered.wait(2)
    e.configure(ScriptedSource(race()), follow=Series.CUP, kind="live")
    old.release.set()
    t.join(2)
    assert result == [0]
    assert e.snapshot().feed.failures == 0 and e.snapshot().feed.message == ""


class SignalSource(RaceSource):
    def __init__(self, result):
        self.result = result
        self.fetched = threading.Event()
        self.closed = False

    def fetch(self):
        self.fetched.set()
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def close(self):
        self.closed = True


def test_configure_wakes_running_engine():
    old = SignalSource(FeedError("down"))
    e = Engine(old, follow=Series.CUP, source_kind="live", poll_seconds=30.0)
    e.start()
    try:
        assert old.fetched.wait(2)
        new = SignalSource(race())
        e.configure(new, follow=Series.CUP, kind="live")
        assert new.fetched.wait(0.5)
    finally:
        e.stop()


def test_thread_closes_current_source_on_exit():
    old = SignalSource(race())
    e = Engine(old, follow=Series.CUP, source_kind="live", poll_seconds=30.0)
    e.start()
    assert old.fetched.wait(2)
    new = SignalSource(race())
    e.configure(new, follow=Series.CUP, kind="live")
    assert new.fetched.wait(2)
    e.stop()
    assert not e.running and new.closed


def test_set_mode():
    import pytest

    e = engine(race())
    assert e.snapshot().mode == "on"
    for mode in ("paused", "blackout", "on"):
        e.set_mode(mode)
        assert e.snapshot().mode == mode
    with pytest.raises(ValueError):
        e.set_mode("off")
    assert e.snapshot().mode == "on"


def test_status_text_mode_prefix():
    from track_glow.engine import EngineState, status_text
    from track_glow.models import FeedStatus

    full = RaceState(Flag.GREEN, 1, Series.CUP, 1, lap=112, laps_in_race=267)
    ok = FeedStatus("ok")
    assert status_text(EngineState(race=full, feed=ok, mode="paused")) == (
        "Paused · GREEN · Cup · Lap 112/267"
    )
    assert status_text(EngineState(feed=ok, mode="blackout")) == "Blackout · No race"
    assert status_text(EngineState(override=Flag.RED, mode="paused")) == (
        "Paused · RED · manual override"
    )
    assert status_text(EngineState(race=full, feed=ok, mode="on")) == "GREEN · Cup · Lap 112/267"
