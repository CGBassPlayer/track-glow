import re

import httpx2
import pytest

from track_glow import __version__
from track_glow.wled import (
    ControllerSpec,
    ProgressSpec,
    WledError,
    discover_led_count,
    fetch_segment,
)


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


def test_parse_progress_range():
    assert ProgressSpec.parse("100-120") == ProgressSpec(100, 120, None, None)
    assert ProgressSpec.parse("0-1") == ProgressSpec(0, 1, None, None)


def test_parse_progress_segment():
    assert ProgressSpec.parse("wled.local/1") == ProgressSpec(None, None, "wled.local", 1)
    assert ProgressSpec.parse("10.0.0.5/0") == ProgressSpec(None, None, "10.0.0.5", 0)


@pytest.mark.parametrize("bad", ["120-100", "5-5", "-5", "a-b", "host/x", "/1", "host/-1", "100"])
def test_parse_progress_errors(bad):
    with pytest.raises(ValueError, match=re.escape(repr(bad))):
        ProgressSpec.parse(bad)


_SEGMENTS = {"seg": [{"id": 0, "start": 0, "stop": 100}, {"id": 1, "start": 100, "stop": 120}]}


def test_fetch_segment():
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_SEGMENTS)

    assert fetch_segment("10.0.0.5", 1, client=_client(handler)) == (100, 120)
    assert str(seen[0].url) == "http://10.0.0.5/json/state"
    assert seen[0].method == "GET"
    assert seen[0].headers["User-Agent"] == f"track-glow/{__version__}"


def test_fetch_segment_missing():
    with pytest.raises(WledError, match=r"^WLED at 10\.0\.0\.5 has no segment 4$"):
        fetch_segment(
            "10.0.0.5", 4, client=_client(lambda request: httpx2.Response(200, json=_SEGMENTS))
        )


def test_fetch_segment_empty():
    body = {"seg": [{"id": 2, "start": 50, "stop": 50}]}
    with pytest.raises(WledError, match=r"^Segment 2 on 10\.0\.0\.5 is empty$"):
        fetch_segment(
            "10.0.0.5", 2, client=_client(lambda request: httpx2.Response(200, json=body))
        )


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, text="<html>router login</html>"),
        httpx2.Response(200, json=[1, 2]),
        httpx2.Response(200, json={"on": True}),
        httpx2.Response(200, json={"seg": {"id": 1}}),
        httpx2.Response(200, json={"seg": [{"id": 1, "start": "a", "stop": 120}]}),
        httpx2.Response(200, json={"seg": [{"id": 1, "start": 100}]}),
        httpx2.Response(200, json={"seg": ["x"]}),
    ],
)
def test_fetch_segment_not_wled(response):
    with pytest.raises(WledError, match=r"^10\.0\.0\.5 doesn't look like WLED$"):
        fetch_segment("10.0.0.5", 1, client=_client(lambda request: response))


def test_fetch_segment_unreachable():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(WledError, match=r"^Can't reach WLED at 10\.0\.0\.5 \(ConnectError\)$"):
        fetch_segment("10.0.0.5", 1, client=_client(handler))


def test_fetch_segment_http_error():
    with pytest.raises(WledError, match=r"^WLED at 10\.0\.0\.5 returned HTTP 500$"):
        fetch_segment("10.0.0.5", 1, client=_client(lambda request: httpx2.Response(500)))


def test_controller_led_count_capped():
    assert ControllerSpec.parse("a:10000").led_count == 10000
    with pytest.raises(ValueError, match="10000"):
        ControllerSpec.parse("a:10001")


def test_controller_host_trimmed_lowercased_and_required():
    assert ControllerSpec.parse(" WLED.Local :5") == ControllerSpec("wled.local", 5)
    for bad in ("", "  ", ":5"):
        with pytest.raises(ValueError, match="host"):
            ControllerSpec.parse(bad)


def test_progress_host_lowercased():
    assert ProgressSpec.parse("WLED.local/1").host == "wled.local"
