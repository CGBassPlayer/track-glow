import json
import ssl

import httpcore2
import httpx2
import pytest

from track_glow import __version__
from track_glow.ha import HaClient, HaError

URL = "http://ha.local:8123"
TOKEN = "s3cr3t-token-abc"


def make(handler):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    client = httpx2.Client(transport=httpx2.MockTransport(record))
    return HaClient(URL, TOKEN, client=client), requests


def raising(exc):
    def handler(request):
        raise exc

    return handler


def tls_error():
    root = ssl.SSLCertVerificationError("certificate verify failed: self-signed certificate")
    core = httpcore2.ConnectError(str(root))
    core.__cause__ = root
    exc = httpx2.ConnectError(str(core))
    exc.__cause__ = core
    return exc


def test_turn_on_scene_posts_entity_with_auth():
    ha, requests = make(lambda r: httpx2.Response(200, json=[]))
    ha.turn_on_scene("scene.green")
    (req,) = requests
    assert req.method == "POST"
    assert str(req.url) == f"{URL}/api/services/scene/turn_on"
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert req.headers["User-Agent"] == f"track-glow/{__version__}"
    assert json.loads(req.content) == {"entity_id": "scene.green"}


def test_list_scenes_filters_and_sorts():
    states = [
        {"entity_id": "scene.red"},
        {"entity_id": "light.kitchen"},
        {"entity_id": "scene.green"},
        {"entity_id": "sensor.temp"},
    ]
    ha, requests = make(lambda r: httpx2.Response(200, json=states))
    assert ha.list_scenes() == ["scene.green", "scene.red"]
    (req,) = requests
    assert req.method == "GET"
    assert str(req.url) == f"{URL}/api/states"
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"


def test_list_scenes_bad_shape_is_unexpected_reply():
    ha, _ = make(lambda r: httpx2.Response(200, json={"not": "a list"}))
    with pytest.raises(HaError, match="^Unexpected reply from Home Assistant$"):
        ha.list_scenes()


def test_check_hits_api_root():
    ha, requests = make(lambda r: httpx2.Response(200, json={"message": "API running."}))
    ha.check()
    (req,) = requests
    assert req.method == "GET"
    assert str(req.url) == f"{URL}/api/"
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"


def test_401_message():
    ha, _ = make(lambda r: httpx2.Response(401))
    with pytest.raises(HaError, match="^Home Assistant rejected the access token$"):
        ha.check()


def test_500_message():
    ha, _ = make(lambda r: httpx2.Response(500))
    with pytest.raises(HaError, match="^Home Assistant returned HTTP 500$"):
        ha.turn_on_scene("scene.green")


def test_connect_error_message():
    ha, _ = make(raising(httpx2.ConnectError("Connection refused")))
    with pytest.raises(HaError) as info:
        ha.check()
    assert str(info.value) == f"Can't reach Home Assistant at {URL} (ConnectError)"


def test_timeout_message():
    ha, _ = make(raising(httpx2.ReadTimeout("timed out")))
    with pytest.raises(HaError) as info:
        ha.list_scenes()
    assert str(info.value) == f"Can't reach Home Assistant at {URL} (ReadTimeout)"


def test_tls_error_message():
    ha, _ = make(raising(tls_error()))
    with pytest.raises(HaError) as info:
        ha.check()
    assert str(info.value) == (
        "TLS error talking to Home Assistant (self-signed certificate? turn off Verify TLS)"
    )


def test_bad_json_message():
    ha, _ = make(lambda r: httpx2.Response(200, content=b"<html>nope"))
    with pytest.raises(HaError, match="^Unexpected reply from Home Assistant$"):
        ha.list_scenes()


def test_check_bad_json_message():
    ha, _ = make(lambda r: httpx2.Response(200, content=b"<html>nope"))
    with pytest.raises(HaError, match="^Unexpected reply from Home Assistant$"):
        ha.check()


def _echo_token(request):
    raise httpx2.ConnectError(f"failed {request.headers['Authorization']}")


CALLS = {
    "check": lambda ha: ha.check(),
    "list_scenes": lambda ha: ha.list_scenes(),
    "turn_on": lambda ha: ha.turn_on_scene("scene.green"),
}
FAILURES = {
    "401": (lambda r: httpx2.Response(401, text=TOKEN), CALLS),
    "500": (lambda r: httpx2.Response(500, text=TOKEN), CALLS),
    "connect": (_echo_token, CALLS),
    "tls": (raising(tls_error()), CALLS),
    "bad_json": (
        lambda r: httpx2.Response(200, text=f"not json {TOKEN}"),
        ["check", "list_scenes"],
    ),
}


@pytest.mark.parametrize(
    ("handler", "call"),
    [
        pytest.param(handler, call, id=f"{name}-{call}")
        for name, (handler, calls) in FAILURES.items()
        for call in calls
    ],
)
def test_no_token_in_error_messages(handler, call):
    ha, _ = make(handler)
    with pytest.raises(HaError) as info:
        CALLS[call](ha)
    err = info.value
    assert TOKEN not in str(err)
    assert TOKEN not in repr(err)
    assert err.__cause__ is None
    assert err.__context__ is None or err.__suppress_context__


def test_owned_client_uses_timeout_verify_and_close():
    ha = HaClient(URL, TOKEN, verify_tls=False)
    try:
        assert ha._client.timeout.connect == 5.0
        assert ha._client.timeout.read == 5.0
        assert ha._client.headers["User-Agent"] == f"track-glow/{__version__}"
    finally:
        ha.close()
    assert ha._client.is_closed


def test_close_leaves_injected_client_open():
    client = httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(200)))
    HaClient(URL, TOKEN, client=client).close()
    assert not client.is_closed
    client.close()


def test_invalid_url_and_token_map_to_ha_error_without_token():
    import httpx2

    from track_glow.ha import HaClient, HaError

    def handler(request):
        return httpx2.Response(200, json={})

    transport = httpx2.MockTransport(handler)
    bad_port = HaClient("http://127.0.0.1:abc", "t", client=httpx2.Client(transport=transport))
    with pytest.raises(HaError, match="Invalid Home Assistant URL"):
        bad_port.check()
    token = "abc​secret"
    bad_token = HaClient("http://ha", token, client=httpx2.Client(transport=transport))
    with pytest.raises(HaError) as e:
        bad_token.check()
    assert str(e.value) == "Access token has invalid characters"
    assert "secret" not in repr(e.value) and e.value.__cause__ is None
