import json
from pathlib import Path

import httpx2
import pytest

from track_glow.models import Flag, Series
from track_glow.sources import FeedError
from track_glow.sources.nascar import FEED_URL, NascarFeedSource, parse_live_feed

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def source_with(handler) -> NascarFeedSource:
    return NascarFeedSource(client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def test_offseason_fixture_is_no_race():
    assert parse_live_feed(load("live-feed-offseason.json")) is None


def test_cup_green_fixture_parses():
    state = parse_live_feed(load("live-feed-cup-green.json"))
    assert state.flag is Flag.GREEN
    assert state.raw_flag == 1
    assert state.series is Series.CUP
    assert state.race_id == 5600
    assert state.lap == 112
    assert state.laps_in_race == 267
    assert state.laps_to_go == 155
    assert state.track_name == "Phoenix Raceway"
    assert state.run_name == "NASCAR Cup Series Championship"


def test_unknown_flag_keeps_raw():
    data = load("live-feed-cup-green.json") | {"flag_state": 7}
    state = parse_live_feed(data)
    assert state.flag is None
    assert state.raw_flag == 7


def test_wrong_types_become_none():
    data = load("live-feed-cup-green.json") | {
        "lap_number": "12",
        "flag_state": None,
        "laps_in_race": True,
        "track_name": None,
    }
    del data["laps_to_go"]
    state = parse_live_feed(data)
    assert state.lap is None
    assert state.flag is None and state.raw_flag is None
    assert state.laps_in_race is None
    assert state.laps_to_go is None
    assert state.track_name == ""


@pytest.mark.parametrize(
    "change", [{"race_id": 0}, {"race_id": "5600"}, {"series_id": 4}, {"series_id": None}]
)
def test_no_race_rule(change):
    assert parse_live_feed(load("live-feed-cup-green.json") | change) is None


def test_extra_and_changed_unrelated_fields_ignored():
    data = load("live-feed-cup-green.json") | {"vehicles": "nope", "stage": 3, "brand_new": {}}
    assert parse_live_feed(data).flag is Flag.GREEN


@pytest.mark.parametrize("data", [[], "x", None, 5])
def test_non_dict_raises(data):
    with pytest.raises(FeedError, match="Unexpected feed format"):
        parse_live_feed(data)


def test_fetch_returns_parsed_state():
    body = load("live-feed-cup-green.json")
    src = source_with(lambda request: httpx2.Response(200, json=body))
    assert src.fetch().series is Series.CUP


def test_fetch_requests_feed_url():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx2.Response(200, json=load("live-feed-offseason.json"))

    assert source_with(handler).fetch() is None
    assert seen == [FEED_URL]


def test_http_500_raises_feed_error():
    src = source_with(lambda request: httpx2.Response(500, text="boom"))
    with pytest.raises(FeedError, match="Feed returned HTTP 500"):
        src.fetch()


def test_html_body_raises_invalid_json():
    src = source_with(lambda request: httpx2.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(FeedError, match="Feed returned invalid JSON"):
        src.fetch()


def test_json_array_raises_feed_error():
    src = source_with(lambda request: httpx2.Response(200, json=[]))
    with pytest.raises(FeedError, match="Unexpected feed format"):
        src.fetch()


def test_timeout_raises_cant_reach():
    def handler(request):
        raise httpx2.ConnectTimeout("timed out", request=request)

    with pytest.raises(FeedError, match=r"Can't reach NASCAR feed \(ConnectTimeout\)"):
        source_with(handler).fetch()


def test_sends_user_agent():
    def handler(request):
        assert request.headers["user-agent"].startswith("track-glow/")
        return httpx2.Response(200, json=load("live-feed-offseason.json"))

    source_with(handler).fetch()


def test_default_client_timeout():
    src = NascarFeedSource()
    try:
        assert src._client.timeout == httpx2.Timeout(8.0, connect=4.0)
    finally:
        src.close()
