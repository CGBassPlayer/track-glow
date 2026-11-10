import pytest
from conftest import FakeEngine
from test_wled_output import make, step

from track_glow.engine import EngineState
from track_glow.models import FeedStatus, Flag, RaceState, Series
from track_glow.outputs.wled import BarStatus
from track_glow.render import LED_COLORS, WHITE, flag_frame, progress_bar, solid
from track_glow.wled import ProgressSpec, WledError

GREEN = LED_COLORS[Flag.GREEN]


def race_state(flag=Flag.GREEN, lap=40, laps=80, override=None) -> EngineState:
    race = RaceState(
        flag=flag, raw_flag=int(flag), series=Series.CUP, race_id=1, lap=lap, laps_in_race=laps
    )
    return EngineState(race=race, feed=FeedStatus("ok"), follow=Series.CUP, override=override)


def no_fetch(host, segment):
    pytest.fail(f"unexpected segment fetch {host}/{segment}")


def with_bar(specs, progress, engine=None, fetch_segment=no_fetch, **kw):
    return make(
        specs,
        engine=engine or FakeEngine(race_state()),
        progress=ProgressSpec.parse(progress),
        fetch_segment=fetch_segment,
        **kw,
    )


def test_range_bar_overwrites_slice_flag_elsewhere():
    out, sender = with_bar(["a:20"], "10-20")
    step(out, sender, 0.0)
    step(out, sender, 2.0)
    frame = sender.sends[-1][2]
    assert frame[:30] == solid(10, GREEN)
    assert frame[30:] == progress_bar(10, 0.5, GREEN)
    bar = out.bar_status()
    assert (bar.state, bar.start, bar.stop, bar.fraction) == ("ok", 10, 20, 0.5)


def test_bar_does_not_flash():
    out, sender = with_bar(["a:20"], "10-20")
    step(out, sender, 0.0)
    step(out, sender, 0.3)
    frame = out.frame()
    assert frame[:30] == flag_frame(Flag.GREEN, 20, 0.3)[:30]
    assert frame[30:] == progress_bar(10, 0.5, GREEN)


def test_lap_tick_sends_immediately_during_hold():
    engine = FakeEngine(race_state(lap=40))
    out, sender = with_bar(["a:20"], "10-20", engine=engine)
    step(out, sender, 0.0)
    step(out, sender, 2.0)
    engine.state = race_state(lap=41)
    step(out, sender, 2.1)
    assert sender.sends[-1][0] == 2.1
    assert sender.sends[-1][2][30:] == progress_bar(10, 41 / 80, GREEN)
    assert sender.sends[-1][2][:30] == solid(10, GREEN)


def test_segment_bar_uses_controller_offset():
    calls = []

    def fetch(host, segment):
        calls.append((host, segment))
        return (5, 15)

    out, sender = with_bar(["a:10", "b:30"], "b/1", fetch_segment=fetch)
    step(out, sender, 2.0)
    assert calls == [("b", 1)]
    bar = out.bar_status()
    assert (bar.state, bar.start, bar.stop) == ("ok", 15, 25)
    assert out.frame()[45:75] == progress_bar(10, 0.5, GREEN)


def test_segment_offset_moves_when_earlier_controller_missing():
    reachable = {}

    def discover(host):
        if host not in reachable:
            raise WledError("down")
        return reachable[host]

    out, sender = with_bar(
        ["a", "b:30"], "b/1", fetch_segment=lambda h, s: (5, 15), discover=discover
    )
    step(out, sender, 2.0)
    assert (out.bar_status().start, out.bar_status().stop) == (5, 15)
    reachable["a"] = 10
    step(out, sender, 5.0)
    assert (out.bar_status().start, out.bar_status().stop) == (15, 25)


def test_segment_bar_waits_for_controller():
    def discover(host):
        raise WledError("down")

    out, sender = with_bar(["a:10", "b"], "b/1", discover=discover)
    step(out, sender, 0.0)
    step(out, sender, 2.0)
    assert out.bar_status().state == "waiting"
    assert out.frame() == solid(10, GREEN)


def test_segment_error_reported_and_retried():
    attempts = []

    def fetch(host, segment):
        attempts.append(host)
        raise WledError("WLED at b has no segment 9")

    out, sender = with_bar(["a:10", "b:10"], "b/9", fetch_segment=fetch)
    step(out, sender, 0.0)
    step(out, sender, 2.0)
    bar = out.bar_status()
    assert (bar.state, bar.message) == ("error", "WLED at b has no segment 9")
    assert out.frame() == solid(20, GREEN)
    step(out, sender, 2.9)
    assert attempts == ["b"]
    step(out, sender, 3.0)
    assert attempts == ["b", "b"]


def test_progress_host_not_a_controller():
    out, _ = with_bar(["a:10"], "zzz/1")
    bar = out.bar_status()
    assert (bar.state, bar.message) == ("error", "Progress host zzz is not a --wled controller")


def test_range_outside_strip_is_error():
    out, sender = with_bar(["a:20"], "15-30")
    step(out, sender, 0.0)
    step(out, sender, 2.0)
    bar = out.bar_status()
    assert (bar.state, bar.message) == ("error", "Progress range 15-30 is outside the 20-LED strip")
    assert out.frame() == solid(20, GREEN)


def test_checkered_bar_full_white():
    out, sender = with_bar(["a:20"], "10-20", engine=FakeEngine(race_state(Flag.CHECKERED, 10)))
    step(out, sender, 6.0)
    assert out.frame()[30:] == progress_bar(10, 1.0, WHITE)


def test_override_recolors_bar():
    out, sender = with_bar(["a:20"], "10-20", engine=FakeEngine(race_state(override=Flag.RED)))
    step(out, sender, 2.0)
    assert out.frame()[30:] == progress_bar(10, 0.5, LED_COLORS[Flag.RED])


def test_offline_and_release_ignore_bar():
    offline = FakeEngine(EngineState(feed=FeedStatus("offline")))
    out, sender = with_bar(["a:20"], "10-20", engine=offline)
    step(out, sender, 0.0)
    from track_glow.render import OFFLINE

    assert out.frame() == solid(20, OFFLINE)
    released = FakeEngine(EngineState(feed=FeedStatus("ok")))
    out, sender = with_bar(["a:20"], "10-20", engine=released)
    step(out, sender, 0.0)
    assert out.frame() == b""


def test_bar_status_off_without_spec():
    out, _ = make(["a:20"])
    assert out.bar_status().state == "off"


def test_segment_refetched_after_edit():
    seg = {"v": (5, 15)}
    out, sender = with_bar(["a:10", "b:30"], "b/1", fetch_segment=lambda h, s: seg["v"])
    step(out, sender, 0.0)
    assert (out.bar_status().start, out.bar_status().stop) == (15, 25)
    seg["v"] = (0, 30)
    step(out, sender, 29.0)
    assert (out.bar_status().start, out.bar_status().stop) == (15, 25)
    step(out, sender, 30.0)
    assert (out.bar_status().start, out.bar_status().stop) == (10, 40)


def test_failed_refetch_keeps_last_segment():
    calls = []

    def fetch(host, segment):
        calls.append(host)
        if len(calls) > 1:
            raise WledError("Can't reach WLED at b")
        return (5, 15)

    out, sender = with_bar(["a:10", "b:30"], "b/1", fetch_segment=fetch)
    step(out, sender, 0.0)
    step(out, sender, 30.0)
    assert len(calls) == 2
    bar = out.bar_status()
    assert (bar.state, bar.start, bar.stop) == ("ok", 15, 25)


def test_segment_past_controller_leds_is_error():
    out, sender = with_bar(["a:60", "b:100"], "a/1", fetch_segment=lambda h, s: (50, 100))
    step(out, sender, 0.0)
    step(out, sender, 2.0)
    bar = out.bar_status()
    assert (bar.state, bar.message) == ("error", "Segment 1 on a ends past its 60 LEDs")
    assert out.frame() == solid(160, GREEN)


def test_bar_status_not_ok_when_bar_not_drawn():
    offline = FakeEngine(EngineState(feed=FeedStatus("offline")))
    out, sender = with_bar(["a:20"], "10-20", engine=offline)
    step(out, sender, 0.0)
    assert (out.bar_status().state, out.bar_status().message) == ("waiting", "Feed offline")
    released = FakeEngine(EngineState(feed=FeedStatus("ok")))
    out, sender = with_bar(["a:20"], "10-20", engine=released)
    step(out, sender, 0.0)
    assert (out.bar_status().state, out.bar_status().message) == ("waiting", "No race")


def test_unexpected_fetch_error_still_waits_for_retry():
    calls = []

    def fetch(host, segment):
        calls.append(host)
        raise ValueError("bad host")

    out, sender = with_bar(["a:10"], "a/1", fetch_segment=fetch)
    for now in (0.0, 0.1, 0.2, 2.9):
        sender.now = now
        with pytest.raises(ValueError) if now == 0.0 else _nothing():
            out.discover_pending(now)
    assert calls == ["a"]


def test_initial_bar_status_has_message():
    out, _ = with_bar(["a:20"], "10-20")
    assert out.bar_status() == BarStatus("waiting", "Starting")


class _nothing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
