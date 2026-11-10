import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from track_glow.ddp import DdpSender
from track_glow.outputs import Output
from track_glow.render import OFFLINE, flag_frame, solid
from track_glow.web import EngineLike
from track_glow.wled import ControllerSpec, WledError, discover_led_count

log = logging.getLogger(__name__)

STOP_JOIN_SECONDS = 1.0
DISCOVERY_POLL_SECONDS = 0.1


@dataclass(frozen=True)
class ControllerStatus:
    host: str
    led_count: int | None
    state: Literal["connecting", "ok", "error"]
    message: str = ""
    address: str | None = None


class WledOutput(Output):
    def __init__(
        self,
        engine: EngineLike,
        specs: list[ControllerSpec],
        sender: DdpSender | None = None,
        discover: Callable[[str], int] = discover_led_count,
        resolve: Callable[[str], str] = socket.gethostbyname,
        clock: Callable[[], float] = time.monotonic,
        tick: float = 0.02,
        keepalive: float = 1.0,
        retry: float = 3.0,
    ):
        self._engine = engine
        self._sender = sender or DdpSender()
        self._discover = discover
        self._resolve = resolve
        self._clock = clock
        self._tick = tick
        self._keepalive = keepalive
        self._retry = retry
        self._lock = threading.Lock()
        self._status = [ControllerStatus(s.host, s.led_count, "connecting") for s in specs]
        self._last_attempt: dict[int, float] = {}
        self._scene: tuple | None = None
        self._changed_at = 0.0
        self._frame = b""
        self._last_sent_frame: bytes | None = None
        self._last_sent = float("-inf")
        self._seq = 0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def status(self) -> list[ControllerStatus]:
        with self._lock:
            return list(self._status)

    def frame(self) -> bytes:
        with self._lock:
            return self._frame

    def discover_pending(self, now: float) -> None:
        for i, s in enumerate(self.status()):
            if s.state == "ok" or self._stop.is_set():
                continue
            if now - self._last_attempt.get(i, float("-inf")) < self._retry:
                continue
            started = self._clock()
            try:
                count = s.led_count or self._discover(s.host)
                address = self._resolve(s.host)
                new = replace(s, led_count=count, state="ok", message="", address=address)
            except WledError as e:
                new = replace(s, state="error", message=str(e))
            except OSError as e:
                new = replace(s, state="error", message=f"Can't resolve {s.host} ({e})")
            # From the attempt end: a 3 s timeout must not cause back-to-back retries.
            self._last_attempt[i] = now + (self._clock() - started)
            with self._lock:
                self._status[i] = new

    def step(self, now: float) -> None:
        live = [s for s in self.status() if s.state == "ok"]
        n = sum(s.led_count for s in live)

        state = self._engine.snapshot()
        if state.feed.health == "offline":
            scene = ("offline",)
        elif state.flag is None:
            scene = None
        else:
            scene = ("flag", state.flag)
        if scene != self._scene:
            self._scene = scene
            self._changed_at = now

        if n == 0 or scene is None:
            frame = b""
        elif scene[0] == "offline":
            frame = solid(n, OFFLINE)
        else:
            frame = flag_frame(scene[1], n, now - self._changed_at)
        with self._lock:
            self._frame = frame
        if not frame:
            self._last_sent_frame = None
            return
        if frame == self._last_sent_frame and now - self._last_sent < self._keepalive:
            return
        if self._stop.is_set():
            return

        self._seq = self._seq % 15 + 1
        start = 0
        for c in live:
            end = start + 3 * c.led_count
            self._sender.send(c.address, frame[start:end], self._seq)
            start = end
        self._last_sent_frame = frame
        self._last_sent = now

    def start(self) -> None:
        if any(t.is_alive() for t in self._threads):
            return
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._render_loop, name="track-glow-wled", daemon=True),
            threading.Thread(
                target=self._discovery_loop, name="track-glow-wled-discovery", daemon=True
            ),
        ]
        for t in self._threads:
            t.start()

    def _render_loop(self) -> None:
        failing = False
        try:
            while not self._stop.is_set():
                try:
                    self.step(self._clock())
                    failing = False
                except Exception:
                    if not failing:
                        log.exception("WLED output step failed")
                    failing = True
                self._stop.wait(self._tick)
        finally:
            self._sender.close()

    def _discovery_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.discover_pending(self._clock())
            except Exception:
                log.exception("WLED discovery failed")
            self._stop.wait(DISCOVERY_POLL_SECONDS)

    def stop(self) -> None:
        self._stop.set()
        if not self._threads:
            self._sender.close()
            return
        render = self._threads[0]
        render.join(STOP_JOIN_SECONDS)
