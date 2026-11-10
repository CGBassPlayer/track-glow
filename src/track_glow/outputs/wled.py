import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from track_glow.ddp import DdpSender
from track_glow.outputs import Output
from track_glow.render import OFFLINE, flag_frame, solid
from track_glow.web import EngineLike
from track_glow.wled import ControllerSpec, WledError, discover_led_count

log = logging.getLogger(__name__)

STOP_JOIN_SECONDS = 1.0


@dataclass(frozen=True)
class ControllerStatus:
    host: str
    led_count: int | None
    state: Literal["connecting", "ok", "error"]
    message: str = ""


class WledOutput(Output):
    def __init__(
        self,
        engine: EngineLike,
        specs: list[ControllerSpec],
        sender: DdpSender | None = None,
        discover: Callable[[str], int] = discover_led_count,
        clock: Callable[[], float] = time.monotonic,
        tick: float = 0.02,
        keepalive: float = 1.0,
        retry: float = 3.0,
    ):
        self._engine = engine
        self._sender = sender or DdpSender()
        self._discover = discover
        self._clock = clock
        self._tick = tick
        self._keepalive = keepalive
        self._retry = retry
        self._lock = threading.Lock()
        self._status = [
            ControllerStatus(s.host, s.led_count, "ok" if s.led_count else "connecting")
            for s in specs
        ]
        self._last_attempt: dict[int, float] = {}
        self._scene: tuple | None = None
        self._changed_at = 0.0
        self._frame = b""
        self._last_sent_frame: bytes | None = None
        self._last_sent = float("-inf")
        self._seq = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def status(self) -> list[ControllerStatus]:
        with self._lock:
            return list(self._status)

    def frame(self) -> bytes:
        with self._lock:
            return self._frame

    def step(self, now: float) -> None:
        self._discover_pending(now)
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

        self._seq = self._seq % 15 + 1
        start = 0
        for c in live:
            end = start + 3 * c.led_count
            self._sender.send(c.host, frame[start:end], self._seq)
            start = end
        self._last_sent_frame = frame
        self._last_sent = now

    def _discover_pending(self, now: float) -> None:
        for i, s in enumerate(self.status()):
            if s.state == "ok":
                continue
            if now - self._last_attempt.get(i, float("-inf")) < self._retry:
                continue
            self._last_attempt[i] = now
            try:
                count = self._discover(s.host)
                new = ControllerStatus(s.host, count, "ok")
            except WledError as e:
                new = ControllerStatus(s.host, None, "error", str(e))
            with self._lock:
                self._status[i] = new

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="track-glow-wled", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    self.step(self._clock())
                except Exception:
                    log.exception("WLED output step failed")
                self._stop.wait(self._tick)
        finally:
            self._sender.close()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is None:
            self._sender.close()
            return
        self._thread.join(STOP_JOIN_SECONDS)
        if not self._thread.is_alive():
            self._thread = None
