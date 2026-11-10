import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from track_glow.ddp import DdpSender
from track_glow.outputs import Output
from track_glow.render import OFF, OFFLINE, bar_color, bar_fraction, flag_frame, progress_bar, solid
from track_glow.web import EngineLike
from track_glow.wled import (
    ControllerSpec,
    ProgressSpec,
    WledError,
    discover_led_count,
    fetch_segment,
)

log = logging.getLogger(__name__)

STOP_JOIN_SECONDS = 1.0
DISCOVERY_POLL_SECONDS = 0.1
SEGMENT_REFRESH_SECONDS = 30.0


@dataclass(frozen=True)
class ControllerStatus:
    host: str
    led_count: int | None
    state: Literal["connecting", "ok", "error"]
    message: str = ""
    address: str | None = None


@dataclass(frozen=True)
class BarStatus:
    state: Literal["off", "waiting", "ok", "error"]
    message: str = ""
    start: int | None = None
    stop: int | None = None
    fraction: float = 0.0


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
        progress: ProgressSpec | None = None,
        fetch_segment: Callable[[str, int], tuple[int, int]] = fetch_segment,
        offline_hold: bool = False,
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
        self._fetch_segment = fetch_segment
        self._frame = b""
        self._seq = 0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._generation = 0
        self._render_generation = -1
        self._changed_at = 0.0
        self._last_sent = float("-inf")
        self._configure_locked(specs, progress, offline_hold)

    def configure(
        self,
        specs: list[ControllerSpec],
        progress: ProgressSpec | None = None,
        offline_hold: bool = False,
    ) -> None:
        with self._lock:
            self._configure_locked(specs, progress, offline_hold)

    def _configure_locked(self, specs, progress, offline_hold) -> None:
        self._generation += 1
        self._status = [ControllerStatus(s.host, s.led_count, "connecting") for s in specs]
        self._last_attempt: dict[int, float] = {}
        self._progress = progress
        self._offline_hold = offline_hold
        self._segment: tuple[int, int] | None = None
        self._segment_error = ""
        self._segment_attempt = float("-inf")
        self._bar_controller: int | None = None
        self._bar_config_error = ""
        if progress is not None and progress.host is not None:
            hosts = [s.host for s in specs]
            if progress.host in hosts:
                self._bar_controller = hosts.index(progress.host)
            else:
                self._bar_config_error = f"Progress host {progress.host} is not a --wled controller"
        self._bar = BarStatus("off") if progress is None else BarStatus("waiting", "Starting")
        if self._bar_config_error:
            self._bar = BarStatus("error", self._bar_config_error)

    def status(self) -> list[ControllerStatus]:
        with self._lock:
            return list(self._status)

    def frame(self) -> bytes:
        with self._lock:
            return self._frame

    def bar_status(self) -> BarStatus:
        with self._lock:
            return self._bar

    def discover_pending(self, now: float) -> None:
        self._discover_controllers(now)
        self._discover_segment(now)

    def _discover_segment(self, now: float) -> None:
        with self._lock:
            gen, i, spec = self._generation, self._bar_controller, self._progress
            ok = i is not None and self._status[i].state == "ok"
            have = self._segment is not None
            last = self._segment_attempt
        if not ok or self._stop.is_set():
            return
        if now - last < (SEGMENT_REFRESH_SECONDS if have else self._retry):
            return
        started = self._clock()
        segment, error = None, ""
        try:
            segment = self._fetch_segment(spec.host, spec.segment)
        except WledError as e:
            error = str(e)
        finally:
            with self._lock:
                if self._generation == gen:
                    self._segment_attempt = now + (self._clock() - started)
                    if segment is not None or not have:
                        self._segment, self._segment_error = segment, error

    def _discover_controllers(self, now: float) -> None:
        with self._lock:
            gen, statuses = self._generation, list(self._status)
            attempts = dict(self._last_attempt)
        for i, s in enumerate(statuses):
            if s.state == "ok" or self._stop.is_set():
                continue
            if now - attempts.get(i, float("-inf")) < self._retry:
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
            with self._lock:
                if self._generation != gen:
                    return
                # From the attempt end: a 3 s timeout must not cause back-to-back retries.
                self._last_attempt[i] = now + (self._clock() - started)
                self._status[i] = new

    def step(self, now: float) -> None:
        with self._lock:
            gen = self._generation
            statuses = list(self._status)
            config = (self._progress, self._bar_controller, self._bar_config_error)
            segment = (self._segment, self._segment_error)
            offline_hold = self._offline_hold
        if gen != self._render_generation:
            self._render_generation = gen
            self._scene = None
            self._last_sent_frame = None
            self._last_flag_scene = None
            self._last_fraction = 0.0
        live = [s for s in statuses if s.state == "ok"]
        n = sum(s.led_count for s in live)

        state = self._engine.snapshot()
        held = False
        if state.mode == "paused":
            scene = None
        elif state.mode == "blackout":
            scene = ("blackout",)
        elif state.feed.health == "offline":
            held = offline_hold and self._last_flag_scene is not None
            scene = self._last_flag_scene if held else ("offline",)
        elif state.flag is None:
            scene = None
        else:
            scene = ("flag", state.flag)
        if scene != self._scene:
            self._scene = scene
            self._changed_at = now

        bar = self._resolve_bar(live, n, state, statuses, config, segment)
        if bar.state == "ok":
            if state.mode == "paused":
                bar = BarStatus("waiting", "Paused")
            elif scene is None:
                bar = BarStatus("waiting", "No race")
            elif scene[0] == "blackout":
                bar = BarStatus("waiting", "Blackout")
            elif scene[0] == "offline":
                bar = BarStatus("waiting", "Feed offline")
            elif held:
                bar = replace(bar, fraction=self._last_fraction)
            else:
                self._last_fraction = bar.fraction
        if scene is not None and scene[0] == "flag":
            self._last_flag_scene = scene
        if n == 0 or scene is None:
            frame = b""
        elif scene[0] == "blackout":
            frame = solid(n, OFF)
        elif scene[0] == "offline":
            frame = solid(n, OFFLINE)
        else:
            frame = flag_frame(scene[1], n, now - self._changed_at)
            if bar.state == "ok":
                pixels = progress_bar(bar.stop - bar.start, bar.fraction, bar_color(scene[1]))
                frame = frame[: 3 * bar.start] + pixels + frame[3 * bar.stop :]
        with self._lock:
            if self._generation != gen:
                return
            self._frame = frame
            self._bar = bar
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

    def _resolve_bar(self, live, n, state, statuses, config, segment_state) -> BarStatus:
        spec, bar_controller, config_error = config
        if spec is None:
            return BarStatus("off")
        if config_error:
            return BarStatus("error", config_error)
        if spec.host is None:
            start, stop = spec.start, spec.stop
        else:
            controller = statuses[bar_controller]
            segment, error = segment_state
            if controller.state != "ok":
                return BarStatus("waiting", f"Waiting for {spec.host}")
            if error:
                return BarStatus("error", error)
            if segment is None:
                return BarStatus("waiting", f"Reading segment {spec.segment} on {spec.host}")
            offset = 0
            for c in live:
                if c.host == spec.host:
                    break
                offset += c.led_count
            if segment[1] > controller.led_count:
                return BarStatus(
                    "error",
                    f"Segment {spec.segment} on {spec.host} ends past its "
                    f"{controller.led_count} LEDs",
                )
            start, stop = offset + segment[0], offset + segment[1]
        if n == 0:
            return BarStatus("waiting", "No controllers")
        if not 0 <= start < stop <= n:
            return BarStatus("error", f"Progress range {start}-{stop} is outside the {n}-LED strip")
        race = state.race
        fraction = bar_fraction(
            state.flag, race.lap if race else None, race.laps_in_race if race else None
        )
        return BarStatus("ok", "", start, stop, fraction)

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
