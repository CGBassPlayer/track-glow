import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from track_glow.engine import EngineState
from track_glow.ha import HaClient, HaError
from track_glow.outputs import Output
from track_glow.web import EngineLike

log = logging.getLogger(__name__)

STOP_JOIN_SECONDS = 1.0


@dataclass(frozen=True)
class HaStatus:
    state: Literal["off", "ok", "error", "idle"]
    message: str = ""
    scene: str | None = None


@dataclass(frozen=True)
class _Config:
    url: str = ""
    token: str = field(default="", repr=False)
    verify_tls: bool = True
    scenes: tuple[tuple[str, str], ...] = ()
    offline_hold: bool = False


class HomeAssistantOutput(Output):
    def __init__(
        self,
        engine: EngineLike,
        client_factory: Callable[..., HaClient] = HaClient,
        clock: Callable[[], float] = time.monotonic,
        tick: float = 0.25,
        retry: float = 5.0,
    ):
        self._engine = engine
        self._client_factory = client_factory
        self._clock = clock
        self._tick = tick
        self._retry = retry
        self._lock = threading.Lock()
        self._config = _Config()
        self._generation = 0
        self._status = HaStatus("off")
        self._applied = -1
        self._client: HaClient | None = None
        self._sent_key: str | None = None
        self._last_flag_key: str | None = None
        self._failed_key: str | None = None
        self._next_try = float("-inf")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def configure(
        self, url: str, token: str, verify_tls: bool, scenes: dict, offline_hold: bool
    ) -> None:
        with self._lock:
            self._config = _Config(url, token, verify_tls, tuple(scenes.items()), offline_hold)
            self._generation += 1
            self._status = HaStatus("idle", "Connecting") if url else HaStatus("off")

    def ha_status(self) -> HaStatus:
        with self._lock:
            return self._status

    def status(self) -> list[HaStatus]:
        return [self.ha_status()]

    def _key(self, state: EngineState, hold: bool) -> str | None:
        if state.mode == "blackout":
            return "blackout"
        if state.override is not None:
            return state.override.key
        if state.feed.health == "offline":
            return self._last_flag_key if hold else "offline"
        key = state.flag.key if state.flag is not None else "no_race"
        self._last_flag_key = key
        return key

    def _set_status(self, generation: int, status: HaStatus) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            self._status = status
            return True

    def _replace_connecting(self, generation: int, message: str) -> None:
        with self._lock:
            if generation == self._generation and self._status.message in (
                "Connecting",
                "Paused",
                "Waiting for a flag",
            ):
                self._status = HaStatus("idle", message, self._status.scene)

    def step(self, now: float) -> None:
        with self._lock:
            generation, config = self._generation, self._config
        if generation != self._applied:
            self._applied = generation
            if self._client is not None:
                self._client.close()
            self._client = (
                self._client_factory(config.url, config.token, config.verify_tls)
                if config.url
                else None
            )
            self._sent_key = self._failed_key = None
            self._next_try = float("-inf")
        if self._client is None:
            return
        state = self._engine.snapshot()
        if state.mode == "paused":
            self._replace_connecting(generation, "Paused")
            return
        key = self._key(state, config.offline_hold)
        if key is None:
            self._replace_connecting(generation, "Waiting for a flag")
            return
        if key == self._sent_key:
            return
        entity = dict(config.scenes).get(key)
        if not entity:
            if self._set_status(generation, HaStatus("idle", f"No scene for {key}")):
                self._sent_key = key
            return
        if key == self._failed_key and now < self._next_try:
            return
        started = self._clock()
        try:
            self._client.turn_on_scene(entity)
        except HaError as e:
            if self._set_status(generation, HaStatus("error", str(e))):
                self._failed_key = key
                # From the attempt end: a call that hits its timeout must not retry back-to-back.
                self._next_try = now + (self._clock() - started) + self._retry
                self._sent_key = None
            return
        if self._set_status(generation, HaStatus("ok", "", entity)):
            self._sent_key, self._failed_key = key, None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="track-glow-ha", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        failing = False
        try:
            while not self._stop.is_set():
                try:
                    self.step(self._clock())
                    failing = False
                except Exception:
                    if not failing:
                        log.exception("Home Assistant output step failed")
                    failing = True
                self._stop.wait(self._tick)
        finally:
            if self._client is not None:
                self._client.close()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is None:
            if self._client is not None:
                self._client.close()
            return
        self._thread.join(STOP_JOIN_SECONDS)
