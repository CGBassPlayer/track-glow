from fastapi.testclient import TestClient

from track_glow import __version__
from track_glow.web import create_app


def client(engine) -> TestClient:
    return TestClient(create_app(engine))


def test_health_reports_ok_and_version(fake_engine):
    r = client(fake_engine).get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


def test_index_is_placeholder_page(fake_engine):
    r = client(fake_engine).get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Track Glow" in r.text and "No race" in r.text


def test_index_has_state_polling(fake_engine):
    assert "/api/state" in client(fake_engine).get("/").text


def test_state_no_race(fake_engine):
    s = client(fake_engine).get("/api/state").json()
    assert s["flag"] is None and s["flag_label"] is None and s["lap"] is None
    assert s["feed"] == {"health": "connecting", "message": "", "failures": 0}
    assert s["follow"] == "Cup" and s["source"] == "live"
    assert s["status"] == "No race"


def test_state_green_cup(green_engine):
    s = client(green_engine).get("/api/state").json()
    assert s == {
        "flag": "green",
        "flag_label": "GREEN",
        "flag_color": "#2e7d32",
        "series": "Cup",
        "lap": 112,
        "laps_in_race": 267,
        "track_name": "Phoenix Raceway",
        "run_name": "NASCAR Cup Series Championship",
        "feed": {"health": "ok", "message": "", "failures": 0},
        "follow": "Cup",
        "waiting_for_series": None,
        "override": None,
        "source": "live",
        "status": "GREEN · Cup · Lap 112/267",
        "lights": [],
    }


def test_override_post_sets_and_clears(green_engine):
    c = client(green_engine)
    r = c.post("/api/override", json={"flag": "red"})
    assert r.status_code == 200 and r.json()["flag"] == "red" and r.json()["override"] == "red"
    r = c.post("/api/override", json={"flag": None})
    assert r.json()["flag"] == "green" and r.json()["override"] is None


def test_override_unknown_flag_422(green_engine):
    assert client(green_engine).post("/api/override", json={"flag": "purple"}).status_code == 422


def test_index_resets_display_when_unreachable(fake_engine):
    html = client(fake_engine).get("/").text
    assert "Not connected" in html and "r.ok" in html


def test_state_includes_lights(fake_engine):
    from conftest import FakeLights

    from track_glow.outputs.wled import ControllerStatus

    lights = FakeLights(
        [ControllerStatus("10.0.0.5", 60, "ok"), ControllerStatus("10.0.0.6", None, "error", "x")]
    )
    s = TestClient(create_app(fake_engine, lights)).get("/api/state").json()
    assert s["lights"] == [
        {"host": "10.0.0.5", "led_count": 60, "state": "ok", "message": ""},
        {"host": "10.0.0.6", "led_count": None, "state": "error", "message": "x"},
    ]


def test_state_lights_empty_without_output(fake_engine):
    assert client(fake_engine).get("/api/state").json()["lights"] == []


def test_frame_endpoint_hex(fake_engine):
    from conftest import FakeLights

    lights = FakeLights(frame=bytes([0, 255, 0, 0, 0, 0]))
    r = TestClient(create_app(fake_engine, lights)).get("/api/frame").json()
    assert r == {"pixels": "00ff00000000", "led_count": 2}


def test_frame_empty_without_output(fake_engine):
    assert client(fake_engine).get("/api/frame").json() == {"pixels": "", "led_count": 0}


def test_index_has_strip_preview(fake_engine):
    html = client(fake_engine).get("/").text
    assert 'id="strip"' in html and "/api/frame" in html


def test_strip_preview_polls_faster_than_flash_and_never_overlaps(fake_engine):
    html = client(fake_engine).get("/").text
    assert "setTimeout(drawStrip, FRAME_MS)" in html and "const FRAME_MS = 100" in html
    assert "setInterval(drawStrip" not in html
