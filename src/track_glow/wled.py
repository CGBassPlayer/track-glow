from dataclasses import dataclass

import httpx2

from track_glow import __version__

_HEADERS = {"User-Agent": f"track-glow/{__version__}"}
_TIMEOUT = 3.0


class WledError(Exception):
    pass


@dataclass
class ControllerSpec:
    host: str
    led_count: int | None = None

    @classmethod
    def parse(cls, text: str) -> "ControllerSpec":
        host, sep, count = text.partition(":")
        if not sep:
            return cls(host)
        try:
            led_count = int(count)
        except ValueError:
            raise ValueError(f"Bad LED count in {text!r}") from None
        if led_count <= 0:
            raise ValueError(f"LED count must be positive in {text!r}")
        return cls(host, led_count)


def discover_led_count(host: str, client: httpx2.Client | None = None) -> int:
    if client is None:
        with httpx2.Client(timeout=_TIMEOUT) as owned:
            return _fetch_count(host, owned)
    return _fetch_count(host, client)


def _fetch_count(host: str, client: httpx2.Client) -> int:
    try:
        response = client.get(f"http://{host}/json/info", headers=_HEADERS, timeout=_TIMEOUT)
        response.raise_for_status()
    except httpx2.HTTPStatusError as e:
        raise WledError(f"WLED at {host} returned HTTP {e.response.status_code}") from e
    except httpx2.RequestError as e:
        raise WledError(f"Can't reach WLED at {host} ({type(e).__name__})") from e
    try:
        data = response.json()
    except ValueError as e:
        raise WledError(f"{host} doesn't look like WLED") from e
    leds = data.get("leds") if isinstance(data, dict) else None
    count = leds.get("count") if isinstance(leds, dict) else None
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise WledError(f"{host} doesn't look like WLED")
    return count
