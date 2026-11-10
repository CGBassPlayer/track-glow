import socket
import threading
import time

import pytest
from conftest import FakeEngine

from track_glow.ddp import DdpSender
from track_glow.engine import EngineState
from track_glow.models import FeedStatus, Flag, RaceState, Series
from track_glow.outputs.wled import WledOutput
from track_glow.render import OFFLINE, flag_frame, solid
from track_glow.wled import ControllerSpec, WledError


def green_state(flag=Flag.GREEN) -> EngineState:
    race = RaceState(flag=flag, raw_flag=int(flag), series=Series.CUP, race_id=1, lap=1)
    return EngineState(race=race, feed=FeedStatus("ok"), follow=Series.CUP)


class RecordingSender:
    def __init__(self):
        self.sends = []
        self.closed = False
        self.now = 0.0

    def send(self, host, pixels, seq):
        self.sends.append((self.now, host, pixels, seq))

    def close(self):
        self.closed = True


def make(specs, engine=None, discover=None, sender=None):
    sender = sender or RecordingSender()
    out = WledOutput(
        engine or FakeEngine(green_state()),
        [ControllerSpec.parse(s) for s in specs],
        sender=sender,
        discover=discover or (lambda host: pytest.fail(f"unexpected discovery of {host}")),
    )
    return out, sender


def step(out, sender, now):
    sender.now = now
    out.step(now)


def test_spanned_slices_reassemble_virtual_frame():
    out, sender = make(["a:10", "b:8"])
    step(out, sender, 0.0)
    (_, ha, pa, _), (_, hb, pb, _) = sender.sends
    assert (ha, len(pa), hb, len(pb)) == ("a", 30, "b", 24)
    assert pa + pb == flag_frame(Flag.GREEN, 18, 0)
    assert pa[18:30] == bytes(12) and pb[:6] == bytes(6)


def test_all_controllers_sent_same_tick():
    out, sender = make(["a:10", "b:8"])
    step(out, sender, 0.0)
    assert {(now, seq) for now, _, _, seq in sender.sends} == {(0.0, 1)}


def test_seq_cycles_1_to_15():
    out, sender = make(["a:4"])
    for i in range(16):
        step(out, sender, i * 1.0)
    assert [s[3] for s in sender.sends] == [*range(1, 16), 1]


def test_flag_change_restarts_flash():
    engine = FakeEngine(green_state())
    out, sender = make(["a:12"], engine=engine)
    step(out, sender, 0.0)
    step(out, sender, 0.3)
    engine.state = green_state(Flag.YELLOW)
    step(out, sender, 0.4)
    assert sender.sends[-1][2] == flag_frame(Flag.YELLOW, 12, 0)
    assert out.frame() == flag_frame(Flag.YELLOW, 12, 0)


def test_hold_resends_as_keepalive():
    out, sender = make(["a:12"])
    step(out, sender, 0.0)
    sender.sends.clear()
    for now in (2.0, 2.5, 3.1):
        step(out, sender, now)
    assert [s[0] for s in sender.sends] == [2.0, 3.1]


def test_no_race_releases():
    out, sender = make(["a:12"], engine=FakeEngine(EngineState(feed=FeedStatus("ok"))))
    step(out, sender, 0.0)
    step(out, sender, 2.0)
    assert sender.sends == [] and out.frame() == b""


def test_offline_shows_amber():
    out, sender = make(["a:5"], engine=FakeEngine(EngineState(feed=FeedStatus("offline"))))
    step(out, sender, 0.0)
    assert sender.sends[0][2] == solid(5, OFFLINE)


def test_override_drives_output():
    engine = FakeEngine(EngineState(feed=FeedStatus("ok"), override=Flag.RED))
    out, sender = make(["a:12"], engine=engine)
    step(out, sender, 2.0)
    assert sender.sends[0][2] == flag_frame(Flag.RED, 12, 0)


def test_unreachable_controller_excluded_then_joins():
    attempts = []
    reachable = {"a": 10}

    def discover(host):
        attempts.append(host)
        if host not in reachable:
            raise WledError(f"Can't reach WLED at {host}")
        return reachable[host]

    out, sender = make(["a", "b", "c:4"], discover=discover)
    step(out, sender, 0.0)
    assert [s.state for s in out.status()] == ["ok", "error", "ok"]
    assert out.status()[1].message == "Can't reach WLED at b"
    assert [s[1] for s in sender.sends] == ["a", "c"]
    assert len(out.frame()) == 3 * 14

    step(out, sender, 2.9)
    assert attempts == ["a", "b"]

    reachable["b"] = 6
    sender.sends.clear()
    step(out, sender, 3.0)
    assert attempts == ["a", "b", "b"]
    assert [s[1] for s in sender.sends] == ["a", "b", "c"]
    assert sender.sends[1][2] == flag_frame(Flag.GREEN, 20, 3.0)[30:48]


def test_status_before_first_step_is_connecting():
    out, _ = make(["a", "b:5"])
    assert [(s.host, s.led_count, s.state) for s in out.status()] == [
        ("a", None, "connecting"),
        ("b", 5, "ok"),
    ]


def test_zero_controllers_idle():
    def discover(host):
        raise WledError("nope")

    out, sender = make(["a", "b"], discover=discover)
    step(out, sender, 0.0)
    assert sender.sends == [] and out.frame() == b""
    assert [s.state for s in out.status()] == ["error", "error"]


def test_large_controller_gets_full_slice():
    out, sender = make(["a:600"])
    step(out, sender, 0.0)
    assert len(sender.sends[0][2]) == 1800


def test_stop_is_prompt_and_silent():
    out, sender = make(["a:12"])
    out.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    out.stop()
    assert time.monotonic() - t0 < 1
    assert sender.closed
    count = len(sender.sends)
    time.sleep(0.1)
    assert len(sender.sends) == count


def _listener(host: str, port: int = 0) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((host, port))
    s.settimeout(0.05)
    return s


def test_real_udp_sync():
    a = _listener("127.0.0.1")
    port = a.getsockname()[1]
    try:
        b = _listener("127.0.0.2", port)
    except OSError:
        a.close()
        pytest.skip("127.0.0.2 not bindable")
    received: dict[str, dict[int, float]] = {"a": {}, "b": {}}
    stop = threading.Event()

    def recv(name, sock):
        while not stop.is_set():
            try:
                data = sock.recv(2048)
            except TimeoutError:
                continue
            received[name].setdefault(data[1], time.monotonic())

    threads = [threading.Thread(target=recv, args=x) for x in (("a", a), ("b", b))]
    for t in threads:
        t.start()
    out = WledOutput(
        FakeEngine(green_state()),
        [ControllerSpec("127.0.0.1", 60), ControllerSpec("127.0.0.2", 60)],
        sender=DdpSender(port=port),
    )
    out.start()
    time.sleep(0.5)
    out.stop()
    stop.set()
    for t in threads:
        t.join()
    a.close()
    b.close()
    common = set(received["a"]) & set(received["b"])
    assert common
    assert max(abs(received["a"][s] - received["b"][s]) for s in common) < 0.02
