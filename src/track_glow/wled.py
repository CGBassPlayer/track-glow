from dataclasses import dataclass

import httpx2

from track_glow import __version__

_HEADERS = {"User-Agent": f"track-glow/{__version__}"}
_TIMEOUT = 3.0


class WledError(Exception):
    pass


MAX_LEDS = 10000


@dataclass
class ControllerSpec:
    host: str
    led_count: int | None = None

    @classmethod
    def parse(cls, text: str) -> "ControllerSpec":
        host, sep, count = text.partition(":")
        host = host.strip().lower()
        if not host:
            raise ValueError(f"Missing host in {text!r}")
        if not sep:
            return cls(host)
        try:
            led_count = int(count)
        except ValueError:
            raise ValueError(f"Bad LED count in {text!r}") from None
        if not 0 < led_count <= MAX_LEDS:
            raise ValueError(f"LED count must be 1-{MAX_LEDS} in {text!r}")
        return cls(host, led_count)


@dataclass(frozen=True)
class ProgressSpec:
    start: int | None = None
    stop: int | None = None
    host: str | None = None
    segment: int | None = None

    @classmethod
    def parse(cls, text: str) -> "ProgressSpec":
        host, sep, segment = text.rpartition("/")
        host = host.strip().lower()
        if sep:
            if not host:
                raise ValueError(f"Empty host in {text!r}")
            try:
                seg = int(segment)
            except ValueError:
                raise ValueError(f"Bad segment in {text!r}") from None
            if seg < 0:
                raise ValueError(f"Bad segment in {text!r}")
            return cls(host=host, segment=seg)
        start_text, sep, stop_text = text.partition("-")
        try:
            start, stop = int(start_text), int(stop_text)
        except ValueError:
            raise ValueError(f"Expected START-STOP or HOST/SEG, got {text!r}") from None
        if stop <= start:
            raise ValueError(f"Stop must be greater than start in {text!r}")
        return cls(start=start, stop=stop)


def discover_led_count(host: str, client: httpx2.Client | None = None) -> int:
    data = _get_json(host, "/json/info", client)
    leds = data.get("leds") if isinstance(data, dict) else None
    count = leds.get("count") if isinstance(leds, dict) else None
    if not _is_int(count) or count <= 0:
        raise WledError(f"{host} doesn't look like WLED")
    return count


def fetch_segment(host: str, segment: int, client: httpx2.Client | None = None) -> tuple[int, int]:
    data = _get_json(host, "/json/state", client)
    segs = data.get("seg") if isinstance(data, dict) else None
    if not isinstance(segs, list) or not all(isinstance(s, dict) for s in segs):
        raise WledError(f"{host} doesn't look like WLED")
    match = next((s for s in segs if s.get("id") == segment), None)
    if match is None:
        raise WledError(f"WLED at {host} has no segment {segment}")
    start, stop = match.get("start"), match.get("stop")
    if not _is_int(start) or not _is_int(stop):
        raise WledError(f"{host} doesn't look like WLED")
    if stop <= start:
        raise WledError(f"Segment {segment} on {host} is empty")
    return start, stop


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _get_json(host: str, path: str, client: httpx2.Client | None) -> object:
    if client is None:
        with httpx2.Client(timeout=_TIMEOUT) as owned:
            return _get_json(host, path, owned)
    try:
        response = client.get(f"http://{host}{path}", headers=_HEADERS, timeout=_TIMEOUT)
        response.raise_for_status()
    except httpx2.HTTPStatusError as e:
        raise WledError(f"WLED at {host} returned HTTP {e.response.status_code}") from e
    except httpx2.RequestError as e:
        raise WledError(f"Can't reach WLED at {host} ({type(e).__name__})") from e
    try:
        return response.json()
    except ValueError as e:
        raise WledError(f"{host} doesn't look like WLED") from e
