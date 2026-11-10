import httpx2

from track_glow import __version__
from track_glow.models import Flag, RaceState, Series
from track_glow.sources import FeedError, RaceSource

FEED_URL = "https://cf.nascar.com/live/feeds/live-feed.json"
_HEADERS = {"User-Agent": f"track-glow/{__version__}"}


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: object) -> str:
    return str(value or "")


def parse_live_feed(data: object) -> RaceState | None:
    if not isinstance(data, dict):
        raise FeedError("Unexpected feed format")
    race_id = _int(data.get("race_id"))
    series_id = _int(data.get("series_id"))
    if race_id is None or race_id <= 0 or series_id not in Series:
        return None
    raw_flag = _int(data.get("flag_state"))
    return RaceState(
        flag=Flag(raw_flag) if raw_flag in Flag else None,
        raw_flag=raw_flag,
        series=Series(series_id),
        race_id=race_id,
        lap=_int(data.get("lap_number")),
        laps_in_race=_int(data.get("laps_in_race")),
        laps_to_go=_int(data.get("laps_to_go")),
        track_name=_str(data.get("track_name")),
        run_name=_str(data.get("run_name")),
    )


class NascarFeedSource(RaceSource):
    def __init__(self, url: str = FEED_URL, client: httpx2.Client | None = None) -> None:
        self._url = url
        self._client = client or httpx2.Client(timeout=httpx2.Timeout(8.0, connect=4.0))

    def fetch(self) -> RaceState | None:
        try:
            response = self._client.get(self._url, headers=_HEADERS)
            response.raise_for_status()
        except httpx2.HTTPStatusError as e:
            raise FeedError(f"Feed returned HTTP {e.response.status_code}") from e
        except httpx2.RequestError as e:
            raise FeedError(f"Can't reach NASCAR feed ({type(e).__name__})") from e
        try:
            data = response.json()
        except ValueError as e:
            raise FeedError("Feed returned invalid JSON") from e
        return parse_live_feed(data)

    def close(self) -> None:
        self._client.close()
