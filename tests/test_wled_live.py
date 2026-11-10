import threading
from dataclasses import replace

from conftest import FakeEngine
from test_wled_output import make, step
from test_wled_progress import race_state, with_bar

from track_glow.engine import EngineState
from track_glow.models import FeedStatus, Flag
from track_glow.render import LED_COLORS, OFF, OFFLINE, flag_frame, progress_bar, solid
from track_glow.wled import ControllerSpec, ProgressSpec

GREEN = LED_COLORS[Flag.GREEN]


def moded(mode, **kw):
    return replace(race_state(**kw), mode=mode)


def test_configure_swaps_controllers():
    out, sender = make(["a:10"])
    step(out, sender, 0.0)
    out.configure([ControllerSpec("b", 5)])
    sender.sends.clear()
    step(out, sender, 0.1)
    assert {s[1] for s in sender.sends} == {"b"}
    assert [(c.host, c.led_count, c.state) for c in out.status()] == [("b", 5, "ok")]


def test_configure_resets_bar():
    out, sender = with_bar(["a:20"], "10-20")
    step(out, sender, 0.0)
    assert out.bar_status().state == "ok"
    out.configure([ControllerSpec("a", 20)])
    step(out, sender, 0.1)
    assert out.bar_status().state == "off"
    out.configure([ControllerSpec("a", 20)], progress=ProgressSpec.parse("0-5"))
    step(out, sender, 0.2)
    assert (out.bar_status().start, out.bar_status().stop) == (0, 5)


def test_configure_restarts_flash():
    out, sender = make(["a:20"])
    step(out, sender, 0.0)
    step(out, sender, 2.0)
    assert out.frame() == solid(20, GREEN)
    out.configure([ControllerSpec("a", 20)])
    step(out, sender, 2.1)
    assert out.frame() == flag_frame(Flag.GREEN, 20, 0.0)


def test_stale_discovery_dropped_after_configure():
    release = threading.Event()
    entered = threading.Event()

    def discover(host):
        entered.set()
        release.wait(5)
        return 60

    out, sender = make(["old1", "old2"], discover=discover)
    t = threading.Thread(target=out.discover_pending, args=(0.0,))
    t.start()
    assert entered.wait(5)
    out.configure([ControllerSpec("new", 5)])
    release.set()
    t.join(5)
    assert [(c.host, c.led_count, c.state) for c in out.status()] == [("new", 5, "connecting")]


def test_stale_segment_dropped_after_configure():
    release = threading.Event()
    entered = threading.Event()

    def fetch(host, segment):
        entered.set()
        release.wait(5)
        return (5, 15)

    out, sender = with_bar(["a:10", "b:30"], "b/1", fetch_segment=fetch)
    sender.now = 0.0
    out._discover_controllers(0.0)
    t = threading.Thread(target=out.discover_pending, args=(0.0,))
    t.start()
    assert entered.wait(5)
    out.configure(
        [ControllerSpec("a", 10), ControllerSpec("b", 30)], progress=ProgressSpec.parse("b/1")
    )
    release.set()
    t.join(5)
    out._discover_controllers(0.1)
    out.step(0.1)
    assert out.bar_status().message == "Reading segment 1 on b"


def test_paused_sends_nothing():
    out, sender = with_bar(["a:20"], "10-20", engine=FakeEngine(moded("paused")))
    step(out, sender, 0.0)
    step(out, sender, 1.5)
    assert sender.sends == []
    assert out.frame() == b""
    assert (out.bar_status().state, out.bar_status().message) == ("waiting", "Paused")


def test_blackout_sends_black_with_keepalive():
    out, sender = with_bar(["a:20"], "10-20", engine=FakeEngine(moded("blackout")))
    step(out, sender, 0.0)
    step(out, sender, 0.5)
    step(out, sender, 1.0)
    assert [s[0] for s in sender.sends] == [0.0, 1.0]
    assert all(s[2] == solid(20, OFF) for s in sender.sends)
    assert (out.bar_status().state, out.bar_status().message) == ("waiting", "Blackout")


def test_back_to_on_flashes_again():
    engine = FakeEngine(moded("blackout"))
    out, sender = make(["a:20"], engine=engine)
    step(out, sender, 0.0)
    engine.state = moded("on")
    step(out, sender, 3.0)
    assert out.frame() == flag_frame(Flag.GREEN, 20, 0.0)


def test_offline_hold_keeps_last_flag_and_bar():
    engine = FakeEngine(race_state(lap=40))
    out, sender = with_bar(["a:20"], "10-20", engine=engine, offline_hold=True)
    step(out, sender, 0.0)
    step(out, sender, 2.0)
    held = out.frame()
    assert held[30:] == progress_bar(10, 0.5, GREEN)
    engine.state = EngineState(feed=FeedStatus("offline"))
    step(out, sender, 2.1)
    assert out.frame() == held
    assert out.bar_status().state == "ok"


def test_offline_hold_without_previous_flag_is_amber():
    engine = FakeEngine(EngineState(feed=FeedStatus("offline")))
    out, sender = make(["a:20"], engine=engine, offline_hold=True)
    step(out, sender, 0.0)
    assert out.frame() == solid(20, OFFLINE)


def test_offline_without_hold_is_amber():
    engine = FakeEngine(race_state())
    out, sender = make(["a:20"], engine=engine)
    step(out, sender, 0.0)
    engine.state = EngineState(feed=FeedStatus("offline"))
    step(out, sender, 0.1)
    assert out.frame() == solid(20, OFFLINE)


def test_override_wins_over_offline():
    engine = FakeEngine(EngineState(feed=FeedStatus("offline"), override=Flag.RED))
    out, sender = make(["a:20"], engine=engine)
    step(out, sender, 0.0)
    assert out.frame() == flag_frame(Flag.RED, 20, 0.0)
