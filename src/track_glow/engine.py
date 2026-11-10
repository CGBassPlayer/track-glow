import logging
import threading
import time
from dataclasses import dataclass, replace

from track_glow.models import FeedStatus, Flag, RaceState, Series
from track_glow.sources import FeedError, RaceSource

log = logging.getLogger(__name__)

STOP_JOIN_SECONDS = 1.0
MODES = ("on", "paused", "blackout")


@dataclass(frozen=True)
class EngineState:
    race: RaceState | None = None
    feed: FeedStatus = FeedStatus()
    follow: Series | None = None
    waiting_for_series: Series | None = None
    override: Flag | None = None
    source_kind: str = "live"
    mode: str = "on"

    @property
    def flag(self) -> Flag | None:
        if self.override is not None:
            return self.override
        return self.race.flag if self.race is not None else None


class Engine:
    def __init__(
        self,
        source: RaceSource,
        follow: Series | None,
        source_kind: str,
        poll_seconds: float = 3.0,
        offline_after: int = 3,
        max_backoff: float = 30.0,
    ):
        self._source = source
        self._generation = 0
        self._poll_seconds = poll_seconds
        self._offline_after = offline_after
        self._max_backoff = max_backoff
        self._lock = threading.Lock()
        self._state = EngineState(follow=follow, source_kind=source_kind)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> EngineState:
        with self._lock:
            return self._state

    def set_override(self, flag: Flag | None) -> None:
        with self._lock:
            self._state = replace(self._state, override=flag)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown mode {mode!r}")
        with self._lock:
            self._state = replace(self._state, mode=mode)

    def configure(self, source: RaceSource, follow: Series | None, kind: str) -> None:
        with self._lock:
            old = self._source
            self._source = source
            self._generation += 1
            self._state = replace(
                self._state,
                race=None,
                feed=FeedStatus(),
                waiting_for_series=None,
                follow=follow,
                source_kind=kind,
            )
        old.close()
        self._wake.set()

    def poll_once(self) -> float:
        with self._lock:
            source, generation = self._source, self._generation
        try:
            race = source.fetch()
        except Exception as e:
            if not isinstance(e, FeedError):
                log.exception("Race source failed unexpectedly")
            return self._record_failure(str(e) or type(e).__name__, generation)
        if not self._record_success(race, generation):
            return 0
        return self._poll_seconds

    def _record_success(self, race: RaceState | None, generation: int) -> bool:
        with self._lock:
            if generation != self._generation:
                return False
            follow = self._state.follow
            waiting = None
            message = ""
            if race is not None and follow is not None and race.series is not follow:
                waiting = follow
                message = f"{follow.label} not live — {race.series.label} is"
                race = None
            self._state = replace(
                self._state,
                race=race,
                waiting_for_series=waiting,
                feed=FeedStatus("ok", message, 0, time.time()),
            )
            return True

    def _record_failure(self, message: str, generation: int) -> float:
        with self._lock:
            if generation != self._generation:
                return 0
            failures = self._state.feed.failures + 1
            offline = failures >= self._offline_after
            self._state = replace(
                self._state,
                race=None if offline else self._state.race,
                feed=FeedStatus(
                    "offline" if offline else "retrying",
                    message,
                    failures,
                    self._state.feed.last_ok,
                ),
            )
        return min(self._poll_seconds * 2 ** min(failures, 4), self._max_backoff)

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="track-glow-engine", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        delay = 0.0
        try:
            while True:
                self._wake.wait(delay)
                self._wake.clear()
                if self._stop.is_set():
                    break
                delay = self.poll_once()
        finally:
            with self._lock:
                source = self._source
            source.close()

    def stop(self) -> None:
        # A request can hang well past its per-operation timeouts; don't block the caller
        # (often the Qt main thread) on it. The daemon thread closes the source on exit.
        self._stop.set()
        self._wake.set()
        if self._thread is None:
            self._source.close()
            return
        self._thread.join(STOP_JOIN_SECONDS)
        if not self._thread.is_alive():
            self._thread = None


def status_text(state: EngineState) -> str:
    prefix = {"paused": "Paused · ", "blackout": "Blackout · "}.get(state.mode, "")
    return prefix + _flag_text(state)


def _flag_text(state: EngineState) -> str:
    if state.override is not None:
        return f"{state.override.label} · manual override"
    if state.feed.health == "offline":
        return "Feed offline"
    if state.waiting_for_series is not None:
        return f"Waiting for {state.waiting_for_series.label}"
    race = state.race
    if race is None:
        return "No race"
    flag = race.flag.label if race.flag else f"Flag unknown ({race.raw_flag})"
    parts = [flag, race.series.label]
    if race.lap is not None:
        parts.append(f"Lap {race.lap}" + (f"/{race.laps_in_race}" if race.laps_in_race else ""))
    return " · ".join(parts)
