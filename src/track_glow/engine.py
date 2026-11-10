import logging
import threading
import time
from dataclasses import dataclass, replace

from track_glow.models import FeedStatus, Flag, RaceState, Series
from track_glow.sources import FeedError, RaceSource

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EngineState:
    race: RaceState | None = None
    feed: FeedStatus = FeedStatus()
    follow: Series | None = None
    waiting_for_series: Series | None = None
    override: Flag | None = None
    source_kind: str = "live"

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
        self._poll_seconds = poll_seconds
        self._offline_after = offline_after
        self._max_backoff = max_backoff
        self._lock = threading.Lock()
        self._state = EngineState(follow=follow, source_kind=source_kind)
        self._stop = threading.Event()
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

    def poll_once(self) -> float:
        try:
            race = self._source.fetch()
        except Exception as e:
            if not isinstance(e, FeedError):
                log.exception("Race source failed unexpectedly")
            return self._record_failure(str(e) or type(e).__name__)
        self._record_success(race)
        return self._poll_seconds

    def _record_success(self, race: RaceState | None) -> None:
        with self._lock:
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

    def _record_failure(self, message: str) -> float:
        with self._lock:
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
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="track-glow-engine", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        delay = 0.0
        while not self._stop.wait(delay):
            delay = self.poll_once()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(10)
            self._thread = None
        self._source.close()
