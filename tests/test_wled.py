import httpx2
import pytest

from track_glow import __version__
from track_glow.wled import ControllerSpec, WledError, discover_led_count


def _client(handler) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def test_parse_specs():
    assert ControllerSpec.parse("10.0.0.5") == ControllerSpec("10.0.0.5", None)
    assert ControllerSpec.parse("10.0.0.5:120") == ControllerSpec("10.0.0.5", 120)
    assert ControllerSpec.parse("wled.local:60") == ControllerSpec("wled.local", 60)
    for bad in ("h:0", "h:abc", "h:-3"):
        with pytest.raises(ValueError):
            ControllerSpec.parse(bad)


def test_discovers_count():
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"leds": {"count": 150}})

    assert discover_led_count("10.0.0.5", client=_client(handler)) == 150
    assert str(seen[0].url) == "http://10.0.0.5/json/info"
    assert seen[0].method == "GET"
    assert seen[0].headers["User-Agent"] == f"track-glow/{__version__}"


def test_unreachable_raises():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(WledError, match=r"^Can't reach WLED at 10\.0\.0\.5 \(ConnectError\)$"):
        discover_led_count("10.0.0.5", client=_client(handler))


def test_http_error_raises():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404)

    with pytest.raises(WledError, match=r"^WLED at 10\.0\.0\.5 returned HTTP 404$"):
        discover_led_count("10.0.0.5", client=_client(handler))


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, text="<html>router login</html>"),
        httpx2.Response(200, json={"leds": {}}),
        httpx2.Response(200, json={"leds": {"count": 0}}),
        httpx2.Response(200, json={"leds": {"count": True}}),
        httpx2.Response(200, json=[1, 2]),
    ],
)
def test_not_wled_raises(response):
    with pytest.raises(WledError, match=r"^10\.0\.0\.5 doesn't look like WLED$"):
        discover_led_count("10.0.0.5", client=_client(lambda request: response))
